"""Admin endpoints — extracted from web.py (CLN-3).

Covers the admin-guarded `/api/admin/*` control surface, EXCEPT the two
sub-domains that live elsewhere: `/api/admin/mcp*` (MCP domain, still inline in
web.py) and `/api/admin/widgets*` (the `secrets.py` router). What's here:

* settings read/write/reseed (`/api/admin/settings*`),
* env inspection (`/api/admin/env`, secret-masked),
* the security audit-log page (`/api/admin/audit`),
* session-memory clear (`/api/admin/memory/clear`),
* agent stats + APM + admin charts (`/api/admin/agents/stats`, `/apm`, `/stats`),
* prompt version control (`/api/admin/prompts/*`, H10.22),
* the per-agent override write (`PUT /api/admin/agents/{id}`),
* the local-backend connectivity probe (`/api/admin/llm/test`).

Every route keeps its original `dependencies=[Depends(admin_guard)]` guard.

State handling (established CLN-3 unblock policy):
* The settings-DB functions `get_all`/`get_category`/`put_category`/`init_db`
  are leaf imports from `core.settings_db` (no web edge).
* `_svs` (the SOUL version store accessor) and `_SECRET_HINTS` were used only by
  this domain in web.py (grep-confirmed), so they move here verbatim — `_svs`
  now resolves the orchestrator through `get_orch()`.
* `_AGENT_SETTINGS` is a *multi-domain* mutable global (also read by the agents
  surface's `_enrich_agents`), so it STAYS in web.py; `admin_agents_put` reaches
  it at request time via `sys.modules.get("agents.web")._get_agent_settings()`.
* `apm_summary`, `estimate_monthly`, `get_metrics`/`_circuit_breakers` are leaf
  imports (cost/resilience modules), unchanged from web.py.
"""

import asyncio
import json
import logging
import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agents.core.app_state import get_orch
from agents.core.log_safe import log_safe
from agents.core.paths import data_path
from agents.core.routers._deps import admin_guard
from agents.core.web_helpers import mask_secret, nocache_json, safe_reflect

logger = logging.getLogger("jarvis.web")

# Settings-DB functions are leaf imports (no edge back into web.py).
from agents.core.settings_db import get_all, get_category, put_category, validate_category
from agents.core.security.types import SecurityEvent, SecurityEventType
from agents.core.security.token_store import SCOPES, get_token_store

router = APIRouter(tags=["admin"])


# Substrings that mark an env var as sensitive — its value is masked in
# /api/admin/env so keys/tokens/secrets are never returned in clear text.
_SECRET_HINTS = ("key", "token", "secret", "password", "passwd", "pass", "client_id")


def _web():
    # Always present at request time (the app is running). Not an import edge.
    # `_AGENT_SETTINGS` is a multi-domain mutable global kept in web.py; reach its
    # accessor here so the single shared dict is read/mutated on each call.
    return sys.modules.get("agents.web")


@router.get("/api/admin/settings", dependencies=[Depends(admin_guard)])
async def admin_get_all():
    return get_all()


@router.get("/api/admin/settings/export", dependencies=[Depends(admin_guard)])
async def admin_export_settings():
    """H157 — the declared settings as JSON for another box. Secrets, values that look
    like credentials and settings that hold credentials by design are left out and
    named in ``excluded``. Registered before ``/{category}`` so it is never read as one."""
    from agents.core import settings_db

    doc = await asyncio.to_thread(settings_db.export_settings)
    resp = nocache_json(doc)
    resp.headers["Content-Disposition"] = 'attachment; filename="nerva-settings.json"'
    return resp


@router.get("/api/admin/settings/resets", dependencies=[Depends(admin_guard)])
async def admin_settings_resets():
    """H259 — the recorded resets, newest first: when, which scope, which settings (never
    their values) and whether each was undone. Registered before ``/{category}``."""
    from agents.core import settings_db

    return nocache_json({"resets": await asyncio.to_thread(settings_db.list_resets)})


@router.get("/api/admin/settings/{category}", dependencies=[Depends(admin_guard)])
async def admin_get_category(category: str):
    items = get_category(category)
    if not items:
        return JSONResponse({"error": f"unknown category: {safe_reflect(category)}"}, status_code=404)
    return {category: items}


class AdminPutBody(BaseModel):
    values: dict


#: Setting kinds whose value is a choice, never a secret: a switch, a pick from a list,
#: a number. The audit row says what such a key became (H153 review: "when was the
#: webhook receiver off?" had no answer in a row that named only the key). A model id is
#: typed, not picked (``model-select`` takes any string), so it is free text: a pasted
#: key would land in the row.
_VALUE_AUDITED_KINDS = frozenset({"toggle", "select", "number", "slider"})


