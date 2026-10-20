"""support_bundle.py — 0.55 Design Partner Kit: a diagnostic "issue bundle".

Assembles a single, **non-sensitive** snapshot a design partner can attach to a
support request — version + posture + readiness + recent activity *counts*, so an
issue can be triaged without a screen-share or a risky data dump.

Safety is by **allow-list**, not redaction: this only ever includes the specific
aggregates below — never raw config, secrets, tokens, message content, audit
previews, or PII. Each section is assembled defensively; a source that fails is
reported as ``{"error": "unavailable"}`` rather than crashing the bundle or
leaking a traceback.

Included:
  * ``meta``         — app version, python, platform, generated_at
  * ``posture``      — hardened profile flags (CDX-12) + active system profile (0.62)
  * ``capabilities`` — readiness roll-ups (counts by state/kind; not the full list)
  * ``egress``       — per-plugin allowed/blocked/external tallies + local-only proof
  * ``audit``        — recent event *counts by type* + hash-chain integrity (no content)
  * ``routes``       — the HTTP route count
  * ``model``        — the selected backend and model ids (H009: names, never a key)
  * ``credentials``  — which provider key *variables* are set or unset (names only)
  * ``overrides``    — settings that differ from their declared default; a value is shown
                       only for plain kinds (toggle/number/select/slider/model id) and
                       never for a secret or free-text row, which reads ``withheld``
"""

from __future__ import annotations

import contextlib
import os
import sys
from collections.abc import Mapping

#: The llm rows that name what answers a turn. Model ids and enum choices only — a
#: base URL can carry credentials, so ``lm_studio_url``/``ollama_url`` are not listed.
_MODEL_KEYS = ("backend_type", "default_model", "gemini_model", "claude_model",
               "compatible_provider", "compatible_model", "cloud_fallback", "reasoning_effort")

#: Setting kinds whose value cannot hold a credential or free text.
_SHOWN_KINDS = frozenset({"toggle", "number", "select", "slider", "model-select"})


def _meta(now_iso: str) -> dict:
    out = {"python": sys.version.split()[0], "platform": sys.platform, "generated_at": now_iso}
    with contextlib.suppress(Exception):
        from agents import __version__
        out["version"] = __version__
    return out


def _posture() -> dict:
    out: dict = {}
    try:
        from agents.core.security import hardened
        out["hardened"] = hardened.posture()
    except Exception:
        out["hardened"] = {"error": "unavailable"}
    try:
        from agents.core import product_posture
        out["product_posture"] = product_posture.snapshot()
    except Exception:
        out["product_posture"] = {"error": "unavailable"}
    try:
        from agents.core import system_profiles
        out["system_profile"] = system_profiles.list_profiles()
    except Exception:
        out["system_profile"] = {"error": "unavailable"}
    return out


def _capabilities(orch) -> dict:
    try:
        from agents.core.observability.capability_registry import snapshot
        snap = snapshot(orch)
        # roll-ups only — omit the full per-capability list to keep the bundle compact
        return {k: snap[k] for k in ("total", "by_state", "by_kind", "harness_pending") if k in snap}
    except Exception:
        return {"error": "unavailable"}


def _egress() -> dict:
    try:
        from agents.core.observability.egress_monitor import EGRESS_MONITOR
        snap = EGRESS_MONITOR.snapshot(limit=0)   # limit=0 → no event payloads, tallies only
        # DRA-23: `model_egress_total` travels with the plugin tallies — without it the
        # bundle asserts local-first purity from plugin traffic alone, while a cloud
        # model may have answered every turn.
        return {k: snap[k] for k in
                ("plugins", "external_egress_total", "model_egress_total",
                 "local_only_violations", "clean") if k in snap}
    except Exception:
        return {"error": "unavailable"}


def _audit(orch) -> dict:
    try:
        audit = getattr(orch, "audit", None)
        if audit is None:
            return {"error": "unavailable"}
        events = audit.query(limit=500)
        counts: dict[str, int] = {}
        for e in events:
            t = str(getattr(e, "event_type", "") or "unknown")
            counts[t] = counts.get(t, 0) + 1
        out = {"recent_event_counts": counts, "window": len(events)}
        with contextlib.suppress(Exception):
            ok, broken_at = audit.verify_chain()
            out["chain_ok"] = bool(ok)
            if not ok:
                out["chain_broken_at"] = broken_at
        return out
    except Exception:
        return {"error": "unavailable"}


