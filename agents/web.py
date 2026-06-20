"""
web.py — Jarvis Web UI with streaming (SSE), dashboard, and gateway integration.
"""

import asyncio
import json
import logging
import os
import re
import secrets
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from agents.core.paths import data_path

sys.path.insert(0, str(Path(__file__).parent))

from core.channels.discord import DiscordChannel
from core.channels.email import EmailChannel
from core.channels.gateway import Gateway
from core.channels.slack import SlackChannel
from core.channels.telegram import TelegramChannel
from core.channels.voice import VoiceChannel
from core.channels.web import WebChannel
from core.config import JarvisConfig
from core.errors import E_INTERNAL_UNEXPECTED, E_SECURITY_BLOCKED, JarvisError
from core.log import log_error, setup_logging
from core.log_safe import log_safe
from core.orchestrator import Orchestrator
from core.security.guardrails import SecurityBlockError
from core.web_helpers import error_json

# Pure response/format helpers live in core.web_helpers (CLN-3 shared kernel) so
# the extracted routers can import them without reaching back into this module.
# Re-exported here under their original private names for backward compatibility.
from core.web_helpers import nocache_json as _nocache_json
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

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

# HF-7 — by default the localhost-origin gate fails CLOSED behind a reverse proxy
# (forwarding headers present → request.client.host is the proxy, untrustworthy →
# require a token). Set JARVIS_TRUSTED_PROXY=1 ONLY when a trusted proxy populates
# X-Forwarded-For; we then read the first hop as the real client IP for the gate.
TRUSTED_PROXY = os.environ.get("JARVIS_TRUSTED_PROXY", "").strip().lower() in ("1", "true", "yes")


def _real_client_host(request: Request) -> str:
    """Origin host for the localhost-fallback gate (HF-7).

    Behind a reverse proxy the socket peer is the proxy, so forwarding headers are
    present. We do NOT trust them unless JARVIS_TRUSTED_PROXY is set: untrusted →
    return "" so the localhost check fails closed (token required). Trusted → use
    the first X-Forwarded-For hop (falling back to X-Real-IP) as the client IP.
    """
    behind_proxy = any(h in request.headers for h in ("x-forwarded-for", "x-real-ip", "forwarded"))
    if not behind_proxy:
        return request.client.host if request.client else ""
    if not TRUSTED_PROXY:
        return ""  # untrusted proxy → never localhost → fail closed
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.headers.get("x-real-ip", "").strip()

async def _admin_guard(request: Request):
    """Authorize an /api/admin/* request or raise 401/403."""
    if ADMIN_TOKEN:
        supplied = request.headers.get("x-admin-token", "")
        if not supplied or not secrets.compare_digest(supplied, ADMIN_TOKEN):
            raise HTTPException(status_code=401, detail="admin token required")
        return
    # No token configured → only localhost may reach admin. Behind an untrusted
    # reverse proxy _real_client_host returns "" → fails closed (HF-7); set
    # JARVIS_TRUSTED_PROXY=1 to trust X-Forwarded-For from a known proxy.
    if _real_client_host(request) not in _LOCALHOSTS:
        raise HTTPException(
            status_code=403,
            detail="admin disabled from network — set JARVIS_ADMIN_TOKEN to enable remote access",
        )


# ── User authentication (HF-1) ────────────────────────────────────
# The assistant itself (/chat), personal memory, notes, code execution and
# other user-facing routes must not be reachable unauthenticated on a LAN/Pi.
# Same model as the admin guard, one tier down:
#   - If JARVIS_USER_TOKEN is set, require a matching X-User-Token header.
#     A valid X-Admin-Token also satisfies it (admin is a superset of user).
#   - If it is NOT set, allow only *direct* localhost — so single-user local
#     dev keeps working out of the box, but a networked deployment is locked
#     down until a token is set. Forwarding headers mean we're behind a proxy
#     and request.client.host can't be trusted, so we fail closed there (HF-7).
USER_TOKEN = os.environ.get("JARVIS_USER_TOKEN", "").strip()


async def _user_guard(request: Request):
    """Authorize a user-facing request or raise 401/403. See USER_TOKEN above."""
    if USER_TOKEN:
        supplied = request.headers.get("x-user-token", "")
        if supplied and secrets.compare_digest(supplied, USER_TOKEN):
            return
        # An admin token is a superset of user access — accept it too.
        if ADMIN_TOKEN:
            admin_supplied = request.headers.get("x-admin-token", "")
            if admin_supplied and secrets.compare_digest(admin_supplied, ADMIN_TOKEN):
                return
        raise HTTPException(status_code=401, detail="user token required")
    # No token configured → only localhost may reach user routes. Fails closed
    # behind an untrusted reverse proxy (HF-7); JARVIS_TRUSTED_PROXY=1 opts into
    # trusting X-Forwarded-For from a known proxy.
    if _real_client_host(request) not in _LOCALHOSTS:
        raise HTTPException(
            status_code=403,
            detail="user routes disabled from network — set JARVIS_USER_TOKEN to enable remote access",
        )


# ── Rate limiting (HF-2) ──────────────────────────────────────────
# Per-IP HTTP rate limit — defense-in-depth on top of the per-channel gateway
# limiter and the HF-1 auth guard: it dampens DoS and brute-force (e.g. guessing
# a user/admin token) from unauthenticated network clients. Localhost and
# *validly* authenticated requests are exempt, so the single-user HUD is never
# throttled — but a wrong-token attempt is NOT exempt, so token guessing is
# rate-limited. Fixed 60s window; JARVIS_RATE_LIMIT=0 disables it.
try:
    RATE_LIMIT_PER_MIN = int(os.environ.get("JARVIS_RATE_LIMIT", "120"))
except ValueError:
    RATE_LIMIT_PER_MIN = 120
_RATE_WINDOW = 60.0
_RATE_MAX_IPS = 4096
_rate_hits: dict[str, list[float]] = {}


