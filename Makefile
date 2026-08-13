# Multi-SDK demo. Each SDK has its own Makefile that brings up the full local
# stack with THAT SDK's worker (shared infra lives in make/common.mk):
#
#   cd python     && make up      # the primary/deployable SDK
#   cd typescript && make up       # local-only TS worker
#
# For convenience, running make FROM THE REPO ROOT forwards to the Python SDK,
# so the familiar commands still work unchanged:
#
#   make up  / make down / make status / make kill-worker / make kill-db  → python/
#
# Only ONE SDK's worker may poll the `travel-agent` queue at a time (a history
# written by one SDK can't be replayed by another). Switch SDKs from their
# folders: `cd python && make kill-worker` then `cd typescript && make up`.

.DEFAULT_GOAL := up

# Forward every root target to python/Makefile.
up down status logs worker kill-worker api web temporal postgres kill-db db seed deps:
	@$(MAKE) --no-print-directory -C python $@

.PHONY: up down status logs worker kill-worker api web temporal postgres kill-db db seed deps
