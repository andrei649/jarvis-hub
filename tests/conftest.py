"""Shared test fixtures and helpers."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))


@pytest.fixture(scope="session", autouse=True)
def _set_jarvis_testing_env():
    """Ensure JARVIS_TESTING=1 for the entire test session.

    This gates network-touching startup code (oracle watcher, external
    event watchers, etc.) so the suite runs fully offline and never hangs
    waiting for GitHub or other external services.
    """
    os.environ["JARVIS_TESTING"] = "1"
    yield
    # Leave the variable set — the process exits after tests anyway.


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
