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

Live rail (default-off): ``JARVIS_CALL_LIVE=1`` constructs the broker with
:class:`HttpCallClient` (transport injectable). Unset → Null client, byte-
identical to before. A live client refuses with ``credential_not_configured``
(no telephony secret) or ``call_config_missing:<keys>`` (no ``JARVIS_CALL_CONFIG``
entry for the provider) instead of dialling with an incomplete request.
"""

from __future__ import annotations

import logging
import hashlib
import time
from typing import Callable, Optional
from urllib.parse import urlparse

from ..automation_contracts import ContractTemplate, predicate
from .dry_run import preview_task
from ..env_config import env_flag
from ..security.secret_broker import SecretBroker

logger = logging.getLogger("jarvis.autonomy.call")

# SSRF guard: the live telephony rail may only reach these provider hosts.
_ALLOWED_HOSTS = frozenset({"api.twilio.com", "api.telnyx.com"})


def _assert_allowed_host(url: str, allowed=_ALLOWED_HOSTS) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host not in allowed:
        raise ValueError(f"call host not allowed: {host!r}")
    return host

# Live rail flag (default-off). Read at call time, never cached (env_config rule).
LIVE_FLAG = "JARVIS_CALL_LIVE"


def live_rail_enabled() -> bool:
    """True only when the owner explicitly set ``JARVIS_CALL_LIVE``."""
    return env_flag(LIVE_FLAG)


# Per-provider config keys the live request cannot be built without.
_CONFIG_REQUIRED: dict[str, tuple[str, ...]] = {
    "twilio": ("account_sid", "from"),
    "telnyx": ("connection_id", "from"),
}


def missing_config(provider: str, config: dict) -> list[str]:
    """Provider config keys absent from *config* (pure; used before a live dial)."""
    cfg = config if isinstance(config, dict) else {}
    return [k for k in _CONFIG_REQUIRED.get((provider or "").lower(), ())
            if not _present(cfg.get(k))]


# A phone call is an external action that reaches a person → ASK (tier 2,
# consistent with the write-back/social brokers); it additionally spends an
# interrupt-budget slot, so calls are doubly gated.
_RISK_TIER = 2
_KIND = "call.outbound"

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


def _call_request_contract_template() -> ContractTemplate:
    """Contract form of the existing governed outbound-call request gate."""
    def call_kind(view, now):
        return view.get("kind") == _KIND

    def provider_allowed(view, now):
        return view.get("provider") in _CREDENTIAL

    def action_is_call(view, now):
        return view.get("action") == "call"

    def required_fields_present(view, now):
        return _present(view.get("to")) and _present(view.get("message"))

    def credential_ref_matches(view, now):
        provider = view.get("provider")
        cred_name = _CREDENTIAL.get(provider, "")
        expected = SecretBroker.reference(cred_name) if cred_name else ""
        return view.get("credential_ref") == expected

    return ContractTemplate(kind="call_request", constraints=(
        predicate("call_kind", call_kind, reason="invalid_kind"),
        predicate("provider_allowed", provider_allowed, reason="unknown_provider"),
        predicate("action_is_call", action_is_call, reason="invalid_action"),
        predicate("required_fields_present", required_fields_present,
                  reason="missing_fields"),
        predicate("credential_ref_matches", credential_ref_matches,
                  reason="credential_ref_mismatch"),
    ), description="Admissibility for governed outbound-call requests.")


CALL_REQUEST_CONTRACT = _call_request_contract_template()


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
        # Honesty layer (Live-vs-Plumbing): a deferred call is a degraded
        # result — stamp it so the HUD/callers can badge it and name the fix.
        from ..plugins.degradation import degraded
        cred_name = _CREDENTIAL.get((provider or "").lower(), "credential")
        return degraded(
            {"status": "deferred", "provider": provider, "to": to,
             "note": "no live call client configured — host seam"},
            reason="call_credential_not_configured",
            needs=[f"secret:{cred_name}"],
        )


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

    KIND = _KIND

    def __init__(self, enqueue: Optional[Callable] = None, agent: str = "jarvis",
                 secret_broker=None, client=None, audit=None, budget=None,
                 config: Optional[dict] = None, kernel=None, ledger=None,
                 http=None) -> None:
        self._enqueue = enqueue
        self.agent = agent
        self._secrets = secret_broker
        # An explicitly injected client (tests, custom rails) is never replaced;
        # only the default NullCallClient may lazily upgrade to the live rail.
        self._client_injected = client is not None
        # Live rail behind the flag: JARVIS_CALL_LIVE=1 → the telephony HTTP
        # client (transport injectable via ``http``). Unset → Null client.
        self.live = client is None and live_rail_enabled()
        if client is None and self.live:
            client = HttpCallClient(http=http)
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
        contract_payload = {
            **payload,
            "kind": self.KIND,
            "agent": agent or self.agent,
            "risk_tier": _RISK_TIER,
        }
        try:
            decision = CALL_REQUEST_CONTRACT.evaluate(contract_payload, now=time.time())
        except Exception:
            logger.warning("call request contract evaluation failed", exc_info=True)
            return {"ok": False, "reason": "contract_error", "kind": self.KIND}
        if not decision.admissible:
            reason = decision.reason or "contract_denied"
            self._record("call.deny", reason, to=to)
            return {"ok": False, "reason": reason, "kind": self.KIND}
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
            credentials = self._resolve_credentials(payload)
            # Live-vs-Plumbing: the moment an approved task resolves a REAL owner
            # credential, the default Null client upgrades to the live telephony
            # rail — no restart needed, still strictly behind the approval funnel
            # AND the interrupt budget below. Unconfigured stays honestly
            # deferred; injected clients are never overridden.
            if (not self._client_injected and credentials.get("token")
                    and isinstance(self._client, NullCallClient)):
                logger.info("call live rail active — credential resolved, "
                            "using HttpCallClient")
                self._client = HttpCallClient()
            config = self.config.get(provider, {}) if isinstance(self.config, dict) else {}
            if isinstance(self._client, HttpCallClient):
                # Live rail armed: refuse an unauthenticated or half-configured
                # dial with the exact missing piece (no budget slot is spent).
                if not credentials.get("token"):
                    cred_name = _CREDENTIAL.get(provider, "credential")
                    self._record("call.refuse", "credential_not_configured", to=to)
                    return {"status": "failed", "reason": "credential_not_configured",
                            "provider": provider, "needs": [f"secret:{cred_name}"]}
                # Config completeness is enforced on the flag-armed rail only; the
                # lazy credential-triggered upgrade keeps its shipped behaviour.
                missing = missing_config(provider, config) if self.live else []
                if missing:
                    self._record("call.refuse", "call_config_missing", to=to)
                    return {"status": "failed",
                            "reason": "call_config_missing:" + ",".join(missing),
                            "provider": provider,
                            "needs": [f"JARVIS_CALL_CONFIG.{provider}.{k}" for k in missing]}
            delivery_broker = getattr(self._budget, "delivery_broker", None)
            performed = False
            if delivery_broker is not None:
                raw_id = getattr(task, "id", None)
                if isinstance(raw_id, int) and raw_id > 0:
                    delivery_id = f"call-task-{raw_id}"
                else:
                    material = f"{provider}:{to}:{message}"
                    delivery_id = f"call-{hashlib.sha256(material.encode()).hexdigest()[:32]}"
                holder: dict = {}

                async def _place_call() -> bool:
                    holder["result"] = await self._client.call(
                        provider, to, message, credentials, config
                    )
                    return True

                delivery = await delivery_broker.dispatch(
                    delivery_id, "call", _place_call
                )
                if delivery["status"] == "downgraded":
                    return {"status": "failed", "reason": "interrupt_budget_exhausted"}
                if delivery["status"] != "delivered":
                    logger.warning("call execute failed: %s", delivery.get("reason"))
                    return {"status": "failed", "reason": "client_error"}
                performed = "result" in holder
                result = holder.get(
                    "result", {"status": "idempotent", "provider": provider}
                )
            else:
                # Compatibility for injected third-party budget objects. The
                # production InterruptBudget always exposes the durable broker.
                if self._budget is not None and not self._budget.consume():
                    return {"status": "failed", "reason": "interrupt_budget_exhausted"}
                try:
                    result = await self._client.call(provider, to, message, credentials, config)
                    performed = True
                except Exception:
                    logger.warning("call execute failed", exc_info=True)
                    return {"status": "failed", "reason": "client_error"}
            if self._ledger is not None and performed:
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
