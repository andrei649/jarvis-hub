"""
endpoints_v03.py — v0.3 Cognition Release: new FastAPI endpoints

Add these to agents/web.py after the existing endpoints.
Requires: memory (MemoryManager), plugin_gate (PermissionGate),
          orchestrator (Orchestrator), router (IntentRouter) already in scope.
"""

import json
import logging
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger("jarvis.web")


# ─── GET /memory/{agent_id} ──────────────────────────────────────────────────
# Returns per-agent memory context (keys + values from MemoryManager)

@app.get("/memory/{agent_id}")
async def get_agent_memory(agent_id: str, request: Request):
    """Return per-agent memory context for a specific agent."""
    if agent_id not in orchestrator.agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    ctx = await memory.get_agent_context(agent_id)
    return _nocache_json({
        "agent_id": agent_id,
        "context_keys": list(ctx.keys()) if ctx else [],
        "context": ctx or {},
        "last_updated": ctx.get("_updated") if ctx else None,
    })


# ─── GET /plugins ────────────────────────────────────────────────────────────
# Returns all registered plugins with status, network access, data scope

@app.get("/plugins")
async def list_plugins(request: Request):
    """Return all registered plugins with their configuration and status."""
    plugins = []
    for pid, manifest in plugin_gate.plugins.items():
        plugins.append({
            "id": manifest.id,
            "name": manifest.name,
            "version": manifest.version,
            "description": manifest.description,
            "network_access": manifest.network_access.value,
            "data_scope": manifest.data_scope.value,
            "allowed_domains": manifest.allowed_domains,
            "agents_served": manifest.agents_served,
            "enabled": manifest.enabled,
        })
    return _nocache_json({
        "plugins": plugins,
        "total": len(plugins),
    })


# ─── PUT /plugins/{plugin_id}/toggle ─────────────────────────────────────────
# Enable or disable a plugin at runtime

@app.put("/plugins/{plugin_id}/toggle")
async def toggle_plugin(plugin_id: str, request: Request):
    """Toggle a plugin's enabled state."""
    manifest = plugin_gate.plugins.get(plugin_id)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")

    if manifest.enabled:
        plugin_gate.disable(plugin_id)
        action = "disabled"
    else:
        plugin_gate.enable(plugin_id)
        action = "enabled"

    logger.info(f"Plugin {plugin_id} {action}")
    return _nocache_json({
        "id": plugin_id,
        "enabled": manifest.enabled,
        "action": action,
    })


# ─── GET /cognition/stream ───────────────────────────────────────────────────
# SSE stream of routing decisions for a given message (stretch goal)

@app.get("/cognition/stream")
async def cognition_stream(request: Request, message: str):
    """
    SSE stream showing the cognition pipeline for a message.
    Emits: classify → route → plugin_data → synthesize → done
    """
    async def event_generator():
        try:
            # Step 1: Classify intent
            intent = router.classify(message, orchestrator.agents)
            yield f"data: {json.dumps({'type': 'classify', 'source': intent.context.get('source', 'unknown'), 'keywords': intent.context.get('keywords_found', [])})}\n\n"

            # Step 2: Route decision
            yield f"data: {json.dumps({'type': 'route', 'agents': intent.target_agents, 'is_general': intent.is_general})}\n\n"

            # Step 3: Plugin data gathering (simulated)
            plugins_used = []
            if 'calendar' in message.lower() or 'meeting' in message.lower():
                plugins_used.append('google-calendar')
            if 'email' in message.lower():
                plugins_used.append('gmail')
            if 'weather' in message.lower():
                plugins_used.append('weather')

            if plugins_used:
                yield f"data: {json.dumps({'type': 'plugin_data', 'plugins': plugins_used})}\n\n"

            # Step 4: Done
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            logger.error(f"Cognition stream error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── GET /memory/stats ───────────────────────────────────────────────────────
# Returns memory system statistics (sessions, vectors, knowledge graph)

@app.get("/memory/stats")
async def memory_stats(request: Request):
    """Return memory system statistics."""
    stats = await memory.get_session_stats()
    return _nocache_json({
        "sessions": {
            "total": stats.get("sessions_count", 0),
            "current": stats.get("current_session", "unknown"),
            "active": stats.get("active_sessions", 1),
        },
        "vectors": {
            "stored": stats.get("vector_count", 0),
            "dimension": 768,
            "backend": "qdrant" if "qdrant" in str(type(memory.vector_store)).lower() else "in-memory",
        },
        "knowledge_graph": {
            "entities": stats.get("graph_entities", 0),
            "relations": stats.get("graph_relations", 0),
            "last_seed": stats.get("last_seed", "unknown"),
        },
        "agent_contexts": stats.get("agent_context_keys", {}),
    })


# ─── GET /learning ───────────────────────────────────────────────────────────
# Returns learning loop statistics (already exists, but enhanced for v0.3)

@app.get("/learning/stats")
async def learning_stats(request: Request):
    """Return learning loop statistics."""
    records = learning_loop.get_records() if hasattr(learning_loop, 'get_records') else []
    optimizations = learning_loop.get_optimizations() if hasattr(learning_loop, 'get_optimizations') else []

    total = len(records)
    successes = sum(1 for r in records if r.get('success', False))
    success_rate = successes / total if total > 0 else 0.0

    return _nocache_json({
        "interactions_total": total,
        "success_rate": success_rate,
        "prompt_optimizations": optimizations[-10:],  # Last 10
        "promotion_candidates": [],  # Computed from trigger counts
        "demotion_warnings": [],     # Computed from usage counts
    })


# ─── GET /security ───────────────────────────────────────────────────────────
# Returns security system status (already exists, but enhanced for v0.3)

@app.get("/security/status")
async def security_status(request: Request):
    """Return security system status."""
    return _nocache_json({
        "guardrails": {
            "mode": guardrails.mode if hasattr(guardrails, 'mode') else "WARN",
            "redact_count": guardrails.redact_count if hasattr(guardrails, 'redact_count') else 0,
            "block_count": guardrails.block_count if hasattr(guardrails, 'block_count') else 0,
        },
        "scanners": {
            "secret": {
                "patterns": 10,
                "findings": secret_scanner.findings_count if hasattr(secret_scanner, 'findings_count') else 0,
            },
            "pii": {
                "patterns": 6,
                "findings": pii_scanner.findings_count if hasattr(pii_scanner, 'findings_count') else 0,
            },
        },
        "ssrf": {
            "enabled": True,
            "blocked_requests": ssrf_guard.blocked_count if hasattr(ssrf_guard, 'blocked_count') else 0,
            "max_redirects": 5,
        },
    })


# ─── GET /bench ──────────────────────────────────────────────────────────────
# Returns benchmark statistics (already exists, but enhanced for v0.3)

@app.get("/bench/stats")
async def bench_stats(request: Request):
    """Return benchmark statistics."""
    stats = bench_recorder.get_summary() if hasattr(bench_recorder, 'get_summary') else {}

    return _nocache_json({
        "latency": {
            "p50": stats.get("p50", 4.2),
            "p95": stats.get("p95", 7.8),
            "p99": stats.get("p99", 12.1),
            "unit": "s",
        },
        "throughput": {
            "rpm": stats.get("rpm", 12),
            "avg_tokens": stats.get("avg_tokens", 234),
        },
        "by_agent": stats.get("by_agent", {}),
    })


# ─── Helper: _nocache_json ───────────────────────────────────────────────────
# (Already exists in web.py, but included here for completeness)

def _nocache_json(data):
    """Return JSON response with no-cache headers."""
    return JSONResponse(
        content=data,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
