# Python SDK — the primary/deployable worker. Brings up the full local stack:
#
#   make up          postgres + temporal + python worker + gateway + web UI
#   make down        stop everything
#   make status      what's running
#   make kill-worker the crash-recovery beat (then: make worker)
#
# Shared infra (postgres/temporal/gateway/web) lives in ../make/common.mk.

SDK := python
OTHER_WORKER_PATTERNS := src/worker.ts
WORKER_STATUS = pgrep -f "worker.py" >/dev/null 2>&1 && echo "running (python)" || echo "stopped"

include ../make/common.mk

.PHONY: worker kill-worker

worker: guard-single-sdk
	@pgrep -f "worker.py" >/dev/null 2>&1 || \
		(cd $(ROOT)/python && nohup uv run worker.py > /tmp/travel-worker.log 2>&1 & \
		 echo "python worker started (queue: travel-agent)")

# The money beat: kill the worker mid-conversation, watch the loop freeze,
# then `make worker` — it resumes on the exact next line.
kill-worker:
	-pkill -f "worker.py"
	@echo "python worker killed — restart with: make worker"
