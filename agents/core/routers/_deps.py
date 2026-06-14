"""Lazy auth-guard dependencies for extracted routers (CLN-3).

The real guards live in `agents/web.py`. Router modules must NOT import web at
load time — importing web executes the app construction + `include_router(...)`
of these very routers, an import cycle. So these wrappers resolve the guard at
REQUEST time, and they look web up in `sys.modules` rather than `import`-ing it:
the guards only ever run while a request is in flight, by which point
`agents.web` is always loaded, and a `sys.modules` lookup is not a static import
edge — so this module stays a leaf and the routers↔web import cycle disappears
(CodeQL flagged the `from agents import web` form on every router import).
Routers get `get_orch` from `core.app_state` (same sys.modules pattern), so the
routers package has no static import back into `agents.web` at all.
"""

import sys

from fastapi import Request


def _web():
    # Always present at request time (the app is running). Not an import edge.
    return sys.modules.get("agents.web")


async def user_guard(request: Request):
    return await _web()._user_guard(request)


async def admin_guard(request: Request):
    return await _web()._admin_guard(request)
