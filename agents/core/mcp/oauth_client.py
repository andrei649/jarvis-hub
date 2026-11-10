"""oauth_client.py — sign in to a remote MCP server that requires OAuth (G9 / H550, H692).

Nerva's MCP client speaks Streamable HTTP (``http_transport.py``); this module gives it the
OAuth 2.1 authorization-code flow the MCP authorization spec asks of a client. It follows the
shape of Hermes's ``tools/mcp_oauth*.py`` (a reference; nothing is adopted), narrowed:

* **Discovery.** RFC 9728 protected-resource metadata at the server's origin
  (``/.well-known/oauth-protected-resource[/<path>]``) names the authorization server; its
  ``resource`` must be the server's own origin. RFC 8414 / OpenID metadata of that server
  follows, and its ``issuer`` must be the URL it was fetched for. With no resource metadata
  the server's own origin is taken as the authorization server (the 2025-03-26 rule).
  Endpoints must be https (http only for a loopback or private-address literal, as the MCP
  transport allows). A server that advertises PKCE methods must offer ``S256``.
* **Client identity.** A pinned ``client_id`` (manifest ``auth.oauth`` or the owner) wins;
  otherwise RFC 7591 dynamic client registration when the server offers it (a public
  client, ``token_endpoint_auth_method: none``), remembered per redirect URI. No CIMD.
* **Flow.** PKCE S256, a random ``state``, RFC 8707 ``resource`` on the authorization and
  token requests. At most :data:`MAX_PENDING` flows wait at once, each for
  :data:`FLOW_TTL` seconds; a new start for a server replaces its older one.
* **Owner binding (H692).** A start returns a random ``binding`` that only the owner's
  client sees (the admin-guarded answer, and an HttpOnly cookie scoped to the callback
  path). A callback is redeemed only with the matching state **and** binding, compared in
  constant time, and only once. The redirect is either the hub's own callback route or a
  loopback address on the owner's machine (``http://127.0.0.1:<port>/…``) whose listener
  relays code and state to the hub; the hub never redirects anywhere itself, so there is
  no open redirect, and the relay never redeems anything.
* **Tokens.** In the hub's encrypted secret store (``mcp.oauth.<server>.access`` /
  ``.refresh`` / ``.meta`` / ``.client``), never in settings or the server config. The
  access token is attached only to requests for the server's own origin (the origin the
  resource metadata vouched for), refreshed when it is within a minute of expiry (one
  refresh per server at a time), and revoked (RFC 7009, best effort) and deleted when the
  owner signs out or removes the server.
* **Every hop is egress.** Each request goes through the MCP transport's guarded client
  (``PluginHTTPClient``: SSRF resolve-and-pin, egress ledger, breaker), without redirects.
  The e-stop refuses a start, a callback and a refresh.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

logger = logging.getLogger("jarvis.mcp.oauth_client")

FLOW_TTL = 300
MAX_PENDING = 8
REFRESH_MARGIN = 60
MAX_METADATA_BYTES = 256 * 1024
TOKEN_PREFIX = "mcp.oauth."  # nosec B105 - a secret-store name prefix, not a secret
HUB_CALLBACK_PATH = "/api/oauth/mcp/callback"
COOKIE_PREFIX = "nerva_mcp_oauth_"
CLIENT_NAME = "Nerva"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]", "::1"})
_PATH_RE = re.compile(r"^/[A-Za-z0-9/_.-]{0,63}$")
_SERVER_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class OAuthError(Exception):
    """A refused or failed step, with a stable ``reason`` the routes and the HUD show."""

    def __init__(self, reason: str, message: str = "", status: int = 400) -> None:
        super().__init__(message or reason)
        self.reason = reason
        self.message = message or reason
        self.status = status


@dataclass
class Flow:
    state: str
    binding: str
    verifier: str
    server: str
    server_url: str
    redirect_uri: str
    relay: bool
    token_endpoint: str
    issuer: str
    revocation_endpoint: str | None
    client_id: str
    client_secret: str | None
    auth_method: str
    resource: str
    scope: str | None
    hub_origin: str | None = None
    iss_required: bool = False
    created: float = field(default_factory=time.time)

    def expired(self, now: float | None = None) -> bool:
        return (now or time.time()) - self.created > FLOW_TTL


_FLOWS: dict[str, Flow] = {}
_LOCKS: dict[str, asyncio.Lock] = {}
_REJECTED: set[str] = set()


def _http_factory(server: str):
    from agents.core.http_client import PluginTimeouts
    from agents.core.mcp.http_transport import _MCPHTTPClient

    return _MCPHTTPClient(f"mcp-oauth:{server}", timeouts=PluginTimeouts(connect=5.0, read=10.0, total=15.0))


#: Test seam: ``server -> PluginHTTPClient`` (tests pass a MockTransport-backed one).
HTTP_FACTORY: Callable[[str], Any] = _http_factory


# ── small helpers ────────────────────────────────────────────────────────────

def origin_of(url: str) -> str:
    parts = urlsplit(str(url or ""))
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").lower()
    port = parts.port or (443 if scheme == "https" else 80)
    if ":" in host:
        host = f"[{host}]"
    return f"{scheme}://{host}:{port}"


_SECOND_LEVEL = frozenset({"co", "com", "net", "org", "gov", "ac", "edu", "ne", "or", "go"})


def registrable(host: str) -> str:
    """The registrable part of a DNS name, approximately (no public-suffix list ships with
    Nerva): the last two labels, or three under a two-letter country code's generic second
    level (``example.co.uk``). An IP literal is itself."""
    host = (host or "").lower().rstrip(".")
    labels = host.split(".")
    if _is_literal(host) or len(labels) <= 2:
        return host
    if len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _is_literal(host: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address((host or "").strip("[]"))
    except ValueError:
        return False
    return True


def _local_host(host: str) -> bool:
    """A loopback/private literal or ``localhost``: what the egress client dials in LAN mode."""
    from agents.core.http_client import _address_mode

    return _address_mode(host) == "lan"


_LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def _same_machine(a: str, b: str) -> bool:
    a, b = (a or "").lower().strip("[]"), (b or "").lower().strip("[]")
    if a == b:
        return True
    loop = {"127.0.0.1", "localhost", "::1"}
    return a in loop and b in loop


def endpoint_problem(url: Any, *, server_url: str, hub_origin: str | None = None) -> str | None:
    """Why an OAuth endpoint may not be called (None when it may).

    * printable, no spaces, no user info or fragment; https, or http only to a loopback or
      private literal;
    * a loopback/private (LAN) endpoint only when the MCP server itself is on that same host:
      a public server's metadata cannot steer a request at the hub's own network;
    * never the hub's own address, nor any loopback address on the hub's port."""
    if not isinstance(url, str) or not url or not url.isprintable() or any(ch in url for ch in " \t\\"):
        return "not a plain URL"
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        return "bad port"
    host = (parts.hostname or "").lower()
    if parts.username or parts.password or not host or parts.fragment:
        return "user info, fragment or no host"
    server_host = (urlsplit(server_url).hostname or "").lower()
    if _local_host(host):
        if not _same_machine(host, server_host):
            return "a local address the MCP server does not live on"
        if parts.scheme not in ("http", "https"):
            return "not http(s)"
    elif parts.scheme != "https":
        return "not https"
    if hub_origin:
        hub = urlsplit(hub_origin)
        hub_port = hub.port or (443 if hub.scheme == "https" else 80)
        eff_port = port or (443 if parts.scheme == "https" else 80)
        if origin_of(url) == origin_of(hub_origin):
            return "the hub's own address"
        if eff_port == hub_port and (host in _LOOPBACK_NAMES or _same_machine(host, hub.hostname or "")):
            return "the hub's own address"
    return None


def _endpoint_ok(url: Any, server_url: str = "", hub_origin: str | None = None) -> bool:
    return endpoint_problem(url, server_url=server_url, hub_origin=hub_origin) is None


def _on_issuer(url: str, issuer: str) -> bool:
    """An endpoint belongs to the issuer when it is on the issuer's host or, for a DNS name,
    the same registrable domain (``auth.example.com`` for ``mcp.example.com``)."""
    a = (urlsplit(url).hostname or "").lower()
    b = (urlsplit(issuer).hostname or "").lower()
    if a == b:
        return True
    if _is_literal(a) or _is_literal(b):
        return False
    return registrable(a) == registrable(b) and "." in registrable(a)


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _check_server(server: str) -> None:
    if not _SERVER_RE.match(server or ""):
        raise OAuthError("invalid_server_name", "OAuth sign-in needs a server name of letters, digits, - and _")


def _estop() -> None:
    from agents.core import estop

    if estop.is_engaged():
        raise OAuthError("estop_engaged", "the emergency stop is engaged; sign-in is paused", status=409)


def validate_redirect(redirect_uri: str, *, hub_base: str | None = None) -> bool:
    """True for the hub's own callback route or a loopback relay address; False otherwise.
    Returns whether it is a relay (loopback) redirect; raises for anything else."""
    raw = str(redirect_uri or "").strip()
    parts = urlsplit(raw)
    if parts.query or parts.fragment or parts.username or parts.password:
        raise OAuthError("invalid_redirect", "a redirect address carries no query, fragment or user info")
    if hub_base is not None and raw == hub_base.rstrip("/") + HUB_CALLBACK_PATH:
        if parts.scheme == "https":
            return False
        if parts.scheme == "http" and (parts.hostname or "").lower() in ("127.0.0.1", "localhost", "::1"):
            return False
        # A code over plain http crosses the network in clear text.
        raise OAuthError("insecure_redirect",
                         "the hub is reached over plain http from another machine: open it over https, "
                         "or sign in with `nerva mcp login` (a loopback return on your machine)")
    host = (parts.netloc.rsplit(":", 1)[0] if parts.port else parts.netloc).lower()
    if parts.scheme != "http" or host not in _LOOPBACK_HOSTS:
        raise OAuthError("invalid_redirect",
                         "the redirect is either the hub's own callback or http://127.0.0.1:<port>/<path>")
    try:
        port = parts.port
    except ValueError:
        port = None
    if not port or port < 1024:
        raise OAuthError("invalid_redirect", "a loopback redirect names a port from 1024 up")
    if not _PATH_RE.match(parts.path or ""):
        raise OAuthError("invalid_redirect", "a loopback redirect has a short plain path")
    return True


async def _get_json(client, url: str) -> dict | None:
    resp = await client.get(url, headers={"Accept": "application/json"}, follow_redirects=False)
    try:
        if resp.status_code != 200:
            return None
        body = resp.content
        if len(body) > MAX_METADATA_BYTES:
            return None
        data = json.loads(body.decode("utf-8"))
        return data if isinstance(data, dict) else None
    except (ValueError, UnicodeDecodeError):
        return None
    finally:
        await resp.aclose()


async def _post_form(client, url: str, data: dict, *, auth: tuple[str, str] | None = None) -> tuple[int, dict]:
    headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
    if auth:
        raw = f"{auth[0]}:{auth[1]}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
    resp = await client.post(url, content=urlencode(data).encode(), headers=headers, follow_redirects=False)
    try:
        body = resp.content
        if len(body) > MAX_METADATA_BYTES:
            return resp.status_code, {}
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except (ValueError, UnicodeDecodeError):
            payload = {}
        return resp.status_code, payload if isinstance(payload, dict) else {}
    finally:
        await resp.aclose()


async def _post_json(client, url: str, body: dict) -> tuple[int, dict]:
    resp = await client.post(url, json=body, headers={"Accept": "application/json"}, follow_redirects=False)
    try:
        raw = resp.content
        if len(raw) > MAX_METADATA_BYTES:
            return resp.status_code, {}
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            payload = {}
        return resp.status_code, payload if isinstance(payload, dict) else {}
    finally:
        await resp.aclose()


# ── discovery ────────────────────────────────────────────────────────────────

async def discover(client, server_url: str, *, hub_origin: str | None = None) -> dict:
    """``{issuer, authorization_endpoint, token_endpoint, registration_endpoint?,
    revocation_endpoint?, resource, scopes, methods}`` for the server, or OAuthError."""
    parts = urlsplit(server_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    path = parts.path.rstrip("/")
    prm = None
    for candidate in ([f"{origin}/.well-known/oauth-protected-resource{path}"] if path else []) + \
            [f"{origin}/.well-known/oauth-protected-resource"]:
        prm = await _get_json(client, candidate)
        if prm is not None:
            break
    resource = server_url
    scopes: list[str] = []
    if prm is not None:
        named = prm.get("resource")
        if isinstance(named, str) and named:
            if origin_of(named) != origin_of(server_url):
                raise OAuthError("resource_mismatch",
                                 "the server's metadata names another origin as its resource")
            resource = named
        servers = prm.get("authorization_servers")
        if not isinstance(servers, list) or not servers or not isinstance(servers[0], str):
            raise OAuthError("no_authorization_server", "the server names no authorization server")
        issuer = servers[0].rstrip("/")
        if isinstance(prm.get("scopes_supported"), list):
            scopes = [s for s in prm["scopes_supported"] if isinstance(s, str)][:32]
    else:
        issuer = origin
    problem = endpoint_problem(issuer, server_url=server_url, hub_origin=hub_origin)
    if problem:
        raise OAuthError("insecure_endpoint", f"the authorization server: {problem}")
    ip = urlsplit(issuer)
    io, ipath = f"{ip.scheme}://{ip.netloc}", ip.path.rstrip("/")
    candidates = ([f"{io}/.well-known/oauth-authorization-server{ipath}",
                   f"{io}/.well-known/openid-configuration{ipath}",
                   f"{io}{ipath}/.well-known/openid-configuration"] if ipath else
                  [f"{io}/.well-known/oauth-authorization-server", f"{io}/.well-known/openid-configuration"])
    meta = None
    for candidate in candidates:
        meta = await _get_json(client, candidate)
        if meta is not None:
            break
    if meta is None:
        raise OAuthError("no_authorization_metadata", "the authorization server publishes no metadata")
    if str(meta.get("issuer") or "").rstrip("/") != issuer:
        raise OAuthError("issuer_mismatch", "the authorization server's metadata names another issuer")
    for key in ("authorization_endpoint", "token_endpoint", "registration_endpoint", "revocation_endpoint"):
        value = meta.get(key)
        if value is None and key in ("registration_endpoint", "revocation_endpoint"):
            continue
        problem = endpoint_problem(value, server_url=server_url, hub_origin=hub_origin)
        if problem:
            raise OAuthError("insecure_endpoint", f"{key}: {problem}")
        # Mix-up defence: every endpoint belongs to the issuer that vouched for it, so a
        # server cannot send the browser to one authorization server and the code (with its
        # PKCE verifier) to another.
        if not _on_issuer(value, issuer):
            raise OAuthError("endpoint_not_on_issuer", f"{key} is not on the authorization server's own host")
    methods = meta.get("code_challenge_methods_supported")
    if isinstance(methods, list) and "S256" not in methods:
        raise OAuthError("pkce_unsupported", "the authorization server does not offer PKCE S256")
    # Only the scopes the resource names are asked for, never the server's whole list.
    return {
        "issuer": issuer,
        "authorization_endpoint": meta["authorization_endpoint"],
        "token_endpoint": meta["token_endpoint"],
        "registration_endpoint": meta.get("registration_endpoint"),
        "revocation_endpoint": meta.get("revocation_endpoint"),
        "auth_methods": [m for m in (meta.get("token_endpoint_auth_methods_supported") or [])
                         if isinstance(m, str)],
        "resource": resource,
        "scopes": scopes,
        "iss_in_response": meta.get("authorization_response_iss_parameter_supported") is True,
    }


# ── the secret store ─────────────────────────────────────────────────────────

def _store():
    from agents.core.mcp.catalog import _store as catalog_store

    return catalog_store()


def _name(server: str, part: str) -> str:
    return f"{TOKEN_PREFIX}{server}.{part}"


def _read_json(server: str, part: str) -> dict:
    try:
        raw = _store().get(_name(server, part))
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.warning("MCP OAuth record unreadable (server=%s part=%s)", server, part)
        return {}


def _read(server: str, part: str) -> str | None:
    try:
        return _store().get(_name(server, part))
    except Exception:
        logger.warning("MCP OAuth record unreadable (server=%s part=%s)", server, part)
        return None


def has_tokens(server: str) -> bool:
    return bool(_read(server, "access") or _read(server, "refresh"))


# ── client identity ──────────────────────────────────────────────────────────

def _pinned_value(server: str, value: Any) -> str | None:
    """A manifest pin: a literal, or ``${NAME}`` read from the server's stored secrets."""
    if value is None:
        return None
    text = str(value)
    m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", text)
    if m:
        from agents.core.mcp.catalog import read_secret

        return read_secret(server, m.group(1))
    return text


