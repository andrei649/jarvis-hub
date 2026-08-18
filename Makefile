# Jarvis Hub — Always-On autonomy runtime + test entrypoints.
#
# runtime-* targets operationalize the headless engine (coordinator + heartbeat +
# night-shift): scripts/runtime_supervisor.py supervises
# agents.core.autonomy.runtime_coordinator, restarting it with backoff on any exit
# (including kill -9) and writing every lifecycle/cycle event to logs/runtime.jsonl.
# See HANDOFF.md for the verification recipe and deploy/systemd/ for the
# production (systemd-supervised) alternative to runtime-up.

PYTHON ?= python3
SUPERVISOR_PIDFILE ?= logs/runtime_supervisor.pid
RUNTIME_LOG ?= logs/runtime.jsonl

.PHONY: test runtime-up runtime-down runtime-status runtime-logs

test:
	$(PYTHON) -m pytest -q

## Start the supervised Always-On runtime in the background. Idempotent: a second
## call while one is already running is a no-op (checked via the pidfile).
runtime-up:
	@mkdir -p logs
	@if [ -f "$(SUPERVISOR_PIDFILE)" ] && kill -0 "$$(cat $(SUPERVISOR_PIDFILE))" 2>/dev/null; then \
		echo "runtime supervisor already running (pid $$(cat $(SUPERVISOR_PIDFILE)))"; \
	else \
		setsid $(PYTHON) scripts/runtime_supervisor.py >> logs/runtime_supervisor.out 2>&1 < /dev/null & \
		echo "runtime supervisor starting — tail $(RUNTIME_LOG) to watch cycles"; \
	fi

## Stop the supervisor (which stops the coordinator child gracefully via SIGTERM).
runtime-down:
	@if [ -f "$(SUPERVISOR_PIDFILE)" ] && kill -0 "$$(cat $(SUPERVISOR_PIDFILE))" 2>/dev/null; then \
		kill -TERM "$$(cat $(SUPERVISOR_PIDFILE))"; \
		echo "stop signal sent to supervisor (pid $$(cat $(SUPERVISOR_PIDFILE)))"; \
	else \
		echo "runtime supervisor is not running"; \
	fi

## Human-facing status: supervisor/coordinator liveness + the last few run-log lines.
runtime-status:
	@if [ -f "$(SUPERVISOR_PIDFILE)" ] && kill -0 "$$(cat $(SUPERVISOR_PIDFILE))" 2>/dev/null; then \
		echo "supervisor: running (pid $$(cat $(SUPERVISOR_PIDFILE)))"; \
	else \
		echo "supervisor: not running"; \
	fi
	@pgrep -f agents.core.autonomy.runtime_coordinator >/dev/null 2>&1 \
		&& echo "coordinator: running (pid $$(pgrep -f agents.core.autonomy.runtime_coordinator | tr '\n' ' '))" \
		|| echo "coordinator: not running"
	@echo "--- last 3 run-log lines ---"
	@tail -3 "$(RUNTIME_LOG)" 2>/dev/null || echo "(no run-log yet)"

runtime-logs:
	@tail -f "$(RUNTIME_LOG)"
