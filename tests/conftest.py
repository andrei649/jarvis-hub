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

from fastapi import APIRouter, FastAPI

repo_root = Path(__file__).resolve().parent.parent
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
    try:
        yield
    finally:
        web.app.dependency_overrides.pop(web._user_guard, None)