def _audited_values(category: str, values: dict) -> str:
    """``key=value`` for the keys whose declared kind is a choice; never a secret key,
    never free text (a URL, a note or a typed model id can carry a credential)."""
    from agents.core import settings_db

    kinds = {(row["category"], row["key"]): row.get("kind") for row in settings_db.DEFAULTS}
    parts = []
    for key in sorted(values):
        if key in settings_db.SECRET_KEYS or kinds.get((category, key)) not in _VALUE_AUDITED_KINDS:
            continue
        try:
            parts.append(f"{key}={json.dumps(values[key], ensure_ascii=False)[:64]}")
        except (TypeError, ValueError):
            continue
    return " ".join(parts)


async def _audit_row(preview: str, action: str, category: str) -> None:
    orch = get_orch()
    audit = getattr(orch, "audit", None) if orch else None
    if audit is None:
        return
    try:
        await asyncio.to_thread(audit.log, SecurityEvent(
            event_type=SecurityEventType.SETTINGS_CHANGE,
            timestamp=time.time(),
            content_preview=preview,
            action_taken=action,
        ))
    except Exception:
        # log_safe (not safe_reflect) is the recognized py/log-injection sanitizer:
        # it strips CR/LF so a hostile category can't forge log lines.
        logger.warning("failed to audit settings change for %s", log_safe(category))


async def _audit_settings_change(category: str, keys: list, values: dict | None = None) -> None:
    """AUD-8: record a settings write in the audit log — the changed KEY NAMES, and the
    new value only for a key whose kind is a choice (a switch, a list pick, a number),
    never a secret or free text, so the row can't leak a secret that was just set."""
    preview = f"settings.{category} updated: {sorted(keys)}"
    shown = _audited_values(category, {key: (values or {}).get(key) for key in keys if key in (values or {})})
    if shown:
        preview = f"{preview} · {shown}"
    await _audit_row(preview, "settings_update", category)


@router.put("/api/admin/settings/{category}", dependencies=[Depends(admin_guard)])
async def admin_put_category(category: str, body: AdminPutBody):
    # AUD-8: reject a malformed write (wrong type / off the select allow-list) with
    # 422 before it can corrupt a setting the rest of the system reads back + trusts.
    errors = validate_category(category, body.values)
    if errors:
        return JSONResponse({"error": "invalid settings", "details": errors}, status_code=422)
    updated, skipped = put_category(category, body.values)
    changed = [k for k in body.values if k not in skipped]
    if changed:
        await _audit_settings_change(category, changed, body.values)
    resp = {"updated": updated, "category": category}
    if skipped:
        resp["skipped"] = skipped
    return resp


_IMPORT_MAX_BYTES = 1_000_000


def _refuse_cross_site_write(request: Request) -> JSONResponse | None:
    """H157 review M1 — a settings write must be a JSON request from this origin. On a
    default install the admin guard trusts loopback, so a page the owner visits could
    otherwise post a plain-text body that needs no browser pre-check. JSON forces that
    pre-check (and the CORS allow-list decides it); a browser that says the request is
    cross-site is refused outright."""
    kind = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if kind != "application/json":
        return nocache_json({"error": "expected application/json"}, status_code=415)
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        return nocache_json({"error": "a settings write must come from this origin"}, status_code=403)
    return None


async def _bounded_body(request: Request, limit: int) -> bytes | None:
    declared = request.headers.get("content-length", "")
    if declared.isascii() and declared.isdigit() and int(declared) > limit:
        return None
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/api/admin/settings/import", dependencies=[Depends(admin_guard)])
async def admin_import_settings(request: Request):
    """H157 — import a settings document (an export, or any ``{"settings": {category:
    {key: value}}}``). Every key must be declared and passes the same validation a single
    write does; one refusal and nothing is written (422 with every reason). The write is
    one transaction with one audit row. ``"dry_run": true`` answers what would change."""
    from agents.core import settings_db

    refused = _refuse_cross_site_write(request)
    if refused is not None:
        return refused
    raw = await _bounded_body(request, _IMPORT_MAX_BYTES)
    if raw is None:
        return nocache_json({"error": "invalid settings", "details": ["the document is over 1 MB"]},
                            status_code=413)
    try:
        doc = json.loads(raw or b"{}")
    except (ValueError, RecursionError):
        return nocache_json({"error": "invalid settings", "details": ["the document is not JSON"]},
                            status_code=422)
    dry_run = doc.pop("dry_run", False) is True if isinstance(doc, dict) else False
    changes, errors = await asyncio.to_thread(settings_db.plan_import, doc)
    if errors:
        return nocache_json({"error": "invalid settings", "details": errors}, status_code=422)
    preview = await asyncio.to_thread(settings_db.describe_changes, changes)
    if dry_run:
        return nocache_json({"dry_run": True, "count": len(preview), "changes": preview})
    written = await asyncio.to_thread(settings_db.apply_import, changes) if changes else 0
    if written:
        names = [f"{cat}.{key}" for cat in sorted(changes) for key in sorted(changes[cat])]
        shown = " ".join(filter(None, (_audited_values(cat, changes[cat]) for cat in sorted(changes))))
        await _audit_row(f"settings imported: {written} setting(s): {names}" + (f" · {shown}" if shown else ""),
                         "settings_import", "import")
    return nocache_json({"ok": True, "updated": written, "changes": preview})