async def _client_identity(client, server: str, meta: dict, redirect_uri: str,
                           pins: dict, *, hub_origin: str | None = None,
                           server_url: str = "") -> tuple[str, str | None, str]:
    pinned = _pinned_value(server, pins.get("client_id"))
    if pinned:
        secret = _pinned_value(server, pins.get("client_secret"))
        return pinned, secret, _auth_method(meta, secret)
    # One registered client per server and issuer. A new return address re-registers it with
    # the addresses it already had (at most four), so a login does not mint a client each time.
    known = _read_json(server, "client")
    redirects = known.get("redirect_uris") if isinstance(known.get("redirect_uris"), list) else (
        [known["redirect_uri"]] if known.get("redirect_uri") else [])
    if known.get("issuer") == meta["issuer"] and redirect_uri in redirects and known.get("client_id"):
        secret = known.get("client_secret") or None
        return known["client_id"], secret, _auth_method(meta, secret)
    endpoint = meta.get("registration_endpoint")
    if not endpoint:
        raise OAuthError("client_registration_unavailable",
                         "the server offers no dynamic registration and no client id is pinned")
    if endpoint_problem(endpoint, server_url=server_url, hub_origin=hub_origin):
        raise OAuthError("insecure_endpoint", "the registration endpoint is not allowed")
    keep = [r for r in redirects if isinstance(r, str)] if known.get("issuer") == meta["issuer"] else []
    redirects = list(dict.fromkeys([*keep, redirect_uri]))[-4:]
    status, body = await _post_json(client, endpoint, {
        "client_name": CLIENT_NAME,
        "redirect_uris": redirects,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",  # nosec B105 - a public PKCE client, no secret
    })
    client_id = body.get("client_id") if isinstance(body.get("client_id"), str) else ""
    if status not in (200, 201) or not client_id:
        raise OAuthError("registration_failed", f"dynamic client registration was refused ({status})", status=502)
    secret = body.get("client_secret") if isinstance(body.get("client_secret"), str) else None
    _store().set(_name(server, "client"), json.dumps({
        "issuer": meta["issuer"], "redirect_uris": redirects, "client_id": client_id,
        **({"client_secret": secret} if secret else {}), "registered_at": int(time.time()),
    }))
    return client_id, secret, _auth_method(meta, secret)


