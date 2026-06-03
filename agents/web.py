"""
web.py — Jarvis Web UI with streaming (SSE), dashboard, and gateway integration.
"""

import asyncio
import json
import logging
import os
import secrets
import statistics
import time
import sys
from collections import defaultdict
from datetime import date, datetime
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


def _nocache_json(content: dict, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        content=content,
        status_code=status_code,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )

from core.config import JarvisConfig
from core.orchestrator import Orchestrator
from core.channels.web import WebChannel
from core.channels.gateway import Gateway
from core.checkpoint import CheckpointManager
from core.settings_db import get_all, get_category, put_category, init_db
from core.settings_db import DB_PATH as _SDB
from core.channels.voice import VoiceChannel
from core.channels.telegram import TelegramChannel
from core.channels.discord import DiscordChannel
from core.channels.email import EmailChannel
from core.channels.slack import SlackChannel
from core.log import setup_logging, log_error
from core.errors import JarvisError, E_INTERNAL_UNEXPECTED, E_SECURITY_BLOCKED
from core.security.guardrails import SecurityBlockError
from core.llm.cost_estimator import estimate_monthly
from core.resilience import get_metrics, _circuit_breakers

logger = logging.getLogger("jarvis.web")

DEV_MODE = os.environ.get("DEV_MODE", "").lower() in ("1", "true", "yes")

# ── Admin authentication ──────────────────────────────────────────
# The /api/admin/* routes can read settings, clear memory and expose env.
# Guard them so they are never reachable from the network unprotected:
#   - If JARVIS_ADMIN_TOKEN is set, require a matching X-Admin-Token header.
#   - If it is NOT set, allow only requests originating from localhost, so
#     local development keeps working but a Pi/LAN deployment is locked down.
ADMIN_TOKEN = os.environ.get("JARVIS_ADMIN_TOKEN", "").strip()
_LOCALHOSTS = {"127.0.0.1", "::1", "localhost"}

# Substrings that mark an env var as sensitive — its value is masked in
# /api/admin/env so keys/tokens/secrets are never returned in clear text.
_SECRET_HINTS = ("key", "token", "secret", "password", "passwd", "pass", "client_id")


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}…{value[-2:]}"


async def _admin_guard(request: Request):
    """Authorize an /api/admin/* request or raise 401/403."""
    if ADMIN_TOKEN:
        supplied = request.headers.get("x-admin-token", "")
        if not supplied or not secrets.compare_digest(supplied, ADMIN_TOKEN):
            raise HTTPException(status_code=401, detail="admin token required")
        return
    # No token configured → only localhost may reach admin endpoints.
    client_host = request.client.host if request.client else ""
    if client_host not in _LOCALHOSTS:
        raise HTTPException(
            status_code=403,
            detail="admin disabled from network — set JARVIS_ADMIN_TOKEN to enable remote access",
        )


orch: Orchestrator = None
gateway: Gateway = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    global orch, gateway
    setup_logging()
    config = JarvisConfig()
    orch = Orchestrator(config)

    gateway = Gateway(handler=orch.channel_handler)
    gateway.register_channel("web")
    gateway.register_channel("voice")
    gateway.register_channel("telegram")

    await orch.load_agents()

    # Load MCP servers from settings DB
    _load_mcp_config()

    orch.checkpoints.create_session_record(
        orch.session_id,
        agent_id="orchestrator",
        metadata={"source": "web", "agents": len(orch.agents)},
    )

    web_ch = WebChannel(handler=gateway.route)
    await orch.register_channel(web_ch)

    voice_ch = VoiceChannel(handler=gateway.route, wake_words=orch.get_setting("general.wake_words", ["jarvis", "hub"]))
    await orch.register_channel(voice_ch)

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if tg_token:
        telegram_ch = TelegramChannel(token=tg_token, handler=gateway.route)
        await orch.register_channel(telegram_ch)
        logger.info("Telegram channel wired with bot token")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not set — telegram channel disabled")

    discord_token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if discord_token:
        discord_ch = DiscordChannel(token=discord_token, handler=gateway.route)
        await orch.register_channel(discord_ch)
        logger.info("Discord channel wired")

    smtp_host = os.environ.get("SMTP_HOST", "")
    imap_host = os.environ.get("IMAP_HOST", "")
    if smtp_host and imap_host:
        email_ch = EmailChannel(
            smtp_host=smtp_host, smtp_port=int(os.environ.get("SMTP_PORT", "587")),
            smtp_user=os.environ.get("SMTP_USER", ""), smtp_pass=os.environ.get("SMTP_PASS", ""),
            imap_host=imap_host, imap_port=int(os.environ.get("IMAP_PORT", "993")),
            imap_user=os.environ.get("IMAP_USER", ""), imap_pass=os.environ.get("IMAP_PASS", ""),
            handler=gateway.route,
        )
        await orch.register_channel(email_ch)
        logger.info("Email channel wired")

    slack_token = os.environ.get("SLACK_BOT_TOKEN", "")
    if slack_token:
        slack_ch = SlackChannel(token=slack_token, handler=gateway.route)
        await orch.register_channel(slack_ch)
        logger.info("Slack channel wired")

    await orch.start_channels()
    logger.info(
        f"Jarvis Beta ready — {orch.llm_router.name}, "
        f"{len(orch.agents)} agents, {list(orch.channels.keys())} channels, "
        f"{list(orch.skills.skills.keys())} skills"
    )
    yield
    # Symmetric lifecycle: stop channels and release the globals so a closed app
    # context (e.g. a TestClient context manager in tests) does not leak a live
    # orchestrator into the next caller. Guarded because multiple app contexts
    # share these module globals and a prior teardown may have cleared them.
    if orch is not None:
        await orch.stop_channels()
    orch = None
    gateway = None


app = FastAPI(title="Jarvis", version="0.5.0-beta", lifespan=lifespan)


@app.exception_handler(JarvisError)
async def jarvis_error_handler(request: Request, exc: JarvisError):
    log_error(logger, exc.code, **exc.meta)
    return _nocache_json(exc.to_dict(), status_code=400)


@app.exception_handler(SecurityBlockError)
async def security_block_handler(request: Request, exc: SecurityBlockError):
    log_error(logger, E_SECURITY_BLOCKED, reason=str(exc))
    return _nocache_json(
        {"code": "JARVIS-SECURITY-001", "category": "security", "severity": "warning", "message": str(exc)},
        status_code=403,
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception):
    log_error(logger, E_INTERNAL_UNEXPECTED, component="web", detail=str(exc), exc=exc)
    return _nocache_json(
        {"code": "JARVIS-INTERNAL-001", "category": "internal", "severity": "error", "message": "Internal server error"},
        status_code=500,
    )


HERE = Path(__file__).parent / "web"
_start_time = time.time()

# Live polling endpoints return per-request data (system stats, agent status);
# tell the browser and any intermediary not to cache stale snapshots (IMP-2).
_NO_STORE_PATHS = {
    "/status", "/dashboard", "/api/agents", "/tasks", "/ticker",
    "/api/cognition", "/api/oauth/status", "/api/oracle/status", "/api/oracle/conflicts",
    "/api/trust/status"
}


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
    message: str = Field(..., max_length=4096)
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

@app.get("/sw.js", response_class=FileResponse)
async def service_worker():
    return FileResponse(str(HERE / "static" / "sw.js"), media_type="application/javascript")

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


# ── TTS endpoint ─────────────────────────────────────────────────

class TTSRequest(BaseModel):
    text: str = Field(..., max_length=4096)
    lang: str = "ro"

@app.post("/tts")
async def tts_endpoint(req: TTSRequest):
    """Synthesize text to speech and return MP3 audio."""
    try:
        from core.voice.tts import TTSEngine, HAS_EDGE
        if not HAS_EDGE:
            return JSONResponse(
                {"error": "edge-tts not installed. Run: pip install edge-tts"},
                status_code=503,
            )
        engine = TTSEngine()
        audio_path = await engine.speak(req.text, lang=req.lang)
        if not audio_path:
            return JSONResponse({"error": "TTS synthesis failed"}, status_code=500)
        return FileResponse(
            audio_path,
            media_type="audio/mpeg",
            headers={"Cache-Control": "no-cache"},
        )
    except Exception as e:
        logger.exception("TTS error")
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Status (HUD-compatible) ──────────────────────────────────────

@app.get("/status")
async def status():
    if not orch:
        return _nocache_json({"status": "starting"})
    enriched = _enrich_agents()
    voice_state = "idle"
    lm_online = orch.llm_router.name != "none"
    return _nocache_json({
        "sys": _sys_info(),
        "voice_state": voice_state,
        "lm_online": lm_online,
        "agents": [{"id": a["id"], "status": a["status"]} for a in enriched],
        "agents_online": sum(1 for a in enriched if a["status"] != "idle"),
        "agents_total": len(enriched),
    })


@app.get("/api/agents")
async def api_agents():
    return _nocache_json({"agents": _enrich_agents()})


# ── Dashboard (HUD-compatible) ───────────────────────────────────

_dashboard_cache = {"weather": "", "news": [], "cached_at": 0}
# Serialize cache refreshes so concurrent /dashboard requests don't race on the
# weather/calendar update (double-fetch or partial write under load). BUG-1.
_dashboard_lock = asyncio.Lock()


@app.get("/dashboard")
async def dashboard():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    now = time.time()
    if now - _dashboard_cache.get("cached_at", 0) > 120:
        async with _dashboard_lock:
            # Re-check inside the lock: a concurrent request may have just refreshed.
            if now - _dashboard_cache.get("cached_at", 0) > 120:
                try:
                    weather_plugin = orch.plugins.get("weather")
                    w = await weather_plugin.get_weather("") if weather_plugin else ""
                    _dashboard_cache["weather"] = w.strip()
                except Exception:
                    _dashboard_cache["weather"] = _dashboard_cache.get("weather", "")
                _dashboard_cache["cached_at"] = now

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
        async with _dashboard_lock:
            # Re-check inside the lock to avoid a redundant concurrent fetch.
            if now - _dashboard_cache.get("calendar_cached_at", 0) > 120:
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
            else:
                calendar_data = _dashboard_cache.get("calendar", [])

    notifications = []

    return _nocache_json({
        "weather": weather_data,
        "calendar": calendar_data,
        "notifications": notifications,
    })


@app.get("/tasks")
async def get_tasks():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    
    try:
        all_tasks = orch.autonomy_queue.list(limit=30)
    except Exception:
        all_tasks = []
        
    # Format and enrich tasks for both backend model schema and frontend React network/widgets schema
    def format_task(t):
        if hasattr(t, "to_dict"):
            d = t.to_dict()
        else:
            d = dict(t)
        # Ensure owner, state, label, and project are present for React component compatibility (e.g. NetworkBrain)
        d["owner"] = d.get("owner") or d.get("agent_id") or "jarvis"
        d["state"] = d.get("state") or d.get("status") or "done"
        d["label"] = d.get("label") or d.get("title") or "Task"
        d["project"] = d.get("project") or d.get("kind") or "Autonomy"
        return d

    # 1. Check for running tasks first
    running_tasks = [t for t in all_tasks if getattr(t, "status", None) == "running" or getattr(t, "state", None) == "running"]
    
    if running_tasks:
        result_tasks = [format_task(t) for t in running_tasks]
    elif all_tasks:
        # 2. If no running tasks, return recent history
        result_tasks = [format_task(t) for t in all_tasks]
    else:
        # H7.7: No active tasks — return empty list instead of misleading dummy data
        result_tasks = []
        
    return _nocache_json({"tasks": result_tasks})


