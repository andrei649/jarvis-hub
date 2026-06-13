"""Lazy auth-guard dependencies for extracted routers (CLN-3).

The real guards live in `agents/web.py`. Importing them at a router module's top
level would risk a circular import (a test can import a router before web.py).
These thin wrappers resolve the guard lazily at request time, so router modules
never import web.py at load time.

Routers also get `get_orch` here (re-exported from core.app_state) so a single
import line covers guards + the orchestrator accessor.
"""

from fastapi import Request

from agents.core.app_state import get_orch  # noqa: F401  (re-exported for routers)


async def user_guard(request: Request):
    from agents import web
    return await web._user_guard(request)


async def admin_guard(request: Request):
    from agents import web
    return await web._admin_guard(request)
