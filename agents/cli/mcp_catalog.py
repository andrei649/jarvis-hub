"""``nerva mcp`` — the MCP server catalog and sign-in from the terminal (G9: H549, H550, H692).

* ``nerva mcp catalog [--search Q]`` lists the reviewed servers the hub can install
  (``GET /api/admin/mcp/catalog``).
* ``nerva mcp install <name>`` asks the hub for the install plan, prints exactly what would
  run, asks the owner to confirm (``--yes`` is that confirmation for a script), reads each
  secret the plan names from the terminal without echo (or one line each from stdin), and
  installs with the plan's digest (``POST /api/admin/mcp/catalog/{preview,install}``).
  Nothing starts: the owner connects after.
* ``nerva mcp login <server>`` signs in to an OAuth-protected HTTP server when the browser is
  on this machine and the hub may be elsewhere (H692): a one-shot listener on this machine's
  loopback receives the browser's return and relays only its code and state, with the start's
  binding, to the hub, which alone redeems them. The listener closes on the first callback,
  on Ctrl-C or after five minutes.
"""

from __future__ import annotations

import argparse
import getpass
import hmac
import http.server
import json
import threading
import webbrowser
from contextlib import suppress
from urllib.parse import parse_qs, quote, urlsplit

CATALOG = "/api/admin/mcp/catalog"
LOGIN_TIMEOUT = 300


def register_parser(verbs) -> None:
    mcp = verbs.add_parser("mcp", help="MCP servers: browse the catalog, install, sign in (admin)")
    actions = mcp.add_subparsers(dest="mcp_action", required=True, metavar="action")
    catalog = actions.add_parser("catalog", help="list the reviewed MCP servers the hub can install")
    catalog.add_argument("--search", "-q", default="", help="words in the name, description or hosts")
    catalog.add_argument("--json", action="store_true")
    install = actions.add_parser("install", help="install one catalog server: shows what runs, asks first")
    install.add_argument("name", help="the catalog name (`nerva mcp catalog` lists them)")
    install.add_argument("--as", dest="server_name", default=None, help="install under another server name")
    install.add_argument("--input", action="append", default=[], metavar="NAME=VALUE",
                         help="a non-secret value the server declares (a server URL to type)")
    install.add_argument("--yes", action="store_true", help="confirm the plan without asking (you read it)")
    install.add_argument("--json", action="store_true")
    login = actions.add_parser("login", help="sign in to an OAuth MCP server through this machine's browser")
    login.add_argument("server", help="the server's name on the hub")
    login.add_argument("--port", type=int, default=0, help="loopback port for the browser's return (0: any)")
    login.add_argument("--no-browser", action="store_true", help="print the address instead of opening it")


def _inputs(pairs: list[str]) -> dict[str, str]:
    out = {}
    for pair in pairs:
        name, sep, value = pair.partition("=")
        if not sep or not name.strip():
            raise argparse.ArgumentTypeError(f"--input takes NAME=VALUE, not {pair!r}")
        out[name.strip()] = value
    return out


def _clean(text, limit: int = 300) -> str:
    s = "".join(ch if ch.isprintable() else " " for ch in str(text or ""))
    return s[:limit]


def run(ns: argparse.Namespace, ctx) -> int:
    from .nerva import EXIT_FAILED, EXIT_OK

    action = ns.mcp_action
    client = ctx.client()
    if action == "catalog":
        reply = client.get(CATALOG + (f"?q={quote(ns.search)}" if ns.search else ""))
        if ns.json:
            ctx.dump(reply)
            return EXIT_OK
        rows = reply.get("entries") if isinstance(reply, dict) else None
        if not isinstance(rows, list):
            ctx.err.write("unexpected reply from the hub\n")
            return EXIT_FAILED
        ctx.say(f"MCP catalog @{_clean(str(reply.get('commit') or '')[:8], 8)}: "
                f"{len(rows)} of {reply.get('total')} shown")
        for row in rows:
            mark = "installed" if row.get("installed") else row.get("status")
            where = row.get("url") or row.get("command") or "(URL typed at install)"
            ctx.say(f"  {_clean(row.get('name'), 40):<20} {_clean(row.get('auth'), 8):<6} {_clean(mark, 16):<10} "
                    f"{_clean(where, 70)}")
            if row.get("description"):
                ctx.say(f"      {_clean(row.get('description'), 110)}")
        if not reply.get("http_client_enabled"):
            ctx.say("note: HTTP servers connect only once JARVIS_MCP_HTTP_CLIENT=1 is set on the hub")
        return EXIT_OK
    if action == "install":
        return _install(ns, ctx, client)
    if action == "login":
        return _login(ns, ctx, client)
    raise argparse.ArgumentTypeError("unknown mcp action")


