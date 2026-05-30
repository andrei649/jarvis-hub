"""
web.py — Jarvis Web UI with streaming (SSE), dashboard, and gateway integration.
"""

import asyncio
import json
import logging
import os
import time
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.config import JarvisConfig
from core.orchestrator import Orchestrator
from core.channels.web import WebChannel
from core.channels.gateway import Gateway
from core.checkpoint import CheckpointManager
from core.settings_db import get_all, get_category, put_category
from core.settings_db import DB_PATH as _SDB

logger = logging.getLogger("jarvis.web")

DEV_MODE = os.environ.get("DEV_MODE", "").lower() in ("1", "true", "yes")

orch: Orchestrator = None
gateway: Gateway = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    global orch, gateway
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
    config = JarvisConfig()
    orch = Orchestrator(config)

    gateway = Gateway(handler=orch.channel_handler)
    gateway.register_channel("web")
    gateway.register_channel("voice")
    gateway.register_channel("telegram")

    await orch.load_agents()

    orch.checkpoints.create_session_record(
        orch.session_id,
        agent_id="orchestrator",
        metadata={"source": "web", "agents": len(orch.agents)},
    )

    web_ch = WebChannel(handler=gateway.route)
    await orch.register_channel(web_ch)
    await orch.start_channels()
    logger.info(
        f"Jarvis Beta ready — {orch.llm_router.name}, "
        f"{len(orch.agents)} agents, {list(orch.channels.keys())} channels, "
        f"{list(orch.skills.skills.keys())} skills"
    )
    yield
    await orch.stop_channels()


app = FastAPI(title="Jarvis", version="0.2.0-beta", lifespan=lifespan)

HERE = Path(__file__).parent / "web"
_start_time = time.time()

# Live polling endpoints return per-request data (system stats, agent status);
# tell the browser and any intermediary not to cache stale snapshots (IMP-2).
_NO_STORE_PATHS = {"/status", "/dashboard", "/api/agents", "/tasks", "/ticker"}


@app.middleware("http")
async def _no_store_for_polling(request: Request, call_next):
    response = await call_next(request)
    if request.url.path in _NO_STORE_PATHS:
        response.headers["Cache-Control"] = "no-store"
    return response


def _uptime_str() -> str:
    s = int(time.time() - _start_time)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _sys_info() -> dict:
    base = {
        "host": "BONOBO-WS",
        "cpu": "Intel Core Ultra 9 · 32c",
        "ram_used": 0, "ram_total": 192,
        "gpu": "RTX 5090 · 24GB",
        "vram_used": 0, "vram_total": 24, "gpu_load": 0,
        "backend": "LM Studio · 1234",
        "model": "google/gemma-4-31b-a4b",
        "latency": 0,
        "uptime": _uptime_str(),
        "sessions": 0,
    }
    try:
        import psutil
        vm = psutil.virtual_memory()
        base["ram_used"] = round(vm.used / 1e9, 1)
        base["ram_total"] = round(vm.total / 1e9, 1)
        cpu_count = psutil.cpu_count(logical=True)
        if cpu_count:
            base["cpu"] = f"Intel Core Ultra 9 · {cpu_count} thr"
    except Exception:
        pass
    try:
        import subprocess
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0:
            parts = r.stdout.strip().split(", ")
            if len(parts) == 3:
                base["vram_used"] = int(float(parts[0])) // 1024
                base["vram_total"] = int(float(parts[1])) // 1024
                base["gpu_load"] = int(float(parts[2]))
    except Exception:
        pass
    return base


_AGENT_SETTINGS = {}  # mutable per-agent overrides: { id: { field: value } }

_AGENT_META = {
    "jarvis":     {"tier": "CNS", "role": "Prime Orchestrator"},
    "friday":     {"tier": "CNS", "role": "Daily Intel"},
    "pepper":     {"tier": "CNS", "role": "Chief of Staff"},
    "jerome":     {"tier": "CNS", "role": "Leisure & Soundtrack"},
    "athena":     {"tier": "BIZ", "role": "External Strategist"},
    "stark":      {"tier": "BIZ", "role": "Biz Intel"},
    "veronica":   {"tier": "BIZ", "role": "Content & Comms"},
    "vision":     {"tier": "BIZ", "role": "Deep Research / OSINT"},
    "steve":      {"tier": "SEC", "role": "CTO / Builds"},
    "oracle":     {"tier": "SEC", "role": "N8N Workflows"},
    "ultron":     {"tier": "SEC", "role": "Security & Automation"},
    "gecko":      {"tier": "FND", "role": "Markets & Capital"},
    "hercules":   {"tier": "FND", "role": "Fitness & Nutrition"},
    "hephaestus": {"tier": "FND", "role": "Builder & Mechanic"},
    "frigga":     {"tier": "FND", "role": "Family Matriarch"},
}