def _auth_method(meta: dict, secret: str | None) -> str:
    if not secret:
        return "none"
    methods = meta.get("auth_methods") or []
    if "client_secret_basic" in methods and "client_secret_post" not in methods:
        return "client_secret_basic"
    return "client_secret_post"


# ── the flow ─────────────────────────────────────────────────────────────────

def _prune(now: float | None = None) -> None:
    for state in [s for s, f in _FLOWS.items() if f.expired(now)]:
        _FLOWS.pop(state, None)


async def start(server: str, server_url: str, *, redirect_uri: str, hub_base: str | None,
                pins: dict | None = None, scope: str | None = None) -> dict:
    """Begin a sign-in: discovery, client identity, PKCE, state and owner binding."""
    _check_server(server)
    _estop()
    from agents.core.mcp.http_transport import validate_mcp_url

    if validate_mcp_url(server_url):
        raise OAuthError("not_http_server", "OAuth sign-in is for a server reached over HTTP")
    relay = validate_redirect(redirect_uri, hub_base=hub_base)
    pinned_redirect = _redirect_pin(pins or {})
    if pinned_redirect and redirect_uri.rstrip("/") != pinned_redirect:
        raise OAuthError("redirect_pinned",
                         f"this server accepts only {pinned_redirect} as the return address: "
                         "sign in with `nerva mcp login` on the machine with the browser")
    hub_origin = origin_of(hub_base) if hub_base else None
    problem = endpoint_problem(server_url, server_url=server_url, hub_origin=hub_origin)
    if problem:
        raise OAuthError("insecure_endpoint", f"the server: {problem}")
    _prune()
    client = HTTP_FACTORY(server)
    try:
        meta = await discover(client, server_url, hub_origin=hub_origin)
        known = _read(server, "issuer_pin")
        if known and known != meta["issuer"]:
            # MINOR-2: a server that first signed in at one authorization server and now names
            # another gets no client secret and no code: the owner re-adds it to trust a new one.
            raise OAuthError("issuer_changed",
                             f"this server signed in at {urlsplit(known).hostname} before and now names "
                             f"{urlsplit(meta['issuer']).hostname}; remove and add it again to trust that")
        client_id, client_secret, method = await _client_identity(client, server, meta, redirect_uri, pins or {},
                                                                  hub_origin=hub_origin, server_url=server_url)
    except OAuthError:
        raise
    except Exception as exc:
        logger.warning("MCP OAuth discovery failed (server=%s type=%s)", server, type(exc).__name__)
        raise OAuthError("discovery_failed", "the server's sign-in details could not be read", status=502) from exc
    finally:
        await client.close()
    for state in [s for s, f in _FLOWS.items() if f.server == server]:
        _FLOWS.pop(state, None)
    if len(_FLOWS) >= MAX_PENDING:
        raise OAuthError("too_many_pending", f"at most {MAX_PENDING} sign-ins can wait at once", status=429)
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(32)
    binding = secrets.token_urlsafe(32)
    wanted_scope = scope or (pins or {}).get("scope") or (" ".join(meta["scopes"]) if meta["scopes"] else None)
    flow = Flow(state=state, binding=binding, verifier=verifier, server=server, server_url=server_url,
                redirect_uri=redirect_uri, relay=relay, token_endpoint=meta["token_endpoint"],
                issuer=meta["issuer"], revocation_endpoint=meta.get("revocation_endpoint"),
                client_id=client_id, client_secret=client_secret, auth_method=method,
                resource=meta["resource"], scope=str(wanted_scope) if wanted_scope else None,
                hub_origin=hub_origin, iss_required=meta["iss_in_response"])
    _FLOWS[state] = flow
    query = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
             "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
             "resource": flow.resource}
    if flow.scope:
        query["scope"] = flow.scope
    auth = urlsplit(meta["authorization_endpoint"])
    joined = (auth.query + "&" if auth.query else "") + urlencode(query)
    url = urlunsplit((auth.scheme, auth.netloc, auth.path, joined, ""))
    return {"authorization_url": url, "state": state, "binding": binding, "expires_in": FLOW_TTL,
            "redirect_uri": redirect_uri, "relay": relay, "issuer": meta["issuer"],
            # The host the browser is sent to (what the owner should check), and the issuer's.
            "authorize_host": auth.hostname, "as_host": urlsplit(meta["issuer"]).hostname,
            "server_origin": origin_of(server_url), "scope": flow.scope}