async def _dry_run_asked(request: Request) -> bool | JSONResponse:
    """H259 — whether a reset's JSON body is ``{"dry_run": true}`` (only a JSON ``true``)."""
    raw = await _bounded_body(request, 4096)
    if raw is None:
        return nocache_json({"error": "the request is over 4 KB"}, status_code=413)
    try:
        doc = json.loads(raw or b"{}")
    except (ValueError, RecursionError):
        return nocache_json({"error": "the request is not JSON"}, status_code=422)
    return isinstance(doc, dict) and doc.get("dry_run") is True


@router.post("/api/admin/settings/{category}/reset", dependencies=[Depends(admin_guard)])
async def admin_reset_category(category: str, request: Request):
    """H157 — put one category back to its declared values (the global reseed was the only
    reset). Its secrets are kept (``kept``); a setting the selected product posture forces
    stays in effect (``overridden``). Audited, naming the keys that moved. A JSON request
    from this origin only (review-H157 M1). H259 — ``{"dry_run": true}`` answers what it
    would change and writes nothing; a reset that moved something is recorded, and
    ``undo`` names the record ``POST /api/admin/settings/undo`` puts back."""
    from agents.core import settings_db

    refused = _refuse_cross_site_write(request)
    if refused is not None:
        return refused
    dry_run = await _dry_run_asked(request)
    if isinstance(dry_run, JSONResponse):
        return dry_run
    if dry_run:
        plan = await asyncio.to_thread(settings_db.plan_reset, category)
        if plan is None:
            return nocache_json({"error": f"unknown category: {safe_reflect(category)}"}, status_code=404)
        return nocache_json({"dry_run": True, "category": category,
                             "changes": await asyncio.to_thread(settings_db.describe_changes, plan),
                             "kept": settings_db.reset_kept(category),
                             "overridden": settings_db.posture_overridden(category)})
    done = await asyncio.to_thread(settings_db.reset_settings, category)
    if done is None:
        return nocache_json({"error": f"unknown category: {safe_reflect(category)}"}, status_code=404)
    moved = sorted(done[0].get(category, {}))
    if moved:
        await _audit_row(f"settings.{category} reset to defaults: {moved}", "settings_reset", category)
    return nocache_json({"ok": True, "category": category, "reset": moved, "undo": done[1],
                         "kept": settings_db.reset_kept(category),
                         "overridden": settings_db.posture_overridden(category)})


@router.post("/api/admin/settings/reseed", dependencies=[Depends(admin_guard)])
async def admin_reseed(request: Request):
    """Every category back to its declared values. H259 — this used to delete the whole
    store (secrets included) with no preview and no way back; it is now the per-category
    reset over every category: the secrets are kept (``kept``), ``{"dry_run": true}``
    answers what it would change, and what it replaced is recorded for ``undo``. A JSON
    request from this origin only; audited (H153 review), naming how many moved."""
    from agents.core import settings_db

    refused = _refuse_cross_site_write(request)
    if refused is not None:
        return refused
    dry_run = await _dry_run_asked(request)
    if isinstance(dry_run, JSONResponse):
        return dry_run
    kept, forced = settings_db.reset_kept_all(), settings_db.posture_overridden_all()
    if dry_run:
        plan = await asyncio.to_thread(settings_db.plan_reset, None)
        return nocache_json({"dry_run": True, "changes": await asyncio.to_thread(settings_db.describe_changes, plan),
                             "kept": kept, "overridden": forced})
    moved, snap = await asyncio.to_thread(settings_db.reset_settings, None)
    names = [f"{cat}.{key}" for cat in sorted(moved) for key in sorted(moved[cat])]
    if names:
        await _audit_row(f"settings reset to defaults in every category: {len(names)} setting(s): {names}",
                         "settings_reseed", "all")
    return nocache_json({"ok": True, "message": "Settings reseeded from defaults", "reset": names,
                         "undo": snap, "kept": kept, "overridden": forced})


@router.post("/api/admin/settings/undo", dependencies=[Depends(admin_guard)])
async def admin_undo_reset(request: Request):
    """H259 — put back what the latest reset replaced. A setting changed since that reset
    is left as it is, and so is a value its declaration no longer accepts; both are named
    in ``skipped``. 404 when there is nothing to undo. A JSON request from this origin
    only; audited."""
    from agents.core import settings_db

    refused = _refuse_cross_site_write(request)
    if refused is not None:
        return refused
    undone = await asyncio.to_thread(settings_db.undo_last_reset)
    if undone is None:
        return nocache_json({"error": "nothing to undo"}, status_code=404)
    skipped = [s["setting"] for s in undone["skipped"]]
    await _audit_row(f"settings reset undone ({undone['scope']}): restored {undone['restored']}"
                     + (f" · left {skipped}" if skipped else ""), "settings_reset_undo", undone["scope"])
    return nocache_json({"ok": True, **undone})


