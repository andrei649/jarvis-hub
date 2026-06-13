"""Lazy auth-guard dependencies for extracted routers (CLN-3).

The real guards live in `agents/web.py`. Importing them at a router module's top
level would risk a circular import (a test can import a router before web.py).
These thin wrappers resolve the guard lazily at request time, so router modules
never import web.py at load time. (Routers import `get_orch` directly from
`core.app_state`; it is intentionally not re-exported here, to keep this module
free of any import that would begin a cycle.)
"""

from fastapi import Request


async def user_guard(request: Request):
    from agents import web
    return await web._user_guard(request)


async def admin_guard(request: Request):
    from agents import web
    return await web._admin_guard(request)