def _match(state: str) -> Flow | None:
    found = None
    for key, flow in list(_FLOWS.items()):
        if hmac.compare_digest(key.encode(), str(state or "").encode()):
            found = flow
    return found


def cancel(server: str) -> int:
    gone = [s for s, f in _FLOWS.items() if f.server == server]
    for state in gone:
        _FLOWS.pop(state, None)
    return len(gone)


def pending(server: str) -> bool:
    _prune()
    return any(f.server == server for f in _FLOWS.values())


def flow_server(state: str) -> str | None:
    flow = _match(state)
    return flow.server if flow else None


async def complete(state: str, code: str, binding: str, *, server: str | None = None,
                   error: str | None = None, iss: str | None = None) -> dict:
    """Redeem a callback: the state must match a waiting flow and the binding its owner's.
    Single use: the flow is gone after this call whatever happens."""
    flow = _match(state)
    if flow is None or flow.expired():
        if flow is not None:
            _FLOWS.pop(flow.state, None)
        raise OAuthError("unknown_state", "this sign-in is unknown or expired; start it again")
    if not binding or not hmac.compare_digest(flow.binding.encode(), str(binding).encode()):
        # A foreign callback does not burn the owner's flow: it is refused and left waiting.
        raise OAuthError("binding_mismatch", "this sign-in was not started from your session", status=403)
    if server is not None and server != flow.server:
        raise OAuthError("server_mismatch", "this sign-in belongs to another server", status=403)
    _FLOWS.pop(flow.state, None)
    # RFC 9207: a response naming another issuer is refused always; one naming none is refused
    # when the authorization server said it names itself.
    if iss is not None and iss.rstrip("/") != flow.issuer:
        raise OAuthError("issuer_mismatch", "the sign-in came back from another authorization server")
    if iss is None and flow.iss_required:
        raise OAuthError("issuer_missing", "the authorization server did not say who answered")
    if error:
        raise OAuthError("authorization_denied", "the sign-in was not approved")
    if not code or len(code) > 4096 or any(ch in code for ch in "\r\n\x00"):
        raise OAuthError("invalid_code", "the callback carried no usable code")
    _estop()
    if endpoint_problem(flow.token_endpoint, server_url=flow.server_url, hub_origin=flow.hub_origin):
        raise OAuthError("insecure_endpoint", "the token endpoint is no longer allowed")
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": flow.redirect_uri,
            "client_id": flow.client_id, "code_verifier": flow.verifier, "resource": flow.resource}
    basic = None
    if flow.auth_method == "client_secret_post" and flow.client_secret:
        form["client_secret"] = flow.client_secret
    elif flow.auth_method == "client_secret_basic" and flow.client_secret:
        basic = (flow.client_id, flow.client_secret)
    client = HTTP_FACTORY(flow.server)
    try:
        status, body = await _post_form(client, flow.token_endpoint, form, auth=basic)
    except Exception as exc:
        logger.warning("MCP OAuth token exchange failed (server=%s type=%s)", flow.server, type(exc).__name__)
        raise OAuthError("token_exchange_failed", "the token exchange did not answer", status=502) from exc
    finally:
        await client.close()
    _save_tokens(flow, status, body)
    return {"server": flow.server, "issuer": flow.issuer, "scope": body.get("scope") or flow.scope,
            "expires_at": _read_json(flow.server, "meta").get("expires_at"),
            "refreshable": bool(body.get("refresh_token")), "relay": flow.relay}


