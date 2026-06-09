"""Per-domain FastAPI routers extracted from the web.py god-object (CLN-3).

Each module here owns a cohesive group of routes that previously lived inline in
`agents/web.py`. Handlers reach the shared singletons/helpers lazily via
`from agents import web` (matching the cognition router), so there is no import
cycle: web.py imports and mounts these routers near the bottom of its module body.
"""
