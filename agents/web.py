"""
web.py — Jarvis Web UI with streaming (SSE), dashboard, and gateway integration.
"""

import asyncio
import json
import logging
import os
import secrets
import time
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


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
    await orch.stop_channels()


app = FastAPI(title="Jarvis", version="0.2.0-beta", lifespan=lifespan)


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

    return _nocache_json({
        "weather": weather_data,
        "calendar": calendar_data,
        "notifications": notifications,
    })


@app.get("/tasks")
async def get_tasks():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    # Placeholder: return empty task list until real data is wired
    return _nocache_json({"tasks": []})


@app.get("/ticker")
async def get_ticker():
    if not orch:
        return _nocache_json({"error": "not initialized"}, status_code=503)
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
    return _nocache_json({"ticker": items})


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
    updated = put_category(category, body.values)
    return {"updated": updated, "category": category}


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
async def admin_get_audit(page: int = 1, limit: int = 50):
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
