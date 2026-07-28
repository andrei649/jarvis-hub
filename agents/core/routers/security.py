"""Security / trust endpoints (H17.1–H17.4 + posture) — extracted from web.py (CLN-3).

Covers the `/api/security/*` surface: prompt-injection quarantine, governance
gate, capability tokens + kill-switch, externally-anchored audit + intent
attribution, and the packaged security posture.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse

from agents.core.routers._deps import admin_guard, user_guard

from agents.core.web_helpers import nocache_json
from agents.core.app_state import get_orch

logger = logging.getLogger("jarvis.web")


router = APIRouter(tags=["security"])


def _admin_kernel_denial(orch, kind: str, cap_name: str, payload: dict, token_id: str):
    """ORIZONT-24 K1 wave-4a/4b: mediate an admin write through the Action Kernel
    (default-off).

    Returns a deny-reason (caller → HTTP 403) or ``None`` (allow). **DENY only** — GRANT
    and QUEUE both allow through: an unknown ``admin.*`` kind classifies high-risk and the
    policy returns ASK→QUEUE, but we do not gate the operator's admin UX on an approval
    card, we only honor a hard **DENY** (a halted kill-switch, a missing capability token,
    or a *presented* token that lacks the named capability). Default-off: returns ``None``
    unless ``JARVIS_ACTION_KERNEL`` is set and a bound kernel is reachable.

    wave-4b: a token is now MANDATORY for this kind (``kernel.TOKEN_MANDATORY_KINDS``).
    Every route that calls this already sits behind ``admin_guard`` — the caller is
    already proven — so when nothing was *presented* via ``x-capability-token`` we mint
    a short-lived, single-capability operator token ourselves and present that instead
    of an empty one, letting the kernel's real capability nucleus run rather than
    tolerating an absent token. An explicitly presented token still wins (a future
    finer-grained caller can supply its own). ``make_action_kernel`` is imported lazily
    so the router stays import-cheap and the exerciser can substitute a spy.
    """
    from agents.core.kernel import kernel_enabled
    if not kernel_enabled():
        return None
    from agents.core.kernel.binding import make_action_kernel
    kernel = make_action_kernel(orch)
    if kernel is None:
        return None
    from agents.core.kernel import Action, Capability, Verdict
    from agents.core.kernel.capabilities import issue_operator_capability
    if not token_id:
        token_id = issue_operator_capability(getattr(orch, "capabilities", None), cap_name)
    scope = (payload or {}).get("scope", "global")
    decision = kernel(
        Action(kind=kind, agent="operator", title=f"admin {kind}",
               payload=payload, scope=scope, origin="external"),
        capability=Capability(token_id=token_id or "", name=cap_name))
    return decision.reason if decision.verdict is Verdict.DENY else None


@router.post("/api/security/spotlight", dependencies=[Depends(user_guard)])
async def security_spotlight(req: Request):
    """H17.1 — datamark untrusted content + flag prompt-injection attempts."""
    from agents.core.security.quarantine import spotlight
    try:
        body = await req.json()
    except Exception:
        body = {}
    text = (body or {}).get("text", "")
    if not text:
        return JSONResponse({"error": "text required"}, status_code=400)
    return nocache_json(spotlight(text, (body or {}).get("source", "untrusted")))


@router.post("/api/security/scan-injection", dependencies=[Depends(user_guard)])
async def security_scan_injection(req: Request):
    """H17.1 — return prompt-injection patterns found in text (empty = clean)."""
    from agents.core.security.quarantine import detect_injection
    try:
        body = await req.json()
    except Exception:
        body = {}
    flags = detect_injection((body or {}).get("text", ""))
    return nocache_json({"flags": flags, "suspicious": bool(flags)})


@router.get("/api/security/governance")
async def security_governance():
    """H17.2 — public trust scorecard: injection + harm suites + OWASP Top 10 + gate."""
    from agents.core.security.governance import governance_gate
    return nocache_json(governance_gate())


# ── H17.3 Capability tokens + out-of-band kill-switch ─────────────────────────

@router.post("/api/security/capabilities/issue", dependencies=[Depends(admin_guard)])
async def capabilities_issue(req: Request):
    """Mint a scoped, expiring capability token (out-of-band; admin only)."""
    orch = get_orch()
    broker = getattr(orch, "capabilities", None) if orch else None
    if broker is None:
        return JSONResponse({"error": "capability broker not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    caps = (body or {}).get("capabilities") or []
    if not caps:
        return JSONResponse({"error": "capabilities required"}, status_code=400)
    # wave-4a: minting a capability is a privileged escalation → kernel-mediated. While a
    # halt is engaged this is denied; the operator's recovery path is to disengage the
    # kill-switch (which bypasses the kernel — see kill_switch_set) and then re-credential.
    denied = _admin_kernel_denial(
        orch, "admin.capability_issue", "admin:capability_issue",
        {"caps": sorted(str(c) for c in caps)},
        req.headers.get("x-capability-token", ""))
    if denied is not None:
        return JSONResponse({"error": f"kernel denied: {denied}"}, status_code=403)
    try:
        ttl = float(body.get("ttl", 3600))
    except (TypeError, ValueError):
        return JSONResponse({"error": "ttl must be a number"}, status_code=400)
    token = broker.issue(caps, source=body.get("source", ""),
                         task_id=body.get("task_id", ""), ttl=ttl)
    return nocache_json({"ok": True, "token": token})


@router.get("/api/security/capabilities/check")
async def capabilities_check(token: str, capability: str):
    """Check whether a token currently grants a capability (read-only)."""
    orch = get_orch()
    broker = getattr(orch, "capabilities", None) if orch else None
    kill = getattr(orch, "kill_switch", None) if orch else None
    if broker is None or kill is None:
        return JSONResponse({"error": "capability broker not available"}, status_code=503)
    from agents.core.security.capability import authorize
    return nocache_json(authorize(broker, kill, token, capability))


@router.get("/api/security/kill-switch")
async def kill_switch_status():
    """Out-of-band kill-switch status."""
    orch = get_orch()
    kill = getattr(orch, "kill_switch", None) if orch else None
    if kill is None:
        return JSONResponse({"error": "kill-switch not available"}, status_code=503)
    return nocache_json(kill.status())


@router.post("/api/security/kill-switch", dependencies=[Depends(admin_guard)])
async def kill_switch_set(req: Request):
    """Engage/disengage the kill-switch (operator action; agent can't reach this)."""
    orch = get_orch()
    kill = getattr(orch, "kill_switch", None) if orch else None
    if kill is None:
        return JSONResponse({"error": "kill-switch not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    scope = (body or {}).get("scope", "global")
    if (body or {}).get("engage", True):
        # wave-4a: engaging a halt is a privileged escalation → kernel-mediated.
        # DISENGAGE is the safety-restoring action and is deliberately NOT mediated:
        # a halted kill-switch would otherwise DENY its own release (is_halted → deny),
        # bricking recovery. So disengage stays admin-guard-only and always works.
        denied = _admin_kernel_denial(
            orch, "admin.kill_switch", "admin:kill_switch",
            {"scope": scope, "engage": True},
            req.headers.get("x-capability-token", ""))
        if denied is not None:
            return JSONResponse({"error": f"kernel denied: {denied}"}, status_code=403)
        return nocache_json({"ok": True, "engaged": kill.engage(scope, body.get("reason", ""))})
    return nocache_json({"ok": True, "disengaged": kill.disengage(scope)})


# ── K3 loop circuit breaker — status + operator reset ─────────────────────────

@router.get("/api/security/loop-breaker")
async def loop_breaker_status():
    """Kernel loop circuit-breaker status (read-only): tripped + threshold/window."""
    orch = get_orch()
    det = getattr(orch, "loop_detector", None) if orch else None
    if det is None:
        return JSONResponse({"error": "loop breaker not available"}, status_code=503)
    return nocache_json(det.status())


@router.post("/api/security/loop-breaker/reset", dependencies=[Depends(admin_guard)])
async def loop_breaker_reset():
    """Reset (close) the kernel loop circuit-breaker after a runaway trip (operator action).

    Like the kill-switch *disengage*, this is a recovery action — admin-guard-only and
    deliberately NOT kernel-mediated, so a tripped breaker (or an engaged halt) can never
    block its own reset."""
    orch = get_orch()
    det = getattr(orch, "loop_detector", None) if orch else None
    if det is None:
        return JSONResponse({"error": "loop breaker not available"}, status_code=503)
    was = det.tripped
    det.reset()
    return nocache_json({"ok": True, "was_tripped": was, "tripped": det.tripped})


# ── H17.4 Externally-anchored audit + intent attribution ──────────────────────

@router.post("/api/security/audit/action", dependencies=[Depends(admin_guard)])
async def audit_record_action(req: Request):
    """Record a signed action with causal intent attribution (why it happened)."""
    orch = get_orch()
    log = getattr(orch, "intent_log", None) if orch else None
    if log is None:
        return JSONResponse({"error": "intent log not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    for k in ("actor", "action", "why"):
        if not (body or {}).get(k):
            return JSONResponse({"error": "actor, action, why required"}, status_code=400)
    entry = log.record(body["actor"], body["action"], body["why"],
                       cause=body.get("cause", ""), metadata=body.get("metadata"))
    return nocache_json({"ok": True, "entry": entry})


@router.get("/api/security/audit/intent")
async def audit_intent(limit: int = Query(100, ge=1, le=1000)):
    """List signed intent records + chain/signature verification."""
    orch = get_orch()
    log = getattr(orch, "intent_log", None) if orch else None
    if log is None:
        return JSONResponse({"error": "intent log not available"}, status_code=503)
    return nocache_json({"verify": log.verify(), "entries": log.list(limit)})


@router.post("/api/security/audit/anchor", dependencies=[Depends(admin_guard)])
async def audit_anchor():
    """Anchor the audit / intent chain head into the external transparency log."""
    orch = get_orch()
    anchor = getattr(orch, "transparency", None) if orch else None
    if anchor is None:
        return JSONResponse({"error": "transparency anchor not available"}, status_code=503)
    root = ""
    if getattr(orch, "audit", None) is not None:
        try:
            root = orch.audit.tail_hash()
        except Exception:
            root = ""
    if not root and getattr(orch, "intent_log", None) is not None:
        root = orch.intent_log.head()
    receipt = anchor.anchor(root or "empty", source="audit")
    return nocache_json({"ok": True, "receipt": receipt})


@router.get("/api/security/audit/verify")
async def audit_verify():
    """Verify the Merkle hash chain of the security audit log (tamper evidence).

    'Tamper-evident' is only real if the chain is actually checked — this is the
    check. Returns the first broken row id when integrity fails.

    Reports `tamper_evident` separately from `valid`, because they are different claims:
    an UNKEYED chain that verifies proves only that nobody edited a row without also
    recomputing its hash, which anyone with file access can do. `reason` says which
    situation you are in, in plain English — including the case where a key was
    configured on a chain that predates it, which is a false verdict with a very
    different remedy from an actual rewrite (adversarial audit 2026-07-25, AUDIT-1)."""
    orch = get_orch()
    audit = getattr(orch, "audit", None) if orch else None
    if audit is None:
        return JSONResponse({"error": "audit log not available"}, status_code=503)
    return nocache_json(await asyncio.to_thread(audit.chain_status))


@router.get("/api/security/audit/anchors")
async def audit_anchors(limit: int = Query(100, ge=1, le=1000)):
    """List external anchor receipts + verify the anchor chain."""
    orch = get_orch()
    anchor = getattr(orch, "transparency", None) if orch else None
    if anchor is None:
        return JSONResponse({"error": "transparency anchor not available"}, status_code=503)
    return nocache_json({"verify": anchor.verify(), "anchors": anchor.list(limit)})


@router.get("/api/security/posture", dependencies=[Depends(admin_guard)])
async def security_posture():
    """Packaged security posture: encrypted secrets + signed skills + sandbox + guardrails (H12.1)."""
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)

    # Secrets at-rest backend. `encrypted_at_rest` is DERIVED from it below, never
    # asserted: it used to be the literal `True`, so a box where the secret store
    # could not even be constructed still got a green "encrypted" badge on the
    # security posture page — the one screen whose whole job is to not do that.
    try:
        from core.secrets import SecretStore
        secret_backend = SecretStore().backend
    except Exception:
        logger.warning("secret store unavailable — posture reports unknown", exc_info=True)
        secret_backend = "unavailable"
    # "fernet"  → AES via the cryptography package.
    # "hmac-fallback" → the pure-Python HMAC-keystream + HMAC-tag cipher used when
    #   cryptography is absent. Genuinely encrypted and authenticated, but not a
    #   vetted AEAD, so it is reported as encrypted AND flagged as the weaker path
    #   rather than being silently equated with fernet.
    # anything else → we could not open the store, so we do not know.
    secrets_posture: dict = {"backend": secret_backend}
    if secret_backend in ("fernet", "hmac-fallback"):
        secrets_posture["encrypted_at_rest"] = True
        secrets_posture["strength"] = "aead" if secret_backend == "fernet" else "fallback-cipher"
        if secret_backend == "hmac-fallback":
            secrets_posture["note"] = (
                "the 'cryptography' package is not installed — secrets use the "
                "pure-Python fallback cipher; install it for AES-based Fernet"
            )
    else:
        secrets_posture["encrypted_at_rest"] = None  # unknown, not false and not true
        secrets_posture["note"] = "secret store could not be opened — at-rest state unknown"

    # Skill signing posture.
    from core.skills import signing as _signing
    from agents.core import product_posture
    from agents.core.security import hardened as _hardened
    skills = list(getattr(orch.skills, "skills", {}).values()) if getattr(orch, "skills", None) else []
    skill_rows = [s.to_dict() for s in skills]
    untrusted = [s for s in skill_rows if not s.get("trusted")]

    # Sandbox isolation posture (HF-6 — flag host-exec without isolation, not just
    # docker availability). Reflects the orchestrator's live Sandbox instance.
    try:
        sandbox_sec = orch.sandbox.security_status()
    except Exception:
        # Sandbox is optional; absence just means posture reports an unavailable
        # backend rather than failing the security-posture endpoint. `isolated` and
        # `insecure_host_exec` are None rather than False — False would be a claim
        # ("nothing runs unisolated") made from a status read that failed.
        sandbox_sec = {"backend": "unavailable", "isolated": None,
                       "insecure_host_exec": None, "docker": False,
                       "note": "sandbox status could not be read"}

    return nocache_json({
        "secrets": secrets_posture,
        "skills": {
            # signing_posture() rather than require_signed(): the latter raises on a
            # misconfigured gate (enforcement on, no key), which is correct for the
            # enforcement path and useless here — a 500 tells the owner nothing. This
            # reports `effective` and `integrity_only` so "the flag is on" is not mistaken
            # for "signatures prove authorship" (SEC-B2).
            **_signing.signing_posture(),
            "total": len(skill_rows),
            "trusted": len(skill_rows) - len(untrusted),
            "untrusted": len(untrusted),
            "untrusted_names": [s["name"] for s in untrusted],
            "detail": skill_rows,
        },
        "sandbox": {"docker_available": sandbox_sec.get("docker", False), **sandbox_sec},
        "guardrails": {"mode": orch.get_setting("security.guardrails_mode", "WARN")},
        # CDX-12: the Design-Partner / Hardened profile posture (opt-in, default-off).
        "hardened": _hardened.posture(),
        "product_posture": product_posture.snapshot(getattr(orch, "_runtime_settings", {})),
    })
