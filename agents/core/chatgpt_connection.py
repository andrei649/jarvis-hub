"""Owner-authorized ChatGPT plan registration and catalog. This service never generates.

One selected registration per Nerva profile. Short encrypted transactions fence sends
and token rotation across processes. The OAuth browser binding and PKCE material expire
after ten minutes. Local disconnect forgets the account while preserving this host ID.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import time
import uuid
from contextlib import contextmanager
from urllib.parse import urlencode, urlsplit

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from agents.core import estop, managed_scope
from agents.core.http_client import PluginEgressError, PluginHTTPClient
from agents.core.llm import data_handling, physical_local
from agents.core.llm.nous_credentials import NousAuthStore
from agents.core.mcp.oauth_client import _pkce
from agents.core.paths import data_path

ISSUER = "https://auth.openai.com"
AUTHORIZE = ISSUER + "/api/accounts/authorize"
TOKEN = ISSUER + "/api/accounts/oauth/token"
JWKS = ISSUER + "/.well-known/jwks.json"
RESOURCE = "https://api.openai.com/v1"
CATALOG = RESOURCE + "/models"
CALLBACK_PATH = "/api/oauth/chatgpt/callback"
DYNAMIC = "dynamic_agent_client"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPES = {"openid", "offline_access", "resource.invoke", "chatgpt.tokens.use.direct"}
FLOW_TTL = 600
MAX_PENDING = 8
_now = time.time


class ConnectionError(Exception):
    """Only the static reason and HTTP status are suitable for the owner-facing route."""

    def __init__(self, reason: str, status: int = 400):
        self.reason = reason
        self.status = status
        super().__init__(reason)


def _store(*, create=False):
    from agents.core.integration_keys import _store as broker_cipher
    from agents.core.memory.private_db import ensure_private

    path = data_path("security", "chatgpt-plan.sqlite3")
    if create:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        ensure_private(path)
    else:
        try:
            path.stat()
        except FileNotFoundError:
            return None
    return NousAuthStore(path, cipher=broker_cipher())


@contextmanager
def _transaction():
    try:
        with _store(create=True).transaction() as record:
            yield record
    except ConnectionError:
        raise
    except Exception:
        raise ConnectionError("credential_store_unavailable", 503) from None


def _read():
    try:
        store = _store()
        return store.read() if store is not None else {}
    except Exception:
        raise ConnectionError("credential_store_unavailable", 503) from None


def _writable():
    try:
        managed_scope.check_writable()
    except Exception:
        raise ConnectionError("managed_configuration", 403) from None


def _available():
    if estop.is_engaged():
        raise ConnectionError("estop_engaged", 409)


def _text(value, maximum=16_384):
    return isinstance(value, str) and 0 < len(value) <= maximum and all(32 < ord(c) < 127 for c in value)


def status():
    return {"connected": bool(_read().get("tokens"))}


def disconnect():
    _writable()
    with _transaction() as record:
        host = record.get("host")
        record.clear()
        if host:
            record.update(host=host, generation=secrets.token_urlsafe(24))
    return {"connected": False}


def start(redirect_uri: str, binding: str):
    _available()
    _writable()
    try:
        uri = urlsplit(redirect_uri)
        valid = (_text(redirect_uri, 256) and uri.port and
                 redirect_uri == f"http://127.0.0.1:{uri.port}{CALLBACK_PATH}")
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise ConnectionError("invalid_redirect")
    if not _text(binding, 512):
        raise ConnectionError("invalid_binding")
    from agents.core.security.website_policy import website_refusal
    try:
        blocked = website_refusal(AUTHORIZE)
    except Exception:
        blocked = True
    if blocked:
        raise ConnectionError("egress_refused", 403)

    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    verifier, challenge = _pkce()
    now = _now()
    with _transaction() as record:
        offers = {k: v for k, v in record.get("offers", {}).items() if now < v["expires"]}
        if len(offers) >= MAX_PENDING:
            raise ConnectionError("too_many_attempts", 429)
        if "host" not in record:
            record["host"] = uuid.uuid4().urn
        if "generation" not in record:
            record["generation"] = secrets.token_urlsafe(24)
        selected = record.get("client")
        offers[state] = {"binding": hashlib.sha256(binding.encode()).hexdigest(), "nonce": nonce,
                         "verifier": verifier, "redirect": redirect_uri, "expires": now + FLOW_TTL}
        record["offers"] = offers
        host = record["host"]
    params = {"client_id": selected or DYNAMIC, "ext_agent_host_id": host, "scope": SCOPES,
              "response_type": "code", "redirect_uri": redirect_uri, "resource": RESOURCE,
              "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256"}
    if not selected:
        params["agent_name_hint"] = "Nerva"
    return {"url": AUTHORIZE + "?" + urlencode(params), "state": state}


def _take(state, binding):
    if not _text(state, 128) or not _text(binding, 512):
        raise ConnectionError("invalid_attempt")
    with _transaction() as record:
        offers = record.get("offers", {})
        offer = offers.get(state)
        if not offer or not hmac.compare_digest(offer["binding"], hashlib.sha256(binding.encode()).hexdigest()):
            raise ConnectionError("invalid_attempt")
        del offers[state]
        generation, client, subject = record["generation"], record.get("client"), record.get("subject")
    if _now() >= offer["expires"]:
        raise ConnectionError("invalid_attempt")
    return offer, generation, client, subject


def _current(generation, record=None):
    record = _read() if record is None else record
    if record.get("generation") != generation:
        raise ConnectionError("connection_changed", 409)


def _http():
    return PluginHTTPClient("chatgpt-plan")


async def _json(method, endpoint, generation, **kwargs):
    """Only fixed destinations. Policy/estop and the selected registration apply to each leg."""
    _available()
    _current(generation)
    request = httpx.Request(method, endpoint, **kwargs)
    try:
        physical_local.check_physical_local_request(request, None, "chatgpt-plan")
        await data_handling.check_physical_request(request)
        async with (_http() as client,
                    client.stream(method, endpoint, follow_redirects=False, **kwargs) as response):
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > 512 * 1024:
                    raise ConnectionError("invalid_provider_response", 502)
                body.extend(chunk)
            if response.status_code != 200:
                if endpoint == TOKEN and response.status_code == 400:
                    try:
                        error = json.loads(body).get("error")
                    except (AttributeError, ValueError):
                        error = None
                    if error == "invalid_grant":
                        raise ConnectionError("reauthorization_required", 409)
                if response.status_code in (401, 403):
                    raise ConnectionError("provider_denied", 403)
                raise ConnectionError("provider_unavailable", 502)
            result = json.loads(body)
            if not isinstance(result, dict):
                raise ConnectionError("invalid_provider_response", 502)
    except ConnectionError:
        raise
    except (PluginEgressError, data_handling.DataHandlingRefused):
        raise ConnectionError("egress_refused", 403) from None
    except Exception:
        raise ConnectionError("provider_unavailable", 502) from None
    _current(generation)
    return result


def _decode(part):
    if not isinstance(part, str) or not re.fullmatch("[A-Za-z0-9_-]+", part):
        raise ValueError
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


async def _identity(token, client, nonce, generation, *, refreshing=False):
    if not _text(token):
        raise ConnectionError("invalid_identity", 403)
    jwks = await _json("GET", JWKS, generation)
    try:
        header, payload, signature = token.split(".")
        meta = json.loads(_decode(header))
        if meta["alg"] != "RS256" or not _text(meta["kid"], 256) or "crit" in meta:
            raise ValueError
        key, = [k for k in jwks["keys"] if k.get("kid") == meta["kid"] and k.get("kty") == "RSA"
                and k.get("alg", "RS256") == "RS256" and k.get("use", "sig") == "sig"
                and "verify" in k.get("key_ops", ["verify"])]
        modulus, exponent = _decode(key["n"]), _decode(key["e"])
        if not 256 <= len(modulus) <= 1024 or not 1 <= len(exponent) <= 8:
            raise ValueError
        public = rsa.RSAPublicNumbers(int.from_bytes(exponent, "big"), int.from_bytes(modulus, "big")).public_key()
        public.verify(_decode(signature), f"{header}.{payload}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
        claims = json.loads(_decode(payload))
        aud = claims["aud"]
        audience = [aud] if isinstance(aud, str) else aud
        if not isinstance(audience, list) or client not in audience:
            raise ValueError
        if (len(audience) != 1 or "azp" in claims) and claims.get("azp") != client:
            raise ValueError
        if claims["iss"] != ISSUER or not _text(claims["sub"], 255):
            raise ValueError
        now = _now()
        if not _number(claims["exp"]) or claims["exp"] <= now:
            raise ValueError
        if not _number(claims["iat"]) or claims["iat"] > now + 5 or claims["iat"] >= claims["exp"]:
            raise ValueError
        if "nbf" in claims and (not _number(claims["nbf"]) or claims["nbf"] > now + 5):
            raise ValueError
        if (not refreshing or "nonce" in claims) and (
            not _text(claims.get("nonce"), 256) or not hmac.compare_digest(claims["nonce"], nonce)
        ):
            raise ValueError
        return claims["sub"]
    except Exception:
        raise ConnectionError("invalid_identity", 403) from None


def _tokens(data, *, previous=None):
    scope = data.get("scope", previous["scope"] if previous else None)
    if not isinstance(scope, str) or len(scope) > 2048 or not PLAN_SCOPES.issubset(scope.split()):
        raise ConnectionError("plan_permission_required", 403)
    kind = data.get("token_type")
    if not isinstance(kind, str) or kind.lower() != "bearer" or not all(
        _text(data.get(name)) for name in ("access_token", "refresh_token")
    ):
        raise ConnectionError("invalid_token_response", 502)
    expires = data.get("expires_in")
    if type(expires) is not int or not 0 < expires <= 2**31:
        raise ConnectionError("invalid_token_response", 502)
    return {"access": data["access_token"], "refresh": data["refresh_token"], "scope": scope,
            "expires": _now() + expires}


async def complete(state, binding, *, code=None, client_id=None, error=None):
    offer, generation, selected, subject = _take(state, binding)
    _available()
    _writable()
    if error is not None:
        raise ConnectionError("authorization_declined", 403)
    if not _text(code, 4096):
        raise ConnectionError("invalid_callback")
    client = selected if client_id is None else client_id
    if not _text(client, 256) or client == DYNAMIC or (selected and selected != client):
        raise ConnectionError("invalid_registration")
    data = await _json("POST", TOKEN, generation, data={"grant_type": "authorization_code",
                       "client_id": client, "redirect_uri": offer["redirect"], "resource": RESOURCE,
                       "code": code, "code_verifier": offer["verifier"]})
    identity = await _identity(data.get("id_token"), client, offer["nonce"], generation)
    if subject and identity != subject:
        raise ConnectionError("account_changed", 409)
    try:
        tokens = _tokens(data)
    except ConnectionError as exc:
        if exc.reason != "plan_permission_required":
            raise
        # Retain the verified registration for reauthorization. No usable grant.
        tokens = None
    if tokens:
        tokens.update(id_token=data["id_token"], nonce=offer["nonce"])
    with _transaction() as record:
        _current(generation, record)
        _writable()
        _available()
        record.update(client=client, subject=identity, generation=secrets.token_urlsafe(24), offers={})
        if tokens:
            record["tokens"] = tokens
        else:
            record.pop("tokens", None)
        record.pop("refreshing", None)
    if not tokens:
        raise ConnectionError("plan_permission_required", 403)
    return {"connected": True}


async def _refresh(generation):
    """Reserve before sending. A crashed/ambiguous rotation requires a fresh sign-in."""
    reservation = secrets.token_urlsafe(24)
    with _transaction() as current:
        _current(generation, current)
        if not current.get("tokens"):
            raise ConnectionError("reauthorization_required", 409)
        if current["tokens"]["expires"] > _now() + 60:
            return current["tokens"]["access"]
        if current.get("refreshing"):
            raise ConnectionError("refresh_in_progress" if _now() < current["refreshing"]["until"]
                                  else "reauthorization_required", 409)
        _writable()
        current["refreshing"] = {"id": reservation, "until": _now() + 60}
        previous, client, subject = current["tokens"], current["client"], current["subject"]
    try:
        data = await _json("POST", TOKEN, generation, data={"grant_type": "refresh_token", "client_id": client,
                           "refresh_token": previous["refresh"], "resource": RESOURCE})
        updated = _tokens(data, previous=previous)
        updated.update(id_token=previous["id_token"], nonce=previous["nonce"])
        if "id_token" in data:
            identity = await _identity(data["id_token"], client, previous["nonce"], generation, refreshing=True)
            if identity != subject:
                raise ConnectionError("account_changed", 409)
            updated["id_token"] = data["id_token"]
        with _transaction() as current:
            _current(generation, current)
            _writable()
            _available()
            if current.get("refreshing", {}).get("id") != reservation:
                raise ConnectionError("connection_changed", 409)
            current["tokens"] = updated
            current.pop("refreshing")
        return updated["access"]
    except ConnectionError as exc:
        if exc.reason in {"invalid_identity", "account_changed", "reauthorization_required", "plan_permission_required",
                          "invalid_token_response", "provider_denied"}:
            with _transaction() as current:
                if current.get("refreshing", {}).get("id") == reservation:
                    current.pop("tokens", None)
                    current.pop("refreshing")
        raise


async def models():
    record = _read()
    if not record.get("tokens"):
        raise ConnectionError("not_connected", 409)
    generation = record["generation"]
    access = record["tokens"]["access"]
    if record["tokens"]["expires"] <= _now() + 60:
        access = await _refresh(generation)
    catalog = await _json("GET", CATALOG, generation, headers={"Authorization": "Bearer " + access})
    entries = catalog.get("models")
    if not isinstance(entries, list):
        raise ConnectionError("invalid_provider_response", 502)
    return {"models": [{"slug": item["slug"], "display_name": item["display_name"]} for item in entries
                       if isinstance(item, dict) and item.get("visibility") == "list" and _text(item.get("slug"), 256)
                       and isinstance(item.get("display_name"), str) and 0 < len(item["display_name"]) <= 256]}
