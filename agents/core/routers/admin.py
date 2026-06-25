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
from agents.core.settings_db import get_all, get_category, init_db, put_category, validate_category
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


@router.get("/api/admin/settings/{category}", dependencies=[Depends(admin_guard)])
async def admin_get_category(category: str):
    items = get_category(category)
    if not items:
        return JSONResponse({"error": f"unknown category: {safe_reflect(category)}"}, status_code=404)
    return {category: items}


class AdminPutBody(BaseModel):
    values: dict


async def _audit_settings_change(category: str, keys: list) -> None:
    """AUD-8: record a settings write in the audit log — the changed KEY NAMES only,
    never their values, so the row can't leak a secret that was just set."""
    orch = get_orch()
    audit = getattr(orch, "audit", None) if orch else None
    if audit is None:
        return
    try:
        await asyncio.to_thread(audit.log, SecurityEvent(
            event_type=SecurityEventType.SETTINGS_CHANGE,
            timestamp=time.time(),
            content_preview=f"settings.{category} updated: {sorted(keys)}",
            action_taken="settings_update",
        ))
    except Exception:
        # log_safe (not safe_reflect) is the recognized py/log-injection sanitizer:
        # it strips CR/LF so a hostile category can't forge log lines.
        logger.warning("failed to audit settings change for %s", log_safe(category))


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
        await _audit_settings_change(category, changed)
    resp = {"updated": updated, "category": category}
    if skipped:
        resp["skipped"] = skipped
    return resp


@router.post("/api/admin/settings/reseed", dependencies=[Depends(admin_guard)])
async def admin_reseed():
    init_db(force=True)
    return {"ok": True, "message": "Settings reseeded from defaults"}


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
    """H23.16 — network monitor: plugin egress ledger from the http_client choke point.

    Returns per-plugin tallies (total/allowed/blocked/external) plus the most recent
    attempts, and `local_only_violations` — the proof that local-only plugins made zero
    outbound calls. Optional `plugin` filters to one; `limit` caps the recent list.
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
    entry = svs.rollback(agent_id, int(version), author=body.get("author", ""))
    if entry is None:
        return JSONResponse({"error": "version not found"}, status_code=404)
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
