"""
social.py — H12.21 Governed social actions (X/Twitter post / reply / DM).

Every social *write* goes through the autonomy approval queue. Auth is via the
SecretBroker (OAuth/bearer token resolved at action time, behind approval) —
never raw cookies in the agent's context. This intentionally parallels the
write-back governance layer (H10.30 `writeback.py`); a shared base is the
natural extraction point once a third governed-action family lands (e.g. H12.22
outbound voice).

Flow: request → validate against a (platform, action) allowlist + sanitize
→ enqueue an ask-tier governed task (`kind=social.<platform>.<action>`); nothing
is posted at request time. On approval the autonomy worker dispatches it to
`SocialBroker.execute`, which resolves credentials behind approval and calls an
INJECTABLE client (`NullSocialClient` offline by default; `HttpSocialClient` is
the live host-side rail built from the pure `build_social_request`).

Pure-Python and offline-testable; the enqueue sink, secret broker, and live
client are all injected.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlparse

from .autonomy.dry_run import preview_task
from .security.secret_broker import SecretBroker

logger = logging.getLogger("jarvis.social")

# SSRF guard: the live rail may only reach the X/Twitter API host.
_ALLOWED_HOSTS = frozenset({"api.twitter.com"})


def _assert_allowed_host(url: str, allowed=_ALLOWED_HOSTS) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host not in allowed:
        raise ValueError(f"social host not allowed: {host!r}")
    return host

# Social writes reach people publicly/directly — external tier, always ASK.
_RISK_TIER = 2

# platform → the secret name whose value is injected at execution time.
_CREDENTIAL: dict[str, str] = {"x": "x_api_token"}

_TEXT_CAP = 4_000      # generous (X premium long-form); ordinary posts are 280
_REF_CAP = 120         # tweet id / recipient handle


@dataclass(frozen=True)
class SocialAction:
    platform: str
    action: str
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    label: str = ""


_CATALOG: "dict[tuple[str, str], SocialAction]" = {}


def _reg(platform: str, action: str, required, optional=(), label: str = "") -> None:
    _CATALOG[(platform, action)] = SocialAction(
        platform, action, tuple(required), tuple(optional), label
    )


_reg("x", "post", ("text",), (), "Post to X")
_reg("x", "reply", ("text", "reply_to"), (), "Reply on X")
_reg("x", "dm", ("text", "recipient"), (), "DM on X")


def _present(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    return bool(v)


def _sanitize_fields(spec: SocialAction, fields: Optional[dict]) -> "tuple[dict, list[str]]":
    fields = fields or {}
    allowed = set(spec.required) | set(spec.optional)
    clean: dict = {}
    for k in allowed:
        if k not in fields:
            continue
        cap = _TEXT_CAP if k == "text" else _REF_CAP
        s = str(fields[k])[:cap]
        if _present(s):
            clean[k] = s
    missing = [k for k in spec.required if k not in clean]
    return clean, missing


def _human_target(platform: str, action: str, fields: dict) -> str:
    if action == "reply":
        return f"reply to {fields.get('reply_to', '?')}"
    if action == "dm":
        return f"DM {fields.get('recipient', '?')}"
    text = fields.get("text", "")
    return (text[:40] + "…") if len(text) > 40 else (text or platform)


# ── concrete HTTP request building (pure, offline-testable) ──────────────────

def _bearer_json(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def build_social_request(platform: str, action: str, fields: dict, credentials: dict) -> dict:
    """Map a (platform, action, fields) social write onto a concrete HTTP request.

    Pure + offline-testable. Returns ``{method, url, headers, json}``.
    """
    platform = (platform or "").lower()
    action = (action or "").lower()
    token = (credentials or {}).get("token", "")
    f = fields or {}

    if platform == "x" and action == "post":
        return {"method": "POST", "url": "https://api.twitter.com/2/tweets",
                "headers": _bearer_json(token), "json": {"text": f.get("text", "")}}
    if platform == "x" and action == "reply":
        return {"method": "POST", "url": "https://api.twitter.com/2/tweets",
                "headers": _bearer_json(token),
                "json": {"text": f.get("text", ""),
                         "reply": {"in_reply_to_tweet_id": f.get("reply_to", "")}}}
    if platform == "x" and action == "dm":
        recipient = f.get("recipient", "")
        return {"method": "POST",
                "url": f"https://api.twitter.com/2/dm_conversations/with/{recipient}/messages",
                "headers": _bearer_json(token), "json": {"text": f.get("text", "")}}

    raise ValueError(f"unsupported social action: {platform}.{action}")


# ── social clients (the deferred live rail) ──────────────────────────────────

class NullSocialClient:
    """Offline default — records the call, performs NO network I/O."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def send(self, platform: str, action: str, fields: dict, credentials: dict) -> dict:
        self.calls.append({"platform": platform, "action": action, "fields": fields,
                           "has_credential": bool((credentials or {}).get("token"))})
        return {"status": "deferred", "platform": platform, "action": action,
                "note": "no live social client configured — host seam"}


