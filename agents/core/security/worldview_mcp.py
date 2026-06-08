"""worldview_mcp.py — JARVIS-side minter/verifier for WorldView MCP capability tokens (H19.3.2).

The WorldView MCP server (`worldview/mcp/src/auth.ts`) gates its WRITE tools
(`watch_aoi`, `reconstruct_event`) on a compact, HMAC-signed capability token. Until now JARVIS
had no way to mint that token shape — its in-process ``CapabilityBroker`` issues an OPAQUE random
id validated by server-side lookup, which is incompatible with the MCP server's stateless,
offline HMAC verification. So the MCP *write* path was unreachable from JARVIS.

This module closes that gap: it mints (and verifies) the EXACT token the MCP server accepts, so a
JARVIS agent can call a WorldView MCP write tool with a scoped, signed, offline-verifiable token,
keyed by the shared ``WORLDVIEW_MCP_SECRET``.

Token format (must stay byte-identical to ``signCapability`` in ``mcp/src/auth.ts`` — pinned by the
shared vectors in ``worldview/mcp/test/fixtures/capability-vectors.json``, asserted by BOTH this
module's tests and the MCP server's tests):

    base64url(JSON(claims)) + "." + base64url(HMAC_SHA256(payloadSegment, secret))

where ``claims = {"scopes": [...], "exp": <unix seconds>, "sub"?: <str>}`` is serialized with
COMPACT separators and key order ``scopes, exp, sub`` (matching ``JSON.stringify``), base64url is
WITHOUT padding, and the HMAC is computed over the payload-segment *string* bytes.

Fail-closed like the verifier: an empty secret / malformed token / bad signature / expiry / missing
scope all return a deny; we never raise and never default to allow.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

WILDCARD_SCOPE = "worldview:*"


def _b64url_encode(data: bytes) -> str:
    """base64url without padding (matches Node's ``Buffer.toString('base64url')``)."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(seg: str) -> bytes | None:
    """base64url-decode (re-pad first); None on any malformed input (never raises)."""
    try:
        pad = "=" * (-len(seg) % 4)
        return base64.urlsafe_b64decode(seg + pad)
    except (ValueError, TypeError):
        return None


def _sign_payload(payload_segment: str, secret: str) -> str:
    """base64url(HMAC-SHA256(payload_segment, secret)) — matches ``signPayload`` on the TS side."""
    digest = hmac.new(secret.encode("utf-8"), payload_segment.encode("utf-8"), hashlib.sha256).digest()
    return _b64url_encode(digest)


def mint_capability(
    scopes: list[str],
    secret: str,
    *,
    ttl_s: int = 300,
    sub: str | None = None,
    now: float | None = None,
) -> str:
    """Mint a WorldView MCP capability token granting ``scopes``, expiring in ``ttl_s`` seconds.

    The claims dict is built in the canonical order (scopes, exp, sub) and serialized compactly so
    the token is byte-identical to the TS ``signCapability`` for the same inputs. ``secret`` must be
    the shared ``WORLDVIEW_MCP_SECRET``.
    """
    if not secret:
        raise ValueError("a non-empty WORLDVIEW_MCP_SECRET is required to mint a capability token")
    issued = int(now if now is not None else time.time())
    claims: dict[str, object] = {"scopes": list(scopes), "exp": issued + int(ttl_s)}
    if sub is not None:
        claims["sub"] = sub
    # ``ensure_ascii=False`` is REQUIRED for byte-identity with TS ``JSON.stringify``: Python's json
    # default escapes non-ASCII as ``\uXXXX`` while JS emits raw UTF-8, so a token whose scope/sub
    # carries a non-ASCII char (UTF-8 region/operator names) would otherwise serialize to different
    # bytes — and a different signature — on each side, silently defeating the cross-language
    # pinning. ``exp`` is always an int (computed above), matching how TS renders the integer. The
    # non-ASCII + float-derived fixture vectors guard this invariant in CI.
    payload_segment = _b64url_encode(
        json.dumps(claims, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    return f"{payload_segment}.{_sign_payload(payload_segment, secret)}"


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    reason: str = ""
    claims: dict[str, object] | None = None


def _scope_satisfies(granted: list[str], required: str) -> bool:
    return WILDCARD_SCOPE in granted or required in granted


def verify_capability(
    token: str | None,
    required_scope: str,
    secret: str | None,
    *,
    now: float | None = None,
) -> VerifyResult:
    """Verify a capability token (mirror of ``verifyCapability`` in ``mcp/src/auth.ts``).

    Fail-closed: returns ``VerifyResult(ok=False, reason=...)`` on no-secret / malformed / bad-sig /
    expired / missing-scope. Constant-time signature compare via ``hmac.compare_digest``.
    """
    if not secret:
        return VerifyResult(False, "no-secret-configured")
    if not isinstance(token, str) or token.strip() == "":
        return VerifyResult(False, "missing-token")
    parts = token.split(".")
    if len(parts) != 2 or parts[0] == "" or parts[1] == "":
        return VerifyResult(False, "malformed-token")
    payload_segment, sig_segment = parts
    expected_sig = _sign_payload(payload_segment, secret)
    if not hmac.compare_digest(sig_segment, expected_sig):
        return VerifyResult(False, "bad-signature")
    raw = _b64url_decode(payload_segment)
    if raw is None:
        return VerifyResult(False, "malformed-payload")
    try:
        claims = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return VerifyResult(False, "malformed-payload")
    if not isinstance(claims, dict):
        return VerifyResult(False, "malformed-payload")
    scopes = claims.get("scopes")
    exp = claims.get("exp")
    if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
        return VerifyResult(False, "malformed-claims")
    if not isinstance(exp, (int, float)) or isinstance(exp, bool):
        return VerifyResult(False, "malformed-claims")
    current = now if now is not None else time.time()
    if exp <= current:
        return VerifyResult(False, "expired")
    if not _scope_satisfies(scopes, required_scope):
        return VerifyResult(False, "missing-scope")
    return VerifyResult(True, "", claims)