def _install(ns, ctx, client) -> int:
    from .nerva import EXIT_FAILED, EXIT_OK

    body = {"name": ns.name, **({"server_name": ns.server_name} if ns.server_name else {})}
    values = _inputs(ns.input)
    if values:
        body["inputs"] = values
    reply = client.post(CATALOG + "/preview", body)
    plan = reply.get("plan") if isinstance(reply, dict) else None
    if not isinstance(plan, dict) or not plan.get("digest"):
        ctx.err.write("unexpected reply from the hub: no install plan\n")
        return EXIT_FAILED
    if plan.get("needs"):
        ctx.err.write("this server needs " + ", ".join(plan["needs"]) + ": pass --input NAME=VALUE\n")
        return EXIT_FAILED
    ctx.say(f"Install MCP server '{_clean(plan.get('name'), 64)}'"
            + (f" from the Hermes catalog @{_clean(str(plan.get('commit') or '')[:8], 8)}"
               if plan.get("origin") == "catalog" else " (not from the reviewed catalog)"))
    ctx.say(f"  will {_clean(plan.get('will_run'), 400)}")
    for key, value in (plan.get("env") or {}).items():
        ctx.say(f"  env {_clean(key, 64)}={_clean(value, 200)}")
    for spec in plan.get("secrets") or []:
        ctx.say(f"  secret {_clean(spec.get('name'), 64)}: {_clean(spec.get('prompt'), 120)} "
                "(stored encrypted on the hub, never in the config)")
    ctx.say(f"  trust: {_clean(plan.get('trust'), 20)}; starts {_clean(plan.get('starts'), 60)}")
    if plan.get("auth") == "oauth":
        ctx.say("  sign-in: OAuth in your browser after install (`nerva mcp login`)")
    if plan.get("name_taken"):
        ctx.err.write("a server with this name exists and is never overwritten: use --as NAME\n")
        return EXIT_FAILED
    if not ns.yes:
        ctx.out.write("Install it? [y/N] ")
        ctx.out.flush()
        if ctx.inp.readline().strip().lower() not in ("y", "yes"):
            ctx.say("not installed")
            return EXIT_FAILED
    secrets: dict[str, str] = {}
    for spec in plan.get("secrets") or []:
        name = str(spec.get("name"))
        prompt = f"{_clean(spec.get('prompt'), 120)} ({name}): "
        if getattr(ctx.inp, "isatty", lambda: False)():
            value = getpass.getpass(prompt)
        else:
            value = ctx.inp.readline().rstrip("\r\n")
        if value:
            secrets[name] = value
    body.update({"confirm": plan["digest"], **({"secrets": secrets} if secrets else {})})
    done = client.post(CATALOG + "/install", body)
    if ns.json:
        ctx.dump(done)
        return EXIT_OK
    ctx.say(_clean(done.get("message") if isinstance(done, dict) else done, 300))
    return EXIT_OK


class _OneShot(http.server.BaseHTTPRequestHandler):
    """Receives one browser return on loopback; keeps only ``code``, ``state``, ``error`` and
    ``iss``. A request without the expected state (a probe, a stale tab, another site's page
    pointing at the port) is answered 400 and ignored: it does not end the login."""

    result: dict = {}
    done = threading.Event()
    expected = ""

    def do_GET(self):  # noqa: N802 - http.server API
        parts = urlsplit(self.path)
        if parts.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        query = {k: v[0] for k, v in parse_qs(parts.query).items() if k in ("code", "state", "error", "iss")}
        expected = type(self).expected
        if not expected or not hmac.compare_digest(query.get("state", "").encode(), expected.encode()):
            self.send_response(400)
            self.end_headers()
            return
        type(self).result = query
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"<!doctype html><meta charset='utf-8'><title>Nerva</title>"
                         b"<p>Received. Return to the terminal; you can close this tab.</p>")
        type(self).done.set()

    def log_message(self, *args):  # the query holds a code: never logged
        return