def _save_tokens(flow: Flow, status: int, body: dict) -> None:
    access = body.get("access_token")
    if status != 200 or not isinstance(access, str) or not access:
        raise OAuthError("token_exchange_failed", f"the authorization server refused the code ({status})",
                         status=502)
    token_type = str(body.get("token_type") or "Bearer")
    if token_type.lower() != "bearer":
        raise OAuthError("unsupported_token_type", "the server issued a token type Nerva does not send")
    store = _store()
    store.set(_name(flow.server, "access"), access)
    refresh = body.get("refresh_token")
    if isinstance(refresh, str) and refresh:
        store.set(_name(flow.server, "refresh"), refresh)
    expires = body.get("expires_in")
    expires_at = int(time.time() + float(expires)) if isinstance(expires, (int, float)) and expires > 0 else None
    store.set(_name(flow.server, "meta"), json.dumps({
        "issuer": flow.issuer, "token_endpoint": flow.token_endpoint,
        "revocation_endpoint": flow.revocation_endpoint, "resource": flow.resource,
        "resource_origin": origin_of(flow.server_url), "client_id": flow.client_id,
        "auth_method": flow.auth_method, "scope": body.get("scope") or flow.scope,
        "expires_at": expires_at, "obtained_at": int(time.time()), "hub_origin": flow.hub_origin,
        "server_url": flow.server_url,
    }))
    # MINOR-2: the first authorization server this server signed in at is kept, past sign-out.
    if not _read(flow.server, "issuer_pin"):
        store.set(_name(flow.server, "issuer_pin"), flow.issuer)
    # A registered client's secret is already in ``.client``; a pinned one is not copied:
    # it is re-read from the server's own secrets at refresh.
    _REJECTED.discard(flow.server)


