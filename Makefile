# Jarvis Hub — developer convenience targets.
# Not a build system: the project runs from source (see CONTRIBUTING.md).

PYTHON ?= python3
PID_FILE := logs/runtime_supervisor.pid

JARVIS_PORT ?= 4719

.PHONY: test runtime-up runtime-down runtime-status jarvis-os

test:
	$(PYTHON) -m pytest tests/ -q

# ANDREI OS / J.A.R.V.I.S. Second Brain & 3D Workshop (apps/jarvis-os) —
# zero-dependency stdlib server on http://localhost:4719. Foreground; Ctrl+C stops it.
# Windows without make: apps\jarvis-os\START.bat, or `npm run jarvis-os`.
jarvis-os:
	JARVIS_PORT=$(JARVIS_PORT) $(PYTHON) apps/jarvis-os/server.py

# Starts the runtime supervisor (coordinator + heartbeat + night shift) in the
# background and records its PID. It respawns scripts/coordinator.py itself on
# any crash, including `kill -9` — see scripts/runtime_supervisor.py.
runtime-up:
	@mkdir -p logs
	@if [ -f $(PID_FILE) ] && kill -0 "$$(cat $(PID_FILE))" 2>/dev/null; then \
		echo "runtime supervisor already running (pid $$(cat $(PID_FILE)))"; \
	else \
		nohup $(PYTHON) scripts/runtime_supervisor.py >> logs/runtime_supervisor.log 2>&1 & \
		echo $$! > $(PID_FILE); \
		echo "runtime supervisor started (pid $$(cat $(PID_FILE)))"; \
	fi

runtime-down:
	@if [ -f $(PID_FILE) ] && kill -0 "$$(cat $(PID_FILE))" 2>/dev/null; then \
		kill -TERM "$$(cat $(PID_FILE))"; \
		echo "runtime supervisor stopped (pid $$(cat $(PID_FILE)))"; \
	else \
		echo "runtime supervisor not running"; \
	fi; \
	rm -f $(PID_FILE)

runtime-status:
	@if [ -f $(PID_FILE) ] && kill -0 "$$(cat $(PID_FILE))" 2>/dev/null; then \
		echo "runtime supervisor running (pid $$(cat $(PID_FILE)))"; \
	else \
		echo "runtime supervisor not running"; \
	fi
