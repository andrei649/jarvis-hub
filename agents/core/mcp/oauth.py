"""
oauth.py — H16.1 MCP server mode upgraded to the 2025-11 spec.

Adds the OAuth 2.1 **Resource Server** layer the new MCP spec requires:

* **RFC 9728** — a ``.well-known/oauth-protected-resource`` metadata document so
  clients can discover the authorization server(s) for this MCP resource.
* **RFC 8707** — resource indicators: a presented token must be **audience-bound**
  to *this* resource (no token replay across resources).
* Bearer-token validation with scope enforcement, LAN-only by default.

For a strictly-local deployment with no external IdP, this also self-issues
HMAC-signed tokens (constant-time verified) so the RS is usable and testable
end-to-end; in a federated setup the same `validate()` accepts tokens minted by
an external authorization server (swap the verification backend).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Optional


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _ub64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def protected_resource_metadata(resource: str, auth_servers: list[str],
                                scopes: Optional[list[str]] = None) -> dict:
    """RFC 9728 protected-resource metadata document."""
    return {
        "resource": resource,
        "authorization_servers": auth_servers or [resource],
        "scopes_supported": scopes or ["mcp"],
        "bearer_methods_supported": ["header"],
        "resource_documentation": f"{resource}/api/mcp/server",
    }


class MCPResourceServer:
    """OAuth 2.1 resource server for MCP — issues (local) and validates tokens."""

    def __init__(self, secret: Optional[str] = None, issuer: str = "jarvis-mcp") -> None:
        self._secret = (secret or secrets.token_urlsafe(32)).encode("utf-8")
        self.issuer = issuer

    # ── local (self-issued) tokens ───────────────────────────────────────────

    def issue_token(self, subject: str, resource: str, scopes: list[str],
                    ttl: int = 3600) -> str:
        now = int(time.time())
        payload = {
            "iss": self.issuer,
            "sub": subject,
            "aud": resource,         # RFC 8707 audience binding
            "resource": resource,
            "scope": " ".join(scopes or []),
            "iat": now,
            "exp": now + int(ttl),
        }
        body = _b64u(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        return f"{body}.{self._sign(body)}"

    def _sign(self, body: str) -> str:
        return _b64u(hmac.new(self._secret, body.encode("ascii"), hashlib.sha256).digest())

    # ── validation ───────────────────────────────────────────────────────────

    def validate(self, token: str, resource: str,
                 required_scope: Optional[str] = None) -> dict:
        """Validate a bearer token for *resource*. Returns {ok, claims} or {ok:False, error}."""
        if not token:
            return {"ok": False, "error": "missing token"}
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        parts = token.split(".")
        if len(parts) != 2:
            return {"ok": False, "error": "malformed token"}
        body, sig = parts
        if not hmac.compare_digest(self._sign(body), sig):
            return {"ok": False, "error": "invalid signature"}
        try:
            claims = json.loads(_ub64u(body))
        except Exception:
            return {"ok": False, "error": "invalid payload"}
        if int(claims.get("exp", 0)) < int(time.time()):
            return {"ok": False, "error": "token expired"}
        # RFC 8707: the token must be bound to THIS resource.
        if resource not in (claims.get("aud"), claims.get("resource")):
            return {"ok": False, "error": "resource/audience mismatch (RFC 8707)"}
        if required_scope and required_scope not in claims.get("scope", "").split():
            return {"ok": False, "error": f"missing required scope '{required_scope}'"}
        return {"ok": True, "claims": claims}

    @staticmethod
    def challenge(resource: str) -> str:
        """WWW-Authenticate header value pointing at the resource metadata (spec)."""
        return (f'Bearer resource_metadata="{resource}/.well-known/oauth-protected-resource"')
