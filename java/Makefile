# Java SDK — local-runnable only. Shared infrastructure lives in ../make/common.mk.
SDK := java
OTHER_WORKER_PATTERNS := worker.py src/worker.ts travel-worker-go
WORKER_STATUS = pgrep -f "travel-agent-java-0.1.0.jar" >/dev/null 2>&1 && echo "running (java)" || echo "stopped"

include ../make/common.mk

.PHONY: worker kill-worker deps test

deps:
	cd $(ROOT)/java && mvn -q -DskipTests package

worker: guard-single-sdk deps
	@pgrep -f "travel-agent-java-0.1.0.jar" >/dev/null 2>&1 || \
		(cd $(ROOT)/java && nohup java -jar target/travel-agent-java-0.1.0.jar > /tmp/travel-worker-java.log 2>&1 & \
		 echo "java worker started (queue: travel-agent)")

kill-worker:
	-pkill -f "travel-agent-java-0.1.0.jar"
	@echo "java worker killed — restart with: make worker"

test:
	cd $(ROOT)/java && mvn test