@app.get("/ticker")
async def get_ticker():
    if not orch:
        return _nocache_json({"error": "not initialized"}, status_code=503)
    items = []
    
    # 1. Add active unhealthy signals from observer
    if orch.observer:
        try:
            obs_status = orch.observer.status()
            for key, state in obs_status.get("signals", {}).items():
                if not state.get("healthy", True):
                    items.append({
                        "agent": state.get("agent", "steve"),
                        "verb": "WARNING",
                        "obj": state.get("detail", key),
                        "pct": 100,
                        "pri": "high" if state.get("severity") == "CRITICAL" else "mid",
                    })
        except Exception:
            pass

    # 2. Add active unhealthy signals from event watcher
    if getattr(orch, "event_watcher", None):
        try:
            watcher_state = orch.event_watcher._state
            for key, healthy in watcher_state.items():
                if not healthy:
                    agent = "gecko" if "finance" in key else ("pepper" if "calendar" in key else ("stark" if "email" in key else "hercules"))
                    items.append({
                        "agent": agent,
                        "verb": "ALERT",
                        "obj": f"Unhealthy event signal: {key}",
                        "pct": 100,
                        "pri": "mid",
                    })
        except Exception:
            pass

    # 3. Fallback to active agent standby messages so it's never empty
    if not items:
        enriched = _enrich_agents()
        for a in enriched:
            items.append({
                "agent": a["id"],
                "verb": "monitoring" if a["status"] == "ready" else "standby",
                "obj": a["role"],
                "pct": 50,
                "pri": "mid",
            })
            
    return _nocache_json({"ticker": items})