class RotateTokensBody(BaseModel):
    scope: str = "admin"
    ttl_days: float | None = None


@router.post("/api/admin/rotate-tokens", dependencies=[Depends(admin_guard)])
async def admin_rotate_tokens(body: RotateTokensBody):
    """AUD-6: mint a fresh issued token (TTL, hashed at rest), revoking the prior
    issued tokens of that scope **and** superseding the static env token for that
    scope (full-replace: the env token stops working after the first rotation). The
    raw token is returned **once** — only its hash is stored. The caller is already
    admin (admin-guarded); old/expired/env tokens are rejected afterwards. Audited
    (never the token value)."""
    scope = body.scope if body.scope in SCOPES else "admin"
    ttl = body.ttl_days if (body.ttl_days and body.ttl_days > 0) else None
    token = await asyncio.to_thread(
        get_token_store().rotate, scope, ttl, "rotated via /api/admin/rotate-tokens"
    )
    orch = get_orch()
    audit = getattr(orch, "audit", None) if orch else None
    if audit is not None:
        try:
            await asyncio.to_thread(audit.log, SecurityEvent(
                event_type=SecurityEventType.AUDIT_LOG,
                timestamp=time.time(),
                content_preview=f"issued token rotated (scope={scope}, ttl_days={ttl})",
                action_taken="token_rotated",
            ))
        except Exception:
            logger.warning("failed to audit token rotation")
    return {"scope": scope, "ttl_days": ttl, "token": token,
            "note": "store this token now — it is shown only once"}


@router.get("/api/admin/env", dependencies=[Depends(admin_guard)])
async def admin_get_env():
    # Mask anything that looks like a credential so secrets are never
    # returned in clear text, even to an authorized admin.
    out = {}
    for key, val in sorted(os.environ.items()):
        if key.startswith("_"):
            continue
        if any(h in key.lower() for h in _SECRET_HINTS):
            out[key] = mask_secret(val)
        else:
            out[key] = val
    return out


@router.get("/api/admin/env/sources", dependencies=[Depends(admin_guard)])
async def admin_env_sources():
    """H273: where each environment key came from — the process environment, the
    repo .env or the data-home .env, and which lower layers it overrides.

    Names and layers only, at the same boundary as /api/admin/env: no value is
    returned, and ``masked`` says whether /api/admin/env masks the key's value.
    """
    from pathlib import Path

    from agents.core import env_provenance
    from agents.core.paths import user_home

    rows = []
    for key, row in sorted(env_provenance.provenance().items()):
        if key.startswith("_"):
            continue
        item = {"key": key, "layer": row["layer"], "label": env_provenance.LABELS[row["layer"]],
                "shadowed": row["shadowed"], "masked": any(h in key.lower() for h in _SECRET_HINTS)}
        note = env_provenance.note_for(key, row["layer"])
        if note:
            item["note"] = note
        rows.append(item)
    # What the load did with each file (read, absent, the same file as the repo .env,
    # or skipped because python-dotenv was switched off); with no load in this process,
    # the files it would read now.
    loaded = env_provenance.files()
    if loaded:
        files = {layer: {"path": info["path"], "present": info["present"], "kind": info["kind"],
                         "read": info["read"]}
                 for layer, info in loaded.items()}
    else:
        repo_env = Path(__file__).resolve().parents[3] / ".env"
        home = user_home()
        home_env = home / ".env" if home is not None else None
        files = {
            "repo_env": {"path": str(repo_env), "present": env_provenance.is_file_or_fifo(repo_env),
                         "read": False},
            "user_env": {"path": str(home_env) if home_env else None,
                         "present": bool(home_env and env_provenance.is_file_or_fifo(home_env)), "read": False},
        }
    return nocache_json({"sources": rows, "files": files})


def _redact_audit_details(details: object) -> object:
    """AUD-12: mask any raw ``matched_text`` in a findings JSON blob at the read
    boundary. New rows are already redacted at write time (audit.py); this also
    covers rows written before that fix so the admin page never exposes a secret."""
    if not isinstance(details, str) or '"matched_text"' not in details:
        return details
    try:
        findings = json.loads(details)
    except (ValueError, TypeError):
        return details
    if not isinstance(findings, list):
        return details
    changed = False
    for f in findings:
        if isinstance(f, dict) and "matched_text" in f:
            mt = f.get("matched_text")
            if isinstance(mt, str) and not mt.startswith("[REDACTED:"):
                f["matched_text"] = f"[REDACTED:{f.get('pattern_name', 'secret')}]"
                changed = True
    return json.dumps(findings) if changed else details