# ── using the token ──────────────────────────────────────────────────────────

def mark_rejected(server: str) -> None:
    """The server answered 401 with our token: the next use refreshes first."""
    _REJECTED.add(server)


async def access_token(server: str, server_url: str, *, rejected: str | None = None,
                       pins: dict | None = None) -> tuple[str | None, str | None]:
    """``(token, None)`` or ``(None, reason)``. Refreshes when the token is about to expire or
    the server answered 401 to it (*rejected*: the token it refused). One refresh per server
    at a time: N callers whose requests were refused with the same token wait on one lock,
    the first refreshes, the others find a different token stored and use it."""
    meta = _read_json(server, "meta")
    if not meta:
        return None, "oauth_required"
    if meta.get("resource_origin") != origin_of(server_url):
        return None, "token_origin_mismatch"
    lock = _LOCKS.setdefault(server, asyncio.Lock())
    async with lock:
        meta = _read_json(server, "meta")
        token = _read(server, "access")
        expires_at = meta.get("expires_at")
        refused = rejected is not None and token is not None and hmac.compare_digest(
            token.encode(), rejected.encode())
        stale = refused or server in _REJECTED or not token or (
            isinstance(expires_at, (int, float)) and expires_at - REFRESH_MARGIN <= time.time())
        if not stale:
            return token, None
        refresh = _read(server, "refresh")
        if not refresh:
            return None, "reauth_required"
        try:
            _estop()
        except OAuthError:
            return None, "estop_engaged"
        token_endpoint = str(meta.get("token_endpoint") or "")
        if endpoint_problem(token_endpoint, server_url=server_url, hub_origin=meta.get("hub_origin")) \
                or not _on_issuer(token_endpoint, str(meta.get("issuer") or "")):
            return None, "reauth_required"
        form = {"grant_type": "refresh_token", "refresh_token": refresh,
                "client_id": meta.get("client_id") or "", "resource": meta.get("resource") or server_url}
        secret = _client_secret(server, pins or {})
        basic = None
        if secret and meta.get("auth_method") == "client_secret_basic":
            basic = (meta.get("client_id") or "", secret)
        elif secret:
            form["client_secret"] = secret
        client = HTTP_FACTORY(server)
        try:
            status, body = await _post_form(client, meta["token_endpoint"], form, auth=basic)
        except Exception as exc:
            logger.warning("MCP OAuth refresh failed (server=%s type=%s)", server, type(exc).__name__)
            return None, "refresh_failed"
        finally:
            await client.close()
        new = body.get("access_token")
        if status != 200 or not isinstance(new, str) or not new:
            if body.get("error") == "invalid_grant":
                store = _store()
                store.delete(_name(server, "access"))
                store.delete(_name(server, "refresh"))
                return None, "reauth_required"
            return None, "refresh_failed"
        store = _store()
        store.set(_name(server, "access"), new)
        if isinstance(body.get("refresh_token"), str) and body["refresh_token"]:
            store.set(_name(server, "refresh"), body["refresh_token"])
        expires = body.get("expires_in")
        meta["expires_at"] = (int(time.time() + float(expires))
                              if isinstance(expires, (int, float)) and expires > 0 else None)
        meta["refreshed_at"] = int(time.time())
        store.set(_name(server, "meta"), json.dumps(meta))
        _REJECTED.discard(server)
        return new, None