class HttpSocialClient:
    """Live rail (host-side seam): builds the request and sends it over HTTP.

    Transport is injectable (async ``request(method, url, headers=, json=)``),
    so it stays offline-testable with a mock; only a real deployment posts.
    """

    def __init__(self, http=None) -> None:
        self._http = http

    async def send(self, platform: str, action: str, fields: dict, credentials: dict) -> dict:
        spec = build_social_request(platform, action, fields, credentials)
        _assert_allowed_host(spec["url"])   # SSRF guard before any request
        http = self._http
        if http is None:  # pragma: no cover - real network path
            from .http_client import PluginHTTPClient
            http = PluginHTTPClient.for_plugin(f"social_{platform}")
        resp = await http.request(spec["method"], spec["url"],
                                  headers=spec["headers"], json=spec["json"])
        resp.raise_for_status()
        out: dict = {"status": "ok", "http_status": getattr(resp, "status_code", None)}
        try:
            out["response"] = resp.json()
        except Exception:
            pass
        return out


# ── the broker ───────────────────────────────────────────────────────────────

class SocialBroker:
    """Governs social writes: request → gated task → approve → execute."""

    KIND_PREFIX = "social."

    def __init__(self, enqueue: Optional[Callable] = None, agent: str = "pepper",
                 secret_broker=None, client=None, audit=None) -> None:
        self._enqueue = enqueue
        self.agent = agent
        self._secrets = secret_broker
        self._client = client or NullSocialClient()
        self._audit = audit

    @staticmethod
    def supports(platform: str, action: str) -> bool:
        return ((platform or "").lower(), (action or "").lower()) in _CATALOG

    def targets(self) -> list[dict]:
        return [
            {"platform": s.platform, "action": s.action, "label": s.label,
             "required": list(s.required), "optional": list(s.optional),
             "kind": f"{self.KIND_PREFIX}{s.platform}.{s.action}",
             "credential": _CREDENTIAL.get(s.platform, "")}
            for s in _CATALOG.values()
        ]

    def request(self, platform: str, action: str, fields: Optional[dict] = None,
                agent: Optional[str] = None, source: str = "") -> dict:
        """Validate + enqueue a governed social write. Never posts.

        With no enqueue sink this is a preview (validation + dry-run only).
        """
        platform = (platform or "").strip().lower()
        action = (action or "").strip().lower()
        spec = _CATALOG.get((platform, action))
        if spec is None:
            return {"ok": False, "reason": "unknown_platform_action",
                    "supported": sorted(f"{p}.{a}" for (p, a) in _CATALOG)}

        clean, missing = _sanitize_fields(spec, fields)
        if missing:
            return {"ok": False, "reason": "missing_fields", "missing": missing,
                    "required": list(spec.required)}

        kind = f"{self.KIND_PREFIX}{platform}.{action}"
        cred_name = _CREDENTIAL.get(platform, "")
        cred_ref = SecretBroker.reference(cred_name) if cred_name else ""
        human = _human_target(platform, action, clean)
        title = f"{spec.label}: {human}" if spec.label else f"{kind} → {human}"
        payload = {
            "platform": platform,
            "action": action,
            "fields": clean,
            "credential_ref": cred_ref,
            "source": source,
            "target": human,
        }
        preview = preview_task({"kind": kind, "title": title,
                                "payload": payload, "risk_tier": _RISK_TIER})

        if self._enqueue is None:
            return {"ok": True, "queued": False, "kind": kind, "title": title,
                    "payload": payload, "preview": preview}
        try:
            task_id = self._enqueue(agent or self.agent, kind, title, payload=payload,
                                    risk_tier=_RISK_TIER, autonomy_level="ask",
                                    origin="generated")
        except Exception:
            logger.warning("social enqueue failed", exc_info=True)
            return {"ok": False, "reason": "enqueue_failed", "kind": kind}

        self._record("social.request", f"{platform}.{action}", target=human)
        return {"ok": True, "queued": True, "task_id": task_id, "kind": kind,
                "title": title, "preview": preview}

    async def execute(self, task) -> dict:
        payload = getattr(task, "payload", None) or {}
        platform = payload.get("platform")
        action = payload.get("action")
        fields = payload.get("fields") or {}
        if not self.supports(platform, action):
            return {"status": "failed", "reason": "unknown_platform_action",
                    "platform": platform, "action": action}
        credentials = self._resolve_credentials(payload)
        try:
            result = await self._client.send(platform, action, fields, credentials)
        except Exception:
            logger.warning("social execute failed", exc_info=True)
            return {"status": "failed", "reason": "client_error",
                    "platform": platform, "action": action}
        self._record("social.execute", f"{platform}.{action}", target=platform)
        return {"status": "ok", "platform": platform, "action": action, "social": result}

    def _resolve_credentials(self, payload: dict) -> dict:
        ref = payload.get("credential_ref") or ""
        token = ""
        if ref and self._secrets is not None:
            out = self._secrets.inject(ref, approved=True)
            if not out.get("blocked"):
                token = out.get("text", "")
        return {"token": token}

    def _record(self, action: str, why: str, **meta) -> None:
        if self._audit is None:
            return
        try:
            if hasattr(self._audit, "record"):
                self._audit.record(actor="social", action=action, why=why, metadata=meta)
            elif hasattr(self._audit, "log"):
                self._audit.log({"event": action, "why": why, **meta})
        except Exception:  # pragma: no cover - audit is best-effort
            pass