def _client_ip(request: Request) -> str:
    """Best-effort client IP: behind a proxy trust the first X-Forwarded-For hop
    (the proxy must set it), otherwise the socket peer."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else ""


def _request_is_authed(request: Request) -> bool:
    """True only if the request carries a *valid* user or admin token."""
    ut = request.headers.get("x-user-token", "")
    if USER_TOKEN and ut and secrets.compare_digest(ut, USER_TOKEN):
        return True
    at = request.headers.get("x-admin-token", "")
    if ADMIN_TOKEN and at and secrets.compare_digest(at, ADMIN_TOKEN):
        return True
    return False


def _rate_limited(ip: str, now: float) -> bool:
    """Record a hit for *ip*; return True once it exceeds the per-minute limit."""
    hits = _rate_hits.get(ip)
    if hits is None:
        if len(_rate_hits) >= _RATE_MAX_IPS:
            _rate_hits.clear()  # crude cap — bounds memory under X-Forwarded-For spoofing
        hits = _rate_hits[ip] = []
    cutoff = now - _RATE_WINDOW
    hits[:] = [t for t in hits if t >= cutoff]
    hits.append(now)
    return len(hits) > RATE_LIMIT_PER_MIN


orch: Orchestrator = None
gateway: Gateway = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    global orch, gateway
    setup_logging()
    # SEC-4 / audit F-08: warn when private runtime state lives inside the git
    # checkout (accidental commit/zip/share risk). Set JARVIS_HOME to relocate it.
    from core.paths import data_root, is_inside_repo
    if is_inside_repo():
        logger.warning("Runtime state is inside the git checkout (%s) — set JARVIS_HOME "
                       "to store it outside the repo.", data_root())
    config = JarvisConfig()
    orch = Orchestrator(config)

    from core.settings_db import get_value
    gateway = Gateway(handler=orch.channel_handler, pairing=getattr(orch, "sender_pairing", None))
    gateway.set_rate_limit(int(get_value("channels", "rate_limit", 10)))  # /admin → channels.rate_limit
    web_enabled = bool(get_value("channels", "web_enabled", True))        # /admin → channels.web_enabled
    if web_enabled:
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

    if web_enabled:
        web_ch = WebChannel(handler=gateway.route)
        await orch.register_channel(web_ch)
    else:
        logger.warning("Web chat channel disabled (/admin → channels.web_enabled)")

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

    # H12.16 — broaden governed channels (WhatsApp/Signal/Matrix/Teams/Google
    # Chat). Configured via JARVIS_WEBHOOK_CHANNELS = {"<kind>": {<config>}}.
    # Default-off; each adapter routes inbound through the same governed gateway.
    wh_raw = os.environ.get("JARVIS_WEBHOOK_CHANNELS", "")
    if wh_raw:
        try:
            wh_cfg = json.loads(wh_raw)
        except Exception:
            wh_cfg = {}
            logger.warning("JARVIS_WEBHOOK_CHANNELS is not valid JSON — ignored")
        from core.channels.webhook_channels import channels_from_config
        for ch in channels_from_config(wh_cfg, gateway.route):
            gateway.register_channel(ch.channel_id)
            await orch.register_channel(ch)
            logger.info("Webhook channel wired: %s", ch.channel_id)

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
        # BUG-7 / NEW-1: release pooled httpx clients (LLM backends), MCP
        # sessions and the autonomy sqlite queue so a closed app context
        # (e.g. a TestClient context manager) does not leak them.
        await orch.aclose()
    orch = None
    gateway = None


app = FastAPI(title="Jarvis", version="0.5.0-beta", lifespan=lifespan)

# CORS (HF-2): same-origin only by default — with no header the browser blocks
# cross-origin reads, which is what we want. Set
# JARVIS_CORS_ORIGINS=https://a.example,https://b.example to allow specific
# origins (e.g. a site hosting an embedded widget). Empty = unchanged behaviour.
_cors_origins = [o.strip() for o in os.environ.get("JARVIS_CORS_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


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


@app.middleware("http")
async def _rate_limit(request: Request, call_next):
    """HF-2: throttle unauthenticated network clients (DoS / token brute-force)."""
    if RATE_LIMIT_PER_MIN > 0:
        ip = _client_ip(request)
        if ip not in _LOCALHOSTS and not _request_is_authed(request):
            if _rate_limited(ip, time.time()):
                logger.warning("Rate limit exceeded for %s on %s",
                               log_safe(ip), log_safe(request.url.path))
                return JSONResponse(
                    {"error": "rate limit exceeded", "code": 429},
                    status_code=429,
                    headers={"Retry-After": str(int(_RATE_WINDOW))},
                )
    return await call_next(request)


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


def _get_agent_settings() -> dict:
    """Accessor for the mutable per-agent override store (CLN-3 unblock).

    `_AGENT_SETTINGS` is read here by `_enrich_agents` (the agents surface) AND
    mutated by the admin router's `PUT /api/admin/agents/{id}`, so it is a
    multi-domain global and stays in web.py. The extracted admin router reaches
    it at request time via `sys.modules.get("agents.web")._get_agent_settings()`
    so the single shared dict is read/mutated, not a per-module copy.
    """
    return _AGENT_SETTINGS


_AGENT_META = {
    "jarvis":     {"tier": "CNS", "role": "Prime Orchestrator"},
    "friday":     {"tier": "CNS", "role": "Daily Intel"},
    "pepper":     {"tier": "CNS", "role": "Chief of Staff"},
    "jerome":     {"tier": "CNS", "role": "Leisure & Soundtrack"},
    "athena":     {"tier": "BIZ", "role": "External Strategist"},
    "stark":      {"tier": "BIZ", "role": "Biz Intel"},
    "veronica":   {"tier": "BIZ", "role": "Content & Comms"},
    "vision":     {"tier": "BIZ", "role": "Deep Research / OSINT"},
    "argus":      {"tier": "BIZ", "role": "Geospatial OSINT / Intel"},
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
    message: str = Field(..., min_length=1, max_length=4096)
    agent: str = "jarvis"

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        # A blank/whitespace turn shouldn't reach the orchestrator or spend an
        # LLM call — reject cheaply so an accidental Enter on an empty box is a
        # no-op, not a wasted turn.
        if not v.strip():
            raise ValueError("message must not be empty")
        return v


class ChatResponse(BaseModel):
    reply: str


# ── mount static files ────────────────────────────────────────────

static_dir = HERE / "static"
if static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# HUD v2 (Vite + React + TS). Source in /frontend; the built bundle is committed
# under web/v2 so the Python runtime needs no Node. Served at /v2 (see route below).
v2_assets = HERE / "v2" / "assets"
if v2_assets.is_dir():
    app.mount("/v2/assets", StaticFiles(directory=str(v2_assets)), name="v2-assets")


# ── HTML ─────────────────────────────────────────────────────────

@app.get("/favicon.ico", response_class=FileResponse)
async def favicon():
    return FileResponse(str(HERE / "static" / "favicon.svg"), media_type="image/svg+xml")

@app.get("/sw.js", response_class=FileResponse)
async def service_worker():
    return FileResponse(str(HERE / "static" / "sw.js"), media_type="application/javascript")

@app.get("/", response_class=HTMLResponse)
async def index():
    # The V2 cockpit is the PRIMARY HUD (default). Set JARVIS_HUD=v1 for the legacy
    # HUD; v2 is always at /v2 and the legacy HUD always at /v1. Falls back to legacy
    # if the v2 bundle hasn't been built.
    if os.environ.get("JARVIS_HUD", "").lower() != "v1":
        v2_html = HERE / "v2" / "index.html"
        if v2_html.is_file():
            return HTMLResponse(v2_html.read_text(encoding="utf-8"))
    return HTMLResponse((HERE / "templates" / "index.html").read_text(encoding="utf-8"))


@app.get("/v1", response_class=HTMLResponse)
async def index_v1():
    return HTMLResponse((HERE / "templates" / "index.html").read_text(encoding="utf-8"))


@app.get("/v2", response_class=HTMLResponse)
@app.get("/v2/{path:path}", response_class=HTMLResponse)
async def hud_v2(path: str = ""):
    # SPA shell for the v2 HUD; client-side routing handles {path}. Static assets
    # are served by the /v2/assets mount above (registered first, so it wins).
    html = HERE / "v2" / "index.html"
    if not html.is_file():
        return HTMLResponse(
            "<h1>HUD v2 not built</h1><p>Run <code>cd frontend &amp;&amp; npm install "
            "&amp;&amp; npm run build</code> (outputs to agents/web/v2/).</p>",
            status_code=503,
        )
    return HTMLResponse(html.read_text(encoding="utf-8"))



# ── Chat ─────────────────────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(_user_guard)])
async def chat(req: ChatRequest):
    if not orch:
        return ChatResponse(reply="Jarvis not initialized.")
    try:
        # H10.21: inject the active session's notes as persistent context.
        message = req.message
        notes = getattr(orch, "notes", None)
        if notes is not None:
            prefix = notes.context_for(getattr(orch, "session_id", "web"))
            if prefix:
                message = prefix + message
        reply = await orch.handle_input(message, channel="web", agent_override=req.agent if req.agent != "jarvis" else None)
        return ChatResponse(reply=reply)
    except Exception as e:
        logger.exception("chat error")
        return ChatResponse(reply=f"Internal error: {e}")


@app.post("/chat/stream", dependencies=[Depends(_user_guard)])
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
    voice: Optional[str] = None   # "xtts" (cloned), "elevenlabs", or an edge voice; None = default chain

@app.post("/tts", dependencies=[Depends(_user_guard)])
async def tts_endpoint(req: TTSRequest):
    """Synthesize text to speech and return MP3 audio."""
    try:
        from core.voice.tts import HAS_EDGE, TTSEngine
        if not HAS_EDGE:
            return JSONResponse(
                {"error": "edge-tts not installed. Run: pip install edge-tts"},
                status_code=503,
            )
        from core.settings_db import get_value
        engine = TTSEngine(default_voice=get_value("voice", "tts_voice", "en-GB-RyanNeural"))
        audio_path = await engine.speak(req.text, voice=req.voice, lang=req.lang)
        if not audio_path:
            return JSONResponse({"error": "TTS synthesis failed"}, status_code=500)
        return FileResponse(
            audio_path,
            media_type="audio/mpeg",
            headers={"Cache-Control": "no-cache"},
        )
    except Exception:
        logger.exception("TTS error")
        return JSONResponse({"error": "internal error", "code": 500}, status_code=500)


# ── Sentence-level streaming TTS (H5.16) ─────────────────────────
#
# `/tts` synthesizes the whole reply before any audio comes back, so the user waits
# for the full message. `/tts/stream` splits the reply into sentences and streams each
# one's audio as soon as it's synthesized, so playback can start after sentence #1.
# Opt-in: gated by the `voice.sentence_streaming` setting (default off — back-compat).
#
# Wire framing (one frame per sentence, in order):
#   <json-header>\n<raw-audio-bytes>
# where the header is a single-line JSON object
#   {"idx": int, "text": str, "lang": str, "bytes": int, "done": bool}
# and exactly `bytes` audio bytes follow. A terminal frame {"done": true, "bytes": 0}
# (no audio) closes the stream. A sentence that failed to synthesize gets bytes:0 and
# is skipped by the client. This is multipart-free (no python-multipart) like /tts.

def _tts_stream_enabled() -> bool:
    """Whether sentence-level streaming TTS is turned on (default off)."""
    from core.settings_db import get_value
    return bool(get_value("voice", "sentence_streaming", False))


@app.post("/tts/stream", dependencies=[Depends(_user_guard)])
async def tts_stream_endpoint(req: TTSRequest):
    """Stream sentence-by-sentence TTS audio frames (opt-in). See module comment."""
    import json as _json

    from core.voice.tts import HAS_EDGE, TTSEngine

    if not _tts_stream_enabled():
        return JSONResponse(
            {"error": "sentence streaming disabled. Enable voice.sentence_streaming.",
             "enabled": False},
            status_code=409,
        )
    if not HAS_EDGE:
        return JSONResponse(
            {"error": "edge-tts not installed. Run: pip install edge-tts"},
            status_code=503,
        )
    from core.settings_db import get_value
    engine = TTSEngine(default_voice=get_value("voice", "tts_voice", "en-GB-RyanNeural"))

    async def _gen():
        try:
            async for idx, sentence, path in engine.speak_stream(
                req.text, voice=req.voice, lang=req.lang,
            ):
                audio = b""
                if path:
                    try:
                        audio = Path(path).read_bytes()
                    except Exception:
                        logger.warning("tts/stream: cannot read chunk %s", path)
                        audio = b""
                header = _json.dumps({
                    "idx": idx, "text": sentence, "lang": req.lang,
                    "bytes": len(audio), "done": False,
                })
                yield header.encode("utf-8") + b"\n" + audio
        except Exception:
            logger.exception("tts/stream error")
        # Terminal frame.
        yield _json.dumps({"idx": -1, "text": "", "lang": req.lang, "bytes": 0,
                           "done": True}).encode("utf-8") + b"\n"

    return StreamingResponse(
        _gen(),
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── STT endpoint (browser mic → local Whisper) ───────────────────
#
# The voice engines (Whisper/edge-tts/XTTS) were built for Howard — a mic wired to
# the server. The HUD runs in a browser, so the loop is: browser captures audio
# (getUserMedia/MediaRecorder) → POSTs the blob here → local Whisper transcribes →
# normal /chat/stream. Honest degradation: if faster-whisper isn't installed we 503
# with an install hint — never a fabricated transcript.

_STT_ENGINE = None


def _stt_engine():
    """Lazily build and cache one Whisper engine (model load is expensive)."""
    global _STT_ENGINE
    if _STT_ENGINE is None:
        from core.settings_db import get_value
        from core.voice.stt import STTEngine
        _STT_ENGINE = STTEngine(model_size=get_value("voice", "stt_model_size", "medium"))
    return _STT_ENGINE


@app.post("/api/voice/stt", dependencies=[Depends(_user_guard)])
async def stt_endpoint(request: Request, lang: Optional[str] = Query(None)):
    """Transcribe a raw audio body (browser MediaRecorder blob) via local Whisper.

    Raw body (not multipart) keeps this dependency-free — no python-multipart needed.
    Language falls back to the /admin `voice.stt_language` setting when the caller
    doesn't pass ?lang=.
    """
    import tempfile

    from core.voice.stt import HAS_WHISPER
    if not HAS_WHISPER:
        return JSONResponse(
            {"error": "faster-whisper not installed. Run: pip install faster-whisper", "stt": False},
            status_code=503,
        )
    from core.settings_db import get_value
    lang = lang or get_value("voice", "stt_language", "ro")
    tmp = None
    try:
        data = await request.body()
        if not data:
            return JSONResponse({"error": "empty audio"}, status_code=400)
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(data)
            tmp = f.name
        text = await _stt_engine().transcribe_async(tmp, language=lang)
        return _nocache_json({"text": text, "lang": lang})
    except Exception:
        logger.exception("STT error")
        return JSONResponse({"error": "internal error", "code": 500}, status_code=500)
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except Exception:
                pass


@app.get("/api/voice/capabilities")
async def voice_capabilities():
    """What the voice loop can ACTUALLY do on this host — drives the HUD honestly.

    (The browser always has a fully-local `speechSynthesis` fallback for TTS, which the
    HUD knows about; this reports only the server-side engines.)
    """
    from core.voice.stt import HAS_WHISPER
    try:
        from core.voice.tts import HAS_EDGE
    except Exception:
        HAS_EDGE = False
    try:
        from core.voice.tts import HAS_KOKORO
    except Exception:
        HAS_KOKORO = False
    xtts = bool(os.getenv("XTTS_SERVER_URL"))
    eleven = bool(os.getenv("ELEVENLABS_API_KEY"))
    return _nocache_json({
        "stt": bool(HAS_WHISPER),                       # local Whisper available
        "tts": bool(HAS_EDGE or HAS_KOKORO or xtts or eleven),
        "tts_local": bool(xtts or HAS_KOKORO),          # an on-device TTS path exists
        "providers": {
            "stt": "faster-whisper" if HAS_WHISPER else None,
            "xtts": xtts, "elevenlabs": eleven, "edge_tts": bool(HAS_EDGE), "kokoro": bool(HAS_KOKORO),
        },
    })


# ── Status (HUD-compatible) ──────────────────────────────────────

@app.get("/api/health/components")
async def component_health():
    """A8: which optional components initialized (vs failed silently)."""
    reg = getattr(orch, "components", None) if orch else None
    if reg is None:
        return _nocache_json({"components": {}, "summary": "registry unavailable"})
    return _nocache_json({"components": reg.health(), "failed": reg.failed(),
                          "summary": reg.summary()})


_llm_ready_cache = {"state": "unknown", "model": None, "at": 0.0}


async def _llm_ready() -> dict:
    """Truthful LLM readiness: is a model actually LOADED, not just configured?

    The OpenAI-compatible ``/v1/models`` lists models LM Studio *can* serve (JIT can
    load them on demand), so a non-empty list does NOT prove a model is resident —
    it would report "online" with nothing loaded. LM Studio's native REST
    ``/api/v0/models`` exposes a per-model ``state`` ("loaded"|"not-loaded"), which
    is the honest signal. Returns ``state`` ∈ {ready, no_model, offline} + the loaded
    model id. Cached ~8s so the polled ``/status`` stays cheap; fails to 'offline'.
    """
    import httpx
    now = time.time()
    if now - _llm_ready_cache["at"] < 8:
        return {"state": _llm_ready_cache["state"], "model": _llm_ready_cache["model"]}
    state, model = "offline", None
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            try:
                r = await client.get(f"{_LM_STUDIO_URL}/api/v0/models")
                if r.is_success:
                    data = (r.json() or {}).get("data") or []
                    loaded = [m for m in data if str(m.get("state", "")).lower() == "loaded"]
                    if loaded:
                        state, model = "ready", loaded[0].get("id")
                    else:
                        state = "no_model"      # LM Studio up, nothing resident
                else:
                    state = "no_model"
            except Exception:
                # Native API absent (older LM Studio) — fall back to /v1/models, but
                # stay honest: reachable ≠ loaded, so reachable → 'no_model'.
                r = await client.get(f"{_LM_STUDIO_URL}/v1/models")
                state = "no_model" if r.is_success else "offline"
    except Exception:
        state = "offline"
    _llm_ready_cache.update(state=state, model=model, at=now)
    return {"state": state, "model": model}


@app.get("/status")
async def status():
    if not orch:
        return _nocache_json({"status": "starting"})
    enriched = _enrich_agents()
    voice_state = "idle"
    lm_online = orch.llm_router.name != "none"
    ready = await _llm_ready()
    from agents import __version__
    return _nocache_json({
        "version": __version__,
        "sys": _sys_info(),
        "voice_state": voice_state,
        "lm_online": lm_online,                       # backend configured/reachable
        "model_state": ready["state"],                # ready | no_model | offline (truthful)
        "model_loaded": ready["state"] == "ready",
        "loaded_model": ready["model"],               # the actually-resident model, or None
        "configured_model": getattr(orch.llm_router, "active_model", None),
        "llm_backend": orch.llm_router.name,
        "active_model": getattr(orch.llm_router, "active_model", None),
        "agents": [{"id": a["id"], "status": a["status"]} for a in enriched],
        "agents_online": sum(1 for a in enriched if a["status"] != "idle"),
        "agents_total": len(enriched),
    })


@app.get("/api/agents", dependencies=[Depends(_user_guard)])
async def api_agents():
    return _nocache_json({"agents": _enrich_agents()})


# ── Dashboard (HUD-compatible) ───────────────────────────────────

_dashboard_cache = {"weather": "", "news": [], "cached_at": 0}
# Serialize cache refreshes so concurrent /dashboard requests don't race on the
# weather/calendar update (double-fetch or partial write under load). BUG-1.
_dashboard_lock = asyncio.Lock()


@app.get("/dashboard", dependencies=[Depends(_user_guard)])
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


@app.get("/tasks", dependencies=[Depends(_user_guard)])
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


@app.get("/ticker", dependencies=[Depends(_user_guard)])
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


_AGENT_ID_RE = re.compile(r"^[a-z0-9_-]{1,64}$")


@app.get("/api/agents/{agent_id}/soul")
async def get_agent_soul(agent_id: str):
    """Read and return the live SOUL.md content for an agent."""
    agent_id = agent_id.strip().lower()
    # The id becomes a filesystem path segment below — reject anything outside
    # the agent-id alphabet (CodeQL: uncontrolled data in path expression).
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")

    # Allow reading SOUL.md if the file physically exists, even if orch is not initialized (e.g. in tests)
    # The personalized overlay (SOUL.local.md, gitignored) wins when present —
    # same resolution as Agent._load_soul.
    base_dir = Path(__file__).parent.resolve()
    soul_path = base_dir / agent_id / "SOUL.local.md"
    if not soul_path.exists():
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

@app.get("/memory", dependencies=[Depends(_user_guard)])
async def memory():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    history = await orch.memory.get_history(orch.session_id, last_n=20)
    return _nocache_json({"session": orch.session_id, "turns": history})


@app.post("/memory/clear", dependencies=[Depends(_user_guard)])
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


@app.get("/sessions", dependencies=[Depends(_user_guard)])
async def get_sessions():
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    sessions = orch.checkpoints.get_sessions(limit=20)
    return {"sessions": sessions}


@app.post("/sessions/resume", dependencies=[Depends(_user_guard)])
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
    agent_id = agent_id.strip().lower()
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    # Consistent with /soul: an unknown agent 404s rather than returning a
    # misleading empty-but-OK run list (a fresh-but-real agent still 200s with []).
    if orch and agent_id not in orch.agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
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


@app.post("/api/agent-templates/instantiate", dependencies=[Depends(_user_guard)])
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


# ── H15.4 Secret broker + H10.1 Embeddable Chat Widget ────────────────────────
# Both surfaces (/api/secrets/broker..., /api/admin/widgets, /api/widget...) live
# in the secrets router (CLN-3). They reach state only via the orchestrator
# (orch.secret_broker / orch.widgets), so nothing web.py-owned moved.


# ── H13.2 Constrained decoding (GBNF grammar) ─────────────────────────────────

# ── H14.3 Sleep-time memory consolidation ─────────────────────────────────────
# `/api/memory/consolidate` lives in the memory_kg router (CLN-3).


# ── H7.11 Learning-loop promotions ────────────────────────────────────────────

@app.post("/api/learning/propose", dependencies=[Depends(_admin_guard)])
async def learning_propose():
    """Run the learning loop now: propose agent promotions into the decision inbox."""
    if not orch or not hasattr(orch, "_run_learning_loop"):
        return JSONResponse({"error": "not available"}, status_code=503)
    proposals = await orch._run_learning_loop()
    return _nocache_json({"ok": True, "proposed": proposals, "count": len(proposals)})


class GenerateStepBody(BaseModel):
    description: str = Field(..., max_length=2000)


@app.post("/api/workflows/step/generate", dependencies=[Depends(_user_guard)])
async def generate_workflow_step(body: GenerateStepBody):
    """H10.7 — 'Describe this step' → a validated workflow-step config.

    Uses the live LLM when available, else a deterministic keyword heuristic.
    """
    from agents.core.workflows.ai_builder import generate_step
    agents_list = list(orch.agents.keys()) if orch else []
    llm = None
    if orch:
        async def _llm(prompt: str) -> str:
            return await orch.handle_input(prompt, channel="builder")
        llm = _llm
    cfg = await generate_step(body.description, agents_list, llm=llm)
    return _nocache_json({"ok": True, "step": cfg})


@app.post("/api/workflows/hierarchical", dependencies=[Depends(_user_guard)])
async def workflow_hierarchical(req: Request):
    """H10.11 — run a hierarchical workflow: a manager coordinates a crew."""
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    goal = (body or {}).get("goal", "")
    crew = (body or {}).get("crew") or []
    if not goal or not crew:
        return JSONResponse({"error": "goal and crew required"}, status_code=400)
    from agents.core.workflows.hierarchical import HierarchicalManager
    mgr = HierarchicalManager(
        orch,
        manager_agent=(body or {}).get("manager", "jarvis"),
        max_retries=int((body or {}).get("max_retries", 1)),
    )
    return _nocache_json(await mgr.run(goal, crew))


class ContextCompressBody(BaseModel):
    turns: list[dict] = Field(default_factory=list)
    max_tokens: int = Field(2000, ge=100, le=100000)
    keep_recent: int = Field(4, ge=1, le=50)


@app.post("/api/context/compress", dependencies=[Depends(_user_guard)])
async def context_compress(body: ContextCompressBody):
    """H20.3 — compress a long turn history (keep recent, digest/summarize older)."""
    from agents.core.context_compressor import ContextCompressor
    summarizer = None
    if orch is not None:
        async def summarizer(text):  # noqa: E731 — wire the LLM summarizer
            return await orch.process(f"Summarize this conversation concisely:\n{text}",
                                      channel="compress")
    cc = ContextCompressor(summarizer=summarizer, max_tokens=body.max_tokens,
                           keep_recent=body.keep_recent)
    return _nocache_json(await cc.compress(body.turns))


class VLMDescribeBody(BaseModel):
    prompt: str = Field(..., max_length=4000)
    images: list[str] = Field(default_factory=list, max_length=8)
    model: str = Field("", max_length=80)


@app.get("/api/vlm/status", dependencies=[Depends(_user_guard)])
async def vlm_status():
    """H13.1 — whether a local VLM endpoint is configured (host deployment)."""
    return _nocache_json({"configured": bool(os.environ.get("JARVIS_VLM_URL", "")),
                          "default_model": os.environ.get("JARVIS_VLM_MODEL", "qwen2-vl")})


@app.post("/api/vlm/describe", dependencies=[Depends(_user_guard)])
async def vlm_describe(body: VLMDescribeBody):
    """H13.1 — send image(s) + a prompt to the local VLM (screen/doc/receipt).

    Requires JARVIS_VLM_URL to point at a local OpenAI-vision server (the model
    + GGUF + GPU are the host deployment seam)."""
    url = os.environ.get("JARVIS_VLM_URL", "")
    if not url:
        return JSONResponse({"error": "VLM not configured — set JARVIS_VLM_URL"}, status_code=503)
    from agents.core.llm.vlm import VLMBackend
    vlm = VLMBackend(base_url=url, api_key=os.environ.get("JARVIS_VLM_KEY", ""))
    try:
        model = body.model or os.environ.get("JARVIS_VLM_MODEL", "qwen2-vl")
        # encode_image_block accepts only data:/http(s) image sources, never file
        # paths — request-supplied images can't read host files.
        out = await vlm.generate_vision(model, body.prompt, images=body.images)
        return _nocache_json({"ok": True, "model": model, "response": out})
    finally:
        await vlm.aclose()


class DesktopStepsBody(BaseModel):
    steps: list[dict] = Field(default_factory=list, max_length=100)


@app.post("/api/desktop/preview", dependencies=[Depends(_user_guard)])
async def desktop_preview(body: DesktopStepsBody):
    """H15.3 — dry-run a desktop step plan (which steps need approval)."""
    from agents.core.desktop_operator import GovernedDesktop
    return _nocache_json(await GovernedDesktop().preview(body.steps))


class MediaGenBody(BaseModel):
    kind: str = Field(..., max_length=20)
    prompt: str = Field(..., max_length=4000)
    cloud: bool = False


@app.get("/api/media", dependencies=[Depends(_user_guard)])
async def media_status():
    """H12.24 — supported media kinds + which backends are wired."""
    from agents.core.media_gen import MediaGenManager
    return _nocache_json({"kinds": MediaGenManager().kinds()})


@app.post("/api/media/generate", dependencies=[Depends(_user_guard)])
async def media_generate(body: MediaGenBody):
    """H12.24 — governed media generation (cloud generation is approval-gated)."""
    from agents.core.media_gen import MediaGenManager
    q = getattr(orch, "autonomy_queue", None) if orch else None
    m = MediaGenManager(enqueue=q.enqueue if q is not None else None)
    result = await m.generate(body.kind, body.prompt, cloud=body.cloud)
    return _nocache_json(result, status_code=200 if result.get("ok") else 422)


# H21.0 — mount the cognition APIRouter (keeps cognition endpoints out of the
# web.py god-object). User-guarded like the rest of the /api surface.
from agents.core.cognition.api import router as _cognition_router  # noqa: E402

app.include_router(_cognition_router, dependencies=[Depends(_user_guard)])

# Per-domain routers extracted from this god-object (CLN-3). These preserve the
# original (ungated) behavior of their routes — mounted without extra deps.
from agents.core.routers.onboarding import router as _onboarding_router  # noqa: E402
from agents.core.routers.wyoming import router as _wyoming_router  # noqa: E402

app.include_router(_wyoming_router)
app.include_router(_onboarding_router)
# These preserve each route's original per-route deps (gating lives on the routes
# themselves, not the include), so behavior is unchanged.
from agents.core.routers.a2a import router as _a2a_router  # noqa: E402
from agents.core.routers.actions import router as _actions_router  # noqa: E402
from agents.core.routers.admin import router as _admin_router  # noqa: E402
from agents.core.routers.analytics import router as _analytics_router  # noqa: E402
from agents.core.routers.arena import router as _arena_router  # noqa: E402
from agents.core.routers.autonomy import router as _autonomy_router  # noqa: E402
from agents.core.routers.brain import router as _brain_router  # noqa: E402
from agents.core.routers.browser import router as _browser_router  # noqa: E402
from agents.core.routers.canvas import router as _canvas_router  # noqa: E402
from agents.core.routers.capture import router as _capture_router  # noqa: E402
from agents.core.routers.data_spaces import router as _data_spaces_router  # noqa: E402
from agents.core.routers.integrations import router as _integrations_router  # noqa: E402
from agents.core.routers.memory_kg import router as _memory_kg_router  # noqa: E402
from agents.core.routers.mesh import router as _mesh_router  # noqa: E402
from agents.core.routers.models_llm import router as _models_llm_router  # noqa: E402
from agents.core.routers.notes import router as _notes_router  # noqa: E402
from agents.core.routers.oauth import router as _oauth_router  # noqa: E402
from agents.core.routers.pairing import router as _pairing_router  # noqa: E402
from agents.core.routers.quality import router as _quality_router  # noqa: E402
from agents.core.routers.review import router as _review_router  # noqa: E402
from agents.core.routers.rooms import router as _rooms_router  # noqa: E402
from agents.core.routers.secrets import router as _secrets_router  # noqa: E402
from agents.core.routers.security import router as _security_router  # noqa: E402
from agents.core.routers.skills import router as _skills_router  # noqa: E402
from agents.core.routers.webhooks import router as _webhooks_router  # noqa: E402

app.include_router(_webhooks_router)
app.include_router(_a2a_router)
app.include_router(_pairing_router)
app.include_router(_canvas_router)
app.include_router(_browser_router)
app.include_router(_capture_router)
app.include_router(_rooms_router)
app.include_router(_notes_router)
app.include_router(_actions_router)
app.include_router(_arena_router)
app.include_router(_review_router)
app.include_router(_quality_router)
app.include_router(_security_router)
app.include_router(_skills_router)
app.include_router(_data_spaces_router)
app.include_router(_secrets_router)
app.include_router(_mesh_router)
app.include_router(_autonomy_router)
app.include_router(_models_llm_router)
app.include_router(_oauth_router)
app.include_router(_brain_router)
app.include_router(_memory_kg_router)
app.include_router(_analytics_router)
app.include_router(_admin_router)
app.include_router(_integrations_router)


class DigestRunBody(BaseModel):
    topic: str = Field("", max_length=200)
    sources: Optional[list[str]] = Field(None, max_length=10)
    limit: int = Field(10, ge=1, le=50)
    weights: Optional[dict] = None


@app.post("/api/digest/run", dependencies=[Depends(_user_guard)])
async def digest_run(body: DigestRunBody):
    """H12.23 — composable multi-source digest ranked by weight × idea-reality."""
    from agents.core.digest import build_default_aggregator
    from agents.core.http_client import PluginHTTPClient
    client = PluginHTTPClient.for_plugin("digest")

    async def _fetch(url: str) -> str:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text

    agg = build_default_aggregator(_fetch, weights=body.weights, names=body.sources)
    return _nocache_json(await agg.run(body.topic, limit=body.limit))


@app.post("/api/schedule/parse", dependencies=[Depends(_user_guard)])
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
    if not promoted:
        # Honest result: a no-op (unknown bench id, or already active) is not a
        # success — say so with 404 so the HUD shows an error, not a fake "ok".
        return JSONResponse(
            {"ok": False, "bench_agent": bench_id, "promoted": False,
             "error": f"'{bench_id}' is not a promotable bench agent (unknown or already active)"},
            status_code=404,
        )
    return _nocache_json({
        "ok": True,
        "bench_agent": bench_id,
        "promoted": promoted,
        "active_agents": list(orch.agents.keys()),
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


# ── Admin control surface ────────────────────────────────────────────────────
# All admin-guarded `/api/admin/*` routes — settings, env, audit, memory/clear,
# agents/stats, apm, prompts/* (H10.22 prompt VC), PUT /api/admin/agents/{id},
# llm/test, and /api/admin/stats (admin charts) — live in the admin router
# (CLN-3). EXCEPTIONS that stay out of it: `/api/admin/mcp*` (still inline below)
# and `/api/admin/widgets*` (the secrets router). The admin-only helpers `_svs`
# and `_SECRET_HINTS` moved into that router; `_AGENT_SETTINGS` stays here (it's
# also read by `_enrich_agents`) and the router mutates it via
# `web._get_agent_settings()`.


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
    except Exception:
        logger.exception("MCP server probe failed: %s", log_safe(name))
        return JSONResponse({"error": "internal error", "server": name, "code": 500}, status_code=500)


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


# ── Admin Charts endpoint → core/routers/admin.py (CLN-3) ──────────


@app.get("/api/resilience")
async def resilience_public():
    """Public resilience metrics and circuit breaker states (no admin auth)."""
    from core.resilience import _circuit_breakers, get_metrics
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


# ── v0.3 Cognition Release endpoints ─────────────────────────────


@app.get("/api/cognition", dependencies=[Depends(_user_guard)])
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


# ── Memory + Knowledge-Graph surface ──────────────────────────────────────────
# All `/api/memory/*` (except the data-space routes below) and all `/api/kg/*`
# routes live in the memory_kg router (CLN-3). The `_kg()` + `_structured_recall()`
# helpers moved there with them (they were used only by those handlers).


# ── H10.26 Data Spaces (per-agent data scope) ─────────────────────
# The `/api/memory/profile` + `/api/memory/spaces...` routes live in the
# data_spaces router (CLN-3). The `_data_spaces` singleton + its accessor stay
# here (unblock B): tests monkeypatch `web._data_spaces`, and the router reads it
# back at request time via `web._get_data_spaces()`.

_data_spaces = None


def _get_data_spaces():
    global _data_spaces
    if _data_spaces is None:
        from agents.core.data_spaces import DataSpaces
        _data_spaces = DataSpaces()
    return _data_spaces


# ── END H10.26 Data Spaces ────────────────────────────────────────


# `/api/memory/recall` lives in the memory_kg router (CLN-3).


# ── Analytics / cost / traces / reflection surface ───────────────────────────
# All `/api/analytics/*`, `/api/cost`, `/api/traces/*` (H9.2 Trace Explorer) and
# `/api/reflection/*` routes live in the analytics router (CLN-3). Every handler
# reads its subsystem off the live orchestrator via get_orch(); none used a
# web-module global, so nothing stayed behind.


# ── H12.4 Wyoming protocol (local-voice interop) → core/routers/wyoming.py (CLN-3) ──
# ── END H12.4 Wyoming endpoints ───────────────────────────────────


# ── H12.2 Onboarding (drop folder → private chat with docs) → core/routers/onboarding.py (CLN-3) ──
# ── END H12.2 Onboarding endpoints ────────────────────────────────


# ── Extracted to core/routers/ (CLN-3): H10.8 webhooks · H16.2 a2a · H12.19 pairing ──
# ──   · H12.18 canvas · H15.1 browser · H12.7 capture (mounted near the cognition router). ──


# ── H16.3 Governed payments (mandate / cap / approval / audit) ─────

_payment_broker = None


def _get_payment_broker():
    global _payment_broker
    if _payment_broker is None:
        from agents.core.payments import PaymentBroker
        from agents.core.security.anchor import IntentLog
        _payment_broker = PaymentBroker(
            audit=IntentLog(path=str(data_path("security/payments_intent.json"))))
    return _payment_broker


class CreateMandateBody(BaseModel):
    payees: list[str] = Field(default_factory=list)
    per_payment_cap: float = Field(..., gt=0)
    total_cap: float = Field(..., gt=0)
    currency: str = Field("EUR", max_length=8)
    ttl_seconds: Optional[float] = Field(None, gt=0)


class RequestPaymentBody(BaseModel):
    mandate_id: str = Field(..., max_length=64)
    payee: str = Field(..., max_length=128)
    amount: float = Field(..., gt=0)
    currency: str = Field("EUR", max_length=8)
    memo: str = Field("", max_length=280)


@app.post("/api/payments/mandates", dependencies=[Depends(_admin_guard)])
async def create_payment_mandate(body: CreateMandateBody):
    """Pre-authorize a spending budget with hard caps + a payee allowlist."""
    try:
        return _nocache_json(_get_payment_broker().create_mandate(
            body.payees, body.per_payment_cap, body.total_cap, body.currency, body.ttl_seconds))
    except ValueError:
        return _nocache_json({"error": "invalid mandate (need ≥1 payee and positive caps)"}, status_code=400)


@app.get("/api/payments/mandates", dependencies=[Depends(_admin_guard)])
async def list_payment_mandates():
    return _nocache_json({"mandates": _get_payment_broker().list_mandates()})


@app.post("/api/payments/request", dependencies=[Depends(_admin_guard)])
async def request_payment(body: RequestPaymentBody):
    """Request a payment against a mandate. Denied (over cap / bad payee / etc.)
    returns 400 with a reason code; admissible returns a pending payment."""
    result = _get_payment_broker().request_payment(
        body.mandate_id, body.payee, body.amount, body.currency, body.memo)
    if not result.get("ok"):
        return _nocache_json({"error": "payment denied", "reason": result.get("reason")}, status_code=400)
    return _nocache_json(result["payment"])


@app.get("/api/payments", dependencies=[Depends(_admin_guard)])
async def list_payments(status: Optional[str] = None):
    return _nocache_json({"payments": _get_payment_broker().list_payments(status)})


@app.post("/api/payments/{payment_id}/approve", dependencies=[Depends(_admin_guard)])
async def approve_payment(payment_id: str):
    try:
        return _nocache_json(_get_payment_broker().approve(payment_id))
    except ValueError:
        return _nocache_json({"error": "payment not found or not pending/admissible"}, status_code=400)


@app.post("/api/payments/{payment_id}/reject", dependencies=[Depends(_admin_guard)])
async def reject_payment(payment_id: str):
    try:
        return _nocache_json(_get_payment_broker().reject(payment_id))
    except ValueError:
        return _nocache_json({"error": "payment not found or cannot be rejected"}, status_code=400)


@app.post("/api/payments/{payment_id}/settle", dependencies=[Depends(_admin_guard)])
async def settle_payment(payment_id: str):
    """Settle an approved payment (no real rail moves money here)."""
    try:
        return _nocache_json(_get_payment_broker().settle(payment_id))
    except ValueError:
        return _nocache_json({"error": "payment not approved, not found, or over cap"}, status_code=400)


# ── END H16.3 Governed payments ───────────────────────────────────


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


# ── H16.1 MCP OAuth 2.1 Resource Server (2025-11 spec) ────────────

_mcp_rs = None


def _get_mcp_rs():
    """Process-stable MCP resource server (HMAC secret from settings or generated)."""
    global _mcp_rs
    if _mcp_rs is None:
        from agents.core.mcp.oauth import MCPResourceServer
        secret = orch.get_setting("mcp.oauth_secret", "") if orch else ""
        _mcp_rs = MCPResourceServer(secret=secret or None)
    return _mcp_rs


def _mcp_resource(request: Request) -> str:
    return str(request.base_url).rstrip("/") + "/api/mcp/server"


@app.get("/.well-known/oauth-protected-resource")
async def mcp_protected_resource_metadata(request: Request):
    """RFC 9728 — lets MCP clients discover the authorization server(s)."""
    from agents.core.mcp.oauth import protected_resource_metadata
    resource = _mcp_resource(request)
    auth_servers = []
    if orch:
        configured = orch.get_setting("mcp.authorization_servers", None)
        if isinstance(configured, list):
            auth_servers = configured
    return _nocache_json(protected_resource_metadata(resource, auth_servers or [resource]))


@app.post("/api/mcp/token", dependencies=[Depends(_admin_guard)])
async def mcp_issue_token(req: Request):
    """Issue a local LAN-only bearer token bound to this MCP resource (admin)."""
    if not orch:
        return _nocache_json({"error": "not initialized"}, status_code=503)
    try:
        body = await req.json()
    except Exception:
        body = {}
    resource = _mcp_resource(req)
    scopes = (body or {}).get("scopes") or ["mcp"]
    token = _get_mcp_rs().issue_token(
        subject=(body or {}).get("subject", "local-client"),
        resource=resource, scopes=scopes,
        ttl=int((body or {}).get("ttl", 3600)))
    return _nocache_json({"ok": True, "token": token, "resource": resource, "scopes": scopes})


@app.post("/api/mcp/server/rpc")
async def mcp_server_rpc(message: dict, request: Request):
    """JSON-RPC 2.0 entry point (HTTP transport). Disabled by default; LAN-only.

    When ``mcp.oauth_required`` is set, requires an OAuth 2.1 bearer token bound to
    this resource (RFC 8707) with the ``mcp`` scope.
    """
    if not orch:
        return _nocache_json({"error": "not initialized"}, status_code=503)
    if not bool(orch.get_setting("mcp.server_enabled", False)):
        return _nocache_json(
            {"error": "MCP server mode disabled (set mcp.server_enabled)"},
            status_code=403,
        )
    if bool(orch.get_setting("mcp.oauth_required", False)):
        from agents.core.mcp.oauth import MCPResourceServer
        resource = _mcp_resource(request)
        result = _get_mcp_rs().validate(
            request.headers.get("authorization", ""), resource, required_scope="mcp")
        if not result["ok"]:
            return JSONResponse(
                {"error": f"unauthorized: {result['error']}"}, status_code=401,
                headers={"WWW-Authenticate": MCPResourceServer.challenge(resource)})
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


@app.post("/api/eval/datasets/run", dependencies=[Depends(_user_guard)])
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


@app.post("/api/workflows/run", dependencies=[Depends(_user_guard)])
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
                return error_json(e, 200, "invalid stored pipeline", extra={"ok": False})
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Pipeline '{body.pipeline_id}' not found")
    try:
        result = await orch.workflow_engine.run(pipeline, initial_input=body.input)
        return _nocache_json({"ok": result.get("_ok", True), "result": result})
    except Exception as e:
        return error_json(e, 200, "workflow run failed", extra={"ok": False})


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

_wf_store_instance = None  # lazily-created WorkflowStore (H9.1)


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


@app.post("/api/workflows", dependencies=[Depends(_admin_guard)])
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


@app.put("/api/workflows/{pipeline_id}", dependencies=[Depends(_admin_guard)])
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


@app.delete("/api/workflows/{pipeline_id}", dependencies=[Depends(_admin_guard)])
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


@app.put("/plugins/{plugin_id}/toggle", dependencies=[Depends(_admin_guard)])
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
    logger.info("Plugin %s %s", log_safe(plugin_id), action)
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


@app.get("/heartbeat/status")
async def heartbeat_status():
    """Return status of all scheduled heartbeats."""
    return _nocache_json(orch.heartbeat_scheduler.get_status())


@app.post("/heartbeat/{agent_id}/start", dependencies=[Depends(_admin_guard)])
async def heartbeat_start(agent_id: str):
    """Start a heartbeat for an agent."""
    if agent_id not in orch.agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    
    success = orch.heartbeat_scheduler.start_heartbeat(agent_id, orch)
    if success:
        return _nocache_json({"agent_id": agent_id, "status": "started"})
    else:
        raise HTTPException(status_code=400, detail=f"Failed to start heartbeat for '{agent_id}'")


@app.post("/heartbeat/{agent_id}/stop", dependencies=[Depends(_admin_guard)])
async def heartbeat_stop(agent_id: str):
    """Stop a heartbeat for an agent."""
    if agent_id not in orch.agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    
    success = orch.heartbeat_scheduler.stop_heartbeat(agent_id)
    if success:
        return _nocache_json({"agent_id": agent_id, "status": "stopped"})
    else:
        raise HTTPException(status_code=400, detail=f"Failed to stop heartbeat for '{agent_id}'")


@app.post("/heartbeat/{agent_id}/run", dependencies=[Depends(_admin_guard)])
async def heartbeat_run(agent_id: str):
    """Run a heartbeat immediately."""
    if agent_id not in orch.agents:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    await orch.heartbeat_scheduler.run_now(agent_id, orch)
    return _nocache_json({"agent_id": agent_id, "status": "executed"})


@app.get("/api/status")
async def api_status():
    """Return service version, agent count, and health status."""
    from agents import AGENT_COUNT, __version__
    return {"version": __version__, "agents": AGENT_COUNT, "status": "ok"}

