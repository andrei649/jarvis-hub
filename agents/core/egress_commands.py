"""Read-only owner chat status for H084 egress, credentials and proxy hints."""

from __future__ import annotations

import asyncio
import re

from . import env_provenance, support_bundle
from .channels.outbound_safety import sanitize_text
from .env_config import env_str
from .observability.egress_monitor import EGRESS_MONITOR

_PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "WSS_PROXY",
               "DISCORD_PROXY", "TELEGRAM_PROXY", "http_proxy", "https_proxy",
               "all_proxy", "no_proxy", "wss_proxy")
_CREDENTIAL_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
_HANDLE_NAME = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")
_DISPLAY_LIMIT = 12
_REPLY_LIMIT = 5_000


def _safe(value: str) -> bool:
    try:
        return sanitize_text(value) == value
    except Exception:
        return False


def _listed(names: list[str]) -> str:
    shown = ", ".join(names[:_DISPLAY_LIMIT]) or "none set"
    extra = len(names) - _DISPLAY_LIMIT
    return shown + (f", +{extra} more" if extra > 0 else "")


def _collect(orch) -> str:
    """Read only live in-process state and the existing local egress ledger."""
    try:
        snap = EGRESS_MONITOR.snapshot(limit=0)
        ledger = snap.get("ledger") if isinstance(snap, dict) else None
        if not isinstance(ledger, dict):
            raise ValueError("missing ledger status")
        persistent = ledger.get("persistent") is True
        ledger_error = bool(ledger.get("error"))
        ledger_status = ("persistent" if persistent else "process-only; persistent ledger unavailable")
        if ledger_error:
            ledger_status += " (read or write warning; history may be incomplete)"
        external = snap.get("external_egress_total")
        model = snap.get("model_egress_total")
        counts_available = (type(external) is int and external >= 0 and type(model) is int
                            and 0 <= model <= external)
        counts = (f"External allowed attempts: {external}; model share: {model}"
                  if counts_available else "External allowed attempts: unavailable")
    except Exception:
        persistent, ledger_error, counts_available = False, True, False
        ledger_status = "unavailable (process and persistent history unknown)"
        counts = "External allowed attempts: unavailable"

    try:
        source = env_provenance.provenance()
        if not isinstance(source, dict):
            source = {}
    except Exception:
        source = {}

    def layer(name: str) -> str:
        row = source.get(name)
        value = row.get("layer") if isinstance(row, dict) else None
        return value if isinstance(value, str) and value in env_provenance.LABELS else "unknown"

    proxies = [f"{name} ({layer(name)})" for name in _PROXY_KEYS if env_str(name)]
    proxy_status = (_listed(proxies) + "; configured only, actual route unverified"
                    if proxies else "no proxy environment variable configured; actual route unverified")

    try:
        inventory = support_bundle._credentials()
        if not isinstance(inventory, dict) or not isinstance(inventory.get("set"), list):
            raise ValueError("credential inventory unavailable")
        credentials = sorted({name for name in inventory["set"]
                              if isinstance(name, str) and _CREDENTIAL_NAME.fullmatch(name)
                              and _safe(name)})
        credential_status = _listed([f"{name} ({layer(name)})" for name in credentials])
    except Exception:
        credential_status = "unavailable"

    try:
        broker = getattr(orch, "secret_broker", None)
        if broker is None:
            raise ValueError("secret broker unavailable")
        names = broker.names()
        if not isinstance(names, list):
            raise ValueError("invalid secret names")
        valid = sorted({name for name in names if isinstance(name, str)
                        and _HANDLE_NAME.fullmatch(name) and _safe(name)})
        handles = [broker.reference(name) for name in valid[:_DISPLAY_LIMIT]]
        if any(not isinstance(handle, str) or not _safe(handle) for handle in handles):
            raise ValueError("unsafe secret handle")
        handle_status = _listed(handles)
        if len(valid) > _DISPLAY_LIMIT:
            handle_status += f", +{len(valid) - _DISPLAY_LIMIT} more"
        handle_status += " (stored names only; availability not checked)"
    except Exception:
        handle_status = "unavailable"

    if not persistent or ledger_error or not counts_available:
        next_step = ("Check /api/admin/network/calls and the hub log; repair unavailable "
                     "ledger or count data before treating this as complete history.")
    elif credential_status == "unavailable":
        next_step = ("Credential name inventory is unavailable. Check /api/admin/env/sources "
                     "before relying on this status.")
    elif handle_status == "unavailable":
        next_step = ("Stored secret handle names are unavailable. Check the secret broker "
                     "before relying on this status.")
    elif proxies:
        next_step = ("Proxy routing is unverified. Check the specific client transport and "
                     "CA trust before relying on this proxy configuration.")
    else:
        next_step = ("No action indicated by this snapshot. If a selected cloud service "
                     "reports an authentication failure, check that provider's credential "
                     "source; local-only use needs no cloud key.")

    reply = "\n".join(("Egress status", f"Ledger: {ledger_status}", counts,
                       f"Outbound proxy: {proxy_status}",
                       f"Credential sources (environment layer only): {credential_status}",
                       f"Secret handles: {handle_status}",
                       "Coverage: instrumented model and plugin attempts only; zero is not proof of no network egress.",
                       f"Next: {next_step}"))
    try:
        clean = sanitize_text(reply)
    except Exception:
        return "Egress status could not be redacted, so it was withheld."
    if not clean.startswith("Egress status") or len(clean) > _REPLY_LIMIT:
        return "Egress status could not be redacted, so it was withheld."
    return clean


async def egress_command(ctx) -> str:
    if not ctx.principal.admin:
        return "Only the owner can inspect egress status."
    if ctx.args.strip().lower() not in ("", "status"):
        return "Usage: /egress [status]."
    return await asyncio.to_thread(_collect, ctx.orch)
