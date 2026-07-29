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
import inspect
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
    # The backend NAME is configuration, not a check. It must not appear under
    # `checks`, where a monitor would read it as a passing probe.
    assert "llm_backend" not in body["checks"]
    assert body["llm"]["configured_backend"] == "lmstudio"


def test_readyz_does_not_present_a_configured_name_as_a_measurement(monkeypatch):
    """The regression this endpoint shipped with: a router that has NEVER been
    probed must not produce anything that reads as a passing LLM check.

    `SimpleNamespace(name="lmstudio")` is exactly what an unreachable-but-configured
    backend looks like — the name is set the moment the owner picks a backend.
    """
    orch = SimpleNamespace(
        agents={"jarvis": object()}, channels={},
        llm_router=SimpleNamespace(name="lmstudio"),
    )
    monkeypatch.setattr(web, "orch", orch)
    body = TestClient(web.app).get("/readyz").json()

    # Nothing under `checks` may carry the backend's identity.
    assert not any("llm" in k for k in body["checks"]), body["checks"]
    # And the LLM block must say plainly that nothing was measured.
    assert body["llm"]["measured"] is None
    assert "never been probed" in body["llm"]["note"]


def test_readyz_labels_a_stale_availability_reading_as_stale(monkeypatch):
    """`detect()` runs at boot and on admin reconnect — never on a timer. An old
    reading must be reported with its age and marked stale, not as live health."""
    from agents.core.routers import ops

    llm = SimpleNamespace(name="lmstudio", _local_available=True)
    llm.probe_age_seconds = lambda: ops._LLM_PROBE_STALE_AFTER + 60
    orch = SimpleNamespace(agents={"jarvis": object()}, channels={}, llm_router=llm)
    monkeypatch.setattr(web, "orch", orch)
    body = TestClient(web.app).get("/readyz").json()

    measured = body["llm"]["measured"]
    assert measured["local_backend_reachable"] is True
    assert measured["stale"] is True
    assert measured["age_seconds"] >= ops._LLM_PROBE_STALE_AFTER
    assert "startup reading" in body["llm"]["note"]


def test_readyz_reports_a_fresh_reading_without_a_stale_warning(monkeypatch):
    """The honest happy path: recently probed and up → measured, fresh, no note."""
    llm = SimpleNamespace(name="lmstudio", _local_available=True)
    llm.probe_age_seconds = lambda: 2.0
    orch = SimpleNamespace(agents={"jarvis": object()}, channels={}, llm_router=llm)
    monkeypatch.setattr(web, "orch", orch)
    body = TestClient(web.app).get("/readyz").json()

    assert body["llm"]["measured"] == {
        "local_backend_reachable": True, "age_seconds": 2.0, "stale": False,
    }
    assert "note" not in body["llm"]


def test_readyz_reports_an_unreachable_backend_as_unreachable(monkeypatch):
    """A configured-but-down backend: the name is still reported, the measurement
    says false. Readiness stays 200 — availability does not gate it."""
    llm = SimpleNamespace(name="lmstudio", _local_available=False)
    llm.probe_age_seconds = lambda: 1.0
    orch = SimpleNamespace(agents={"jarvis": object()}, channels={}, llm_router=llm)
    monkeypatch.setattr(web, "orch", orch)
    resp = TestClient(web.app).get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["llm"]["configured_backend"] == "lmstudio"
    assert body["llm"]["measured"]["local_backend_reachable"] is False


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


def test_log_rotation_sizes_use_shared_env_int(monkeypatch, tmp_path, restore_logging):
    import core.log as log

    logfile = tmp_path / "logs" / "jarvis.log"
    monkeypatch.setenv("JARVIS_LOG_FILE", str(logfile))
    monkeypatch.setenv("JARVIS_LOG_MAX_MB", "not-an-int")
    monkeypatch.setenv("JARVIS_LOG_BACKUPS", "not-an-int")

    def fake_setting(_cat, key, default):
        if key == "log_max_mb":
            return 7
        if key == "log_backups":
            return 2
        return default

    monkeypatch.setattr(log, "_setting", fake_setting)
    path, max_bytes, backups = log._file_logging_config()
    assert path == str(logfile)
    assert max_bytes == 7 * 1024 * 1024
    assert backups == 2

    src = inspect.getsource(log._file_logging_config)
    assert 'env_int("JARVIS_LOG_MAX_MB"' in src
    assert 'env_int("JARVIS_LOG_BACKUPS"' in src
    assert "os.environ.get(env" not in src


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


def test_log_to_file_bad_path_does_not_crash(monkeypatch, tmp_path, restore_logging):
    """An unwritable log path degrades to stderr-only logging, never a crash."""
    import core.log as log
    # Cross-platform "cannot create the parent dir": nest the log file UNDER an
    # existing regular file, so os.makedirs() raises OSError on both POSIX and
    # Windows. (A literal /proc path is unwritable on Linux but a writable D:\proc
    # on Windows, so it can't be used as the portable bad path.)
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("i am a file, not a directory")
    monkeypatch.setenv("JARVIS_LOG_FILE", str(blocker / "sub" / "jarvis.log"))
    log.setup_logging(logging.INFO)          # must not raise
    assert _rotating_handlers() == []        # handler not attached; stderr remains


# ── probes bypass the per-IP rate limiter ─────────────────────────────────────

def test_probes_exempt_from_rate_limit(monkeypatch):
    """A non-localhost LB / Docker healthcheck must never be 429'd — else the
    supervisor evicts a healthy instance. /healthz and /readyz bypass the throttle
    even when an unauthenticated source IP is over budget."""
    monkeypatch.setattr(web, "RATE_LIMIT_PER_MIN", 2)
    monkeypatch.setattr(web, "USER_TOKEN", "")
    web._rate_hits.clear()
    client = TestClient(web.app)  # host 'testclient' — non-localhost, unauthenticated
    # /status (not a probe) hits the limit...
    assert client.get("/status").status_code != 429
    assert client.get("/status").status_code != 429
    assert client.get("/status").status_code == 429
    # ...but the probes keep answering 200/503, never 429, regardless of budget.
    for _ in range(5):
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code in (200, 503)


# ── serve.assert_safe_bind — fail-closed external bind (AUD-4 analog) ──────────

def test_assert_safe_bind_loopback_ok(monkeypatch):
    serve = _fresh_serve()
    for h in ("127.0.0.1", "localhost", "::1", ""):
        serve.assert_safe_bind(h)   # no raise


def test_assert_safe_bind_refuses_open_bind_without_auth(monkeypatch):
    serve = _fresh_serve()
    for var in ("JARVIS_USER_TOKEN", "JARVIS_ADMIN_TOKEN", "JARVIS_ALLOW_INSECURE_BIND"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(SystemExit):
        serve.assert_safe_bind("0.0.0.0")


def test_assert_safe_bind_allows_open_bind_with_token(monkeypatch):
    serve = _fresh_serve()
    monkeypatch.delenv("JARVIS_ALLOW_INSECURE_BIND", raising=False)
    monkeypatch.setenv("JARVIS_USER_TOKEN", "secret")
    serve.assert_safe_bind("0.0.0.0")   # authenticated deployment → allowed


def test_assert_safe_bind_allows_open_bind_with_ack(monkeypatch):
    serve = _fresh_serve()
    monkeypatch.delenv("JARVIS_USER_TOKEN", raising=False)
    monkeypatch.delenv("JARVIS_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("JARVIS_ALLOW_INSECURE_BIND", "1")
    serve.assert_safe_bind("0.0.0.0")   # explicit insecure acknowledgement → allowed