def _client_secret(server: str, pins: dict) -> str | None:
    pinned = _pinned_value(server, pins.get("client_secret"))
    if pinned:
        return pinned
    known = _read_json(server, "client")
    return known.get("client_secret") or None


async def connect_headers(srv) -> tuple[dict, str | None]:
    """The headers an HTTP MCP server is connected with: its in-memory headers, its secret
    header templates filled from the store, and an OAuth bearer when it has a token (or
    requires one). ``(headers, refusal)``."""
    headers = dict(getattr(srv, "headers", {}) or {})
    templates = getattr(srv, "secret_headers", None) or {}
    if templates:
        from agents.core.mcp.catalog import render_secret_headers

        rendered = render_secret_headers(srv.name, templates)
        if rendered is None:
            return headers, "secret_missing"
        headers.update(rendered)
    wants = getattr(srv, "auth", "none") == "oauth"
    if not wants and not (_SERVER_RE.match(srv.name or "") and has_tokens(srv.name)):
        return headers, None
    if not _SERVER_RE.match(srv.name or ""):
        return headers, "oauth_required"
    token, reason = await access_token(srv.name, srv.url, pins=getattr(srv, "oauth", None) or {})
    if token is None:
        return headers, reason or "oauth_required"
    for key in [k for k in headers if k.lower() == "authorization"]:
        headers.pop(key)
    headers["Authorization"] = f"Bearer {token}"
    return headers, None