@router.get("/api/admin/tool-events", dependencies=[Depends(admin_guard)])
async def admin_tool_events(limit: int = Query(100, ge=1, le=500)):
    """The tool loop's recent trail: what each agent asked for, what came back, and
    every time a result was fenced as untrusted data.

    Admin-only and read-only. The rows carry tool names, call ids, statuses, machine
    reasons and counts — never a tool's arguments and never its result, which is what
    lets this be read casually. ``counts`` is monotonic since boot, so "did the fence
    ever fire" is answerable even after the ring buffer has turned over.
    """
    from agents.core.observability.tool_events import TOOL_EVENTS

    return nocache_json({"events": TOOL_EVENTS.snapshot(limit), "counts": TOOL_EVENTS.counts()})


@router.get("/api/admin/logs", dependencies=[Depends(admin_guard)])
async def admin_logs(file: str = Query("", max_length=128), level: str = Query("", max_length=16),
                     component: str = Query("", max_length=200), lines: int = Query(200)):
    """H145 — the hub's own log, from the UI: the newest records of the log file or one of
    its rotations, read backwards within a byte budget (at most 500 records), filtered by
    file, minimum level and component, and redacted again as they are read. Admin-only and
    read-only; when file logging is off the answer says so (``enabled``, ``note``)."""
    from agents.core import log_tail

    try:
        out = await asyncio.to_thread(log_tail.read_log, file=file or None, level=level,
                                      component=component, lines=lines)
    except log_tail.LogRequestError as exc:
        return nocache_json({"error": "bad_request", "reason": str(exc)}, status_code=400)
    return nocache_json(out)


@router.get("/api/admin/audit", dependencies=[Depends(admin_guard)])
async def admin_get_audit(page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200)):
    db = data_path("security/audit.db")
    if not db.exists():
        return {"page": page, "limit": limit, "total": 0, "rows": []}

    # A full-table COUNT + page scan is blocking sqlite I/O; offload it so the audit
    # page (fastest-growing table) can't stall the event loop under load (audit A4).
    def _read() -> tuple[int, list[dict]]:
        import sqlite3
        conn = sqlite3.connect(str(db))
        try:
            conn.row_factory = sqlite3.Row
            has_audit = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='audit_events'").fetchone()
            table = "audit_events" if has_audit else "security_events"
            _QUERIES = {
                "audit_events": ("SELECT COUNT(*) FROM audit_events", "SELECT timestamp, event_type, content_preview AS summary, findings_json AS details FROM audit_events ORDER BY rowid DESC LIMIT ? OFFSET ?"),
                "security_events": ("SELECT COUNT(*) FROM security_events", "SELECT timestamp, event_type, content_preview AS summary, findings_json AS details FROM security_events ORDER BY rowid DESC LIMIT ? OFFSET ?"),
            }
            count_q, select_q = _QUERIES[table]
            total = conn.execute(count_q).fetchone()[0]
            offset = (page - 1) * limit
            rows = conn.execute(select_q, (limit, offset)).fetchall()
            out = []
            for r in rows:
                d = dict(r)
                if "details" in d:
                    d["details"] = _redact_audit_details(d["details"])
                out.append(d)
            return total, out
        finally:
            conn.close()

    total, rows = await asyncio.to_thread(_read)
    return {"page": page, "limit": limit, "total": total, "rows": rows}


@router.post("/api/admin/memory/clear", dependencies=[Depends(admin_guard)])
async def admin_memory_clear():
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    await orch.memory.clear()
    return {"ok": True, "message": "Session memory cleared"}


@router.get("/api/admin/agents/stats", dependencies=[Depends(admin_guard)])
async def admin_agents_stats():
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    return {
        aid: {
            "status": agent.status if hasattr(agent, "status") else "unknown",
            "model": agent.model if hasattr(agent, "model") else "",
            "tier": agent.tier if hasattr(agent, "tier") else "",
            "latency_ms": round(getattr(agent, "_last_latency", 0) * 1000, 1),
        }
        for aid, agent in orch.agents.items()
    }


@router.get("/api/admin/apm", dependencies=[Depends(admin_guard)])
async def admin_apm():
    """H10.16 — org APM: total tokens + $ cost + runs, per agent and per model."""
    from agents.core.cost_tracker import apm_summary
    orch = get_orch()
    apm = apm_summary()
    # Fold in live latency/throughput from the bench system when available.
    if orch and getattr(orch, "bench", None) is not None:
        try:
            apm["latency"] = orch.bench.get_summary()
        except Exception:
            apm["latency"] = {}
    return nocache_json(apm)


