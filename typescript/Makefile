# TypeScript SDK — local-runnable only (no Docker, no deploy). Brings up the
# full local stack with the TS worker instead of the Python one:
#
#   make up          postgres + temporal + TS worker + gateway + web UI
#   make down        stop everything
#   make status      what's running
#   make kill-worker the crash-recovery beat (then: make worker)
#   make deps        npm install (auto-runs on first `make up`)
#
# The gateway + UI are the same Python ones (SDK-agnostic — see CONTRACT.md);
# only the worker differs. Shared infra lives in ../make/common.mk.

SDK := typescript
OTHER_WORKER_PATTERNS := worker.py
WORKER_STATUS = pgrep -f "src/worker.ts" >/dev/null 2>&1 && echo "running (typescript)" || echo "stopped"

include ../make/common.mk

.PHONY: worker kill-worker deps

deps: $(ROOT)/typescript/node_modules
$(ROOT)/typescript/node_modules: $(ROOT)/typescript/package.json
	cd $(ROOT)/typescript && npm install
	@touch $(ROOT)/typescript/node_modules

worker: guard-single-sdk $(ROOT)/typescript/node_modules
	@pgrep -f "src/worker.ts" >/dev/null 2>&1 || \
		(cd $(ROOT)/typescript && nohup npm run worker > /tmp/travel-worker-ts.log 2>&1 & \
		 echo "ts worker started (queue: travel-agent)")

# The money beat: kill the worker mid-conversation, watch the loop freeze,
# then `make worker` — it resumes on the exact next line.
kill-worker:
	-pkill -f "src/worker.ts"
	@echo "ts worker killed — restart with: make worker"