def _login(ns, ctx, client) -> int:
    from .nerva import EXIT_FAILED, EXIT_OK

    handler = type("OneShot", (_OneShot,), {"result": {}, "done": threading.Event(), "expected": ""})
    path = f"/api/admin/mcp/{quote(ns.server, safe='')}/oauth"
    status = client.get(path)
    status = status if isinstance(status, dict) else {}
    pin = status.get("redirect_pin")
    host, wanted = "127.0.0.1", int(ns.port or 0)
    if isinstance(pin, str) and pin:
        # The vendor accepts exactly this address (localhost and 127.0.0.1 differ to it).
        parts = urlsplit(pin)
        host, wanted = parts.hostname or "127.0.0.1", int(parts.port or 0)
    elif not wanted:
        # Reuse the port the registered client already accepts, so no new registration.
        for known in status.get("loopback_redirects") or []:
            parts = urlsplit(str(known))
            if parts.port and parts.path == "/callback":
                host, wanted = parts.hostname or "127.0.0.1", parts.port
                break
    server, reason = None, ""
    for port_try in dict.fromkeys([wanted, 0] if not pin else [wanted]):
        try:
            server = http.server.HTTPServer(("127.0.0.1", port_try), handler)
            break
        except OSError as exc:
            reason = exc.strerror or str(exc)
    if server is None:
        ctx.err.write(f"cannot listen on 127.0.0.1:{wanted}: {reason}\n")
        return EXIT_FAILED
    server.timeout = 1
    port = server.server_address[1]
    if port != wanted:
        host = "127.0.0.1"
    redirect = f"http://{host}:{port}/callback"
    try:
        start = client.post(f"/api/admin/mcp/{quote(ns.server, safe='')}/oauth/start",
                            {"redirect": "loopback", "redirect_uri": redirect})
        if not isinstance(start, dict) or not start.get("authorization_url"):
            ctx.err.write("unexpected reply from the hub: no sign-in address\n")
            return EXIT_FAILED
        handler.expected = str(start.get("state") or "")
        ctx.say(f"Sign in to '{_clean(ns.server, 64)}': your browser opens "
                f"{_clean(start.get('authorize_host') or start.get('as_host'), 120)} "
                f"(authorization server {_clean(start.get('as_host'), 120)}).")
        ctx.say(f"Its token will be sent only to {_clean(start.get('server_origin'), 120)}.")
        ctx.say("Open this address in the browser on this machine:")
        ctx.say(_clean(start["authorization_url"], 4096))
        if not ns.no_browser:
            with suppress(Exception):  # the address is printed above
                webbrowser.open(start["authorization_url"])
        thread = threading.Thread(target=_serve_until, args=(server, handler), daemon=True)
        thread.start()
        if not handler.done.wait(LOGIN_TIMEOUT):
            ctx.err.write("no browser return within five minutes; nothing was signed in\n")
            return EXIT_FAILED
    finally:
        server.server_close()
    got = handler.result
    body = {"state": got.get("state", ""), "binding": start["binding"],
            **({"code": got["code"]} if got.get("code") else {}),
            **({"error": got["error"][:200]} if got.get("error") else {}),
            **({"iss": got["iss"][:2048]} if got.get("iss") else {})}
    done = client.post(f"/api/admin/mcp/{quote(ns.server, safe='')}/oauth/callback", body)
    if not isinstance(done, dict) or not done.get("ok"):
        ctx.err.write("the hub did not confirm the sign-in\n")
        return EXIT_FAILED
    ctx.say(f"Signed in to '{_clean(ns.server, 64)}'. Connect it from the MCP panel or the HUD.")
    return EXIT_OK


def _serve_until(server, handler) -> None:
    while not handler.done.is_set():
        try:
            server.handle_request()
        except (OSError, ValueError):
            return


def dumps(value) -> str:  # pragma: no cover - debugging helper
    return json.dumps(value, indent=2)
