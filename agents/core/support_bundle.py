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
  * ``credentials``  — which provider/tool/platform/hub key *variables* are set (names only)
  * ``overrides``    — settings that differ from their declared default; a value is shown
                       only for plain kinds (toggle/number/select/slider/model id) and
                       never for a secret or free-text row, which reads ``withheld``
  * ``logs``         — opt-in only (``log_lines`` > 0): the newest WARNING+ hub log records,
                       secret-redacted by the log reader and e-mail-masked here. The one
                       section that can carry log text, so it is never in a default bundle.
"""

from __future__ import annotations

import contextlib
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path

#: The llm rows that name what answers a turn. Model ids and enum choices only — a
#: base URL can carry credentials, so ``lm_studio_url``/``ollama_url`` are not listed.
_MODEL_KEYS = ("backend_type", "default_model", "gemini_model", "claude_model",
               "compatible_provider", "compatible_model", "cloud_fallback", "reasoning_effort")

#: Free-text rows that hold a model id: shown only when the value has a model id's shape.
_MODEL_ID_ROWS = frozenset({("llm", "default_model"), ("llm", "claude_model"), ("llm", "compatible_model")})
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}")

#: Tool, platform and hub credentials Nerva reads, beside the LLM provider keys
#: (tests/test_support_bundle.py pins that each one is read somewhere under agents/).
_OTHER_KEYS = {
    "tools": ("ELEVENLABS_API_KEY", "FISH_AUDIO_API_KEY", "FAL_KEY", "TAVILY_API_KEY",
              "PERPLEXITY_API_KEY", "GITHUB_TOKEN", "HASS_TOKEN", "HOMEBRIDGE_TOKEN", "N8N_API_KEY"),
    "platforms": ("TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN"),
    "hub": ("JARVIS_ADMIN_TOKEN", "JARVIS_USER_TOKEN", "JARVIS_BACKUP_KEY"),
}

#: Log lines a support bundle may carry at most, and the floor it reads them at.
MAX_LOG_LINES = 500
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _shown_value(category: str, key: str, kind: str, opts, value) -> tuple[bool, object]:
    """``(True, value)`` only when the stored value cannot carry a credential or free
    text: a number/toggle that is one, a select value that is one of its declared
    choices, a model id with a model id's shape. Anything else is withheld — the kind a
    row declares is not trusted on its own, since a write does not check it."""
    from agents.core import settings_db

    if settings_db.is_secret_setting(category, key):
        return False, None
    if kind in ("toggle",):
        return isinstance(value, bool), value
    if kind in ("number", "slider"):
        return isinstance(value, (int, float)) and not isinstance(value, bool), value
    if kind == "select":
        return bool(opts) and value in opts, value
    if kind == "model-select" or (category, key) in _MODEL_ID_ROWS:
        ok = (value == "" or (isinstance(value, str) and bool(_MODEL_ID.fullmatch(value))
                              and "://" not in value and not settings_db._looks_like_credential(value)))
        return ok, value
    return False, None


def _build_sha() -> str | None:
    """The checked-out commit, read from ``.git`` without running git (None if absent)."""
    root = Path(__file__).resolve().parents[2] / ".git"
    try:
        head = (root / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head[:12] or None
        ref = head[5:]
        loose = root / ref
        if loose.is_file():
            return loose.read_text(encoding="utf-8").strip()[:12] or None
        for line in (root / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return line.split(" ", 1)[0][:12]
    except OSError:
        return None
    return None


def _meta(now_iso: str) -> dict:
    out = {"python": sys.version.split()[0], "platform": sys.platform, "generated_at": now_iso}
    with contextlib.suppress(Exception):
        from agents import __version__
        out["version"] = __version__
    out["build"] = _build_sha()
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
        out: dict = {}
        for key in _MODEL_KEYS:
            spec = settings_db._SPEC.get(("llm", key), {})
            value = settings_db.get_value("llm", key)
            ok, shown = _shown_value("llm", key, str(spec.get("kind", "")), spec.get("opts") or [], value)
            out[key] = shown if ok else "(withheld)"
        return out
    except Exception:
        return {"error": "unavailable"}


def _credentials(environ: Mapping[str, str] | None = None) -> dict:
    """Which credential variables are set — the variable *names*, never a value or a
    prefix of one. Provider keys come from the provider profiles; the ``*_API_KEYS``
    multi-account pool is listed only for the providers that pool (provider_probe)."""
    env = os.environ if environ is None else environ
    try:
        from agents.core.llm.provider_probe import POOLED
        from agents.core.llm.providers import list_profiles
        profiles = [p for p in list_profiles() if p.auth_env]
    except Exception:
        return {"error": "unavailable"}
    groups = {"providers": sorted({p.auth_env for p in profiles}
                                  | {f"{p.auth_env}S" for p in profiles if p.id in POOLED}),
              **{name: sorted(keys) for name, keys in _OTHER_KEYS.items()}}
    names = [n for group in groups.values() for n in group]
    present = [n for n in names if str(env.get(n, "")).strip()]
    return {"set": present, "unset": [n for n in names if n not in present],
            "groups": groups}


def _overrides() -> dict:
    """Stored settings whose value is not their declared default (``source`` other than
    ``default``: set, undeclared or unreadable), each value filtered by _shown_value."""
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
            ok, shown = _shown_value(cat, row["key"], str(row.get("kind", "")), row.get("opts") or [],
                                     row.get("value"))
            if ok:
                item["value"] = shown
            else:
                item["withheld"] = True
            rows.append(item)
    return {"count": len(rows), "settings": rows}


def _logs(lines: int) -> dict:
    """The newest WARNING-and-above records of the hub log (Hermes' ``debug share
    --local`` log tail), through the same reader and secret redactor as the HUD log
    page, with e-mail addresses masked too. Opt-in: ``lines`` 0 leaves logs out."""
    if lines <= 0:
        return {"included": False}
    try:
        from agents.core import log_tail
        tail = log_tail.read_log(level="WARNING", lines=min(int(lines), MAX_LOG_LINES))
    except Exception:
        return {"error": "unavailable"}
    entries = [_EMAIL.sub("[email]", str(e.get("text", ""))) for e in tail.get("entries") or []]
    return {"included": True, "level": "WARNING", "file": tail.get("file"),
            "entries": entries, "truncated": bool(tail.get("truncated")),
            "note": tail.get("note", "")}


def build_bundle(orch=None, *, now_iso: str = "", route_count: int | None = None,
                 environ: Mapping[str, str] | None = None, log_lines: int = 0) -> dict:
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
        "logs": _logs(log_lines),
    }


def render_text(bundle: Mapping) -> str:
    """The bundle as a short pasteable report (``nerva support bundle``). Every line is
    read from the allow-listed bundle, so the text can say nothing the JSON does not."""
    meta = bundle.get("meta") or {}
    build = f" ({meta['build']})" if meta.get("build") else ""
    lines = [f"Nerva {meta.get('version', '?')}{build} · python {meta.get('python', '?')} · "
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
    logs = bundle.get("logs") or {}
    if "error" in logs:
        lines.append("logs: unavailable")
    elif not logs.get("included"):
        lines.append("logs: not included (add --logs N for the newest warnings and errors)")
    else:
        lines.append(f"logs: {len(logs.get('entries') or [])} newest {logs.get('level')}+ records"
                     + (f" ({logs['note']})" if logs.get("note") else ""))
        lines.extend(f"  {entry}" for entry in logs.get("entries") or [])
    return "\n".join(lines) + "\n"
