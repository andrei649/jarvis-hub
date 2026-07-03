"""
call_broker.py — H12.22 Governed outbound voice / call-back.

The agent can place an outbound call (e.g. an escalation that reaches the user
or a contact by phone) — but every call goes through the autonomy approval queue
AND is gated by the daily interrupt budget (a call is an interruption, so it
draws from the same ≤4/day budget that protects the user's attention, H6.2).

Same governance shape as the write-back / social brokers (H10.30 / H12.21):

    request → validate + budget check → ask-tier governed task (`kind=call.outbound`)
            → (approval) → execute draws a budget slot, resolves the telephony
              credential behind approval, and places the call via an INJECTABLE
              client (`NullCallClient` offline by default; `HttpCallClient` is the
              live Twilio/Telnyx rail, a host-side seam).

A persona voice is isolated per the provider config. Pure-Python and
offline-testable; the enqueue sink, budget, secret broker and live client are
all injected.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional
from urllib.parse import urlparse

from .dry_run import preview_task
from ..security.secret_broker import SecretBroker

logger = logging.getLogger("jarvis.autonomy.call")

# SSRF guard: the live telephony rail may only reach these provider hosts.
_ALLOWED_HOSTS = frozenset({"api.twilio.com", "api.telnyx.com"})


def _assert_allowed_host(url: str, allowed=_ALLOWED_HOSTS) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host not in allowed:
        raise ValueError(f"call host not allowed: {host!r}")
    return host

# A phone call is an external action that reaches a person → ASK (tier 2,
# consistent with the write-back/social brokers); it additionally spends an
# interrupt-budget slot, so calls are doubly gated.
_RISK_TIER = 2

# provider → the secret name whose value is injected at call time.
_CREDENTIAL: dict[str, str] = {
    "twilio": "twilio_auth_token",
    "telnyx": "telnyx_api_key",
}

_MESSAGE_CAP = 2_000
_NUMBER_CAP = 40


def _present(v) -> bool:
    return bool(v.strip()) if isinstance(v, str) else bool(v)


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def build_call_request(provider: str, to: str, message: str,
                       credentials: dict, config: dict) -> dict:
    """Map an outbound call onto a concrete telephony request (pure, testable).

    Returns ``{method, url, headers, json?, data?, auth?}``. Twilio uses
    form-encoded + basic auth; Telnyx uses JSON + bearer.
    """
    provider = (provider or "").lower()
    token = (credentials or {}).get("token", "")
    cfg = config or {}

    if provider == "twilio":
        sid = cfg.get("account_sid", "")
        frm = cfg.get("from", "")
        twiml = f"<Response><Say>{_xml_escape(message)}</Say></Response>"
        return {"method": "POST",
                "url": f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json",
                "headers": {"Content-Type": "application/x-www-form-urlencoded"},
                "auth": (sid, token),
                "data": {"To": to, "From": frm, "Twiml": twiml}}

    if provider == "telnyx":
        return {"method": "POST", "url": "https://api.telnyx.com/v2/calls",
                "headers": {"Authorization": f"Bearer {token}",
                            "Content-Type": "application/json"},
                "json": {"connection_id": cfg.get("connection_id", ""),
                         "to": to, "from": cfg.get("from", ""),
                         "audio_message": message}}

    raise ValueError(f"unsupported call provider: {provider}")


class NullCallClient:
    """Offline default — records the call, performs NO telephony I/O."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def call(self, provider: str, to: str, message: str,
                   credentials: dict, config: dict) -> dict:
        self.calls.append({"provider": provider, "to": to, "message": message,
                           "has_credential": bool((credentials or {}).get("token"))})
        return {"status": "deferred", "provider": provider, "to": to,
                "note": "no live call client configured — host seam"}


class HttpCallClient:
    """Live rail (host seam): builds the telephony request and sends it.

    Transport is injectable (async ``request(method, url, headers=, json=, data=,
    auth=)``), so it stays offline-testable with a mock.
    """

    def __init__(self, http=None) -> None:
        self._http = http

    async def call(self, provider: str, to: str, message: str,
                   credentials: dict, config: dict) -> dict:
        spec = build_call_request(provider, to, message, credentials, config)
        _assert_allowed_host(spec["url"])   # SSRF guard before any request
        http = self._http
        if http is None:  # pragma: no cover - real network path
            from ..http_client import PluginHTTPClient
            http = PluginHTTPClient.for_plugin(f"call_{provider}")
        resp = await http.request(spec["method"], spec["url"],
                                  headers=spec.get("headers"), json=spec.get("json"),
                                  data=spec.get("data"), auth=spec.get("auth"))
        if hasattr(resp, "raise_for_status"):
            resp.raise_for_status()
        return {"status": "ok", "http_status": getattr(resp, "status_code", None)}


