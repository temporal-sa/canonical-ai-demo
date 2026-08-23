# Go SDK — local-runnable only. Shared infrastructure lives in ../make/common.mk.
SDK := go
OTHER_WORKER_PATTERNS := worker.py src/worker.ts travel-agent-java-0.1.0.jar
WORKER_STATUS = pgrep -f "travel-worker-go" >/dev/null 2>&1 && echo "running (go)" || echo "stopped"

include ../make/common.mk

.PHONY: worker kill-worker deps test

deps:
	cd $(ROOT)/go && go mod download

$(ROOT)/go/.bin/travel-worker-go: $(shell find $(ROOT)/go -name '*.go') $(ROOT)/go/go.mod
	@mkdir -p $(ROOT)/go/.bin
	cd $(ROOT)/go && go build -o .bin/travel-worker-go ./cmd/worker

worker: guard-single-sdk deps $(ROOT)/go/.bin/travel-worker-go
	@pgrep -f "travel-worker-go" >/dev/null 2>&1 || \
		(cd $(ROOT)/go && nohup ./.bin/travel-worker-go > /tmp/travel-worker-go.log 2>&1 & \
		 echo "go worker started (queue: travel-agent)")

kill-worker:
	-pkill -f "travel-worker-go"
	@echo "go worker killed — restart with: make worker"

test:
	cd $(ROOT)/go && go test ./...