def _enrich_agents() -> list[dict]:
    if not orch:
        return []
    result = []
    for aid, agent in orch.agents.items():
        meta = _AGENT_META.get(aid, {"tier": "FND", "role": ""})
        overrides = _AGENT_SETTINGS.get(aid, {})
        status = overrides.get("status") or "ready" if agent.has_heartbeat else "idle"
        cfg = agent.config or {}
        result.append({
            "id": aid,
            "name": overrides.get("name") or agent.name,
            "tier": overrides.get("tier") or meta["tier"],
            "role": overrides.get("role") or meta["role"],
            "status": status,
            "enabled": overrides.get("enabled", True),
            "has_heartbeat": agent.has_heartbeat,
            "model": overrides.get("model") or cfg.get("model", "google/gemma-4-31b-a4b"),
        })
    return result


class ChatRequest(BaseModel):
    message: str
    agent: str = "jarvis"


class ChatResponse(BaseModel):
    reply: str


# ── mount static files ────────────────────────────────────────────

static_dir = HERE / "static"
if static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ── HTML ─────────────────────────────────────────────────────────

@app.get("/favicon.ico", response_class=FileResponse)
async def favicon():
    return FileResponse(str(HERE / "static" / "favicon.svg"), media_type="image/svg+xml")

@app.get("/", response_class=HTMLResponse)
async def index():
    html = HERE / "templates" / "index.html"
    return HTMLResponse(html.read_text(encoding="utf-8"))


# ── Chat ─────────────────────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not orch:
        return ChatResponse(reply="Jarvis not initialized.")
    try:
        reply = await orch.handle_input(req.message, channel="web", agent_override=req.agent if req.agent != "jarvis" else None)
        return ChatResponse(reply=reply)
    except Exception as e:
        logger.exception("chat error")
        return ChatResponse(reply=f"Internal error: {e}")


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)

    async def event_stream():
        queue = asyncio.Queue()

        async def on_token(token: str):
            await queue.put(("token", token))

        async def runner():
            try:
                full = await orch.handle_input_stream(
                    req.message, channel="web", on_token=on_token,
                    agent_override=req.agent if req.agent != "jarvis" else None,
                )
                await queue.put(("end", full))
            except Exception as e:
                logger.exception("chat stream runner error")
                await queue.put(("error", str(e)))

        task = asyncio.create_task(runner())
        yield f"data: {json.dumps({'type': 'start', 'agent': req.agent})}\n\n"

        while True:
            kind, data = await queue.get()
            if kind == "token":
                yield f"data: {json.dumps({'type': 'token', 'text': data})}\n\n"
            elif kind == "end":
                yield f"data: {json.dumps({'type': 'end', 'agent': req.agent, 'text': data})}\n\n"
                break
            elif kind == "error":
                yield f"data: {json.dumps({'type': 'end', 'agent': req.agent, 'text': f'Eroare internă: {data}'})}\n\n"
                break

        task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Status (HUD-compatible) ──────────────────────────────────────

@app.get("/status")
async def status():
    if not orch:
        return JSONResponse({"status": "starting"})
    enriched = _enrich_agents()
    voice_state = "idle"
    lm_online = orch.llm_router.name != "none"
    return {
        "sys": _sys_info(),
        "voice_state": voice_state,
        "lm_online": lm_online,
        "agents": [{"id": a["id"], "status": a["status"]} for a in enriched],
        "agents_online": sum(1 for a in enriched if a["status"] != "idle"),
        "agents_total": len(enriched),
    }


@app.get("/api/agents")
async def api_agents():
    return {"agents": _enrich_agents()}


# ── Dashboard (HUD-compatible) ───────────────────────────────────

_dashboard_cache = {"weather": "", "news": [], "cached_at": 0}


