"""
web.py — Jarvis Web UI with streaming (SSE), dashboard, and gateway integration.
"""

import asyncio
import json
import logging
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.config import JarvisConfig
from core.orchestrator import Orchestrator
from core.channels.web import WebChannel
from core.channels.gateway import Gateway
from core.checkpoint import CheckpointManager

logger = logging.getLogger("jarvis.web")

app = FastAPI(title="Jarvis", version="0.2.0-beta")
orch: Orchestrator = None
gateway: Gateway = None

HERE = Path(__file__).parent / "web"
_start_time = time.time()


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
        "model": "google/gemma-4-26b-a4b",
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
        status = "ready" if agent.has_heartbeat else "idle"
        cfg = agent.config or {}
        result.append({
            "id": aid,
            "name": agent.name,
            "tier": meta["tier"],
            "role": meta["role"],
            "status": status,
            "enabled": True,
            "has_heartbeat": agent.has_heartbeat,
            "model": cfg.get("model", "google/gemma-4-26b-a4b"),
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


@app.on_event("startup")
async def startup():
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


# ── HTML ─────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    html = HERE / "templates" / "index.html"
    return HTMLResponse(html.read_text(encoding="utf-8"))


# ── Chat ─────────────────────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if not orch:
        return ChatResponse(reply="Jarvis not initialized.")
    reply = await orch.handle_input(req.message, channel="web")
    return ChatResponse(reply=reply)


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)

    async def event_stream():
        yield f"data: {json.dumps({'type': 'start', 'agent': req.agent})}\n\n"
        try:
            full = await orch.handle_input(req.message, channel="web")
            words = full.split(" ")
            chunk = []
            for word in words:
                chunk.append(word)
                if len(chunk) >= 4:
                    yield f"data: {json.dumps({'type': 'token', 'text': ' '.join(chunk) + ' '})}\n\n"
                    chunk = []
                    await asyncio.sleep(0.04)
            if chunk:
                yield f"data: {json.dumps({'type': 'token', 'text': ' '.join(chunk)})}\n\n"
            yield f"data: {json.dumps({'type': 'end', 'agent': req.agent, 'text': full})}\n\n"
        except Exception as e:
            logger.exception("chat stream error")
            yield f"data: {json.dumps({'type': 'end', 'agent': req.agent, 'text': f'Eroare internă: {e}'})}\n\n"

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
    if now - _dashboard_cache["cached_at"] > 120:
        try:
            w = await orch.plugins["weather"].get_weather("")
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

    calendar_data = [
        {"ts": "09:00", "title": "Stand-up matinal",        "owner": "Pepper",  "state": "past"},
        {"ts": "11:00", "title": "Brief strategie",         "owner": "Athena",  "state": "next"},
        {"ts": "15:00", "title": "Call KPI Q2",             "owner": "Stark",   "state": "upcoming"},
        {"ts": "17:30", "title": "Review cod cu Steve",     "owner": "Steve",   "state": "upcoming"},
        {"ts": "20:00", "title": "Cină · familie",          "owner": "Frigga",  "state": "upcoming"},
    ]

    notifications = [
        {"id": "n0", "agent": "jarvis", "level": "ok", "ts": _uptime_str(),
         "text": "Sistemul este operațional. 15 agenți activi."},
    ]

    return {
        "weather": weather_data,
        "calendar": calendar_data,
        "notifications": notifications,
    }


# ── Existing endpoints (unchanged) ───────────────────────────────

@app.get("/memory")
async def memory():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    history = orch.memory.get_history(orch.session_id, last_n=20)
    return {"session": orch.session_id, "turns": history}


@app.post("/memory/clear")
async def clear_memory():
    if orch:
        orch.memory.clear()
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
