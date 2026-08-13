# Shared local-stack targets for every SDK's Makefile.
#
# The demo is multi-SDK: the worker (the durable agent) can be written in any
# Temporal SDK, while postgres + the temporal dev server + the gateway + the web
# UI are identical for all of them. Those shared pieces live here; each SDK's
# Makefile includes this fragment and defines only the SDK-specific bits (how to
# start/kill/status ITS worker).
#
# A per-SDK Makefile looks like:
#     SDK := typescript
#     OTHER_WORKER_PATTERNS := worker.py          # other SDKs' worker processes
#     WORKER_STATUS = pgrep -f "src/worker.ts" ... # one line for `make status`
#     include ../make/common.mk
#     worker: guard-single-sdk ; <start this SDK's worker>
#     kill-worker: ; <kill this SDK's worker>
#
# Then `cd typescript && make up` brings up the whole stack on the TS worker.
#
# Only ONE SDK's worker may poll the shared `travel-agent` queue at a time — a
# history written by one SDK can't be replayed by another. `guard-single-sdk`
# enforces that.
#
# Logs: /tmp/temporal-dev.log /tmp/travel-worker*.log /tmp/travel-api.log /tmp/travel-web.log

# Repo root — computed from THIS fragment's own path, so every target works no
# matter which directory `make` is invoked from.
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)

.PHONY: up down status logs api web temporal postgres kill-db db seed guard-single-sdk

up: postgres temporal worker api web
	@echo ""
	@echo "  SDK          → $(SDK)"
	@echo "  chat UI      → http://localhost:5173"
	@echo "  temporal UI  → http://localhost:8233"
	@echo "  gateway      → http://localhost:8000"

postgres:
	cd $(ROOT) && docker compose up -d

temporal:
	@pgrep -f "temporal server start-dev" >/dev/null 2>&1 || \
		(nohup temporal server start-dev --ui-port 8233 > /tmp/temporal-dev.log 2>&1 & \
		 sleep 3 && echo "temporal dev server started (UI :8233)")

# The gateway + static UI are SDK-agnostic (they drive the workflow by string
# name), so every SDK's stack uses this same Python gateway. See CONTRACT.md.
api:
	@pgrep -f "uvicorn gateway:app" >/dev/null 2>&1 || \
		(cd $(ROOT)/web && nohup uv run uvicorn gateway:app --port 8000 > /tmp/travel-api.log 2>&1 & \
		 echo "gateway started (:8000)")

web:
	@pgrep -f "http.server 5173" >/dev/null 2>&1 || \
		(cd $(ROOT)/web && nohup python3 -m http.server 5173 > /tmp/travel-web.log 2>&1 & \
		 echo "web UI started (:5173)")

# Refuse to start this SDK's worker if another SDK's worker already polls the
# queue (one SDK at a time). Each SDK lists the others in OTHER_WORKER_PATTERNS.
guard-single-sdk:
	@for pat in $(OTHER_WORKER_PATTERNS); do \
		if pgrep -f "$$pat" >/dev/null 2>&1; then \
			echo "another SDK's worker is running ($$pat) — stop it first (one SDK at a time on task queue travel-agent)"; \
			exit 1; \
		fi; \
	done

# Regenerate the seed dataset (destinations, flights, hotels, attractions).
seed:
	cd $(ROOT) && python3 db/generate_seed.py

# The retry beat: kill the DATABASE mid-conversation. The tool activity fails,
# Temporal retries it with backoff (watch the UI), then `make db` brings it back
# and the next retry just... succeeds.
kill-db:
	docker kill postgres
	@echo "database killed — the agent survives this. restore with: make db"

db:
	docker start postgres
	@echo "database back — the retrying activity will succeed on its next attempt"

# Stop this SDK's worker + the whole shared local stack.
down: kill-worker
	-pkill -f "uvicorn gateway:app"
	-pkill -f "http.server 5173"
	-pkill -f "temporal server start-dev"
	cd $(ROOT) && docker compose down
	@echo "all stopped ($(SDK))"

status:
	@printf "SDK      : $(SDK)\n"
	@printf "postgres : "; (cd $(ROOT) && docker compose ps --format '{{.Status}}' postgres 2>/dev/null) || echo "stopped"
	@printf "temporal : "; pgrep -f "temporal server start-dev" >/dev/null 2>&1 && echo "running (:7233, UI :8233)" || echo "stopped"
	@printf "worker   : "; $(WORKER_STATUS)
	@printf "gateway  : "; pgrep -f "uvicorn gateway:app" >/dev/null 2>&1 && echo "running (:8000)" || echo "stopped"
	@printf "web      : "; pgrep -f "http.server 5173" >/dev/null 2>&1 && echo "running (:5173)" || echo "stopped"

logs:
	@tail -n 20 /tmp/travel-worker*.log /tmp/travel-api.log 2>/dev/null