@app.get("/dashboard")
async def dashboard():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    now = time.time()
    if now - _dashboard_cache.get("cached_at", 0) > 120:
        try:
            weather_plugin = orch.plugins.get("weather")
            w = await weather_plugin.get_weather("") if weather_plugin else ""
            _dashboard_cache["weather"] = w.strip()
        except Exception:
            _dashboard_cache["weather"] = _dashboard_cache.get("weather", "")

    raw = _dashboard_cache["weather"]
    w_temp = "—"; w_desc = "Indisponibil"; w_wind = "—"; w_humidity = "—"
    if raw:
        parts = raw.split(", ")
        for p in parts:
            if "°" in p and ("+" in p or "-" in p):
                cleaned = p.split(":")[-1].strip().replace("+", "").replace("°C", "").strip()
                if cleaned:
                    w_temp = cleaned
            elif "humidity" in p:
                w_humidity = p.replace(" humidity", "").strip()
            elif "wind" in p:
                w_wind = p.replace(" wind", "").strip()
            elif p and "°" not in p and ":" not in p:
                candidate = p.strip()
                if candidate and len(candidate) > 2:
                    w_desc = candidate
    weather_data = {
        "city": "București",
        "temp": w_temp,
        "desc": w_desc,
        "wind": w_wind,
        "humidity": w_humidity,
        "feels": "—",
        "updated": "—",
        "forecast": [],
    }

    calendar_data = _dashboard_cache.get("calendar", [])
    if now - _dashboard_cache.get("calendar_cached_at", 0) > 120 and orch:
        try:
            cal_plugin = orch.plugins.get("google-calendar")
            if cal_plugin and cal_plugin.access_token:
                events = await cal_plugin.get_today_events()
                if events and not (len(events) == 1 and "error" in events[0]):
                    calendar_data = events
                    _dashboard_cache["calendar"] = events
                    _dashboard_cache["calendar_cached_at"] = now
        except Exception:
            pass

    notifications = []

    return {
        "weather": weather_data,
        "calendar": calendar_data,
        "notifications": notifications,
    }


@app.get("/tasks")
async def get_tasks():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    # Placeholder: return empty task list until real data is wired
    return {"tasks": []}


@app.get("/ticker")
async def get_ticker():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    # Return live activity items from agent states
    enriched = _enrich_agents()
    items = []
    for a in enriched:
        items.append({
            "agent": a["id"],
            "verb": "monitoring" if a["status"] == "ready" else "standby",
            "obj": a["role"],
            "pct": 50,
            "pri": "mid",
        })
    return {"ticker": items}


# ── Existing endpoints (unchanged) ───────────────────────────────

@app.get("/memory")
async def memory():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    history = orch.memory.get_history(orch.session_id, last_n=20)
    return {"session": orch.session_id, "turns": history}


@app.post("/memory/clear")
async def clear_memory(req: Request):
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if not DEV_MODE:
        confirm = req.headers.get("x-confirm", "").lower()
        if confirm != "true":
            return JSONResponse({"error": "memory clear requires confirmation — send X-Confirm: true header or set DEV_MODE=1"}, status_code=400)
    orch.memory.clear(session_id=orch.session_id)
    orch.session_id = orch.memory.new_session()
    orch.checkpoints.create_session_record(orch.session_id)
    return JSONResponse({"ok": True, "new_session": orch.session_id})


@app.get("/agents")
async def get_agents():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    result = {}
    for aid, agent in orch.agents.items():
        stats = orch.checkpoints.get_agent_stats(aid)
        skills = [s.name for s in orch.skills.get_skills_for_agent(aid)]
        result[aid] = {
            "name": agent.name,
            "tier": agent.config.get("tier", ""),
            "model": agent.config.get("model", ""),
            "heartbeat": agent.has_heartbeat,
            "stats": stats,
            "skills": skills,
        }
    return {"agents": result}


@app.get("/skills")
async def list_skills():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    result = {}
    for name, skill in orch.skills.skills.items():
        result[name] = {
            "name": skill.name,
            "version": skill.version,
            "description": skill.description,
            "agents": skill.agents,
            "commands": skill.commands_meta,
        }
    return {"skills": result}


@app.get("/sessions")
async def get_sessions():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    sessions = orch.checkpoints.get_sessions(limit=20)
    return {"sessions": sessions}


@app.get("/security")
async def get_security():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    guardrails = orch.security is not None
    return {
        "enabled": guardrails,
        "scanners": ["secrets", "pii"] if guardrails else [],
        "ssrf_protection": True,
        "audit_count": orch.checkpoints.count() if hasattr(orch.checkpoints, "count") else 0,
    }


@app.get("/bench")
async def get_bench():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    return {
        "summary": orch.bench.get_summary(),
        "agents": {
            aid: orch.bench.get_results(aid)
            for aid in list(orch.agents.keys())[:5]
        },
    }


@app.get("/sandbox/status")
async def sandbox_status():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    return {
        "available": orch.sandbox._has_docker,
        "docker_image": orch.sandbox.docker_image,
        "timeout": orch.sandbox.timeout,
    }


