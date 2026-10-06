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
    from agents.core.env_config import env_str

    from .bridge import BrokerClient
else:
    # env_config is a standard-library-only leaf. The worker remains unable to
    # import the Hub package. Load it by file without adding Hub paths to
    # sys.path, where they would shadow native Hermes's `agent` package.
    import importlib.util

    from bridge import BrokerClient

    _env_spec = importlib.util.spec_from_file_location(
        "_jarvis_hermes_env_config", Path(__file__).resolve().parents[1] / "env_config.py")
    _env_module = importlib.util.module_from_spec(_env_spec)
    _env_spec.loader.exec_module(_env_module)
    env_str = _env_module.env_str

SOURCE_SHA = "0808ed8ec0420ef2c8e1363d919ef1d83fc4e5e7"


def native_rpc_completion(response, rid):
    """A native JSON-RPC error is a failed call, even when its handler returned."""
    if (type(response) is not dict or response.get("jsonrpc") != "2.0"
            or response.get("id") != rid or ("result" in response) == ("error" in response)):
        return False, {"state": "unknown"}
    if "result" in response:
        return True, {"state": "result", "value": response["result"]}
    error = response["error"]
    if (type(error) is not dict or type(error.get("code")) is not int
            or type(error.get("message")) is not str):
        return False, {"state": "unknown"}
    return False, {"state": "error", "value": {
        "code": error["code"], "message": error["message"]}}


def install_guards(broker):
    """Replace actual handler/registry dispatch, not fail-open plugin hooks."""
    import tools.connectors as connector_exports
    from tools.connectors import dispatch as connectors
    from tools.registry import ToolRegistry
    from tui_gateway import server

    def guarded_method(name, handler):
        @functools.wraps(handler)
        def execute(rid, params):
            decision = broker.authorize("rpc", name, params, request_id=str(rid))
            if decision["verdict"] != "grant":
                return {"jsonrpc": "2.0", "id": rid, "error": {"code": 4030,
                        "message": decision.get("reason", "Jarvis refused operation"),
                        "data": {"jarvis_verdict": decision["verdict"],
                                 "task_id": decision.get("task_id"),
                                 "disposition": decision.get("disposition")}}}
            try:
                result = handler(rid, params)
            except BaseException:
                broker.complete(decision, ok=False, outcome={"state": "unknown"})
                raise
            ok, outcome = native_rpc_completion(result, rid)
            broker.complete(decision, ok=ok, outcome=outcome)
            return result
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
    if env_str("HERMES_HOME") != str(home):
        raise SystemExit("Hermes worker home differs from supervisor")
    os.chdir(source)
    sys.path.insert(0, str(source))
    os.environ.update({"HERMES_SERVE_HEADLESS": "1"})
    # Pop bootstrap credentials before importing any native Hermes module.
    broker = BrokerClient(os.environ.pop("JARVIS_HERMES_BRIDGE_URL"),
                          os.environ.pop("JARVIS_HERMES_BRIDGE_TOKEN"),
                          os.environ.pop("JARVIS_HERMES_GENERATION"))
    # Bootstrap credentials never pass to native helper/CLI subprocesses.
    worker_token = env_str("HERMES_DASHBOARD_SESSION_TOKEN")
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