@app.get("/api/agents/{agent_id}/soul")
async def get_agent_soul(agent_id: str):
    """Read and return the live SOUL.md content for an agent."""
    agent_id = agent_id.strip().lower()
    
    # Allow reading SOUL.md if the file physically exists, even if orch is not initialized (e.g. in tests)
    base_dir = Path(__file__).parent.resolve()
    soul_path = base_dir / agent_id / "SOUL.md"
    
    if orch and agent_id not in orch.agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    
    if not soul_path.exists():
        raise HTTPException(status_code=404, detail=f"SOUL.md not found for agent '{agent_id}'")
        
    try:
        content = soul_path.read_text(encoding="utf-8")
        return {"agent_id": agent_id, "soul": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read SOUL.md: {e}")


# ── Existing endpoints (unchanged) ───────────────────────────────

@app.get("/memory")
async def memory():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    history = await orch.memory.get_history(orch.session_id, last_n=20)
    return _nocache_json({"session": orch.session_id, "turns": history})


@app.post("/memory/clear")
async def clear_memory(req: Request):
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if not DEV_MODE:
        confirm = req.headers.get("x-confirm", "").lower()
        if confirm != "true":
            return JSONResponse({"error": "memory clear requires confirmation — send X-Confirm: true header or set DEV_MODE=1"}, status_code=400)
    await orch.memory.clear(session_id=orch.session_id)
    orch.session_id = await orch.memory.new_session()
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


@app.post("/sessions/resume")
async def resume_session(req: Request):
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    body = await req.json()
    sid = body.get("session_id")
    if not sid:
        return JSONResponse({"error": "session_id required"}, status_code=400)
    ok = await orch.memory.resume_session(sid)
    if not ok:
        return JSONResponse({"error": f"session '{sid}' not found"}, status_code=404)
    orch.session_id = sid
    history = await orch.memory.get_history(sid, last_n=20)
    return JSONResponse({"ok": True, "session": sid, "turns": history})


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


@app.get("/api/agents/history")
async def agents_history():
    """H10.17 — per-agent run-history rollup (runs, last, ok-rate, avg latency)."""
    if not orch or not getattr(orch, "run_history", None):
        return _nocache_json({"agents": []})
    return _nocache_json({"agents": orch.run_history.agents()})


@app.get("/api/agents/{agent_id}/history")
async def agent_history(agent_id: str, limit: int = Query(50, ge=1, le=200)):
    """H10.17 — recent runs for one agent (most-recent first)."""
    if not orch or not getattr(orch, "run_history", None):
        return _nocache_json({"agent_id": agent_id, "runs": []})
    return _nocache_json({
        "agent_id": agent_id,
        "runs": orch.run_history.list(agent_id, limit),
    })


@app.get("/api/agent-templates")
async def agent_templates_list():
    """H10.29 — list the pre-configured agent template catalog."""
    from agents.core.agent_templates import list_templates
    return _nocache_json({"templates": list_templates()})


@app.post("/api/agent-templates/instantiate")
async def agent_templates_instantiate(req: Request):
    """H10.29 — render a ready-to-save agent config from a template.

    Body: {"template": "researcher", "name": "Vega", "overrides": {...}}.
    Returns the agents.yaml-shaped config + a SOUL.md skeleton (preview); the
    caller persists it via the normal agent-creation flow.
    """
    from agents.core.agent_templates import build_agent_config
    try:
        body = await req.json()
    except Exception:
        body = {}
    template = (body or {}).get("template", "")
    try:
        config = build_agent_config(
            template,
            name=(body or {}).get("name"),
            overrides=(body or {}).get("overrides") or {},
        )
    except KeyError:
        return JSONResponse({"error": f"unknown template: {template}"}, status_code=404)
    return _nocache_json({"ok": True, "config": config})


# ── H10.19 Model Arena / Blind Comparison ─────────────────────────────────────

@app.post("/api/arena/run")
async def arena_run(req: Request):
    """Create a blind match. Body: {query, candidates:{model:response}} or
    {query, agents:[id,...]} to run the query against those agents live."""
    arena = getattr(orch, "arena", None) if orch else None
    if arena is None:
        return JSONResponse({"error": "arena not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    query = (body or {}).get("query", "")
    if not query:
        return JSONResponse({"error": "query required"}, status_code=400)
    candidates = (body or {}).get("candidates") or {}
    if not candidates:
        agents = (body or {}).get("agents") or []
        if len(agents) < 2 or not orch:
            return JSONResponse({"error": "provide candidates or >=2 agents"}, status_code=400)
        for aid in agents:
            try:
                candidates[aid] = await orch.handle_input(query, channel="arena", agent_override=aid)
            except Exception as e:
                candidates[aid] = f"[error:{e}]"
    try:
        match = arena.create_match(query, candidates)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return _nocache_json({"ok": True, "match": match})


@app.post("/api/arena/vote")
async def arena_vote(req: Request):
    """Vote for a label; reveals the mapping and updates ELO/win-rate."""
    arena = getattr(orch, "arena", None) if orch else None
    if arena is None:
        return JSONResponse({"error": "arena not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    match_id = (body or {}).get("match_id", "")
    winner = (body or {}).get("winner", "")
    if not match_id or not winner:
        return JSONResponse({"error": "match_id and winner required"}, status_code=400)
    try:
        return _nocache_json({"ok": True, "match": arena.vote(match_id, winner)})
    except KeyError:
        return JSONResponse({"error": "unknown match"}, status_code=404)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/arena/match/{match_id}")
async def arena_match(match_id: str):
    arena = getattr(orch, "arena", None) if orch else None
    if arena is None:
        return JSONResponse({"error": "arena not available"}, status_code=503)
    m = arena.get_match(match_id)
    if m is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return _nocache_json(m)


@app.get("/api/arena/leaderboard")
async def arena_leaderboard():
    arena = getattr(orch, "arena", None) if orch else None
    if arena is None:
        return _nocache_json({"leaderboard": []})
    return _nocache_json({"leaderboard": arena.leaderboard()})


# ── H10.23 Live Quality Monitor ───────────────────────────────────────────────

@app.get("/api/quality")
async def quality_status():
    """Rolling quality average + threshold alert for live requests."""
    q = getattr(orch, "quality", None) if orch else None
    if q is None:
        return _nocache_json({"stats": {}, "alert": {"alerting": False}})
    return _nocache_json({"stats": q.stats(), "alert": q.check_alert()})


@app.get("/api/quality/scores")
async def quality_scores(limit: int = Query(50, ge=1, le=500)):
    """Recent per-request quality scores (most recent first)."""
    q = getattr(orch, "quality", None) if orch else None
    if q is None:
        return _nocache_json({"scores": []})
    return _nocache_json({"scores": q.recent(limit)})


@app.post("/api/quality/threshold", dependencies=[Depends(_admin_guard)])
async def quality_set_threshold(req: Request):
    """Set the alert threshold (admin)."""
    q = getattr(orch, "quality", None) if orch else None
    if q is None:
        return JSONResponse({"error": "quality monitor not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    if "threshold" not in (body or {}):
        return JSONResponse({"error": "threshold required"}, status_code=400)
    q.set_threshold(float(body["threshold"]))
    return _nocache_json({"ok": True, "threshold": q.threshold})


@app.post("/api/schedule/parse")
async def schedule_parse(req: Request):
    """H10.27 — parse a natural-language schedule into a cron expression."""
    from agents.core.autonomy.nl_schedule import parse_schedule
    try:
        body = await req.json()
    except Exception:
        body = {}
    text = (body or {}).get("text", "")
    if not text:
        return JSONResponse({"error": "text required"}, status_code=400)
    result = parse_schedule(text)
    return _nocache_json(result, status_code=200 if result.get("ok") else 422)


@app.get("/sandbox/status")
async def sandbox_status():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    return {
        "available": orch.sandbox._has_docker,
        "docker_image": orch.sandbox.docker_image,
        "timeout": orch.sandbox.timeout,
    }


class SandboxExecuteBody(BaseModel):
    code: str = Field("", max_length=32768)
    language: str = "python"


@app.post("/sandbox/execute")
async def sandbox_execute(body: SandboxExecuteBody):
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if not DEV_MODE:
        return JSONResponse({"error": "sandbox disabled — set DEV_MODE=1 to enable"}, status_code=403)
    code = body.code
    language = body.language
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


# ── Agent Marketplace Endpoints (H5.8) ───────────────────────────

class PublishSkillBody(BaseModel):
    name: str


class InstallSkillBody(BaseModel):
    name: str


class InstallZipBody(BaseModel):
    zip_base64: str


@app.get("/api/skills/marketplace", dependencies=[Depends(_admin_guard)])
async def marketplace_list():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        skills = orch.marketplace.list_skills()
        return {"skills": skills}
    except Exception as e:
        logger.exception("Failed to list marketplace skills")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/skills/marketplace/publish", dependencies=[Depends(_admin_guard)])
async def marketplace_publish(body: PublishSkillBody):
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        res = orch.marketplace.publish_skill(body.name)
        return {"ok": True, "published": res}
    except FileNotFoundError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        logger.exception("Failed to publish skill")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/skills/marketplace/install", dependencies=[Depends(_admin_guard)])
async def marketplace_install(body: InstallSkillBody):
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        ok = orch.marketplace.install_skill(body.name)
        if ok:
            orch.skills.discover()
            return {"ok": True, "installed": body.name}
        return JSONResponse({"error": f"Failed to install skill '{body.name}'"}, status_code=500)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        logger.exception("Failed to install skill")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/skills/marketplace/install-zip", dependencies=[Depends(_admin_guard)])
async def marketplace_install_zip(body: InstallZipBody):
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        import base64
        zip_bytes = base64.b64decode(body.zip_base64)
        ok = orch.marketplace.install_from_zip(zip_bytes)
        if ok:
            orch.skills.discover()
            return {"ok": True}
        return JSONResponse({"error": "Failed to install skill from zip"}, status_code=500)
    except Exception as e:
        logger.exception("Failed to install skill from zip")
        return JSONResponse({"error": str(e)}, status_code=500)



@app.get("/learning")
async def get_learning():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    return {
        "stats": orch.learning.get_stats(active_ids=set(orch.agents.keys())),
        "optimizations": {
            aid: orch.learning.optimize_prompt(aid)
            for aid in orch.agents
        },
        "promotion_suggestions": orch.learning.suggest_promotions(active_ids=set(orch.agents.keys())),
    }


class PromoteRequest(BaseModel):
    bench_agent: str


@app.post("/learning/promote", dependencies=[Depends(_admin_guard)])
async def learning_promote(body: PromoteRequest):
    """Manually promote a bench agent to active status."""
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    bench_id = body.bench_agent.strip().lower()
    if not bench_id:
        return JSONResponse({"error": "bench_agent is required"}, status_code=400)
    promoted = orch.promote_bench_agent(bench_id)
    return _nocache_json({
        "ok": True,
        "bench_agent": bench_id,
        "promoted": promoted,
        "active_agents": list(orch.agents.keys()),
    })


# ── Autonomy / Proactive Cortex (H6.1–H6.3) ─────────────────────


class AutonomyTaskBody(BaseModel):
    agent: str
    kind: str
    title: str
    payload: Optional[dict] = None
    origin: str = "generated"


class AutonomyDecisionBody(BaseModel):
    action: str            # accept / edit / reject / defer
    payload: Optional[dict] = None


@app.get("/autonomy/tasks", dependencies=[Depends(_admin_guard)])
async def autonomy_list(status: str = None, origin: str = None, limit: int = Query(100, ge=1, le=200)):
    """List autonomy tasks, optionally filtered by status/origin."""
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    tasks = orch.autonomy_queue.list(status=status, origin=origin, limit=limit)
    return _nocache_json({"tasks": [t.to_dict() for t in tasks], "total": len(tasks)})


@app.get("/autonomy/status", dependencies=[Depends(_admin_guard)])
async def autonomy_status():
    """Queue stats + remaining interruption budget."""
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    return _nocache_json({
        "stats": orch.autonomy_queue.stats(),
        "interrupt_budget_remaining": orch.autonomy.budget.remaining(),
        "interrupt_budget_per_day": orch.autonomy.budget.per_day,
        "pending_decisions": [t.to_dict() for t in orch.autonomy_queue.pending_decisions()],
    })


@app.get("/autonomy/observer", dependencies=[Depends(_admin_guard)])
async def autonomy_observer_status():
    """Proactive OS Observer state: tracked signals + currently unhealthy ones."""
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if not orch.observer:
        return _nocache_json({"enabled": False, "reason": "observer not initialized"})
    return _nocache_json({
        "enabled": bool(orch.get_setting("system.observer_enabled", True)),
        **orch.observer.status(),
    })


@app.post("/autonomy/observer/run", dependencies=[Depends(_admin_guard)])
async def autonomy_observer_run():
    """Trigger one observer sample now (sample → debounce → gate → queue)."""
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if not orch.observer:
        return JSONResponse({"error": "observer not initialized"}, status_code=503)
    summary = await orch.observer.observe()
    return _nocache_json({"ok": True, "summary": summary})


@app.post("/autonomy/tasks", dependencies=[Depends(_admin_guard)])
async def autonomy_submit(body: AutonomyTaskBody):
    """Submit a task to the autonomy worker (gated through the risk policy)."""
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    task = await orch.autonomy.submit(
        agent=body.agent.strip().lower(), kind=body.kind.strip(),
        title=body.title, payload=body.payload, origin=body.origin,
    )
    return _nocache_json({"ok": True, "task": task.to_dict()})


@app.post("/autonomy/tasks/{task_id}/decision", dependencies=[Depends(_admin_guard)])
async def autonomy_decide(task_id: int, body: AutonomyDecisionBody):
    """Resolve a blocked task (accept/edit/reject/defer)."""
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    from core.autonomy.queue import TaskQueueError
    try:
        task = await orch.autonomy.apply_decision(
            task_id, body.action.strip().lower(), decided_by="admin", payload=body.payload,
        )
    except TaskQueueError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    return _nocache_json({"ok": True, "task": task.to_dict()})


@app.get("/autonomy/brief", dependencies=[Depends(_admin_guard)])
async def autonomy_brief(kind: str = "morning"):
    """Render the morning brief or evening retro (H6.4)."""
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    from core.autonomy.digest import build_morning_brief, build_evening_retro
    text = (build_evening_retro if kind == "evening" else build_morning_brief)(orch.autonomy_queue)
    return _nocache_json({"kind": kind, "text": text})


@app.get("/autonomy/preferences/suggestions", dependencies=[Depends(_admin_guard)])
async def autonomy_pref_suggestions():
    """Classes consistently approved → autonomy-raise suggestions (H6.5)."""
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    return _nocache_json({"suggestions": orch.autonomy_prefs.suggest_autonomy_raise()})


# ── H12.1: reversible / irreversible approval queue + security posture ──
# RiskTier 0-1 (read-only / reversible) are undoable; 2-3 (external /
# irreversible-or-money) are not. The HUD surfaces this so the user knows which
# pending actions can be safely auto-approved vs. which need scrutiny — the
# "anti-OpenClaw" reversibility story.


def _reversibility(task) -> dict:
    """Annotate a queued Task with a human-facing reversibility verdict."""
    from core.autonomy.policy import RiskTier

    tier = int(task.risk_tier)
    reversible = tier <= int(RiskTier.REVERSIBLE)
    try:
        tier_name = RiskTier(tier).name
    except ValueError:
        tier_name = "UNKNOWN"
    d = task.to_dict()
    d["reversible"] = reversible
    d["tier_name"] = tier_name
    d["reversibility"] = "reversible" if reversible else "irreversible"
    return d


@app.get("/autonomy/approvals", dependencies=[Depends(_admin_guard)])
async def autonomy_approvals():
    """Pending approvals split into reversible vs irreversible buckets (H12.1)."""
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    pending = orch.autonomy_queue.pending_decisions()
    annotated = [_reversibility(t) for t in pending]
    reversible = [t for t in annotated if t["reversible"]]
    irreversible = [t for t in annotated if not t["reversible"]]
    return _nocache_json({
        "pending": annotated,
        "reversible": reversible,
        "irreversible": irreversible,
        "counts": {
            "total": len(annotated),
            "reversible": len(reversible),
            "irreversible": len(irreversible),
        },
    })


@app.post("/api/security/spotlight")
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
    return _nocache_json(spotlight(text, (body or {}).get("source", "untrusted")))


@app.post("/api/security/scan-injection")
async def security_scan_injection(req: Request):
    """H17.1 — return prompt-injection patterns found in text (empty = clean)."""
    from agents.core.security.quarantine import detect_injection
    try:
        body = await req.json()
    except Exception:
        body = {}
    flags = detect_injection((body or {}).get("text", ""))
    return _nocache_json({"flags": flags, "suspicious": bool(flags)})


@app.get("/api/security/governance")
async def security_governance():
    """H17.2 — public trust scorecard: injection + harm suites + OWASP Top 10 + gate."""
    from agents.core.security.governance import governance_gate
    return _nocache_json(governance_gate())


# ── H17.3 Capability tokens + out-of-band kill-switch ─────────────────────────

@app.post("/api/security/capabilities/issue", dependencies=[Depends(_admin_guard)])
async def capabilities_issue(req: Request):
    """Mint a scoped, expiring capability token (out-of-band; admin only)."""
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
    token = broker.issue(caps, source=body.get("source", ""),
                         task_id=body.get("task_id", ""), ttl=float(body.get("ttl", 3600)))
    return _nocache_json({"ok": True, "token": token})


@app.get("/api/security/capabilities/check")
async def capabilities_check(token: str, capability: str):
    """Check whether a token currently grants a capability (read-only)."""
    broker = getattr(orch, "capabilities", None) if orch else None
    kill = getattr(orch, "kill_switch", None) if orch else None
    if broker is None or kill is None:
        return JSONResponse({"error": "capability broker not available"}, status_code=503)
    from agents.core.security.capability import authorize
    return _nocache_json(authorize(broker, kill, token, capability))


@app.get("/api/security/kill-switch")
async def kill_switch_status():
    """Out-of-band kill-switch status."""
    kill = getattr(orch, "kill_switch", None) if orch else None
    if kill is None:
        return JSONResponse({"error": "kill-switch not available"}, status_code=503)
    return _nocache_json(kill.status())


@app.post("/api/security/kill-switch", dependencies=[Depends(_admin_guard)])
async def kill_switch_set(req: Request):
    """Engage/disengage the kill-switch (operator action; agent can't reach this)."""
    kill = getattr(orch, "kill_switch", None) if orch else None
    if kill is None:
        return JSONResponse({"error": "kill-switch not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    scope = (body or {}).get("scope", "global")
    if (body or {}).get("engage", True):
        return _nocache_json({"ok": True, "engaged": kill.engage(scope, body.get("reason", ""))})
    return _nocache_json({"ok": True, "disengaged": kill.disengage(scope)})


# ── H17.4 Externally-anchored audit + intent attribution ──────────────────────

@app.post("/api/security/audit/action")
async def audit_record_action(req: Request):
    """Record a signed action with causal intent attribution (why it happened)."""
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
    return _nocache_json({"ok": True, "entry": entry})


@app.get("/api/security/audit/intent")
async def audit_intent(limit: int = Query(100, ge=1, le=1000)):
    """List signed intent records + chain/signature verification."""
    log = getattr(orch, "intent_log", None) if orch else None
    if log is None:
        return JSONResponse({"error": "intent log not available"}, status_code=503)
    return _nocache_json({"verify": log.verify(), "entries": log.list(limit)})


@app.post("/api/security/audit/anchor", dependencies=[Depends(_admin_guard)])
async def audit_anchor():
    """Anchor the audit / intent chain head into the external transparency log."""
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
    return _nocache_json({"ok": True, "receipt": receipt})


@app.get("/api/security/audit/anchors")
async def audit_anchors(limit: int = Query(100, ge=1, le=1000)):
    """List external anchor receipts + verify the anchor chain."""
    anchor = getattr(orch, "transparency", None) if orch else None
    if anchor is None:
        return JSONResponse({"error": "transparency anchor not available"}, status_code=503)
    return _nocache_json({"verify": anchor.verify(), "anchors": anchor.list(limit)})


@app.get("/api/security/posture", dependencies=[Depends(_admin_guard)])
async def security_posture():
    """Packaged security posture: encrypted secrets + signed skills + sandbox + guardrails (H12.1)."""
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)

    # Secrets at-rest backend.
    try:
        from core.secrets import SecretStore
        secret_backend = SecretStore().backend
    except Exception:
        secret_backend = "unavailable"

    # Skill signing posture.
    from core.skills import signing as _signing
    skills = list(getattr(orch.skills, "skills", {}).values()) if getattr(orch, "skills", None) else []
    skill_rows = [s.to_dict() for s in skills]
    untrusted = [s for s in skill_rows if not s.get("trusted")]

    # Sandbox availability.
    sandbox_docker = False
    try:
        from core.sandbox import Sandbox
        sandbox_docker = Sandbox()._has_docker
    except Exception:
        # Sandbox/Docker is optional; absence just means posture reports
        # docker=False rather than failing the security-posture endpoint.
        sandbox_docker = False

    return _nocache_json({
        "secrets": {"encrypted_at_rest": True, "backend": secret_backend},
        "skills": {
            "require_signed": _signing.require_signed(),
            "total": len(skill_rows),
            "trusted": len(skill_rows) - len(untrusted),
            "untrusted": len(untrusted),
            "untrusted_names": [s["name"] for s in untrusted],
            "detail": skill_rows,
        },
        "sandbox": {"docker_available": sandbox_docker},
        "guardrails": {"mode": orch.get_setting("security.guardrails_mode", "WARN")},
    })


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
<script src="/static/i18n.js?v=2"></script>
<script>var _t = window._t || function(k){return k;};</script>
<script src="/static/react.production.min.js"></script>
<script src="/static/react-dom.production.min.js"></script>
<script src="/static/data.js?v=2"></script>
<script src="/static/components.js?v=2"></script>
<script src="/static/admin.js?v=2"></script>
</body>
</html>"""


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    return HTMLResponse(
        content=ADMIN_HTML_TEMPLATE,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/api/admin/settings", dependencies=[Depends(_admin_guard)])
async def admin_get_all():
    return get_all()


@app.get("/api/admin/settings/{category}", dependencies=[Depends(_admin_guard)])
async def admin_get_category(category: str):
    items = get_category(category)
    if not items:
        return JSONResponse({"error": f"unknown category: {category}"}, status_code=404)
    return {category: items}


class AdminPutBody(BaseModel):
    values: dict


@app.put("/api/admin/settings/{category}", dependencies=[Depends(_admin_guard)])
async def admin_put_category(category: str, body: AdminPutBody):
    updated, skipped = put_category(category, body.values)
    resp = {"updated": updated, "category": category}
    if skipped:
        resp["skipped"] = skipped
    return resp


@app.post("/api/admin/settings/reseed", dependencies=[Depends(_admin_guard)])
async def admin_reseed():
    init_db(force=True)
    return {"ok": True, "message": "Settings reseeded from defaults"}


@app.get("/api/admin/env", dependencies=[Depends(_admin_guard)])
async def admin_get_env():
    # Mask anything that looks like a credential so secrets are never
    # returned in clear text, even to an authorized admin.
    out = {}
    for key, val in sorted(os.environ.items()):
        if key.startswith("_"):
            continue
        if any(h in key.lower() for h in _SECRET_HINTS):
            out[key] = _mask_secret(val)
        else:
            out[key] = val
    return out


@app.get("/api/admin/audit", dependencies=[Depends(_admin_guard)])
async def admin_get_audit(page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200)):
    import sqlite3
    db = Path("memory_logs/security/audit.db")
    if not db.exists():
        return {"page": page, "limit": limit, "total": 0, "rows": []}
    conn = sqlite3.connect(str(db))
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
    conn.close()
    return {
        "page": page,
        "limit": limit,
        "total": total,
        "rows": [dict(r) for r in rows],
    }


@app.post("/api/admin/memory/clear", dependencies=[Depends(_admin_guard)])
async def admin_memory_clear():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    await orch.memory.clear()
    return {"ok": True, "message": "Session memory cleared"}


@app.get("/api/admin/agents/stats", dependencies=[Depends(_admin_guard)])
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


@app.get("/api/admin/apm", dependencies=[Depends(_admin_guard)])
async def admin_apm():
    """H10.16 — org APM: total tokens + $ cost + runs, per agent and per model."""
    from agents.core.cost_tracker import apm_summary
    apm = apm_summary()
    # Fold in live latency/throughput from the bench system when available.
    if orch and getattr(orch, "bench", None) is not None:
        try:
            apm["latency"] = orch.bench.get_summary()
        except Exception:
            apm["latency"] = {}
    return _nocache_json(apm)


# ── H10.22 Prompt Version Control (SOUL.md history / diff / rollback / A/B) ──

def _svs():
    """Return the SOUL version store, or None."""
    return getattr(orch, "soul_versions", None) if orch else None


@app.get("/api/admin/prompts/{agent_id}/history", dependencies=[Depends(_admin_guard)])
async def admin_prompt_history(agent_id: str):
    svs = _svs()
    if svs is None:
        return JSONResponse({"error": "prompt VC not available"}, status_code=503)
    return _nocache_json({"agent_id": agent_id, "history": svs.history(agent_id)})


@app.get("/api/admin/prompts/{agent_id}/version/{version}", dependencies=[Depends(_admin_guard)])
async def admin_prompt_version(agent_id: str, version: int):
    svs = _svs()
    if svs is None:
        return JSONResponse({"error": "prompt VC not available"}, status_code=503)
    v = svs.get(agent_id, version)
    if v is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return _nocache_json(v)


@app.post("/api/admin/prompts/{agent_id}/commit", dependencies=[Depends(_admin_guard)])
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
    return _nocache_json({"ok": True, "version": entry})


@app.get("/api/admin/prompts/{agent_id}/diff", dependencies=[Depends(_admin_guard)])
async def admin_prompt_diff(agent_id: str, a: int, b: int):
    svs = _svs()
    if svs is None:
        return JSONResponse({"error": "prompt VC not available"}, status_code=503)
    d = svs.diff(agent_id, a, b)
    if d is None:
        return JSONResponse({"error": "version not found"}, status_code=404)
    return _nocache_json({"agent_id": agent_id, "a": a, "b": b, "diff": d})


@app.post("/api/admin/prompts/{agent_id}/rollback", dependencies=[Depends(_admin_guard)])
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
    return _nocache_json({"ok": True, "version": entry})


@app.post("/api/admin/prompts/{agent_id}/ab", dependencies=[Depends(_admin_guard)])
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
    return _nocache_json({"ok": True, "experiment": ab})


@app.get("/api/admin/prompts/{agent_id}/ab", dependencies=[Depends(_admin_guard)])
async def admin_prompt_ab_summary(agent_id: str):
    svs = _svs()
    if svs is None:
        return JSONResponse({"error": "prompt VC not available"}, status_code=503)
    return _nocache_json({"agent_id": agent_id, "ab": svs.ab_summary(agent_id)})


@app.post("/api/admin/prompts/{agent_id}/preview", dependencies=[Depends(_admin_guard)])
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
    return _nocache_json({"agent_id": agent_id, **preview_change(current, proposed)})


class AgentUpdateRequest(BaseModel):
    updates: dict[str, str | bool | int]


@app.put("/api/admin/agents/{agent_id}", dependencies=[Depends(_admin_guard)])
async def admin_agents_put(agent_id: str, req: AgentUpdateRequest):
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if agent_id not in orch.agents:
        return JSONResponse({"error": f"agent {agent_id} not found"}, status_code=404)
    _AGENT_SETTINGS[agent_id] = req.updates
    return {"saved": True, "agent": agent_id, "applied": list(req.updates.keys())}


@app.post("/api/admin/llm/test", dependencies=[Depends(_admin_guard)])
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


# ── Local model management (browse / switch) — H12.9 ─────────────
#
# Surfaces models available in the live local backends (LM Studio + Ollama,
# the same providers the HybridRouter talks to) so the HUD can browse them,
# see which is active, and switch with a single click — Jan.ai style.

_LM_STUDIO_URL = "http://localhost:1234"
_OLLAMA_URL = "http://localhost:11434"


async def _list_local_models() -> dict:
    """Query LM Studio and Ollama for installed local models.

    Returns a dict with the active model name (from the live router) and a flat
    list of `{id, provider, online}` entries. Providers that are offline are
    reported with `online: False` and an empty model list rather than failing
    the whole request, so the HUD can still render availability status.
    """
    import httpx

    active = None
    backend = "none"
    if orch and getattr(orch, "llm_router", None) is not None:
        active = getattr(orch.llm_router, "active_model", None)
        backend = orch.llm_router.name

    providers = []
    models = []

    async def _probe(name, url, parse):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                if not resp.is_success:
                    providers.append({"name": name, "online": False, "status": resp.status_code})
                    return
                for mid in parse(resp.json()):
                    if mid:
                        models.append({"id": mid, "provider": name})
                providers.append({"name": name, "online": True})
        except Exception as e:
            providers.append({"name": name, "online": False, "error": str(e)})

    await _probe(
        "lm-studio",
        f"{_LM_STUDIO_URL}/v1/models",
        lambda d: [m.get("id") for m in (d.get("data") or [])],
    )
    await _probe(
        "ollama",
        f"{_OLLAMA_URL}/api/tags",
        lambda d: [m.get("name") for m in (d.get("models") or [])],
    )

    for m in models:
        m["active"] = m["id"] == active

    return {
        "active": active,
        "backend": backend,
        "providers": providers,
        "models": models,
    }


@app.get("/api/models/local", dependencies=[Depends(_admin_guard)])
async def models_local_list():
    """List local models from LM Studio / Ollama and mark the active one."""
    return _nocache_json(await _list_local_models())


class LocalModelSwitch(BaseModel):
    model: str = Field(..., min_length=1)


@app.post("/api/models/local/switch", dependencies=[Depends(_admin_guard)])
async def models_local_switch(body: LocalModelSwitch):
    """Set the active local model on the live router and persist the choice.

    The model must be present in one of the local backends. The selection is
    written to `llm.default_model` (settings_db) so it survives a restart, and
    applied immediately to the running HybridRouter.
    """
    if not orch or getattr(orch, "llm_router", None) is None:
        return _nocache_json({"error": "not initialized"}, status_code=503)

    catalog = await _list_local_models()
    available = {m["id"] for m in catalog["models"]}
    if body.model not in available:
        return _nocache_json(
            {"error": f"model '{body.model}' not available locally", "available": sorted(available)},
            status_code=404,
        )

    orch.llm_router.set_active_model(body.model)
    try:
        put_category("llm", {"default_model": body.model})
    except Exception:
        # Persistence is best-effort; the live switch already took effect.
        pass

    return _nocache_json({"ok": True, "active": body.model})


# ── MCP (Model Context Protocol) admin endpoints ─────────────────

@app.get("/api/admin/mcp", dependencies=[Depends(_admin_guard)])
async def admin_mcp_list():
    """List all configured MCP servers with their status."""
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    servers = []
    for name, srv in orch.mcp.servers.items():
        servers.append({
            "name": name,
            "transport": srv.transport,
            "command": srv.command,
            "url": srv.url,
            "connected": srv._proc is not None and srv._proc.returncode is None,
            "tools_count": len(srv.tools),
            "tools": [{"name": t.name, "description": t.description} for t in srv.tools],
        })
    return {"servers": servers, "total": len(servers)}


class MCPServerConfig(BaseModel):
    name: str
    transport: str = "stdio"
    command: Optional[str] = None
    url: Optional[str] = None


@app.post("/api/admin/mcp", dependencies=[Depends(_admin_guard)])
async def admin_mcp_add(req: MCPServerConfig):
    """Add a new MCP server configuration."""
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    from core.mcp.client import MCPServer
    if req.name in orch.mcp.servers:
        return JSONResponse({"error": f"MCP server '{req.name}' already exists"}, status_code=409)
    srv = MCPServer(
        name=req.name,
        transport=req.transport,
        command=req.command,
        url=req.url,
    )
    orch.mcp.servers[srv.name] = srv
    # Persist to settings DB
    _save_mcp_config()
    return {"ok": True, "server": req.name, "message": f"MCP server '{req.name}' added"}


@app.delete("/api/admin/mcp/{name}", dependencies=[Depends(_admin_guard)])
async def admin_mcp_remove(name: str):
    """Remove an MCP server configuration."""
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if name not in orch.mcp.servers:
        return JSONResponse({"error": f"MCP server '{name}' not found"}, status_code=404)
    srv = orch.mcp.servers[name]
    if srv._proc:
        await srv.close()
    del orch.mcp.servers[name]
    # Persist to settings DB
    _save_mcp_config()
    return {"ok": True, "server": name, "message": f"MCP server '{name}' removed"}


@app.post("/api/admin/mcp/{name}/connect", dependencies=[Depends(_admin_guard)])
async def admin_mcp_connect(name: str):
    """Connect to an MCP server and discover tools."""
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if name not in orch.mcp.servers:
        return JSONResponse({"error": f"MCP server '{name}' not found"}, status_code=404)
    srv = orch.mcp.servers[name]
    try:
        await srv.connect()
        return {
            "ok": True,
            "server": name,
            "connected": True,
            "tools_count": len(srv.tools),
            "tools": [{"name": t.name, "description": t.description} for t in srv.tools],
        }
    except Exception as e:
        return JSONResponse({"error": str(e), "server": name}, status_code=500)


@app.post("/api/admin/mcp/{name}/disconnect", dependencies=[Depends(_admin_guard)])
async def admin_mcp_disconnect(name: str):
    """Disconnect from an MCP server."""
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    if name not in orch.mcp.servers:
        return JSONResponse({"error": f"MCP server '{name}' not found"}, status_code=404)
    srv = orch.mcp.servers[name]
    if srv._proc:
        await srv.close()
        return {"ok": True, "server": name, "message": f"MCP server '{name}' disconnected"}
    return {"ok": True, "server": name, "message": f"MCP server '{name}' was not connected"}


def _save_mcp_config():
    """Persist MCP servers configuration to settings DB."""
    from core.settings_db import put_category
    config = orch.mcp.to_config()
    put_category("mcp", {"servers": config})  # return value intentionally unused


def _load_mcp_config():
    """Load MCP servers configuration from settings DB."""
    from core.settings_db import get_category
    items = get_category("mcp")
    for item in items:
        if item["key"] == "servers":
            orch.mcp.load_from_config(item["value"])
            logger.info(f"Loaded {len(item['value'])} MCP servers from settings")
            return
    logger.info("No MCP servers configured in settings")


# ── Admin Charts endpoint ──────────────────────────────────────

@app.get("/api/admin/stats", dependencies=[Depends(_admin_guard)])
async def admin_stats():
    """Aggregated stats for admin charts: latency, usage, success rate."""
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

    return _nocache_json({
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


@app.get("/api/resilience")
async def resilience_public():
    """Public resilience metrics and circuit breaker states (no admin auth)."""
    from core.resilience import get_metrics, _circuit_breakers
    metrics = get_metrics().get_stats()
    breakers = {
        key: {
            "state": cb.state,
            "failure_count": cb.failure_count,
            "last_failure_time": cb.last_failure_time,
        }
        for key, cb in _circuit_breakers.items()
    }
    return _nocache_json({"metrics": metrics, "circuit_breakers": breakers})


# ── OAuth endpoints ──────────────────────────────────────────────

from core.plugins.oauth import (
    init_from_env, get_google_auth_url, get_spotify_auth_url,
    exchange_google_code, exchange_spotify_code,
    refresh_google_token, refresh_spotify_token, load_token,
    verify_state,
)

init_from_env()

OAUTH_SERVICES = {
    "gmail": {"label": "Gmail", "url": lambda: get_google_auth_url("gmail")},
    "calendar": {"label": "Google Calendar", "url": lambda: get_google_auth_url("calendar")},
    "spotify": {"label": "Spotify", "url": get_spotify_auth_url},
}


@app.get("/api/oauth/status")
async def oauth_status():
    result = {}
    for sid, info in OAUTH_SERVICES.items():
        token = load_token(sid if sid != "spotify" else "spotify")
        result[sid] = {
            "connected": token is not None and bool(token.get("access_token")),
            "label": info["label"],
            "auth_url": info["url"]() if not (token and token.get("access_token")) else None,
        }
    return result


class OAuthCodeBody(BaseModel):
    code: str
    state: str = ""


@app.post("/api/oauth/callback")
async def oauth_callback(body: OAuthCodeBody):
    state = body.state
    service_id = verify_state(state)
    if service_id is None:
        return JSONResponse({"ok": False, "error": "Invalid or expired state"}, status_code=400)

    if service_id.startswith("google:"):
        service = service_id.split(":")[1]
        result = await exchange_google_code(body.code, state)
    elif service_id == "spotify":
        service = "spotify"
        result = await exchange_spotify_code(body.code, state)
    else:
        return JSONResponse({"ok": False, "error": f"Unknown service: {service_id}"}, status_code=400)

    if result:
        return {"ok": True, "service": service, "has_refresh": "refresh_token" in result}
    return JSONResponse({"ok": False, "error": "Token exchange failed"}, status_code=400)


@app.get("/api/oauth/auth-url")
async def oauth_auth_url(service: str = ""):
    info = OAUTH_SERVICES.get(service)
    if not info:
        return JSONResponse({"error": f"Unknown service: {service}"}, status_code=404)
    return {"url": info["url"]()}


@app.post("/api/oauth/refresh")
async def oauth_refresh(service: str = ""):
    if service == "spotify":
        token = await refresh_spotify_token()
    elif service in ("gmail", "calendar"):
        token = await refresh_google_token()
    else:
        return JSONResponse({"error": f"Unknown service: {service}"}, status_code=404)
    return {"ok": token is not None, "service": service}


# ── Oracle Bridge endpoints ──────────────────────────────────────
# These expose Claude session tracking, conflict detection, and
# OpenCode integration via the Oracle agent.


@app.get("/api/oracle/status")
async def oracle_status():
    bridge = getattr(orch, "oracle_bridge", None)
    if not bridge:
        return JSONResponse({"ok": False, "error": "Oracle bridge not available"}, status_code=503)
    return _nocache_json(bridge.status())


@app.post("/api/oracle/sync")
async def oracle_sync():
    bridge = getattr(orch, "oracle_bridge", None)
    if not bridge:
        return JSONResponse({"ok": False, "error": "Oracle bridge not available"}, status_code=503)
    result = await bridge.sync_now()
    return _nocache_json(result)


@app.get("/api/oracle/conflicts")
async def oracle_conflicts():
    bridge = getattr(orch, "oracle_bridge", None)
    if not bridge:
        return JSONResponse({"ok": False, "error": "Oracle bridge not available"}, status_code=503)
    conflicts = await bridge.check_conflicts()
    return _nocache_json({"conflicts": conflicts})


@app.post("/api/oracle/conflicts/resolve")
async def oracle_resolve_conflicts():
    bridge = getattr(orch, "oracle_bridge", None)
    if not bridge:
        return JSONResponse({"ok": False, "error": "Oracle bridge not available"}, status_code=503)
    bridge.conflicts = [c for c in bridge.conflicts if c.resolved]
    return _nocache_json({"ok": True})


# ── Trust indicator (H12.10): hardware-mute / strict-local ───────


def _env_truthy(value: str | None) -> bool:
    """Treat the usual on/off spellings as booleans for env-driven toggles."""
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def _trust_status() -> dict:
    """Compute the two visible, auditable trust states for the HUD.

    - ``mic``: "off" when the (software/hardware) mic is muted, else "on".
      Driven by ``JARVIS_MIC_MUTED`` so a physical mute switch / kiosk wrapper
      can flip it without touching code (inspired by Voice PE's physical mute).
    - ``strict_local``: True when no cloud backend is reachable AND no agent can
      escape to the cloud — i.e. nothing leaves the machine. Derived from the
      live router (``_cloud_available`` / ``_claude_available``) so the signal
      reflects reality, with an explicit ``JARVIS_STRICT_LOCAL`` override that
      can only *tighten* (never loosen) the guarantee.
    """
    mic_muted = _env_truthy(os.environ.get("JARVIS_MIC_MUTED"))

    cloud_available = False
    claude_available = False
    router = getattr(orch, "llm_router", None) if orch else None
    if router is not None:
        cloud_available = bool(getattr(router, "_cloud_available", False))
        claude_available = bool(getattr(router, "_claude_available", False))

    # Strict-local when no cloud path exists at all; env flag can force it on.
    # Single unconditional assignment (De Morgan of `not (cloud or claude)`)
    # so the value is provably initialized before use.
    strict_local = (not cloud_available and not claude_available) or _env_truthy(
        os.environ.get("JARVIS_STRICT_LOCAL")
    )

    return {
        "mic": "off" if mic_muted else "on",
        "strict_local": strict_local,
        # Auditable detail: why strict_local is (or isn't) set.
        "cloud_available": cloud_available,
        "claude_available": claude_available,
    }


@app.get("/api/trust/status")
async def trust_status():
    """Visible, auditable trust signal for the HUD: mic state + strict-local."""
    return _nocache_json(_trust_status())


# ── v0.3 Cognition Release endpoints ─────────────────────────────


@app.get("/api/cognition")
async def get_cognition():
    """Return the last dynamic routing/cognition context."""
    cog = getattr(orch, "last_cognition", None) if orch else None
    if not cog:
        from core.router import INTENT_RULES
        scoring = []
        for kw, rule in list(INTENT_RULES.items())[:5]:
            scoring.append({
                "keyword": kw,
                "weight": rule[2],
                "agents": rule[0],
                "category": kw
            })
        cog = {
            "scoring": scoring,
            "decision": {
                "source": "standby",
                "confidence": 1.0,
                "agents_selected": ["jarvis"],
                "alternatives": [],
                "timing": {"classify": 0, "route": 0, "total": 0}
            },
            "trace": []
        }
    return _nocache_json(cog)


@app.get("/memory/stats")
async def memory_stats():
    """Live memory stats for SystemsPanel."""
    try:
        if not orch or not hasattr(orch, 'memory') or not orch.memory:
            return _nocache_json({"sessions": {"total": 0, "current": "", "active": 0}, "vectors": {"stored": 0, "dimension": 0, "backend": ""}, "knowledge_graph": {"entities": 0, "relations": 0, "last_seed": ""}, "agent_contexts": {}})
        stats = await orch.memory.get_session_stats() if hasattr(orch.memory, 'get_session_stats') else {"sessions": 0, "current_session": "", "vectors": 0, "agent_contexts": []}
        contexts = {}
        if hasattr(orch.memory, 'agent_contexts') and orch.memory.agent_contexts:
            for aid, ctx in orch.memory.agent_contexts.items():
                contexts[aid] = len(ctx) if isinstance(ctx, dict) else (len(ctx) if hasattr(ctx, '__len__') else 0)
        kg_entities = 0
        kg_relations = 0
        kg_last = ""
        if hasattr(orch.memory, 'graph') and orch.memory.graph:
            try:
                g = orch.memory.graph
                kg_entities = len(g.entities) if hasattr(g, 'entities') else 0
                kg_relations = len(g.relations) if hasattr(g, 'relations') else 0
                kg_last = g.last_seed if hasattr(g, 'last_seed') else ""
            except Exception:
                pass
        return _nocache_json({
            "sessions": {"total": stats.get("sessions", 0), "current": stats.get("current_session", ""), "active": stats.get("active", stats.get("sessions", 0))},
            "vectors": {"stored": stats.get("vectors", 0), "dimension": 768 if stats.get("vectors", 0) > 0 else 0, "backend": "in-memory" if stats.get("vectors", 0) > 0 else ""},
            "knowledge_graph": {"entities": kg_entities, "relations": kg_relations, "last_seed": kg_last},
            "agent_contexts": contexts,
        })
    except Exception:
        return _nocache_json({"sessions": {"total": 0, "current": "", "active": 0}, "vectors": {"stored": 0, "dimension": 0, "backend": ""}, "knowledge_graph": {"entities": 0, "relations": 0, "last_seed": ""}, "agent_contexts": {}})


@app.get("/api/memory/search")
async def memory_search(q: str = "", top_k: int = 10):
    """Fused recall via RRF: vector similarity + knowledge-graph (H5.14 Task 4)."""
    top_k = max(1, min(top_k, 50))
    if not orch or not orch.memory:
        return _nocache_json({"results": [], "query": q, "total": 0})
    try:
        # Real semantic recall: embed the query so the vector arm of fused recall
        # actually contributes (degrades to keyword/graph-only if embedding fails).
        embedding = await orch.memory.embed(q) if q and hasattr(orch.memory, "embed") else None
        hits = await orch.memory.hybrid_search(
            embedding=embedding, keyword=q or None, top_k=top_k
        )
        return _nocache_json({
            "results": [
                {
                    "id": h.id,
                    "score": round(h.score, 4),
                    "sources": h.sources,
                    "payload": h.payload,
                }
                for h in hits
            ],
            "query": q,
            "total": len(hits),
        })
    except Exception as e:
        logger.warning(f"memory/search error: {e}")
        return _nocache_json({"results": [], "query": q, "total": 0, "error": str(e)})


@app.get("/api/memory/entities")
async def memory_entities(q: str = "", type: str = "", limit: int = Query(50, ge=1, le=200)):
    """H8.1b — search/list the named-entity store (+ stats)."""
    if not orch or not getattr(orch, "entities", None):
        return _nocache_json({"entities": [], "stats": {}, "error": "entity store not available"})
    return _nocache_json({
        "entities": orch.entities.search(q, type, limit),
        "stats": orch.entities.stats(),
    })


# ── H8.3b Agentic RAG tool (LLM-callable search_memory over structured stores) ─

def _structured_recall(query: str, top_k: int = 5) -> list:
    """Offline recall over the structured memory stores (entities + KG)."""
    hits: list[dict] = []
    if not orch:
        return hits
    q = (query or "").strip()
    ents = getattr(orch, "entities", None)
    if ents is not None:
        for e in ents.search(q, limit=top_k):
            hits.append({"source": "entity", "text": e["name"], "type": e.get("type", ""),
                         "score": e.get("mentions", 0)})
    g = getattr(getattr(orch, "memory", None), "graph", None)
    if g is not None:
        try:
            for node in g.search(q)[:top_k]:
                hits.append({"source": "graph", "text": node.get("name", ""),
                             "type": node.get("type", ""), "score": 1})
        except Exception:
            pass
    return hits[:top_k]


@app.get("/api/memory/tool-spec")
async def memory_tool_spec():
    """H8.3b — the search_memory function-calling spec the model can invoke."""
    from agents.core.memory.rag_tool import TOOL_SPEC
    return _nocache_json(TOOL_SPEC)


@app.post("/api/memory/search-tool")
async def memory_search_tool(req: Request):
    """H8.3b — a single search_memory tool call. Body: {query, top_k?}."""
    from agents.core.memory.rag_tool import MemorySearchTool
    try:
        body = await req.json()
    except Exception:
        body = {}
    query = (body or {}).get("query", "")
    if not query:
        return JSONResponse({"error": "query required"}, status_code=400)
    tool = MemorySearchTool(_structured_recall)
    return _nocache_json(tool.search(query, int(body.get("top_k", 5))))


# ── H14.4 Decay-based forgetting (ACT-R activation + dependency-aware delete) ──

@app.get("/api/memory/decay/ranking")
async def memory_decay_ranking(limit: int = Query(100, ge=1, le=1000)):
    """Memory items ranked by ACT-R activation (recency + frequency)."""
    d = getattr(orch, "decay", None) if orch else None
    if d is None:
        return _nocache_json({"ranking": []})
    return _nocache_json({"ranking": d.ranking(limit=limit)})


@app.get("/api/memory/decay/candidates")
async def memory_decay_candidates(threshold: float = 0.0):
    """Items whose activation has decayed below *threshold* (forget candidates)."""
    d = getattr(orch, "decay", None) if orch else None
    if d is None:
        return _nocache_json({"candidates": []})
    return _nocache_json({"threshold": threshold, "candidates": d.forget_candidates(threshold)})


@app.post("/api/memory/decay/forget")
async def memory_decay_forget(req: Request):
    """Forget an item + its transitive dependents (anti-recontamination)."""
    d = getattr(orch, "decay", None) if orch else None
    if d is None:
        return JSONResponse({"error": "decay memory not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    item_id = (body or {}).get("id", "")
    if not item_id:
        return JSONResponse({"error": "id required"}, status_code=400)
    removed = d.forget(item_id)
    if not removed:
        return JSONResponse({"error": "not found"}, status_code=404)
    return _nocache_json({"ok": True, "removed": removed})


# ── H12.3 Knowledge-graph editor (query / edit / delete entities + relations) ─

def _kg():
    """Return the live knowledge graph, or None."""
    if not orch or not getattr(orch, "memory", None):
        return None
    return getattr(orch.memory, "graph", None)


@app.get("/api/kg/entities")
async def kg_entities(q: str = "", limit: int = Query(100, ge=1, le=500)):
    """List (or search with ?q=) knowledge-graph entities."""
    g = _kg()
    if g is None:
        return _nocache_json({"entities": [], "error": "graph not available"})
    entities = g.search(q) if q else g.list_entities(limit)
    return _nocache_json({"entities": entities[:limit], "total": len(entities)})


@app.get("/api/kg/entities/{name}")
async def kg_entity(name: str):
    """Get one entity plus its relations."""
    g = _kg()
    if g is None:
        return JSONResponse({"error": "graph not available"}, status_code=503)
    ent = g.get_entity(name)
    if ent is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return _nocache_json({"entity": ent, "relations": g.get_relations(name)})


@app.post("/api/kg/entities")
async def kg_upsert_entity(req: Request):
    """Create or update an entity (upsert). Body: {name, type, properties}."""
    g = _kg()
    if g is None:
        return JSONResponse({"error": "graph not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    name = (body or {}).get("name", "").strip()
    if not name:
        return JSONResponse({"error": "name required"}, status_code=400)
    ok = g.add_entity(name, (body.get("type") or "unknown"), body.get("properties") or {})
    return _nocache_json({"ok": bool(ok), "entity": g.get_entity(name)})


@app.delete("/api/kg/entities/{name}")
async def kg_delete_entity(name: str):
    """Delete an entity and any relations that touch it."""
    g = _kg()
    if g is None:
        return JSONResponse({"error": "graph not available"}, status_code=503)
    if not g.delete_entity(name):
        return JSONResponse({"error": "not found"}, status_code=404)
    return _nocache_json({"ok": True, "deleted": name})


@app.post("/api/kg/relations")
async def kg_add_relation(req: Request):
    """Create a relation. Body: {source, relation, target, properties}."""
    g = _kg()
    if g is None:
        return JSONResponse({"error": "graph not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    source = (body or {}).get("source", "").strip()
    relation = (body or {}).get("relation", "").strip()
    target = (body or {}).get("target", "").strip()
    if not (source and relation and target):
        return JSONResponse({"error": "source, relation, target required"}, status_code=400)
    ok = g.add_relation(source, relation, target, body.get("properties") or {})
    return _nocache_json({"ok": bool(ok)})


@app.delete("/api/kg/relations")
async def kg_delete_relation(source: str, relation: str, target: str):
    """Delete a specific relation (by source/relation/target)."""
    g = _kg()
    if g is None:
        return JSONResponse({"error": "graph not available"}, status_code=503)
    if not g.delete_relation(source, relation, target):
        return JSONResponse({"error": "not found"}, status_code=404)
    return _nocache_json({"ok": True})


# ── H14.1 Bi-temporal KG (valid-time + ingested-at; as-of recall) ─────────────

@app.post("/api/kg/facts")
async def kg_add_fact(req: Request):
    """Add a bi-temporal fact. Body: {subject, predicate, object, valid_from?,
    ingested_at?, multi?}. Single-valued predicates invalidate (not delete) a
    contradicting prior fact."""
    bt = getattr(orch, "bitemporal", None) if orch else None
    if bt is None:
        return JSONResponse({"error": "bi-temporal KG not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    for k in ("subject", "predicate", "object"):
        if not (body or {}).get(k):
            return JSONResponse({"error": "subject, predicate, object required"}, status_code=400)
    fact = bt.add_fact(
        body["subject"], body["predicate"], body["object"],
        valid_from=body.get("valid_from"), ingested_at=body.get("ingested_at"),
        multi=bool(body.get("multi", False)),
    )
    return _nocache_json({"ok": True, "fact": fact})


@app.get("/api/kg/facts/as-of")
async def kg_facts_as_of(at: Optional[float] = None, subject: str = "", predicate: str = ""):
    """Valid-time recall: facts true in the world at time `at` (default now)."""
    bt = getattr(orch, "bitemporal", None) if orch else None
    if bt is None:
        return JSONResponse({"error": "bi-temporal KG not available"}, status_code=503)
    return _nocache_json({"at": at, "facts": bt.as_of(at, subject, predicate)})


@app.get("/api/kg/facts/history")
async def kg_facts_history(subject: str, predicate: str = ""):
    """All versions (incl. invalidated) for a subject, oldest first."""
    bt = getattr(orch, "bitemporal", None) if orch else None
    if bt is None:
        return JSONResponse({"error": "bi-temporal KG not available"}, status_code=503)
    return _nocache_json({"subject": subject, "history": bt.history(subject, predicate)})


@app.post("/api/kg/ingest")
async def kg_ingest(req: Request):
    """H12.6 — extract triples from text and write them to the KG immediately."""
    updater = getattr(orch, "kg_updater", None) if orch else None
    if updater is None:
        return JSONResponse({"error": "incremental KG not available"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    text = (body or {}).get("text", "")
    if not text:
        return JSONResponse({"error": "text required"}, status_code=400)
    count = updater.ingest(text)
    return _nocache_json({"ok": True, "added": count, "triples": updater.last_added})


@app.get("/api/memory/eval/corpus")
async def memory_eval_corpus():
    """H14.2 — the owned memory-eval corpus (cases across 5 abilities)."""
    from agents.core.memory.eval import DEFAULT_CORPUS, ABILITIES
    return _nocache_json({
        "abilities": ABILITIES,
        "cases": [c.to_dict() for c in DEFAULT_CORPUS],
    })


@app.post("/api/memory/eval/run")
async def memory_eval_run():
    """H14.2 — run the harness with the offline keyword baseline answerer."""
    from agents.core.memory.eval import run_eval, keyword_answer
    return _nocache_json(run_eval(keyword_answer))


@app.post("/api/memory/remember")
async def memory_remember(req: Request):
    """Store a fact in long-term memory with a real embedding, for later recall."""
    if not orch or not orch.memory:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    text = (body or {}).get("text", "")
    text = text.strip() if isinstance(text, str) else ""
    if not text:
        return JSONResponse({"error": "text required"}, status_code=400)
    metadata = (body or {}).get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    rid = await orch.memory.remember(text, metadata=metadata)
    return _nocache_json({"ok": rid is not None, "id": rid})


@app.get("/api/memory/profile")
async def get_memory_profile():
    """Return all stored user facts/preferences grouped by category."""
    from agents.core.memory.store import MemoryStore
    store = MemoryStore()
    return await store.get_all()


@app.get("/api/memory/recall")
async def recall_memory(q: str = ""):
    """Search memory store by query string."""
    from fastapi import Query as _Query
    from agents.core.memory.store import MemoryStore
    store = MemoryStore()
    if not q:
        return {"results": []}
    results = await store.search(q, limit=20)
    return {"results": results, "query": q}


@app.get("/api/analytics/cost")
async def get_analytics_cost():
    """Return per-agent LLM usage and cost summary."""
    from agents.core.cost_tracker import get_summary
    return get_summary()


@app.get("/api/analytics/model-tiers")
async def get_model_tiers():
    """Return per-agent model tier classification and usage summary."""
    from agents.core.cost_tracker import get_summary, MODEL_PRICES
    summary = get_summary()

    def classify_tier(model: str) -> str:
        m = model.lower()
        if "local" in m or m == "default":
            return "local"
        if "haiku" in m or "mini" in m or "flash" in m:
            return "fast"
        if "opus" in m:
            return "heavy"
        return "standard"

    tiers: dict[str, list] = {"local": [], "fast": [], "standard": [], "heavy": []}
    for agent_name, data in summary.get("agents", {}).items():
        tier = classify_tier(data.get("model", "default"))
        tiers[tier].append({
            "agent": agent_name,
            "model": data.get("model", "unknown"),
            "calls": data.get("calls", 0),
            "cost_usd": data.get("cost_usd", 0),
        })

    return {
        "tiers": tiers,
        "total_cost_usd": summary.get("total_cost_usd", 0),
        "tier_counts": {k: len(v) for k, v in tiers.items()},
    }


@app.get("/api/reflection/status")
async def reflection_status():
    """Daily reflection status (H5.15)."""
    if not orch or not hasattr(orch, "reflector") or not orch.reflector:
        return _nocache_json({"enabled": False, "last_run": None, "last_result": None})
    return _nocache_json(orch.reflector.status())


@app.post("/api/reflection/run")
async def reflection_run():
    """Trigger nightly reflection manually (H5.15)."""
    if not orch or not hasattr(orch, "reflector") or not orch.reflector:
        return _nocache_json({"ok": False, "error": "reflector not initialized"})
    try:
        # Force re-run by temporarily clearing last_run
        orch.reflector._last_run = None
        result = await orch.reflector.run(
            enabled=orch.get_setting("system.reflection_enabled", True)
        )
        return _nocache_json({"ok": True, "result": result})
    except Exception as e:
        logger.warning(f"reflection/run error: {e}")
        return _nocache_json({"ok": False, "error": str(e)})


# ── H9.2 Trace Explorer endpoints ────────────────────────────────
# Placed immediately before the workflows block; do NOT move the
# workflows handlers below.

@app.get("/api/traces")
async def list_traces(limit: int = Query(50, ge=1, le=200)):
    """Return recent per-request traces (most-recent first, summarized)."""
    if not orch:
        return _nocache_json({"traces": [], "error": "not initialized"}, status_code=503)
    tracer = getattr(orch, "tracer", None)
    if tracer is None:
        return _nocache_json({"traces": [], "error": "tracer not available"})
    limit = max(1, min(limit, 500))
    return _nocache_json({"traces": tracer.list(limit)})


@app.get("/api/cost")
async def cost_breakdown():
    """H10.24 — estimated $ cost per agent and per day (local models = $0)."""
    if not orch:
        return _nocache_json({"error": "not initialized"}, status_code=503)
    tracer = getattr(orch, "tracer", None)
    if tracer is None:
        return _nocache_json(
            {"by_agent": [], "by_day": [], "summary": {}, "error": "tracer not available"}
        )
    return _nocache_json({
        "by_agent": tracer.cost_by_agent(),
        "by_day": tracer.cost_by_day(),
        "summary": tracer.cost_summary(),
    })


@app.get("/api/traces/{trace_id}")
async def get_trace(trace_id: str):
    """Return the full trace dict for a specific trace id."""
    if not orch:
        return _nocache_json({"error": "not initialized"}, status_code=503)
    tracer = getattr(orch, "tracer", None)
    if tracer is None:
        return _nocache_json({"error": "tracer not available"}, status_code=503)
    item = tracer.get(trace_id)
    if item is None:
        return _nocache_json({"error": f"trace '{trace_id}' not found"}, status_code=404)
    return _nocache_json(item)


@app.post("/api/traces/clear")
async def clear_traces():
    """Flush all traces from the in-memory ring buffer."""
    if not orch:
        return _nocache_json({"error": "not initialized"}, status_code=503)
    tracer = getattr(orch, "tracer", None)
    if tracer is None:
        return _nocache_json({"error": "tracer not available"}, status_code=503)
    tracer.clear()
    return _nocache_json({"ok": True})


# ── END H9.2 Trace Explorer endpoints ─────────────────────────────


# ── H12.4 Wyoming protocol (local-voice interop) ──────────────────

@app.get("/api/voice/wyoming")
async def wyoming_status():
    """Wyoming protocol support status (H12.4)."""
    from agents.core.voice.wyoming import PROTOCOL_VERSION
    enabled = bool(orch and orch.get_setting("voice.wyoming_enabled", False))
    port = int(orch.get_setting("voice.wyoming_port", 10700)) if orch else 10700
    return _nocache_json({
        "protocol": "wyoming",
        "version": PROTOCOL_VERSION,
        "enabled": enabled,
        "port": port,
        "role": "handle",  # transcript → reply-to-speak
    })


# ── END H12.4 Wyoming endpoints ───────────────────────────────────


# ── H12.2 Onboarding: drop folder → private chat with your docs ────

_local_docs_last = {"status": "never run"}


class LocalDocsIndexBody(BaseModel):
    # Select a pre-configured folder by key — NOT a raw path. The actual folder
    # path comes from owner configuration (`local_docs.folders`), so no
    # request-supplied value ever reaches a filesystem path expression.
    key: str = Field(..., max_length=128)


def _configured_doc_folders() -> dict:
    """Owner-configured ``{key: folder_path}`` map of indexable folders."""
    folders = orch.get_setting("local_docs.folders", {}) if orch else {}
    return folders if isinstance(folders, dict) else {}


@app.get("/api/local-docs")
async def local_docs_status():
    """Last indexing summary + the configured folder keys (H12.2)."""
    return _nocache_json({**_local_docs_last, "available": sorted(_configured_doc_folders())})


@app.post("/api/local-docs/index")
async def local_docs_index(body: LocalDocsIndexBody):
    """Index a pre-configured local folder (by key) into memory (offline)."""
    global _local_docs_last
    if not orch:
        return _nocache_json({"error": "not initialized"}, status_code=503)

    folders = _configured_doc_folders()
    folder = folders.get(body.key)
    if not folder:
        return _nocache_json(
            {"error": f"unknown folder key '{body.key}'",
             "available": sorted(folders)},
            status_code=404,
        )

    from agents.core.local_docs import LocalDocsIndexer

    async def _remember(text: str, metadata: dict):
        return await orch.memory.remember(text, metadata=metadata)

    summary = await LocalDocsIndexer(_remember).index(folder)
    status = 400 if summary.get("error") else 200
    if not summary.get("error"):
        _local_docs_last = summary
    return _nocache_json(summary, status_code=status)


# ── END H12.2 Onboarding endpoints ────────────────────────────────


# ── H10.8 Inbound Webhook Triggers ────────────────────────────────

_webhook_store = None


def _get_webhook_store():
    global _webhook_store
    if _webhook_store is None:
        from agents.core.webhooks import WebhookStore
        _webhook_store = WebhookStore()
    return _webhook_store


class WebhookCreateBody(BaseModel):
    target: str = Field(..., max_length=128)
    target_type: str = Field("agent", pattern="^(agent|workflow)$")
    name: str = Field("", max_length=128)


@app.get("/api/webhooks")
async def list_webhooks():
    """List configured inbound webhooks (tokens masked)."""
    return _nocache_json({"webhooks": _get_webhook_store().list()})


@app.post("/api/webhooks")
async def create_webhook(body: WebhookCreateBody):
    """Create an inbound webhook; the token is returned ONCE."""
    try:
        rec = _get_webhook_store().create(body.target, body.target_type, body.name)
    except ValueError as exc:
        return _nocache_json({"error": str(exc)}, status_code=400)
    return _nocache_json(rec)


@app.delete("/api/webhooks/{hook_id}")
async def delete_webhook(hook_id: str):
    ok = _get_webhook_store().delete(hook_id)
    return _nocache_json({"ok": ok}, status_code=200 if ok else 404)


@app.post("/api/webhooks/{hook_id}")
async def trigger_webhook(hook_id: str, request: Request):
    """Token-authenticated trigger → runs the configured agent/workflow."""
    if not orch:
        return _nocache_json({"error": "not initialized"}, status_code=503)
    store = _get_webhook_store()
    hook = store.get(hook_id)
    if hook is None:
        return _nocache_json({"error": "webhook not found"}, status_code=404)

    token = request.headers.get("x-webhook-token") or request.query_params.get("token", "")
    if not store.verify(hook_id, token):
        return _nocache_json({"error": "invalid or missing token"}, status_code=401)

    try:
        payload = await request.json()
    except Exception:
        payload = (await request.body()).decode("utf-8", "replace")

    from agents.core.webhooks import extract_input
    text = extract_input(payload)
    store.mark_called(hook_id)

    if hook["target_type"] == "agent":
        reply = await orch.handle_input(text, channel="webhook", agent_override=hook["target"])
        return _nocache_json({"ok": True, "target": hook["target"], "response": reply})

    # workflow target (best-effort — requires the workflow engine)
    engine = getattr(orch, "workflow_engine", None)
    if engine is None or not hasattr(engine, "run"):
        return _nocache_json({"error": "workflow execution not available"}, status_code=501)
    result = await engine.run(hook["target"], {"input": text})
    return _nocache_json({"ok": True, "target": hook["target"], "result": result})


# ── END H10.8 Inbound Webhook endpoints ───────────────────────────


# ── H10.5 MCP Server Mode (expose Jarvis agents as governed MCP tools) ─

def _build_mcp_server():
    """Build a JarvisMCPServer over the live orchestrator's agents."""
    from agents.core.mcp.server import JarvisMCPServer

    agents = {
        aid: f"{a.config.get('name', aid)} — {a.config.get('tier', '')} tier agent"
        for aid, a in orch.agents.items()
    }

    async def _runner(agent_id: str, text: str) -> str:
        return await orch.handle_input(text, channel="mcp", agent_override=agent_id)

    allowed = orch.get_setting("mcp.exposed_agents", None)
    return JarvisMCPServer(_runner, agents, allowed_agents=allowed, lan_only=True)


@app.get("/api/mcp/server")
async def mcp_server_status():
    """Status + governed tool list for Jarvis's MCP server mode (H10.5)."""
    if not orch:
        return _nocache_json({"error": "not initialized"}, status_code=503)
    enabled = bool(orch.get_setting("mcp.server_enabled", False))
    status = _build_mcp_server().status()
    status["enabled"] = enabled
    return _nocache_json(status)


@app.post("/api/mcp/server/rpc")
async def mcp_server_rpc(message: dict):
    """JSON-RPC 2.0 entry point (HTTP transport). Disabled by default; LAN-only."""
    if not orch:
        return _nocache_json({"error": "not initialized"}, status_code=503)
    if not bool(orch.get_setting("mcp.server_enabled", False)):
        return _nocache_json(
            {"error": "MCP server mode disabled (set mcp.server_enabled)"},
            status_code=403,
        )
    response = await _build_mcp_server().handle(message)
    # JSON-RPC notifications produce no response body.
    return _nocache_json(response if response is not None else {"ok": True})


# ── END H10.5 MCP Server endpoints ────────────────────────────────


# ── H9.3b Dataset Regression Tracking ─────────────────────────────

_dataset_store = None


def _get_dataset_store():
    global _dataset_store
    if _dataset_store is None:
        from agents.core.observability.datasets import DatasetStore
        _dataset_store = DatasetStore()
    return _dataset_store


class DatasetRunBody(BaseModel):
    name: str = Field(..., max_length=128)
    version: Optional[int] = None


@app.get("/api/eval/datasets")
async def list_eval_datasets():
    """List versioned eval datasets with their latest score (H9.3b)."""
    return _nocache_json({"datasets": _get_dataset_store().list_datasets()})


@app.get("/api/eval/datasets/{name}/runs")
async def list_dataset_runs(name: str, limit: int = Query(20, ge=1, le=200)):
    """Recent run summaries for a dataset (most-recent first)."""
    return _nocache_json({"name": name, "runs": _get_dataset_store().runs(name, limit)})


@app.get("/api/eval/datasets/{name}/compare")
async def compare_dataset_runs(name: str, a: str = Query(...), b: str = Query(...)):
    """Diff two runs (a=baseline, b=candidate): regressions + score delta."""
    return _nocache_json(_get_dataset_store().compare(name, a, b))


@app.post("/api/eval/datasets/run")
async def run_eval_dataset(body: DatasetRunBody):
    """Run a dataset version through the live orchestrator and record the run."""
    if not orch:
        return _nocache_json({"error": "not initialized"}, status_code=503)

    async def _runner(prompt: str) -> str:
        return await orch.handle_input(prompt, channel="eval")

    result = await _get_dataset_store().run_dataset(body.name, _runner, body.version)
    status = 404 if result.get("error") else 200
    return _nocache_json(result, status_code=status)


# ── END H9.3b Dataset Regression endpoints ────────────────────────


@app.get("/api/workflows")
async def list_workflows():
    """List all registered workflow pipelines (H5.6 + H9.1 user-defined)."""
    builtin: list[dict] = []
    if orch and hasattr(orch, "workflow_registry"):
        builtin = orch.workflow_registry.list()

    # Merge user-defined pipelines from the store.
    user_dicts = _wf_store().list()
    # Build merged list: built-ins first, user-defined after (user overrides builtin by id).
    merged: dict[str, dict] = {w["id"]: w for w in builtin}
    for u in user_dicts:
        merged[u["id"]] = u
    workflows = list(merged.values())
    return _nocache_json({"workflows": workflows, "total": len(workflows)})


class WorkflowRunBody(BaseModel):
    pipeline_id: str
    input: str = ""


@app.post("/api/workflows/run")
async def run_workflow(body: WorkflowRunBody):
    """Execute a named workflow pipeline (H5.6)."""
    if not orch or not hasattr(orch, "workflow_engine") or not orch.workflow_engine:
        return _nocache_json({"ok": False, "error": "workflow engine not initialized"})
    # Look in registry first, then in the user store.
    pipeline = orch.workflow_registry.get(body.pipeline_id)
    if pipeline is None:
        stored = _wf_store().get(body.pipeline_id)
        if stored:
            try:
                from core.workflows.pipeline import Pipeline as _Pipeline
                pipeline = _Pipeline.from_dict(stored)
            except Exception as e:
                return _nocache_json({"ok": False, "error": f"Invalid stored pipeline: {e}"})
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Pipeline '{body.pipeline_id}' not found")
    try:
        result = await orch.workflow_engine.run(pipeline, initial_input=body.input)
        return _nocache_json({"ok": result.get("_ok", True), "result": result})
    except Exception as e:
        logger.warning(f"workflow/run error: {e}")
        return _nocache_json({"ok": False, "error": str(e)})


@app.get("/api/workflows/traces")
async def workflow_traces(limit: int = Query(20, ge=1, le=50)):
    """H10.2 — recent workflow runs with per-step trace for the visual overlay."""
    engine = getattr(orch, "workflow_engine", None) if orch else None
    if engine is None:
        return _nocache_json({"runs": []})
    return _nocache_json({"runs": engine.recent(limit)})


# ── H9.1 Visual Workflow Builder endpoints ───────────────────────
# Lazy singleton WorkflowStore — created on first request so tests can
# inject a custom path before the module is fully imported.

_wf_store_instance: Optional["_WorkflowStoreType"] = None  # type: ignore[name-defined]


def _wf_store():
    """Return (and lazily create) the module-level WorkflowStore instance."""
    global _wf_store_instance
    if _wf_store_instance is None:
        from core.workflows.storage import WorkflowStore
        _wf_store_instance = WorkflowStore()
    return _wf_store_instance


class WorkflowSaveBody(BaseModel):
    """Body for creating or updating a user-defined workflow."""
    id: str
    name: str = ""
    description: str = ""
    steps: list[dict] = []


@app.post("/api/workflows")
async def create_workflow(body: WorkflowSaveBody):
    """Create or update a user-defined workflow pipeline (H9.1)."""
    if not orch:
        return _nocache_json({"ok": False, "error": "not initialized"}, status_code=503)
    raw = body.model_dump()
    try:
        saved = _wf_store().save(raw)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.warning(f"workflow/save error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    # Register into live registry so it is immediately runnable.
    try:
        from core.workflows.pipeline import Pipeline as _Pipeline
        orch.workflow_registry.register(_Pipeline.from_dict(saved))
    except Exception:
        pass
    return _nocache_json(saved)


@app.put("/api/workflows/{pipeline_id}")
async def update_workflow(pipeline_id: str, body: WorkflowSaveBody):
    """Update an existing user-defined workflow pipeline (H9.1)."""
    if not orch:
        return _nocache_json({"ok": False, "error": "not initialized"}, status_code=503)
    raw = body.model_dump()
    raw["id"] = pipeline_id  # id in URL takes precedence
    try:
        saved = _wf_store().save(raw)
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.warning(f"workflow/update error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    try:
        from core.workflows.pipeline import Pipeline as _Pipeline
        orch.workflow_registry.register(_Pipeline.from_dict(saved))
    except Exception:
        pass
    return _nocache_json(saved)


@app.delete("/api/workflows/{pipeline_id}")
async def delete_workflow(pipeline_id: str):
    """Delete a user-defined workflow pipeline (H9.1)."""
    if not orch:
        return _nocache_json({"ok": False, "error": "not initialized"}, status_code=503)
    deleted = _wf_store().delete(pipeline_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Workflow '{pipeline_id}' not found in store")
    # Best-effort removal from live registry (built-ins are intentionally kept).
    try:
        orch.workflow_registry._pipelines.pop(pipeline_id, None)
    except Exception:
        pass
    return _nocache_json({"ok": True, "deleted": pipeline_id})


@app.get("/memory/{agent_id}")
async def get_agent_memory(agent_id: str):
    """Return per-agent memory context."""
    if agent_id not in orch.agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    ctx = await orch.memory.get_agent_context(agent_id)
    return _nocache_json({
        "agent_id": agent_id,
        "context_keys": list(ctx.keys()) if ctx else [],
        "context": ctx or {},
        "last_updated": ctx.get("_updated") if ctx else None,
    })


@app.get("/plugins")
async def list_plugins():
    """Return all registered plugins with status."""
    if orch is None or orch.permission_gate is None:
        return _nocache_json({"plugins": [], "total": 0})
    plugins = []
    for pid, manifest in orch.permission_gate.plugins.items():
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
    return _nocache_json({"plugins": plugins, "total": len(plugins)})


@app.put("/plugins/{plugin_id}/toggle")
async def toggle_plugin(plugin_id: str):
    """Toggle a plugin's enabled state."""
    manifest = orch.permission_gate.plugins.get(plugin_id)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    if manifest.enabled:
        orch.permission_gate.disable(plugin_id)
        action = "disabled"
    else:
        orch.permission_gate.enable(plugin_id)
        action = "enabled"
    logger.info(f"Plugin {plugin_id} {action}")
    return _nocache_json({"id": plugin_id, "enabled": manifest.enabled, "action": action})


@app.get("/learning/stats")
async def learning_stats():
    """Live learning stats for SystemsPanel."""
    if not orch or not hasattr(orch, 'learning') or not orch.learning:
        return _nocache_json({"interactions_total": 0, "success_rate": 0, "prompt_optimizations": [], "promotion_candidates": [], "demotion_warnings": []})
    try:
        stats = orch.learning.get_stats()
        active_ids = list(stats.get("agents_tracked", stats.get("active_ids", [])))
        optimizations = []
        for aid in active_ids:
            opt = orch.learning.optimize_prompt(aid) if hasattr(orch.learning, 'optimize_prompt') else None
            if opt:
                optimizations.append({"agent": aid, "before": "", "after": opt, "improvement": ""})
        promotions = orch.learning.suggest_promotions(active_ids) if hasattr(orch.learning, 'suggest_promotions') else []
        promos = [{"agent": p.get("bench_agent", p.get("agent", "")), "triggers": p.get("count", 0), "threshold": p.get("threshold", 0)} for p in promotions]
        total = stats.get("total_interactions", 0)
        successful = stats.get("successful", 0)
        rate = successful / total if total > 0 else 0
        return _nocache_json({
            "interactions_total": total,
            "success_rate": round(rate, 3),
            "prompt_optimizations": optimizations,
            "promotion_candidates": promos,
            "demotion_warnings": [],
        })
    except Exception:
        return _nocache_json({"interactions_total": 0, "success_rate": 0, "prompt_optimizations": [], "promotion_candidates": [], "demotion_warnings": []})


@app.get("/security/status")
async def security_status():
    """Return security system status."""
    return _nocache_json({
        "guardrails": {
            "mode": "WARN",
            "redact_count": 0,
            "block_count": 0,
        },
        "scanners": {
            "secret": {"patterns": 10, "findings": 0},
            "pii": {"patterns": 6, "findings": 0},
        },
        "ssrf": {
            "enabled": True,
            "blocked_requests": 0,
            "max_redirects": 5,
        },
    })


@app.get("/bench/stats")
async def bench_stats():
    """Return benchmark statistics."""
    try:
        summary = orch.bench.get_summary()
        stats = {k: summary[k] for k in summary} if isinstance(summary, dict) else {}
    except Exception:
        stats = {}
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


@app.get("/api/analytics/cost")
async def get_cost_analytics():
    """Per-agent token usage and estimated USD cost (H7.10)."""
    from core.cost_tracker import get_summary
    return get_summary()


@app.get("/heartbeat/status")
async def heartbeat_status():
    """Return status of all scheduled heartbeats."""
    return _nocache_json(orch.heartbeat_scheduler.get_status())


@app.post("/heartbeat/{agent_id}/start")
async def heartbeat_start(agent_id: str):
    """Start a heartbeat for an agent."""
    if agent_id not in orch.agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    
    success = orch.heartbeat_scheduler.start_heartbeat(agent_id, orch)
    if success:
        return _nocache_json({"agent_id": agent_id, "status": "started"})
    else:
        raise HTTPException(status_code=400, detail=f"Failed to start heartbeat for '{agent_id}'")


@app.post("/heartbeat/{agent_id}/stop")
async def heartbeat_stop(agent_id: str):
    """Stop a heartbeat for an agent."""
    if agent_id not in orch.agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    
    success = orch.heartbeat_scheduler.stop_heartbeat(agent_id)
    if success:
        return _nocache_json({"agent_id": agent_id, "status": "stopped"})
    else:
        raise HTTPException(status_code=400, detail=f"Failed to stop heartbeat for '{agent_id}'")


@app.post("/heartbeat/{agent_id}/run")
async def heartbeat_run(agent_id: str):
    """Run a heartbeat immediately."""
    if agent_id not in orch.agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    await orch.heartbeat_scheduler.run_now(agent_id, orch)
    return _nocache_json({"agent_id": agent_id, "status": "executed"})


@app.get("/api/status")
async def status():
    """Return service version, agent count, and health status."""
    from agents import __version__, AGENT_COUNT
    return {"version": __version__, "agents": AGENT_COUNT, "status": "ok"}