# ── status and sign-out ──────────────────────────────────────────────────────

def status(server: str) -> dict:
    meta = _read_json(server, "meta") if _SERVER_RE.match(server or "") else {}
    signed_in = bool(meta) and has_tokens(server)
    return {
        "signed_in": signed_in,
        "issuer": meta.get("issuer"),
        "as_host": urlsplit(meta["issuer"]).hostname if meta.get("issuer") else None,
        "resource_origin": meta.get("resource_origin"),
        "scope": meta.get("scope"),
        "expires_at": meta.get("expires_at"),
        "refreshable": bool(_read(server, "refresh")) if signed_in else False,
        "pending": pending(server),
        "needs_sign_in": bool(meta) and not signed_in,
        "issuer_pin": _read(server, "issuer_pin") if _SERVER_RE.match(server or "") else None,
        # A loopback address the registered client already accepts (the CLI reuses its port).
        "loopback_redirects": [r for r in (_read_json(server, "client").get("redirect_uris") or [])
                               if isinstance(r, str) and r.startswith("http://")
                               and (urlsplit(r).hostname or "") in ("127.0.0.1", "localhost")]
        if _SERVER_RE.match(server or "") else [],
    }


async def sign_out(server: str, *, revoke: bool = True, forget: bool = False) -> dict:
    """Revoke (RFC 7009, best effort) and delete every OAuth record of *server*. The issuer
    pin stays unless *forget* (the server is being removed). Under the e-stop nothing is sent:
    the tokens are deleted here and revocation is skipped (``revoked: "skipped_estop"``)."""
    cancel(server)
    _check_server(server)
    meta = _read_json(server, "meta")
    revoked = None
    endpoint = meta.get("revocation_endpoint")
    from agents.core import estop

    allowed = bool(endpoint) and endpoint_problem(
        endpoint, server_url=str(meta.get("server_url") or meta.get("resource") or ""),
        hub_origin=meta.get("hub_origin")) is None and _on_issuer(endpoint, str(meta.get("issuer") or ""))
    if revoke and endpoint and estop.is_engaged():
        revoked = "skipped_estop"
    elif revoke and allowed:
        revoked = False
        client = HTTP_FACTORY(server)
        try:
            for kind in ("refresh", "access"):
                token = _read(server, kind)
                if not token:
                    continue
                form = {"token": token, "token_type_hint": f"{kind}_token",
                        "client_id": meta.get("client_id") or ""}
                status_code, _ = await _post_form(client, endpoint, form)
                revoked = revoked or status_code == 200
        except Exception as exc:
            logger.warning("MCP OAuth revocation failed (server=%s type=%s)", server, type(exc).__name__)
        finally:
            await client.close()
    store = _store()
    removed = 0
    keep = set() if forget else {_name(server, "issuer_pin")}
    for part in ("access", "refresh", "meta", "client", "issuer_pin"):
        name = _name(server, part)
        if name not in keep and store.delete(name):
            removed += 1
    _REJECTED.discard(server)
    return {"revoked": revoked, "removed": removed}


def _redirect_pin(pins: dict) -> str | None:
    """A manifest's ``redirect_host`` / ``redirect_port``: the exact loopback return address a
    vendor without registration accepts (``http://localhost:27890/callback`` for Asana)."""
    host, port = pins.get("redirect_host"), pins.get("redirect_port")
    if not host and not port:
        return None
    host = str(host or "127.0.0.1").lower()
    try:
        port = int(port)
    except (TypeError, ValueError):
        return None
    if host not in ("localhost", "127.0.0.1") or not 1024 <= port <= 65535:
        return None
    return f"http://{host}:{port}/callback"


def redirect_pin(pins: dict | None) -> str | None:
    return _redirect_pin(pins or {})


def reset_for_tests() -> None:
    _FLOWS.clear()
    _LOCKS.clear()
    _REJECTED.clear()
