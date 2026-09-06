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

Live rail (default-off): ``JARVIS_SOCIAL_LIVE=1`` constructs the broker with
:class:`HttpSocialClient` (transport injectable). Unset → Null client, byte-
identical to before. A live client with no resolvable credential refuses with
``credential_not_configured`` instead of posting unauthenticated.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlparse

from .automation_contracts import ContractTemplate, predicate
from .autonomy.dry_run import preview_task
from .env_config import env_flag
from .security.secret_broker import SecretBroker

logger = logging.getLogger("jarvis.social")

# SSRF guard: the live rail may only reach the X/Twitter API host.
_ALLOWED_HOSTS = frozenset({"api.twitter.com"})


def _assert_allowed_host(url: str, allowed=_ALLOWED_HOSTS) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host not in allowed:
        raise ValueError(f"social host not allowed: {host!r}")
    return host

# Live rail flag (default-off). Read at call time, never cached (env_config rule).
LIVE_FLAG = "JARVIS_SOCIAL_LIVE"


def live_rail_enabled() -> bool:
    """True only when the owner explicitly set ``JARVIS_SOCIAL_LIVE``."""
    return env_flag(LIVE_FLAG)


# Social writes reach people publicly/directly — external tier, always ASK.
_RISK_TIER = 2
_KIND_PREFIX = "social."

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
# 0.69 — governed Postiz scheduling: the ONLY path that may arm a live
# (non-draft) Postiz publish. The plugin itself stays draft-first; auth lives
# in the plugin (POSTIZ_API_KEY), so no SecretBroker credential is declared.
_reg("postiz", "schedule", ("text", "integration_id", "publish_at"), (),
     "Schedule via Postiz")


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


def _social_draft_contract_template() -> ContractTemplate:
    """Contract form of the existing social draft-before-send gate."""
    def social_kind(view, now):
        kind = view.get("kind")
        return isinstance(kind, str) and kind.startswith(_KIND_PREFIX)

    def platform_action_allowed(view, now):
        return (view.get("platform"), view.get("action")) in _CATALOG

    def required_fields_present(view, now):
        spec = _CATALOG.get((view.get("platform"), view.get("action")))
        fields = view.get("fields")
        if spec is None or not isinstance(fields, dict):
            return False
        return all(_present(fields.get(k)) for k in spec.required)

    def credential_ref_matches(view, now):
        platform = view.get("platform")
        cred_name = _CREDENTIAL.get(platform, "")
        expected = SecretBroker.reference(cred_name) if cred_name else ""
        return view.get("credential_ref") == expected

    return ContractTemplate(kind="social_draft", constraints=(
        predicate("social_kind", social_kind, reason="invalid_kind"),
        predicate("platform_action_allowed", platform_action_allowed,
                  reason="unknown_platform_action"),
        predicate("required_fields_present", required_fields_present,
                  reason="missing_fields"),
        predicate("credential_ref_matches", credential_ref_matches,
                  reason="credential_ref_mismatch"),
    ), description="Admissibility for governed social draft-before-send requests.")


SOCIAL_DRAFT_CONTRACT = _social_draft_contract_template()


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
        # Honesty layer (Live-vs-Plumbing): a deferred social write is a degraded
        # result — stamp it so the HUD/callers can badge it and name the fix.
        from .plugins.degradation import degraded
        cred_name = _CREDENTIAL.get((platform or "").lower(), "credential")
        return degraded(
            {"status": "deferred", "platform": platform, "action": action,
             "note": "no live social client configured — host seam"},
            reason="social_credential_not_configured",
            needs=[f"secret:{cred_name}"],
        )


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
            # non-JSON response body → omit it from the result
            pass
        return out


# ── the broker ───────────────────────────────────────────────────────────────

