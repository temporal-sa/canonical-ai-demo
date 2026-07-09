# One-command local demo stack.
#
#   make up          start everything → open http://localhost:5173
#   make down        stop everything
#   make status      what's running
#   make kill-worker the crash-recovery demo beat (then: make worker)
#
# Logs: /tmp/temporal-dev.log /tmp/agent-worker.log /tmp/agent-api.log /tmp/agent-web.log

.PHONY: up down status logs worker api web temporal postgres kill-worker kill-db db

up: postgres temporal worker api web
	@echo ""
	@echo "  chat UI      → http://localhost:5173"
	@echo "  temporal UI  → http://localhost:8233"
	@echo "  gateway      → http://localhost:8000"

postgres:
	docker compose up -d

temporal:
	@pgrep -f "temporal server start-dev" >/dev/null 2>&1 || \
		(nohup temporal server start-dev --ui-port 8233 > /tmp/temporal-dev.log 2>&1 & \
		 sleep 3 && echo "temporal dev server started (UI :8233)")

worker:
	@pgrep -f "worker.py" >/dev/null 2>&1 || \
		(cd python && nohup uv run worker.py > /tmp/agent-worker.log 2>&1 & \
		 echo "worker started")

api:
	@pgrep -f "uvicorn gateway:app" >/dev/null 2>&1 || \
		(cd web && nohup uv run uvicorn gateway:app --port 8000 > /tmp/agent-api.log 2>&1 & \
		 echo "gateway started (:8000)")

web:
	@pgrep -f "http.server 5173" >/dev/null 2>&1 || \
		(cd web && nohup python3 -m http.server 5173 > /tmp/agent-web.log 2>&1 & \
		 echo "web UI started (:5173)")

# The money beat: kill the worker mid-conversation, watch the loop freeze,
# then `make worker` — it resumes on the exact next line.
kill-worker:
	-pkill -f "worker.py"
	@echo "worker killed — restart with: make worker"

# The retry beat (slide 31): kill the DATABASE mid-conversation. The tool
# activity fails, Temporal retries it with backoff (watch the UI), then
# `make db` brings it back and the next retry just... succeeds.
kill-db:
	docker kill postgres
	@echo "database killed — the agent survives this. restore with: make db"

db:
	docker start postgres
	@echo "database back — the retrying activity will succeed on its next attempt"

down:
	-pkill -f "worker.py"
	-pkill -f "uvicorn gateway:app"
	-pkill -f "http.server 5173"
	-pkill -f "temporal server start-dev"
	docker compose down
	@echo "all stopped"

status:
	@printf "postgres : "; docker compose ps --format '{{.Status}}' postgres 2>/dev/null || echo "stopped"
	@printf "temporal : "; pgrep -f "temporal server start-dev" >/dev/null 2>&1 && echo "running (:7233, UI :8233)" || echo "stopped"
	@printf "worker   : "; pgrep -f "worker.py" >/dev/null 2>&1 && echo "running" || echo "stopped"
	@printf "gateway  : "; pgrep -f "uvicorn gateway:app" >/dev/null 2>&1 && echo "running (:8000)" || echo "stopped"
	@printf "web      : "; pgrep -f "http.server 5173" >/dev/null 2>&1 && echo "running (:5173)" || echo "stopped"

logs:
	@tail -n 20 /tmp/agent-worker.log /tmp/agent-api.log 2>/dev/null