def _model() -> dict:
    try:
        from agents.core import settings_db
        return {key: settings_db.get_value("llm", key) for key in _MODEL_KEYS}
    except Exception:
        return {"error": "unavailable"}


def _credentials(environ: Mapping[str, str] | None = None) -> dict:
    """Which provider key variables are set — the variable *names*, never a value or a
    prefix of one. ``*_API_KEYS`` (the multi-account pool) counts as set too."""
    env = os.environ if environ is None else environ
    try:
        from agents.core.llm.providers import list_profiles
        names = sorted({p.auth_env for p in list_profiles() if p.auth_env})
    except Exception:
        return {"error": "unavailable"}
    names += sorted({f"{n}S" for n in names if n.endswith("_API_KEY")})
    present = [n for n in names if str(env.get(n, "")).strip()]
    return {"set": present, "unset": [n for n in names if n not in present]}


def _overrides() -> dict:
    try:
        from agents.core import settings_db
        groups = settings_db.get_all()
    except Exception:
        return {"error": "unavailable"}
    rows = []
    for cat, entries in sorted(groups.items()):
        for row in entries:
            if row.get("source") == "default":
                continue
            item = {"name": f"{cat}.{row['key']}", "source": row.get("source")}
            if row.get("kind") in _SHOWN_KINDS and not settings_db.is_secret_setting(cat, row["key"]):
                item["value"] = row.get("value")
            else:
                item["withheld"] = True
            rows.append(item)
    return {"count": len(rows), "settings": rows}


def build_bundle(orch=None, *, now_iso: str = "", route_count: int | None = None,
                 environ: Mapping[str, str] | None = None) -> dict:
    """Assemble the diagnostic bundle. Pure aside from reading live diagnostics; every
    section is defensive so the bundle is always well-formed.

    ``route_count`` is supplied by the caller (the router reads ``request.app.routes``)
    so this core module never imports ``agents.web`` — keeping it out of an import cycle.
    """
    return {
        "meta": _meta(now_iso),
        "posture": _posture(),
        "capabilities": _capabilities(orch),
        "egress": _egress(),
        "audit": _audit(orch),
        "routes": route_count,
        "model": _model(),
        "credentials": _credentials(environ),
        "overrides": _overrides(),
    }


def render_text(bundle: Mapping) -> str:
    """The bundle as a short pasteable report (``nerva support bundle``). Every line is
    read from the allow-listed bundle, so the text can say nothing the JSON does not."""
    meta = bundle.get("meta") or {}
    lines = [f"Nerva {meta.get('version', '?')} · python {meta.get('python', '?')} · "
             f"{meta.get('platform', '?')} · {meta.get('generated_at', '')}".rstrip(" ·")]
    model = bundle.get("model") or {}
    if "error" in model:
        lines.append("model: unavailable")
    else:
        lines.append("model: " + ", ".join(f"{k}={model.get(k)!s}" for k in _MODEL_KEYS
                                            if model.get(k) not in (None, "")))
    creds = bundle.get("credentials") or {}
    if "error" in creds:
        lines.append("keys: unavailable")
    else:
        lines.append("keys set: " + (", ".join(creds.get("set") or []) or "none"))
    over = bundle.get("overrides") or {}
    if "error" in over:
        lines.append("overrides: unavailable")
    else:
        lines.append(f"overrides: {over.get('count', 0)}")
        for item in over.get("settings") or []:
            shown = "(withheld)" if item.get("withheld") else repr(item.get("value"))
            lines.append(f"  {item['name']} = {shown}  [{item.get('source')}]")
    posture = bundle.get("posture") or {}
    hard = posture.get("hardened") or {}
    prod = posture.get("product_posture") or {}
    lines.append(f"posture: hardened={hard.get('enabled', '?')} product={prod.get('name', '?')}")
    caps = bundle.get("capabilities") or {}
    if "error" not in caps:
        lines.append(f"capabilities: {caps.get('total', '?')} {caps.get('by_state', {})}")
    egress = bundle.get("egress") or {}
    if "error" not in egress:
        lines.append(f"egress: external={egress.get('external_egress_total', '?')} "
                     f"model={egress.get('model_egress_total', '?')} clean={egress.get('clean', '?')}")
    audit = bundle.get("audit") or {}
    lines.append("audit: unavailable" if "error" in audit else
                 f"audit: {audit.get('window', 0)} recent events, chain_ok={audit.get('chain_ok', '?')}")
    if bundle.get("routes") is not None:
        lines.append(f"routes: {bundle['routes']}")
    return "\n".join(lines) + "\n"