@app.post("/sandbox/execute")
async def sandbox_execute(req: Request):
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if not DEV_MODE:
        return JSONResponse({"error": "sandbox disabled — set DEV_MODE=1 to enable"}, status_code=403)
    body = await req.json()
    code = body.get("code", "")
    language = body.get("language", "python")
    if language == "python":
        result = await orch.sandbox.execute_python(code)
    else:
        result = await orch.sandbox.execute_shell(code)
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
        "duration": result.duration,
        "success": result.success,
    }


@app.post("/skills/import")
async def skills_import(req: Request):
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if not DEV_MODE:
        return JSONResponse({"error": "skill import disabled — set DEV_MODE=1 to enable"}, status_code=403)
    body = await req.json()
    source = body.get("source", "hermes")
    skill_name = body.get("skill", "")
    if not skill_name:
        return JSONResponse({"error": "skill name required"}, status_code=400)
    if source == "hermes":
        ok = await orch.skill_importer.import_from_hermes(skill_name)
    elif source == "openclaw":
        ok = await orch.skill_importer.import_from_openclaw(skill_name)
    else:
        ok = await orch.skill_importer.import_from_github(source, skill_name)
    if ok:
        orch.skills.discover()
        return {"ok": True, "source": source, "skill": skill_name}
    return JSONResponse({"ok": False, "error": f"Skill '{skill_name}' not found in {source}"}, status_code=404)


@app.get("/skills/imported")
async def skills_imported():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    return {"imported": orch.skill_importer.list_imported()}


@app.get("/learning")
async def get_learning():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    return {
        "stats": orch.learning.get_stats(),
        "optimizations": {
            aid: orch.learning.optimize_prompt(aid)
            for aid in orch.agents
        },
    }


# ── Admin panel ──────────────────────────────────────────────────


ADMIN_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ro">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>JARVIS HUB · Admin</title>
<link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
<link rel="stylesheet" href="/static/fonts.css">
<link rel="stylesheet" href="/static/style.css">
<link rel="stylesheet" href="/static/admin.css">
</head>
<body>
<div id="root"></div>
<script src="/static/react.production.min.js"></script>
<script src="/static/react-dom.production.min.js"></script>
<script src="/static/data.js"></script>
<script src="/static/components.js"></script>
<script src="/static/admin.js"></script>
</body>
</html>"""


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    return HTMLResponse(ADMIN_HTML_TEMPLATE)


@app.get("/api/admin/settings")
async def admin_get_all():
    return get_all()


@app.get("/api/admin/settings/{category}")
async def admin_get_category(category: str):
    items = get_category(category)
    if not items:
        return JSONResponse({"error": f"unknown category: {category}"}, status_code=404)
    return {category: items}


class AdminPutBody(BaseModel):
    values: dict


@app.put("/api/admin/settings/{category}")
async def admin_put_category(category: str, body: AdminPutBody):
    updated = put_category(category, body.values)
    return {"updated": updated, "category": category}


@app.get("/api/admin/env")
async def admin_get_env():
    return {
        key: val
        for key, val in sorted(os.environ.items())
        if not key.startswith("_")
    }


@app.get("/api/admin/audit")
async def admin_get_audit(page: int = 1, limit: int = 50):
    import sqlite3
    db = Path("memory_logs/security/audit.db")
    if not db.exists():
        return {"page": page, "limit": limit, "total": 0, "rows": []}
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    table = "audit_events" if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='audit_events'").fetchone() else "security_events"
    total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    offset = (page - 1) * limit
    rows = conn.execute(
        f"SELECT timestamp, event_type, content_preview AS summary, findings_json AS details FROM {table} ORDER BY rowid DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    conn.close()
    return {
        "page": page,
        "limit": limit,
        "total": total,
        "rows": [dict(r) for r in rows],
    }


@app.post("/api/admin/memory/clear")
async def admin_memory_clear():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    orch.memory.clear()
    return {"ok": True, "message": "Session memory cleared"}


@app.get("/api/admin/agents/stats")
async def admin_agents_stats():
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


class AgentUpdateRequest(BaseModel):
    updates: dict[str, str | bool | int]


@app.put("/api/admin/agents/{agent_id}")
async def admin_agents_put(agent_id: str, req: AgentUpdateRequest):
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if agent_id not in orch.agents:
        return JSONResponse({"error": f"agent {agent_id} not found"}, status_code=404)
    _AGENT_SETTINGS[agent_id] = req.updates
    return {"saved": True, "agent": agent_id, "applied": list(req.updates.keys())}


@app.post("/api/admin/llm/test")
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
            results.append({"name": name, "url": url, "ok": False, "error": str(e)})
    return {"results": results}