class CallBroker:
    """Governs outbound calls: request → budget-gate + approve → execute."""

    KIND = "call.outbound"

    def __init__(self, enqueue: Optional[Callable] = None, agent: str = "jarvis",
                 secret_broker=None, client=None, audit=None, budget=None,
                 config: Optional[dict] = None, kernel=None, ledger=None) -> None:
        self._enqueue = enqueue
        self.agent = agent
        self._secrets = secret_broker
        self._client = client or NullCallClient()
        self._audit = audit
        self._budget = budget   # InterruptBudget: .remaining() / .consume()
        self.config = config or {}
        self._kernel = kernel   # ORIZONT-24 K1: bound kernel.authorize (default-off)
        # H23.1 (opt-in): kernel BudgetLedger (token/wall-time/recursion). None →
        # no enforcement, execute() stays byte-identical. Build via
        # kernel.binding.make_budget_ledger(...) when a limit is configured.
        self._ledger = ledger

    @staticmethod
    def supports(provider: str) -> bool:
        return (provider or "").lower() in _CREDENTIAL

    def providers(self) -> list[dict]:
        return [{"provider": p, "credential": cred} for p, cred in _CREDENTIAL.items()]

    def request(self, to: str, message: str, provider: str = "twilio",
                reason: str = "", agent: Optional[str] = None) -> dict:
        provider = (provider or "").strip().lower()
        if provider not in _CREDENTIAL:
            return {"ok": False, "reason": "unknown_provider",
                    "supported": sorted(_CREDENTIAL)}
        to = str(to or "")[:_NUMBER_CAP]
        message = str(message or "")[:_MESSAGE_CAP]
        if not _present(to) or not _present(message):
            return {"ok": False, "reason": "missing_fields",
                    "missing": [k for k, v in (("to", to), ("message", message))
                                if not _present(v)]}
        # A call is an interruption — refuse if the daily budget is spent.
        if self._budget is not None and self._budget.remaining() <= 0:
            return {"ok": False, "reason": "interrupt_budget_exhausted"}

        cred_ref = SecretBroker.reference(_CREDENTIAL[provider])
        title = f"Call {to} via {provider}" + (f": {reason}" if reason else "")
        payload = {
            "provider": provider,
            "action": "call",
            "to": to,
            "message": message,
            "reason": reason,
            "credential_ref": cred_ref,
            "target": to,
        }
        preview = preview_task({"kind": self.KIND, "title": title,
                                "payload": payload, "risk_tier": _RISK_TIER})
        # ORIZONT-24 K1: route through the Action Kernel when enabled (default-off →
        # this block is skipped and the path below is byte-identical to before).
        autonomy_level = "ask"
        if self._kernel is not None:
            from ..kernel import Action, Verdict, kernel_enabled
            from ..action_origin import current_action_origin
            if kernel_enabled():
                decision = self._kernel(Action(kind=self.KIND, agent=agent or self.agent,
                                               title=title, payload=payload,
                                               origin=current_action_origin()))
                if decision.verdict is Verdict.DENY:
                    return {"ok": False, "reason": decision.reason, "kind": self.KIND}
                if decision.verdict is Verdict.GRANT:
                    autonomy_level = "act"
        if self._enqueue is None:
            return {"ok": True, "queued": False, "kind": self.KIND, "title": title,
                    "payload": payload, "preview": preview}
        try:
            task_id = self._enqueue(agent or self.agent, self.KIND, title, payload=payload,
                                    risk_tier=_RISK_TIER, autonomy_level=autonomy_level,
                                    origin="generated")
        except Exception:
            logger.warning("call enqueue failed", exc_info=True)
            return {"ok": False, "reason": "enqueue_failed"}
        self._record("call.request", f"{provider}:{to}", to=to)
        return {"ok": True, "queued": True, "task_id": task_id, "kind": self.KIND,
                "title": title, "preview": preview}

    async def execute(self, task) -> dict:
        payload = getattr(task, "payload", None) or {}
        provider = payload.get("provider")
        to = payload.get("to")
        message = payload.get("message", "")
        if not self.supports(provider) or not to:
            return {"status": "failed", "reason": "invalid_call", "provider": provider}
        # H23.1 (opt-in): enter the budget ledger; the try/finally below guarantees a
        # single matching leave(). When no ledger is attached this is a no-op wrapper
        # and the path is byte-identical to before.
        if self._ledger is not None:
            self._ledger.start()
            self._ledger.enter()
        try:
            if self._ledger is not None:
                reason = self._ledger.exceeded()
                if reason is not None:   # token / wall-time / recursion-depth breach
                    self._record("call.budget_denied", reason, to=to)
                    return {"status": "failed", "reason": "budget_exceeded", "detail": reason}
            # Draw an interrupt-budget slot at the moment the call is actually placed.
            if self._budget is not None and not self._budget.consume():
                return {"status": "failed", "reason": "interrupt_budget_exhausted"}
            credentials = self._resolve_credentials(payload)
            config = self.config.get(provider, {}) if isinstance(self.config, dict) else {}
            try:
                result = await self._client.call(provider, to, message, credentials, config)
            except Exception:
                logger.warning("call execute failed", exc_info=True)
                return {"status": "failed", "reason": "client_error"}
            if self._ledger is not None:
                self._ledger.add_tokens(len(message))   # coarse per-call usage signal
            self._record("call.execute", f"{provider}:{to}", to=to)
            return {"status": "ok", "provider": provider, "to": to, "call": result}
        finally:
            if self._ledger is not None:
                self._ledger.leave()

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
                self._audit.record(actor="call", action=action, why=why, metadata=meta)
            elif hasattr(self._audit, "log"):
                self._audit.log({"event": action, "why": why, **meta})
        except Exception:  # pragma: no cover - best-effort
            pass