@router.get("/api/admin/network/calls", dependencies=[Depends(admin_guard)])
async def admin_network_calls(plugin: str = Query(None), limit: int = Query(100)):
    """H23.16 — network monitor: the egress ledger from the http_client choke point.

    Returns per-plugin tallies (total/allowed/blocked/external) plus the most recent
    attempts, and `local_only_violations` — the proof that local-only plugins made zero
    outbound calls. Optional `plugin` filters to one; `limit` caps the recent list.

    DRA-23 — no longer plugin-only, and this docstring said otherwise for a release.
    Model traffic is recorded too, under `llm:<provider>` rows, and its share of the
    external total is `model_egress_total`. That share can never appear in
    `local_only_violations`: LLM backends have no manifest gate, so those rows record
    what left and never a block that did not happen. A caller reading `clean` alone is
    therefore reading a claim about PLUGIN policy, not about whether anything left the
    machine — which is why the HUD's headline takes `model_egress_total` as its own term.
    Still not instrumented at all (recorded so this docstring does not overclaim in the
    other direction): cloud TTS in `voice/tts.py`, `skills/importer.py`,
    `cameras/frigate.py`, `house/home_assistant.py` and `channels/telegram.py`.
    """
    from agents.core.observability.egress_monitor import EGRESS_MONITOR
    return nocache_json(EGRESS_MONITOR.snapshot(plugin=plugin, limit=limit))


# ── H10.22 Prompt Version Control (SOUL.md history / diff / rollback / A/B) ──

def _svs():
    """Return the SOUL version store, or None."""
    orch = get_orch()
    return getattr(orch, "soul_versions", None) if orch else None


@router.get("/api/admin/prompts/{agent_id}/history", dependencies=[Depends(admin_guard)])
async def admin_prompt_history(agent_id: str):
    svs = _svs()
    if svs is None:
        return JSONResponse({"error": "prompt VC not available"}, status_code=503)
    return nocache_json({"agent_id": agent_id, "history": svs.history(agent_id)})


@router.get("/api/admin/prompts/{agent_id}/version/{version}", dependencies=[Depends(admin_guard)])
async def admin_prompt_version(agent_id: str, version: int):
    svs = _svs()
    if svs is None:
        return JSONResponse({"error": "prompt VC not available"}, status_code=503)
    v = svs.get(agent_id, version)
    if v is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return nocache_json(v)