class SocialBroker:
    """Governs social writes: request → gated task → approve → execute."""

    KIND_PREFIX = _KIND_PREFIX

    def __init__(self, enqueue: Optional[Callable] = None, agent: str = "pepper",
                 secret_broker=None, client=None, audit=None, kernel=None,
                 postiz_resolver: Optional[Callable] = None, http=None) -> None:
        self._enqueue = enqueue
        self.agent = agent
        self._secrets = secret_broker
        # An explicitly injected client (tests, custom rails) is never replaced;
        # only the default NullSocialClient may lazily upgrade to the live rail.
        self._client_injected = client is not None
        # Live rail behind the flag: JARVIS_SOCIAL_LIVE=1 → the HTTP client
        # (transport injectable via ``http``). Unset → Null client, byte-identical.
        self.live = client is None and live_rail_enabled()
        if client is None and self.live:
            client = HttpSocialClient(http=http)
        self._client = client or NullSocialClient()
        self._audit = audit
        self._kernel = kernel   # ORIZONT-24 K1: bound kernel.authorize (default-off)
        # 0.69 — lazy PostizPlugin accessor; approved postiz.schedule tasks
        # execute through the plugin (its own config + egress gate), not the
        # X HTTP client.
        self._postiz_resolver = postiz_resolver

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
        contract_payload = {
            **payload,
            "kind": kind,
            "agent": agent or self.agent,
            "risk_tier": _RISK_TIER,
        }
        try:
            decision = SOCIAL_DRAFT_CONTRACT.evaluate(contract_payload, now=time.time())
        except Exception:
            logger.warning("social draft contract evaluation failed", exc_info=True)
            return {"ok": False, "reason": "contract_error", "kind": kind}
        if not decision.admissible:
            reason = decision.reason or "contract_denied"
            self._record("social.deny", reason, target=human)
            return {"ok": False, "reason": reason, "kind": kind}
        preview = preview_task({"kind": kind, "title": title,
                                "payload": payload, "risk_tier": _RISK_TIER})

        # ORIZONT-24 K1: route through the Action Kernel when enabled (default-off →
        # skipped, path below byte-identical to before).
        autonomy_level = "ask"
        if self._kernel is not None:
            from .action_origin import current_action_origin
            from .kernel import Action, Verdict, kernel_enabled
            if kernel_enabled():
                decision = self._kernel(Action(kind=kind, agent=agent or self.agent,
                                               title=title, payload=payload,
                                               origin=current_action_origin()))
                if decision.verdict is Verdict.DENY:
                    return {"ok": False, "reason": decision.reason, "kind": kind}
                if decision.verdict is Verdict.GRANT:
                    autonomy_level = "act"
        if self._enqueue is None:
            return {"ok": True, "queued": False, "kind": kind, "title": title,
                    "payload": payload, "preview": preview}
        try:
            task_id = self._enqueue(agent or self.agent, kind, title, payload=payload,
                                    risk_tier=_RISK_TIER, autonomy_level=autonomy_level,
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
        if platform == "postiz":
            return await self._execute_postiz(fields)
        credentials = self._resolve_credentials(payload)
        if isinstance(self._client, HttpSocialClient) and not credentials.get("token"):
            # Live rail armed but no owner credential: refuse with the exact
            # missing secret rather than posting unauthenticated.
            cred_name = _CREDENTIAL.get(platform, "credential")
            self._record("social.refuse", "credential_not_configured", target=platform)
            return {"status": "failed", "reason": "credential_not_configured",
                    "platform": platform, "action": action,
                    "needs": [f"secret:{cred_name}"]}
        # Live-vs-Plumbing: the moment an approved task resolves a REAL owner
        # credential, the default Null client upgrades to the live HTTP rail —
        # no restart needed, still strictly behind the approval funnel (this
        # method only runs on approved tasks). Unconfigured stays honestly
        # deferred; injected clients are never overridden.
        if (not self._client_injected and credentials.get("token")
                and isinstance(self._client, NullSocialClient)):
            logger.info("social live rail active — credential resolved, using HttpSocialClient")
            self._client = HttpSocialClient()
        try:
            result = await self._client.send(platform, action, fields, credentials)
        except Exception:
            logger.warning("social execute failed", exc_info=True)
            return {"status": "failed", "reason": "client_error",
                    "platform": platform, "action": action}
        self._record("social.execute", f"{platform}.{action}", target=platform)
        return {"status": "ok", "platform": platform, "action": action, "social": result}

    async def _execute_postiz(self, fields: dict) -> dict:
        """Run an APPROVED postiz.schedule task through the PostizPlugin.

        This is the one governed caller allowed to pass ``kind="schedule"`` —
        the plugin's own default stays draft-first. Unconfigured/missing plugin
        fails honestly; nothing is fabricated.
        """
        plugin = self._postiz_resolver() if self._postiz_resolver is not None else None
        if plugin is None or not getattr(plugin, "available", lambda: False)():
            return {"status": "failed", "reason": "postiz_not_configured",
                    "platform": "postiz", "action": "schedule"}
        try:
            result = await plugin.schedule_post(
                fields.get("text", ""), [fields.get("integration_id", "")],
                fields.get("publish_at", ""), kind="schedule",
            )
        except Exception:
            logger.warning("postiz schedule execute failed", exc_info=True)
            return {"status": "failed", "reason": "client_error",
                    "platform": "postiz", "action": "schedule"}
        if not result.get("ok"):
            return {"status": "failed", "reason": result.get("error", "postiz_error"),
                    "platform": "postiz", "action": "schedule"}
        self._record("social.execute", "postiz.schedule", target="postiz")
        return {"status": "ok", "platform": "postiz", "action": "schedule",
                "social": result.get("data")}

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
