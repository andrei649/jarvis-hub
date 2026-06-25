"""H23.11 — operability: liveness/readiness probes, graceful-shutdown config,
and opt-in rotating file logging.

These are the productionization pieces a credible 1.0 needs so a supervisor
(systemd / Docker / a load balancer) can health-check, drain, and rotate logs.

- ``GET /healthz`` — liveness; dependency-free, always 200 while serving.
- ``GET /readyz``  — readiness; 503 until the orchestrator + agents are loaded.
- ``serve.server_config`` — env-driven uvicorn config with a bounded
  ``timeout_graceful_shutdown`` (defaults preserve the historical behaviour).
- ``core.log.setup_logging`` — attaches a ``RotatingFileHandler`` only when
  opted in (``$JARVIS_LOG_FILE`` or ``system.log_to_file``); never crashes boot.
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import agents.web as web  # noqa: E402

# ── /healthz — liveness ───────────────────────────────────────────────────────

def test_healthz_ok_without_orchestrator():
    """Liveness answers 200 even with no orchestrator (no lifespan) — it must not
    depend on any backend, so a slow LLM/DB can never make it flap."""
    client = TestClient(web.app)  # no `with` → lifespan not run → orch is None
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert isinstance(body["uptime_seconds"], (int, float))
    assert body["uptime_seconds"] >= 0


def test_healthz_is_no_store():
    client = TestClient(web.app)
    resp = client.get("/healthz")
    assert "no-store" in resp.headers.get("cache-control", "").lower()


# ── /readyz — readiness ───────────────────────────────────────────────────────

def test_readyz_503_when_starting(monkeypatch):
    """No orchestrator yet (mid-boot) → not ready → 503 so a load balancer holds
    traffic back."""
    monkeypatch.setattr(web, "orch", None)
    client = TestClient(web.app)
    resp = client.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["ready"] is False
    assert body["reason"] == "starting"
    assert "no-store" in resp.headers.get("cache-control", "").lower()


def test_readyz_503_when_agents_not_loaded(monkeypatch):
    """Orchestrator exists but no agents loaded yet → still not ready."""
    orch = SimpleNamespace(agents={}, channels={}, llm_router=SimpleNamespace(name="none"))
    monkeypatch.setattr(web, "orch", orch)
    resp = TestClient(web.app).get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["ready"] is False
    assert body["reason"] == "agents-not-loaded"


def test_readyz_200_when_loaded(monkeypatch):
    """Orchestrator + agents loaded → ready; the LLM backend is reported but does
    NOT gate readiness (the hub degrades gracefully when the model is down)."""
    orch = SimpleNamespace(
        agents={"jarvis": object(), "friday": object()},
        channels={"web": object()},
        llm_router=SimpleNamespace(name="lmstudio"),
    )
    monkeypatch.setattr(web, "orch", orch)
    resp = TestClient(web.app).get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    assert body["checks"]["agents_loaded"] == 2
    assert body["checks"]["channels"] == 1
    assert body["checks"]["llm_backend"] == "lmstudio"


def test_readyz_ready_even_with_llm_offline(monkeypatch):
    """A loaded orchestrator with the LLM backend 'none' is still ready — readiness
    must not depend on the local model being up."""
    orch = SimpleNamespace(
        agents={"jarvis": object()}, channels={},
        llm_router=SimpleNamespace(name="none"),
    )
    monkeypatch.setattr(web, "orch", orch)
    resp = TestClient(web.app).get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["ready"] is True


# ── serve.server_config — graceful shutdown ───────────────────────────────────

def _fresh_serve():
    # serve imports agents.web at module load; importing it here is cheap (already
    # imported above) and gives us server_config()/_env_int().
    import serve
    return serve


def test_server_config_defaults(monkeypatch):
    for var in ("JARVIS_HOST", "JARVIS_PORT", "JARVIS_LOG_LEVEL", "JARVIS_SHUTDOWN_TIMEOUT"):
        monkeypatch.delenv(var, raising=False)
    cfg = _fresh_serve().server_config()
    assert cfg.host == "127.0.0.1"          # loopback by default (local-first)
    assert cfg.port == 8080
    assert cfg.timeout_graceful_shutdown == 10   # bounded drain on SIGTERM/SIGINT


def test_server_config_env_override(monkeypatch):
    monkeypatch.setenv("JARVIS_HOST", "0.0.0.0")
    monkeypatch.setenv("JARVIS_PORT", "9001")
    monkeypatch.setenv("JARVIS_LOG_LEVEL", "warning")
    monkeypatch.setenv("JARVIS_SHUTDOWN_TIMEOUT", "30")
    cfg = _fresh_serve().server_config()
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9001
    assert cfg.log_level == "warning"
    assert cfg.timeout_graceful_shutdown == 30


def test_server_config_bad_int_falls_back(monkeypatch):
    monkeypatch.setenv("JARVIS_PORT", "not-a-port")
    monkeypatch.setenv("JARVIS_SHUTDOWN_TIMEOUT", "")
    cfg = _fresh_serve().server_config()
    assert cfg.port == 8080                 # garbage → default, never crashes boot
    assert cfg.timeout_graceful_shutdown == 10


# ── core.log — rotating file logging (opt-in) ─────────────────────────────────

def _rotating_handlers():
    return [h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler)]


@pytest.fixture
def restore_logging():
    """Rebuild logging to the default (no file handler) after the test so an
    attached RotatingFileHandler can't leak a file handle into other tests."""
    import core.log as log
    yield
    for var in ("JARVIS_LOG_FILE", "JARVIS_LOG_MAX_MB", "JARVIS_LOG_BACKUPS"):
        os.environ.pop(var, None)
    log.setup_logging(logging.INFO)  # force=True closes the rotating handler


