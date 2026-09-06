#!/usr/bin/env python3
"""nerva_mcp_stdio.py — stdio bridge from a desktop MCP client to a running Nerva hub (H10.5).

Claude Desktop, Cursor and most editor MCP clients launch a *stdio* server: a
process that reads newline-delimited JSON-RPC on stdin and answers on stdout.
The Nerva hub exposes its governed MCP server over HTTP (``POST
/api/mcp/server/rpc``, off by default behind ``mcp.server_enabled``). This
script is the adapter between the two: every frame the client writes is
forwarded to the hub through the same SSRF-guarded Streamable HTTP transport
the hub's own MCP client uses (``agents/core/mcp/http_transport.py``), and
the hub's answer is written back with the client's original request id.

    {
      "mcpServers": {
        "nerva": {
          "command": "python",
          "args": ["/path/to/jarvis-hub/scripts/nerva_mcp_stdio.py"],
          "env": {"JARVIS_USER_TOKEN": "..."}
        }
      }
    }

Governance — nothing is widened here:

* the bridge does not build an orchestrator and cannot answer a tool call by
  itself; the hub's route keeps every gate (``mcp.server_enabled``, the
  user-token / localhost posture, OAuth when ``mcp.oauth_required``, the
  mutating-tool identity + Action Kernel gates);
* the credential is read from an **environment variable** (default
  ``JARVIS_USER_TOKEN``), never from argv — argv is visible to every process;
* logging goes to stderr only, so stdout carries nothing but protocol frames;
* the hub URL defaults to loopback; a remote hub must be given explicitly and
  still passes the SSRF guard (metadata hosts refused, DNS pinned).

Exit codes: 0 clean EOF from the client; 2 bad arguments / unusable URL.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from agents.core.mcp.http_transport import (  # noqa: E402
    MCPTransportError,
    StreamableHttpTransport,
    validate_mcp_url,
)
from agents.core.mcp.server import open_stdio_streams, run_stdio_loop  # noqa: E402

DEFAULT_HUB_URL = "http://127.0.0.1:8080"
DEFAULT_RPC_PATH = "/api/mcp/server/rpc"
DEFAULT_TOKEN_ENV = "JARVIS_USER_TOKEN"
HUB_URL_ENV = "NERVA_HUB_URL"

logger = logging.getLogger("nerva.mcp.stdio")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nerva_mcp_stdio",
        description="Bridge a stdio MCP client to a running Nerva hub over HTTP.",
    )
    parser.add_argument(
        "--hub-url",
        default=os.environ.get(HUB_URL_ENV) or DEFAULT_HUB_URL,
        help=f"Hub base URL (env {HUB_URL_ENV}; default {DEFAULT_HUB_URL}).",
    )
    parser.add_argument(
        "--rpc-path", default=DEFAULT_RPC_PATH,
        help=f"MCP JSON-RPC route on the hub (default {DEFAULT_RPC_PATH}).",
    )
    parser.add_argument(
        "--token-env", default=DEFAULT_TOKEN_ENV,
        help=f"Name of the env var holding the user/admin token (default {DEFAULT_TOKEN_ENV}). "
             "Never pass the token itself on the command line.",
    )
    parser.add_argument(
        "--admin", action="store_true",
        help="Send the token as X-Admin-Token instead of X-User-Token.",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout in seconds.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging on stderr.")
    return parser


def rpc_url(hub_url: str, rpc_path: str) -> str:
    return hub_url.strip().rstrip("/") + "/" + rpc_path.strip().lstrip("/")


def auth_headers(token: str, *, admin: bool = False) -> dict[str, str]:
    token = (token or "").strip()
    if not token:
        return {}
    return {"X-Admin-Token" if admin else "X-User-Token": token}


def make_forwarder(transport: StreamableHttpTransport):
    """Build the ``run_stdio_loop`` handler that proxies one frame to the hub.

    The transport numbers its own requests; the hub's reply comes back carrying
    the transport id, so it is re-stamped with the client's original ``id``
    before it is written to stdout. Notifications (no ``id``) are forwarded and
    produce no frame. A transport refusal (egress guard, oversized reply) is
    surfaced as a JSON-RPC error rather than a dead pipe.
    """

    async def _forward(message: dict) -> dict | None:
        method = str(message.get("method") or "")
        params = message.get("params")
        params = params if isinstance(params, dict) else {}
        if "id" not in message:
            try:
                await transport.notify(method, params)
            except MCPTransportError as exc:
                logger.warning("notification refused: %s", exc.reason)
            return None
        client_id = message.get("id")
        try:
            response = await transport.request(method, params)
        except MCPTransportError as exc:
            return {"jsonrpc": "2.0", "id": client_id,
                    "error": {"code": -32000, "message": f"transport: {exc.reason}"}}
        if not isinstance(response, dict) or not response:
            return {"jsonrpc": "2.0", "id": client_id,
                    "error": {"code": -32000, "message": "hub unreachable or refused the request"}}
        return {**response, "id": client_id}

    return _forward


async def serve(transport: StreamableHttpTransport, reader=None, writer=None) -> int:
    if reader is None or writer is None:
        reader, writer = await open_stdio_streams()
    try:
        return await run_stdio_loop(make_forwarder(transport), reader, writer)
    finally:
        await transport.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    url = rpc_url(args.hub_url, args.rpc_path)
    reason = validate_mcp_url(url)
    if reason:
        logger.error("unusable hub URL (%s)", reason)
        return 2
    token = os.environ.get(args.token_env, "")
    if not token:
        logger.warning(
            "no token in $%s — the hub accepts unauthenticated MCP only from localhost "
            "with JARVIS_USER_TOKEN unset", args.token_env,
        )
    try:
        transport = StreamableHttpTransport(
            url, auth_headers(token, admin=args.admin), name="stdio-bridge", timeout=args.timeout,
        )
    except MCPTransportError as exc:
        logger.error("cannot build transport (%s)", exc.reason)
        return 2
    logger.info("bridging stdio ⇄ %s", url)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve(transport))
    return 0


if __name__ == "__main__":
    sys.exit(main())
