"""Standalone entrypoint under Hermes's managed Python, never Hub's interpreter."""

from __future__ import annotations

import argparse
import functools
import hmac
import os
import sys
from pathlib import Path

# This script is deliberately executable without importing the agents package.
if __package__:
    from .bridge import BrokerClient
else:
    from bridge import BrokerClient

SOURCE_SHA = "0808ed8ec0420ef2c8e1363d919ef1d83fc4e5e7"


def install_guards(broker):
    """Replace actual handler/registry dispatch, not fail-open plugin hooks."""
    import tools.connectors as connector_exports
    from tools.connectors import dispatch as connectors
    from tools.registry import ToolRegistry
    from tui_gateway import server

    def guarded_method(name, handler):
        @functools.wraps(handler)
        def execute(rid, params):
            decision = broker.authorize("rpc", name, params)
            if decision["verdict"] != "grant":
                return {"jsonrpc": "2.0", "id": rid, "error": {"code": 4030,
                        "message": decision.get("reason", "Jarvis refused operation"),
                        "data": {"jarvis_verdict": decision["verdict"]}}}
            return handler(rid, params)
        return execute

    for name, handler in tuple(server._methods.items()):
        server._methods[name] = guarded_method(name, handler)
    original_register = server.register_method

    def register(name, handler):
        return original_register(name, guarded_method(name, handler))

    server.register_method = register
    original_dispatch = ToolRegistry.dispatch

    def dispatch(self, name, args, **kwargs):
        return broker.run("tool", name, args, lambda: original_dispatch(self, name, args, **kwargs))

    ToolRegistry.dispatch = dispatch
    original_connector = connectors.dispatch_connector_call

    def connector(name, args, tool_call_id):
        return broker.run("tool", name, args, lambda: original_connector(name, args, tool_call_id))

    connectors.dispatch_connector_call = connector
    connector_exports.dispatch_connector_call = connector


class PrivateTransport:
    """Only the controlled RPC connection and authenticated readiness are exposed.

    REST, PTY, plugin HTTP and SPA routes have independent effect paths and are
    deliberately unavailable through this worker until their own mediation lands.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        kind, path = scope["type"], scope.get("path", "")
        if kind == "websocket" and path != "/api/ws":
            await send({"type": "websocket.close", "code": 1008})
            return
        if kind == "http" and path != "/__jarvis__/ready":
            await send({"type": "http.response.start", "status": 403, "headers": []})
            await send({"type": "http.response.body", "body": b'RPC transport required'})
            return
        await self.app(scope, receive, send)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--host", choices=["127.0.0.1"], required=True)
    parser.add_argument("--port", type=int, required=True)
    options = parser.parse_args()
    if sys.version_info[:2] != (3, 14):
        raise SystemExit("Hermes worker requires managed Python 3.14")
    source, home = options.source.resolve(), options.home.resolve()
    if os.environ.get("HERMES_HOME") != str(home):
        raise SystemExit("Hermes worker home differs from supervisor")
    os.chdir(source)
    sys.path.insert(0, str(source))
    os.environ["HERMES_SERVE_HEADLESS"] = "1"
    broker = BrokerClient(os.environ["JARVIS_HERMES_BRIDGE_URL"], os.environ["JARVIS_HERMES_BRIDGE_TOKEN"], os.environ["JARVIS_HERMES_GENERATION"])
    # Bootstrap credentials never pass to native helper/CLI subprocesses.
    for name in ("JARVIS_HERMES_BRIDGE_URL", "JARVIS_HERMES_BRIDGE_TOKEN", "JARVIS_HERMES_GENERATION"):
        os.environ.pop(name, None)
    worker_token = os.environ["HERMES_DASHBOARD_SESSION_TOKEN"]
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from hermes_cli import web_server
    os.environ.pop("HERMES_DASHBOARD_SESSION_TOKEN", None)

    globals()["Request"] = Request  # FastAPI resolves the postponed annotation globally.

    install_guards(broker)

    @web_server.app.get("/__jarvis__/ready")
    async def ready(request: Request):
        supplied = request.headers.get("X-Jarvis-Runtime-Token", "")
        if not hmac.compare_digest(supplied, worker_token):
            return JSONResponse({"ready": False}, status_code=403)
        return {"ready": True, "generation": broker.generation, "source_sha": SOURCE_SHA}

    # Upstream mounts a catch-all headless page during app import. Readiness
    # must precede it, otherwise the HTTP server is live but never becomes ready.
    web_server.app.router.routes.insert(0, web_server.app.router.routes.pop())

    web_server.app.add_middleware(PrivateTransport)
    web_server.start_server(host=options.host, port=options.port, open_browser=False, headless=True, isolated=True)


if __name__ == "__main__":
    main()