def test_log_to_file_disabled_by_default(monkeypatch, restore_logging):
    import core.log as log
    monkeypatch.delenv("JARVIS_LOG_FILE", raising=False)
    # Force the setting off regardless of any pre-existing settings.db state.
    monkeypatch.setattr(log, "_setting",
                        lambda cat, key, default: False if key == "log_to_file" else default)
    log.setup_logging(logging.INFO)
    assert _rotating_handlers() == []


def test_log_to_file_via_env_rotates(monkeypatch, tmp_path, restore_logging):
    import core.log as log
    logfile = tmp_path / "logs" / "jarvis.log"
    monkeypatch.setenv("JARVIS_LOG_FILE", str(logfile))
    monkeypatch.setenv("JARVIS_LOG_MAX_MB", "2")
    monkeypatch.setenv("JARVIS_LOG_BACKUPS", "3")
    log.setup_logging(logging.INFO)

    handlers = _rotating_handlers()
    assert len(handlers) == 1
    h = handlers[0]
    assert h.maxBytes == 2 * 1024 * 1024      # MB → bytes
    assert h.backupCount == 3
    assert logfile.parent.is_dir()            # logs/ created

    logging.getLogger("jarvis.test.h2311").warning("rotating-marker-h2311")
    h.flush()
    assert "rotating-marker-h2311" in logfile.read_text(encoding="utf-8")


def test_log_to_file_via_setting_uses_data_root(monkeypatch, tmp_path, restore_logging):
    import core.log as log
    monkeypatch.delenv("JARVIS_LOG_FILE", raising=False)
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))   # data_root() → tmp
    monkeypatch.setattr(log, "_setting",
                        lambda cat, key, default: True if key == "log_to_file" else default)
    log.setup_logging(logging.INFO)

    handlers = _rotating_handlers()
    assert len(handlers) == 1
    # default path is <data_root>/logs/jarvis.log
    assert str(tmp_path) in handlers[0].baseFilename
    assert handlers[0].baseFilename.endswith("jarvis.log")


def test_log_to_file_bad_path_does_not_crash(monkeypatch, restore_logging):
    """An unwritable log path degrades to stderr-only logging, never a crash."""
    import core.log as log
    monkeypatch.setenv("JARVIS_LOG_FILE", "/proc/nonexistent-h2311/jarvis.log")
    log.setup_logging(logging.INFO)          # must not raise
    assert _rotating_handlers() == []        # handler not attached; stderr remains
