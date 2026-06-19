"""Shared test fixtures and helpers."""

import importlib.util
import os
import sys
from pathlib import Path

# Gate network calls BEFORE any agents.web import (set at module level so it's
# guaranteed to take effect during pytest collection, before fixtures run).
# This prevents the oracle_bridge watcher and other external pollers from
# starting and hanging the suite on network timeouts.
os.environ.setdefault("JARVIS_TESTING", "1")
# HF-2: the per-IP HTTP rate limiter is off in the suite (TestClient connects as a
# single non-localhost host and some suites burst many requests). test_rate_limit_hf2
# monkeypatches a low limit to exercise it directly.
os.environ.setdefault("JARVIS_RATE_LIMIT", "0")
# SEC-5: plugin egress is strict-by-default in production, but the suite runs
# non-strict so plugin tests that hit real/mock hosts aren't blocked; the
# dedicated egress tests opt back into strict via monkeypatch.setenv.
os.environ.setdefault("JARVIS_STRICT_EGRESS", "0")

from fastapi import APIRouter, FastAPI

repo_root = Path(__file__).resolve().parent.parent

# HF-5: keep the audit signing key out of the real ~/.config during tests — point
# it at a gitignored repo-local dir so IntentLog() (constructed by the orchestrator)
# doesn't write to the developer's home. Tests that exercise key resolution set
# JARVIS_KEY_DIR themselves to an isolated tmp path.
# Parallel isolation (pytest-xdist): each worker gets its own runtime-data root +
# key dir so the file-backed stores (settings.db, audit.db, JSON stores) can't
# collide across processes. Must run before any store module is imported, so it's
# here at conftest module load. Serial runs (no xdist) keep the repo defaults.
_xdist_worker = os.environ.get("PYTEST_XDIST_WORKER")
if _xdist_worker:
    import tempfile
    _worker_home = tempfile.mkdtemp(prefix=f"jarvis-test-{_xdist_worker}-")
    os.environ["JARVIS_HOME"] = _worker_home  # data_root() honors this (F-08)
    os.environ["JARVIS_KEY_DIR"] = str(Path(_worker_home) / ".keys")
else:
    os.environ.setdefault("JARVIS_KEY_DIR", str(repo_root / "memory_logs" / ".keys"))
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


def make_app(module_path: str, fallback_name: str, prefix: str = "",
             fallback_routes: dict | None = None) -> FastAPI:
    """Create a FastAPI app that imports a real module or falls back to dummy routes.

    Args:
        module_path: dotted module path (e.g. 'agents.core.skills.calendar')
        fallback_name: short name for the fallback router
        prefix: URL prefix for routes
        fallback_routes: dict like {'GET /path': handler_fn} for the fallback
    """
    app = FastAPI()

    # Try real module first
    parts = module_path.split(".")
    file_path = repo_root.joinpath(*parts).with_suffix(".py")
    if file_path.exists():
        try:
            spec = importlib.util.spec_from_file_location(f"{fallback_name}_test", file_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            app.include_router(mod.router, prefix=prefix)
            return app
        except Exception:
            pass

    # Fallback: create dummy router
    router = APIRouter()
    if fallback_routes:
        for route_spec, handler in fallback_routes.items():
            method, path = route_spec.split(" ", 1)
            method = method.upper()
            if isinstance(handler, tuple):
                handler, status_code = handler
                router.add_api_route(path, handler, methods=[method], status_code=status_code)
            else:
                router.add_api_route(path, handler, methods=[method])

    app.include_router(router, prefix=prefix)
    return app


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _disable_user_guard():
    """HF-1: user-facing routes are guarded by web._user_guard. Its behavior is
    unit-tested directly in test_user_guard_hf1.py; here we override it to a
    no-op so the existing TestClient(web.app) suites — which connect as a
    non-localhost 'testclient' host — keep exercising those routes without a
    token. A test that wants the real guard pops this override itself."""
    try:
        from agents import web
    except Exception:
        yield
        return
    web.app.dependency_overrides[web._user_guard] = lambda: None
    # Routes extracted into core/routers/ depend on a lazy wrapper (the same guard,
    # resolved at request time to avoid an import cycle). Override it too so those
    # routes behave like the inline ones did under TestClient.
    try:
        from agents.core.routers._deps import user_guard as _ru
        web.app.dependency_overrides[_ru] = lambda: None
    except Exception:
        _ru = None
    try:
        yield
    finally:
        web.app.dependency_overrides.pop(web._user_guard, None)
        if _ru is not None:
            web.app.dependency_overrides.pop(_ru, None)