@router.post("/api/admin/prompts/{agent_id}/commit", dependencies=[Depends(admin_guard)])
async def admin_prompt_commit(agent_id: str, req: Request):
    svs = _svs()
    if svs is None:
        return JSONResponse({"error": "prompt VC not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    content = (body or {}).get("content")
    if content is None:
        return JSONResponse({"error": "content required"}, status_code=400)
    entry = svs.commit(agent_id, content, message=body.get("message", ""), author=body.get("author", ""))
    from agents.core import soul_edit

    # H156: a saved version is a persona edit for the audit log, live or not.
    await asyncio.to_thread(soul_edit.record_version, get_orch(), agent_id, entry, "commit")
    return nocache_json({"ok": True, "version": entry})


@router.get("/api/admin/prompts/{agent_id}/diff", dependencies=[Depends(admin_guard)])
async def admin_prompt_diff(agent_id: str, a: int, b: int):
    svs = _svs()
    if svs is None:
        return JSONResponse({"error": "prompt VC not available"}, status_code=503)
    d = svs.diff(agent_id, a, b)
    if d is None:
        return JSONResponse({"error": "version not found"}, status_code=404)
    return nocache_json({"agent_id": safe_reflect(agent_id), "a": a, "b": b, "diff": d})


@router.post("/api/admin/prompts/{agent_id}/rollback", dependencies=[Depends(admin_guard)])
async def admin_prompt_rollback(agent_id: str, req: Request):
    svs = _svs()
    if svs is None:
        return JSONResponse({"error": "prompt VC not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    version = (body or {}).get("version")
    if version is None:
        return JSONResponse({"error": "version required"}, status_code=400)
    try:
        version = int(version)
    except (TypeError, ValueError):
        return JSONResponse({"error": "version must be an integer"}, status_code=400)
    author = str((body or {}).get("author", "") or "")[:64]
    # H156: an agent's persona rolls back through the one apply path, so the rollback is
    # what the model reads next turn, not only a new line in this history. The shared
    # contract (`_identity`, served from IDENTITY.local.md) and keys that are no loaded
    # agent keep the history-only rollback.
    from agents.core import soul_edit
    from agents.core.agent import IDENTITY_KEY

    orch = get_orch()
    folder = soul_edit.agent_folder(agent_id)
    if agent_id != IDENTITY_KEY and folder is not None and folder in (getattr(orch, "agents", None) or {}):
        target = svs.get(folder, version)
        if target is None:
            return JSONResponse({"error": "version not found"}, status_code=404)
        try:
            result = await asyncio.to_thread(soul_edit.apply_soul, orch, folder, target["content"],
                                             message=f"rollback to v{version}", author=author,
                                             action="rollback")
        except soul_edit.SoulEditError as exc:
            return JSONResponse(exc.body(), status_code=exc.status)
        return nocache_json({"ok": True, **result})
    entry = svs.rollback(agent_id, version, author=author)
    if entry is None:
        return JSONResponse({"error": "version not found"}, status_code=404)
    await asyncio.to_thread(soul_edit.record_version, orch, agent_id, entry, "rollback_history")
    return nocache_json({"ok": True, "version": entry})


@router.post("/api/admin/prompts/{agent_id}/ab", dependencies=[Depends(admin_guard)])
async def admin_prompt_ab_set(agent_id: str, req: Request):
    svs = _svs()
    if svs is None:
        return JSONResponse({"error": "prompt VC not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    try:
        ab = svs.set_experiment(agent_id, int(body["a"]), int(body["b"]), float(body.get("split", 0.5)))
    except KeyError:
        return JSONResponse({"error": "a and b must be existing versions"}, status_code=400)
    except (TypeError, ValueError):
        # KeyError alone covered a MISSING field but not a malformed one, so a
        # non-numeric version id or split fell through int()/float() as a 500.
        return JSONResponse(
            {"error": "a and b must be integer version ids and split a number"},
            status_code=400)
    return nocache_json({"ok": True, "experiment": ab})


@router.get("/api/admin/prompts/{agent_id}/ab", dependencies=[Depends(admin_guard)])
async def admin_prompt_ab_summary(agent_id: str):
    svs = _svs()
    if svs is None:
        return JSONResponse({"error": "prompt VC not available"}, status_code=503)
    return nocache_json({"agent_id": agent_id, "ab": svs.ab_summary(agent_id)})


@router.post("/api/admin/prompts/{agent_id}/preview", dependencies=[Depends(admin_guard)])
async def admin_prompt_preview(agent_id: str, req: Request):
    """H10.28 — preview a proposed SOUL/prompt change (diff + validation).

    Body: {"proposed": "...", "current": "..."?}. If `current` is omitted it's
    taken from the agent's latest committed version (H10.22).
    """
    from agents.core.config_preview import preview_change
    try:
        body = await req.json()
    except Exception:
        body = {}
    proposed = (body or {}).get("proposed")
    if proposed is None:
        return JSONResponse({"error": "proposed required"}, status_code=400)
    current = (body or {}).get("current")
    if current is None:
        svs = _svs()
        cur = svs.current(agent_id) if svs else None
        current = cur["content"] if cur else ""
    return nocache_json({"agent_id": agent_id, **preview_change(current, proposed)})


class AgentUpdateRequest(BaseModel):
    updates: dict[str, str | bool | int]


@router.put("/api/admin/agents/{agent_id}", dependencies=[Depends(admin_guard)])
async def admin_agents_put(agent_id: str, req: AgentUpdateRequest):
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if agent_id not in orch.agents:
        return JSONResponse({"error": f"agent {safe_reflect(agent_id)} not found"}, status_code=404)
    _web()._get_agent_settings()[agent_id] = req.updates
    return {"saved": True, "agent": agent_id, "applied": list(req.updates.keys())}


@router.post("/api/admin/llm/test", dependencies=[Depends(admin_guard)])
async def admin_llm_test():
    import httpx
    configs = [
        ("LM Studio", "http://localhost:1234/v1/models"),
        ("Ollama", "http://localhost:11434/api/tags"),
    ]
    results = []
    for name, url in configs:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(url)
                results.append({"name": name, "url": url, "ok": r.is_success, "status": r.status_code})
        except Exception as e:
            # CWE-209: log the full detail server-side, expose only a static
            # reason to the client (the raw exception can carry internal paths).
            logger.warning("admin llm/test probe failed for %s (%s): %s", name, url, e)
            results.append({"name": name, "url": url, "ok": False, "error": "connection failed"})
    return {"results": results}


class ProviderProbeRequest(BaseModel):
    provider: str | None = None
    force: bool = False


@router.post("/api/admin/llm/providers/probe", dependencies=[Depends(admin_guard)])
async def admin_llm_providers_probe(req: ProviderProbeRequest):
    """H380 — prove each configured cloud provider accepts its key: one authenticated
    read of its model list (cached, rate-limited; the key and the body never returned).
    ``provider`` probes one; ``force`` re-probes a verdict older than the minimum
    interval."""
    from agents.core.llm import provider_probe

    if req.provider:
        try:
            result = await provider_probe.probe(req.provider.strip().lower(), force=req.force)
        except KeyError:
            return JSONResponse({"error": f"unknown provider {safe_reflect(req.provider)}"}, status_code=404)
        return nocache_json({"providers": [result]})
    return nocache_json({"providers": await provider_probe.probe_all(force=req.force)})


# ── Admin Charts endpoint ──────────────────────────────────────

@router.get("/api/admin/stats", dependencies=[Depends(admin_guard)])
async def admin_stats():
    """Aggregated stats for admin charts: latency, usage, success rate."""
    # Import via the top-level `core.*` path (as the original web.py route did):
    # the resilience metrics + circuit-breaker registry are in-memory singletons,
    # and web.py runs with `agents/` on sys.path so `core.resilience` and
    # `agents.core.resilience` are *distinct* module objects with *distinct*
    # singletons. The resilience tests populate `core.resilience`, so this route
    # must read the same module to observe them (estimate_monthly is stateless but
    # kept on the same path for consistency).
    from core.llm.cost_estimator import estimate_monthly
    from core.resilience import _circuit_breakers, get_metrics
    orch = get_orch()
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    interactions = getattr(orch.learning, 'interactions', [])
    samples = getattr(orch.bench, 'samples', [])

    total = len(interactions)
    successes = sum(1 for r in interactions if r.success)
    success_rate = successes / total if total else 0.0
    latencies = [r.latency for r in interactions if r.success and r.latency > 0]
    avg_latency = statistics.mean(latencies) if latencies else 0.0

    unique_agents = set(s.agent_id for s in samples) | set(r.agent_id for r in interactions)

    agents_list = []
    for aid in sorted(unique_agents):
        results = orch.bench.get_results(aid, last_n=100) if hasattr(orch.bench, 'get_results') else []
        if results:
            r = results[0]
            agents_list.append({
                "agent_id": aid,
                "samples": r.samples,
                "success_rate": round(r.success_rate, 3),
                "p50_latency": round(r.median_latency, 2),
                "p95_latency": round(r.p95_latency, 2),
                "avg_latency": round(r.mean_latency, 2),
                "model": r.model,
            })
        else:
            agent_records = [x for x in interactions if x.agent_id == aid]
            if agent_records:
                agent_lat = [x.latency for x in agent_records if x.success and x.latency > 0]
                agents_list.append({
                    "agent_id": aid,
                    "samples": len(agent_records),
                    "success_rate": round(sum(1 for x in agent_records if x.success) / len(agent_records), 3),
                    "p50_latency": round(statistics.median(agent_lat), 2) if len(agent_lat) > 1 else round(agent_lat[0], 2) if agent_lat else 0,
                    "p95_latency": 0,
                    "avg_latency": round(statistics.mean(agent_lat), 2) if agent_lat else 0,
                    "model": "",
                })

    daily_map = defaultdict(lambda: {"total": 0, "successful": 0, "failed": 0, "latencies": []})
    for r in interactions:
        d = date.fromtimestamp(r.timestamp).isoformat()
        daily_map[d]["total"] += 1
        if r.success:
            daily_map[d]["successful"] += 1
            if r.latency > 0:
                daily_map[d]["latencies"].append(r.latency)
        else:
            daily_map[d]["failed"] += 1
    daily = []
    for d in sorted(daily_map.keys()):
        entry = daily_map[d]
        daily.append({
            "date": d,
            "total": entry["total"],
            "successful": entry["successful"],
            "failed": entry["failed"],
            "avg_latency": round(statistics.mean(entry["latencies"]), 2) if entry["latencies"] else 0,
        })

    channels = defaultdict(int)
    for r in interactions:
        ch = (r.metadata or {}).get("channel", "unknown")
        channels[ch] += 1

    error_types = {}
    if hasattr(orch.learning, 'get_failure_patterns'):
        for aid in unique_agents:
            patterns = orch.learning.get_failure_patterns(aid)
            for err, count in patterns:
                error_types[err] = error_types.get(err, 0) + count
    error_types_list = sorted(error_types.items(), key=lambda x: -x[1])[:10]

    # Route usage
    route_usage = orch.learning.get_route_counts() if hasattr(orch.learning, 'get_route_counts') else {}

    # Cost estimates
    cost_records = []
    for r in interactions:
        cost_records.append({
            "model": r.route_name or "unknown",
            "input_tokens": (r.metadata or {}).get("input_tokens", 0),
            "output_tokens": (r.metadata or {}).get("output_tokens", 0),
            "cached_tokens": (r.metadata or {}).get("cached_tokens", 0),
        })
    cost_estimates = estimate_monthly(cost_records)

    # Resilience metrics
    resilience_metrics = get_metrics().get_stats()
    circuit_breaker_states = {
        key: {
            "state": cb.state,
            "failure_count": cb.failure_count,
            "last_failure_time": cb.last_failure_time,
        }
        for key, cb in _circuit_breakers.items()
    }

    return nocache_json({
        "overview": {
            "total_interactions": total,
            "success_rate": round(success_rate, 3),
            "avg_latency": round(avg_latency, 2),
            "agents_tracked": len(unique_agents),
        },
        "agents": agents_list,
        "daily": daily[-30:],
        "channels": dict(channels),
        "error_types": [[k, v] for k, v in error_types_list],
        "route_usage": route_usage,
        "cost_estimates": cost_estimates,
        "resilience": resilience_metrics,
        "circuit_breakers": circuit_breaker_states,
    })
