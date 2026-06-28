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
# AUD-6 (full-replace posture): the managed token store is the authoritative
# credential system; the static JARVIS_ADMIN_TOKEN is only the *bootstrap*.
#   - JARVIS_ADMIN_TOKEN, if set, is accepted (constant-time) — UNTIL a rotation
#     through the store supersedes it, after which it is revoked for good
#     (TokenStore.env_revoked), so adopting a managed token truly replaces it.
#   - Issued tokens (TTL / rotation / hash-at-rest) are first-class admin creds.
#   - With no admin credential configured at all, a direct-localhost origin is
#     trusted (dev posture); a Pi/LAN deployment is locked down.
#   - Lost every token? The offline CLI `python -m agents.core.security.token_store
#     rotate admin` mints a fresh one from the machine itself — no HTTP, no lockout.
ADMIN_TOKEN = os.environ.get("JARVIS_ADMIN_TOKEN", "").strip()
_LOCALHOSTS = {"127.0.0.1", "::1", "localhost"}

# token_store is a leaf module (imports only agents.core.paths), so there is no
# import edge back into web.
from agents.core.security.token_store import get_token_store


def _env_admin_active() -> bool:
    """True when the static admin env token is set AND not yet superseded by a
    rotation (AUD-6). Once rotated, the env token is dead even if still exported."""
    return bool(ADMIN_TOKEN) and not get_token_store().env_revoked("admin")


def _admin_configured() -> bool:
    """True when some admin credential exists: an un-revoked env token, or at
    least one issued admin token in the store. Drives the localhost-fallback gate."""
    return _env_admin_active() or get_token_store().has_scope("admin")

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

def _admin_credential_ok(supplied: str) -> bool:
    """True if *supplied* is a valid admin credential (AUD-6): a valid, unexpired
    issued admin token in the store, OR the static env token while it is still
    active (set and not yet superseded by a rotation — see _env_admin_active)."""
    if not supplied:
        return False
    if get_token_store().verify(supplied) == "admin":
        return True
    return _env_admin_active() and secrets.compare_digest(supplied, ADMIN_TOKEN)


async def _admin_guard(request: Request):
    """Authorize an /api/admin/* request or raise 401/403."""
    if _admin_credential_ok(request.headers.get("x-admin-token", "")):
        return
    # No admin credential configured at all → dev posture: trust a direct-localhost
    # origin (so a fresh box can mint its first token), reject the network. Behind
    # an untrusted reverse proxy _real_client_host returns "" → fails closed
    # (HF-7); JARVIS_TRUSTED_PROXY=1 trusts X-Forwarded-For from a known proxy.
    if not _admin_configured():
        if _real_client_host(request) in _LOCALHOSTS:
            return
        raise HTTPException(
            status_code=403,
            detail="admin disabled from network — set JARVIS_ADMIN_TOKEN to enable remote access",
        )
    # A credential is configured but none/invalid was supplied. Recovery if every
    # token is lost: the offline `token_store` CLI on the box.
    raise HTTPException(status_code=401, detail="admin token required")


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


def _env_user_active() -> bool:
    """True when the static user env token is set AND not superseded by a rotation
    (AUD-6) — the user-tier analog of _env_admin_active."""
    return bool(USER_TOKEN) and not get_token_store().env_revoked("user")


def _user_token_required() -> bool:
    """True when a user credential exists (network posture).

    AUD-6: True when the static user env token is active OR a user token has been
    issued into the store. When False the hub is in the localhost-only dev
    posture: the HTTP guard trusts a localhost origin and requires no token (see
    ``_user_guard``). Single source of truth reused by the MCP mutating-tool
    identity gate so it matches the guard exactly."""
    return _env_user_active() or get_token_store().has_scope("user")


def _user_credential_ok(user_supplied: str = "", admin_supplied: str = "") -> bool:
    """Validate a presented user credential the SAME way ``_user_guard`` does.

    Request-free core of the user identity check, so a non-HTTP caller (the MCP
    in-process mutating-tool path, which has no ``Request``) can enforce the
    identical rule instead of forking it:

      * a valid user-scope token in the managed store, OR
      * a user token matching the active static env token, OR
      * a valid admin credential (admin ⊇ user).

    AUD-6 full-replace: managed tokens are first-class; the static env tokens are
    the bootstrap, revoked once rotated. Only meaningful when
    ``_user_token_required()`` is True; with no token configured the localhost
    posture applies and no credential is needed."""
    if user_supplied and get_token_store().verify(user_supplied) == "user":
        return True
    if _env_user_active() and user_supplied and secrets.compare_digest(user_supplied, USER_TOKEN):
        return True
    # An admin credential is a superset of user access — accept it too.
    if _admin_credential_ok(admin_supplied):
        return True
    return False


async def _user_guard(request: Request):
    """Authorize a user-facing request or raise 401/403. See USER_TOKEN above."""
    if USER_TOKEN:
        if _user_credential_ok(
            user_supplied=request.headers.get("x-user-token", ""),
            admin_supplied=request.headers.get("x-admin-token", ""),
        ):
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
    return _user_credential_ok(
        user_supplied=request.headers.get("x-user-token", ""),
        admin_supplied=request.headers.get("x-admin-token", ""),
    )


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


from agents import __version__ as _APP_VERSION  # CDX-4: single-source the version
app = FastAPI(title="Jarvis", version=_APP_VERSION, lifespan=lifespan)

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


# H23.11/AUD-17: machine-facing endpoints a supervisor or monitor polls — the
# liveness/readiness probes (LB / systemd / Docker HEALTHCHECK) and the Prometheus
# /metrics scrape. They are unauthenticated by design and frequently arrive from a
# non-localhost peer (reverse-proxy / docker-bridge gateway / monitoring host), so
# they must bypass the unauthenticated per-IP throttle — otherwise unrelated load
# from that same source IP could 429 a probe and make a load balancer evict a
# perfectly healthy instance (the opposite of the operability goal).
_PROBE_PATHS = {"/healthz", "/readyz", "/metrics"}


@app.middleware("http")
async def _rate_limit(request: Request, call_next):
    """HF-2: throttle unauthenticated network clients (DoS / token brute-force)."""
    if RATE_LIMIT_PER_MIN > 0 and request.url.path not in _PROBE_PATHS:
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


# AUD-3: security headers (clickjacking, MIME-sniff, and a CSP as defense-in-depth
# behind the HUD's output escaping). The HUD ships its own inline <script>/<style>,
# so script/style-src must allow 'unsafe-inline'; the CSP still blocks external
# scripts, plugins/objects and cross-origin framing. Override the policy with
# $JARVIS_CSP, or set $JARVIS_DISABLE_CSP=1 to drop the CSP header if it ever
# interferes with a deployment.
_DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "font-src 'self' data:; "
    "connect-src 'self' ws: wss:; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
)
_CSP_POLICY = os.environ.get("JARVIS_CSP", _DEFAULT_CSP)
_CSP_ENABLED = os.environ.get("JARVIS_DISABLE_CSP", "").lower() not in ("1", "true", "yes")


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if _CSP_ENABLED:
        response.headers.setdefault("Content-Security-Policy", _CSP_POLICY)
    return response


# AUD-17: HTTP golden signals (RED — rate/errors/duration) for every request,
# exposed at GET /metrics. Registered last so it is the OUTERMOST middleware: the
# duration spans the whole stack (incl. a rate-limit 429) — what a client sees —
# and the in-flight gauge counts genuinely concurrent requests. Labels use the
# matched route template (request.scope["route"].path) to bound cardinality.
from agents.core.observability.http_metrics import HTTP_METRICS  # noqa: E402


@app.middleware("http")
async def _golden_signals(request: Request, call_next):
    HTTP_METRICS.inc_in_flight()
    start = time.perf_counter()
    status = 500  # if call_next raises, the client sees a 500 — record it as such
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        duration = time.perf_counter() - start
        route = request.scope.get("route")
        template = getattr(route, "path", None) or "<unmatched>"
        HTTP_METRICS.dec_in_flight()
        HTTP_METRICS.record(request.method, template, status, duration)


def _uptime_str() -> str:
    s = int(time.time() - _start_time)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _sys_info() -> dict:
    """Host/CPU/GPU readiness — honest (CDX-10).

    Every value is *probed*; when a probe fails we surface ``unknown`` / ``none`` / ``0``,
    never a plausible-but-fabricated host, CPU brand or GPU. The trust/readiness screen
    must never imply hardware (or a loaded model) that isn't actually there.
    """
    import contextlib
    import platform
    import shutil
    import socket

    base = {
        "host": "unknown",
        "cpu": "unknown",
        "ram_used": 0, "ram_total": 0,
        "gpu": "unknown",
        "vram_used": 0, "vram_total": 0, "gpu_load": 0,
        "backend": "unknown",
        "model": "unknown",
        "latency": 0,
        "uptime": _uptime_str(),
        "sessions": 0,
    }
    with contextlib.suppress(Exception):
        base["host"] = socket.gethostname() or "unknown"
    # CPU — the real model string, no fabricated brand. platform.processor() is often blank
    # on Linux, so fall back to the /proc/cpuinfo model name, then to a bare thread count.
    with contextlib.suppress(Exception):
        import psutil
        cpu = (platform.processor() or "").strip()
        if not cpu:
            with contextlib.suppress(OSError), open("/proc/cpuinfo", encoding="utf-8") as fh:
                for line in fh:
                    if line.lower().startswith("model name"):
                        cpu = line.split(":", 1)[1].strip()
                        break
        n = psutil.cpu_count(logical=True)
        if cpu and n:
            base["cpu"] = f"{cpu} · {n} thr"
        elif cpu:
            base["cpu"] = cpu
        elif n:
            base["cpu"] = f"{n} threads"
        vm = psutil.virtual_memory()
        base["ram_used"] = round(vm.used / 1e9, 1)
        base["ram_total"] = round(vm.total / 1e9, 1)
    # GPU — the real card name + VRAM via nvidia-smi; an honest "none" when there is no
    # NVIDIA GPU (binary absent / non-zero exit), never a fabricated card. A present-but-
    # erroring probe leaves the honest "unknown" default.
    if shutil.which("nvidia-smi") is None:
        base["gpu"] = "none"
    else:
        with contextlib.suppress(Exception):
            import subprocess
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0 and r.stdout.strip():
                parts = [p.strip() for p in r.stdout.strip().splitlines()[0].split(",")]
                if len(parts) == 4:
                    base["gpu"] = parts[0] or "unknown"
                    base["vram_used"] = int(float(parts[1])) // 1024
                    base["vram_total"] = int(float(parts[2])) // 1024
                    base["gpu_load"] = int(float(parts[3]))
            else:
                base["gpu"] = "none"
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


async def _chat_event_stream(orch, message: str, agent: str, agent_override):
    """SSE producer for /chat/stream — cancellation-safe (AUD-7 / F8).

    The model turn runs in a background ``runner`` task feeding a queue; this
    generator consumes it. The consume loop is wrapped in try/finally so that ANY
    exit cancels the runner and awaits its cancellation: a normal end, an error,
    OR — the bug this fixes — the client disconnecting mid-stream, where Starlette
    throws ``GeneratorExit`` into this generator. Previously ``task.cancel()`` sat
    after the loop and was skipped on disconnect, leaving the LLM turn running
    orphaned (burning the backend, never releasing resources)."""
    queue: asyncio.Queue = asyncio.Queue()

    async def on_token(token: str):
        await queue.put(("token", token))

    async def runner():
        try:
            full = await orch.handle_input_stream(
                message, channel="web", on_token=on_token, agent_override=agent_override,
            )
            await queue.put(("end", full))
        except asyncio.CancelledError:
            raise  # client disconnected → propagate so the turn actually stops
        except Exception as e:
            logger.exception("chat stream runner error")
            await queue.put(("error", str(e)))

    task = asyncio.create_task(runner())
    try:
        yield f"data: {json.dumps({'type': 'start', 'agent': agent})}\n\n"
        while True:
            kind, data = await queue.get()
            if kind == "token":
                yield f"data: {json.dumps({'type': 'token', 'text': data})}\n\n"
            elif kind == "end":
                yield f"data: {json.dumps({'type': 'end', 'agent': agent, 'text': data})}\n\n"
                break
            elif kind == "error":
                yield f"data: {json.dumps({'type': 'end', 'agent': agent, 'text': f'Eroare internă: {data}'})}\n\n"
                break
    finally:
        # Runs on normal completion AND on client disconnect (GeneratorExit). Awaiting
        # a non-yielding coroutine here is allowed during generator close, so the model
        # turn is always cancelled and reaped — never left running for a gone client.
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("chat stream runner cleanup failed")


@app.post("/chat/stream", dependencies=[Depends(_user_guard)])
async def chat_stream(req: ChatRequest):
    if not orch:
        return JSONResponse({"error": "not initialized"}, status_code=503)

    agent_override = req.agent if req.agent != "jarvis" else None
    return StreamingResponse(
        _chat_event_stream(orch, req.message, req.agent, agent_override),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# Voice routes (/tts, /tts/stream, /api/voice/*) extracted to routers/voice.py (CLN-3).


# ── Status (HUD-compatible) ──────────────────────────────────────

# ... extracted to routers/status.py (CLN-3)


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


# ... /status extracted to routers/status.py (CLN-3)




# ── Dashboard (HUD-compatible) ───────────────────────────────────

_dashboard_cache = {"weather": "", "news": [], "cached_at": 0}
# Serialize cache refreshes so concurrent /dashboard requests don't race on the
# weather/calendar update (double-fetch or partial write under load). BUG-1.
_dashboard_lock = asyncio.Lock()


# CLN-3: /dashboard, /tasks, /ticker extracted to agents/core/routers/dashboard.py
# (`_dashboard_cache` + `_dashboard_lock` above stay here — the router reads them
#  through `sys.modules.get("agents.web")` so tests' monkeypatch is still observed.)




# ── Existing endpoints (unchanged) ───────────────────────────────

# `/memory` + `/memory/clear` (bare HUD routes) live in the memory_hud router (CLN-3).




# CLN-3: /sessions + /sessions/resume extracted to agents/core/routers/sessions.py


# /security route extracted to agents/core/routers/security_hud.py (CLN-3).


# /bench route extracted to agents/core/routers/bench.py (CLN-3).








# ── H15.4 Secret broker + H10.1 Embeddable Chat Widget ────────────────────────
# Both surfaces (/api/secrets/broker..., /api/admin/widgets, /api/widget...) live
# in the secrets router (CLN-3). They reach state only via the orchestrator
# (orch.secret_broker / orch.widgets), so nothing web.py-owned moved.


# ── H13.2 Constrained decoding (GBNF grammar) ─────────────────────────────────

# ── H14.3 Sleep-time memory consolidation ─────────────────────────────────────
# `/api/memory/consolidate` lives in the memory_kg router (CLN-3).


# ── H7.11 Learning-loop promotions ────────────────────────────────────────────

# /api/learning/propose extracted to agents/core/routers/learning.py (CLN-3)


# /api/workflows step/generate + hierarchical extracted to routers/workflows.py (CLN-3).


# /api/context/compress (+ ContextCompressBody) extracted to routers/tools.py (CLN-3)


# CLN-3: vlm/desktop/media routes (VLMDescribeBody/DesktopStepsBody/MediaGenBody +
# /api/vlm/status, /api/vlm/describe, /api/desktop/preview, /api/media,
# /api/media/generate) extracted to agents/core/routers/multimodal.py.


# H21.0 — mount the cognition APIRouter (keeps cognition endpoints out of the
# web.py god-object). User-guarded like the rest of the /api surface.
from agents.core.cognition.api import router as _cognition_router  # noqa: E402

app.include_router(_cognition_router, dependencies=[Depends(_user_guard)])

# Per-domain routers extracted from this god-object (CLN-3). These preserve the
# original (ungated) behavior of their routes — mounted without extra deps.
from agents.core.routers.feedback import router as _feedback_router  # noqa: E402
from agents.core.routers.onboarding import router as _onboarding_router  # noqa: E402
from agents.core.routers.wyoming import router as _wyoming_router  # noqa: E402

app.include_router(_wyoming_router)
app.include_router(_onboarding_router)
app.include_router(_feedback_router)
# These preserve each route's original per-route deps (gating lives on the routes
# themselves, not the include), so behavior is unchanged.
from agents.core.routers.a2a import router as _a2a_router  # noqa: E402
from agents.core.routers.actions import router as _actions_router  # noqa: E402
from agents.core.routers.admin import router as _admin_router  # noqa: E402
from agents.core.routers.analytics import router as _analytics_router  # noqa: E402
from agents.core.routers.arena import router as _arena_router  # noqa: E402
from agents.core.routers.autonomy import router as _autonomy_router  # noqa: E402
from agents.core.routers.missions import router as _missions_router  # noqa: E402
from agents.core.routers.bench import router as _bench_router  # noqa: E402
from agents.core.routers.ops import router as _ops_router  # noqa: E402
from agents.core.routers.backup import router as _backup_router  # noqa: E402
from agents.core.routers.brain import router as _brain_router  # noqa: E402
from agents.core.routers.browser import router as _browser_router  # noqa: E402
from agents.core.routers.canvas import router as _canvas_router  # noqa: E402
from agents.core.routers.capture import router as _capture_router  # noqa: E402
from agents.core.routers.data_spaces import router as _data_spaces_router  # noqa: E402
from agents.core.routers.integrations import router as _integrations_router  # noqa: E402
from agents.core.routers.memory_hud import router as _memory_hud_router  # noqa: E402
from agents.core.routers.memory_kg import router as _memory_kg_router  # noqa: E402
from agents.core.routers.mesh import router as _mesh_router  # noqa: E402
from agents.core.routers.models_llm import router as _models_llm_router  # noqa: E402
from agents.core.routers.multimodal import router as _multimodal_router  # noqa: E402
from agents.core.routers.notes import router as _notes_router  # noqa: E402
from agents.core.routers.oauth import router as _oauth_router  # noqa: E402
from agents.core.routers.osint import router as _osint_router  # noqa: E402
from agents.core.routers.market import router as _market_router  # noqa: E402
from agents.core.routers.creative import router as _creative_router  # noqa: E402
from agents.core.routers.pairing import router as _pairing_router  # noqa: E402
from agents.core.routers.dashboard import router as _dashboard_router  # noqa: E402
from agents.core.routers.agents_api import router as _agents_api_router  # noqa: E402
from agents.core.routers.dashboard import dashboard  # noqa: E402  (re-export: MCP route-tool + drift guard resolve web.dashboard)
from agents.core.routers.payments import router as _payments_router  # noqa: E402
from agents.core.routers.mcp import router as _mcp_router  # noqa: E402
from agents.core.routers.voice import router as _voice_router  # noqa: E402
from agents.core.routers.eval import router as _eval_router  # noqa: E402
from agents.core.routers.heartbeat import router as _heartbeat_router  # noqa: E402
from agents.core.routers.learning import router as _learning_router  # noqa: E402
from agents.core.routers.workflows import router as _workflows_router  # noqa: E402
from agents.core.routers.plugins import router as _plugins_router  # noqa: E402
from agents.core.routers.quality import router as _quality_router  # noqa: E402
from agents.core.routers.review import router as _review_router  # noqa: E402
from agents.core.routers.sessions import router as _sessions_router  # noqa: E402
from agents.core.routers.rooms import router as _rooms_router  # noqa: E402
from agents.core.routers.secrets import router as _secrets_router  # noqa: E402
from agents.core.routers.security import router as _security_router  # noqa: E402
from agents.core.routers.security_hud import router as _security_hud_router  # noqa: E402
from agents.core.routers.skills import router as _skills_router  # noqa: E402
from agents.core.routers.status import router as _status_router  # noqa: E402
from agents.core.routers.status import status  # noqa: E402  (re-export: MCP route-tool + drift guard resolve web.status)
from agents.core.routers.tools import router as _tools_router  # noqa: E402
from agents.core.routers.webhooks import router as _webhooks_router  # noqa: E402

app.include_router(_webhooks_router)
app.include_router(_a2a_router)
app.include_router(_pairing_router)
app.include_router(_canvas_router)
app.include_router(_browser_router)
app.include_router(_capture_router)
app.include_router(_rooms_router)
app.include_router(_notes_router)
app.include_router(_osint_router)
app.include_router(_market_router)
app.include_router(_creative_router)
app.include_router(_actions_router)
app.include_router(_arena_router)
app.include_router(_review_router)
app.include_router(_quality_router)
app.include_router(_security_router)
app.include_router(_security_hud_router)
app.include_router(_skills_router)
app.include_router(_status_router)
app.include_router(_data_spaces_router)
app.include_router(_secrets_router)
app.include_router(_mesh_router)
app.include_router(_autonomy_router)
app.include_router(_missions_router)
app.include_router(_models_llm_router)
app.include_router(_oauth_router)
app.include_router(_brain_router)
app.include_router(_memory_hud_router)
app.include_router(_memory_kg_router)
app.include_router(_analytics_router)
app.include_router(_admin_router)
app.include_router(_integrations_router)
app.include_router(_dashboard_router)
app.include_router(_payments_router)
app.include_router(_mcp_router)
app.include_router(_agents_api_router)
app.include_router(_voice_router)
app.include_router(_multimodal_router)
app.include_router(_eval_router)
app.include_router(_heartbeat_router)
app.include_router(_learning_router)
app.include_router(_workflows_router)
app.include_router(_tools_router)
app.include_router(_plugins_router)
app.include_router(_sessions_router)
app.include_router(_bench_router)
app.include_router(_ops_router)
app.include_router(_backup_router)


# /api/digest/run (+ DigestRunBody) and /api/schedule/parse extracted to routers/tools.py (CLN-3)


# /learning and /learning/promote (+ PromoteRequest) extracted to agents/core/routers/learning.py (CLN-3)


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


# `GET /api/resilience` + `GET /api/cognition` (system/ops reads) live in the ops router (CLN-3).


# `/memory/stats` (HUD/SystemsPanel) lives in the memory_hud router (CLN-3).


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
        from agents.core.kernel.binding import make_action_kernel
        # ORIZONT-24 K1 payment micro-wave: bind the same kernel.authorize the wave-1
        # brokers use (kill-switch · capabilities · policy · audit). None if the live
        # orchestrator/policy isn't reachable → kernel-less, unchanged behavior.
        # Default-off at runtime regardless (JARVIS_ACTION_KERNEL).
        _payment_broker = PaymentBroker(
            audit=IntentLog(path=str(data_path("security/payments_intent.json"))),
            kernel=make_action_kernel(globals().get("orch")))
    return _payment_broker


# Routes extracted to agents/core/routers/payments.py (CLN-3). The singleton +
# accessor above stay here (web owns it; tests patch web._payment_broker); the
# router resolves it at request time via sys.modules.
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
    route_tools = _build_mcp_route_tools()
    mutating_route_tools = _build_mcp_mutating_route_tools()
    return JarvisMCPServer(
        _runner,
        agents,
        allowed_agents=allowed,
        lan_only=True,
        route_tools=route_tools,
        mutating_route_tools=mutating_route_tools,
    )


def _build_mcp_route_tools():
    """H22.9 (read-only) — bind allow-listed READ-ONLY routes for MCP exposure.

    Gated OFF by default via the ``JARVIS_MCP_ROUTE_TOOLS`` kill-switch: when the
    switch is off this returns ``[]`` and the MCP server exposes only the existing
    ``ask_<agent>`` tools (unchanged behaviour). When on, the curated read-only
    routes (``/status``, ``/api/memory/search``, ``/dashboard``) are bound to their
    in-process handlers — no loopback HTTP, no mutating routes (those are post-1.0).
    """
    from agents.core.mcp.route_tools import build_route_tools, route_tools_enabled

    if not route_tools_enabled():
        return []
    from agents.core.routers.memory_kg import memory_search

    handlers = {
        "status": status,
        "memory_search": memory_search,
        "dashboard": dashboard,
    }
    return build_route_tools(handlers)


def _build_mcp_mutating_route_tools():
    """H22.9 (mutating) — bind allow-listed WRITE routes for MCP exposure.

    DOUBLE-gated OFF by default: returns ``[]`` unless BOTH
    ``JARVIS_MCP_ROUTE_TOOLS`` AND ``JARVIS_MCP_MUTATING_TOOLS`` are on. When both
    are on, the curated mutating route(s) are bound to an in-process write adapter
    (NOT a loopback HTTP call) and every invocation is audited via ``orch.audit``.

    SECURITY: the in-process adapter has no ``Request``, so it cannot run
    ``Depends(user_guard)`` directly. Instead a per-identity gate
    (``_mcp_identity_check``) is threaded onto every mutating tool; it re-applies
    the SAME rule ``user_guard`` uses (``_user_token_required`` /
    ``_user_credential_ok``). A mutating call without a valid identity is refused
    even with both kill-switches on. The transport (``mcp_server_rpc``) extracts
    the credential from the request headers and passes it to the server. Residual
    gap: a leaked token alone drives the write surface, and the unset-token posture
    trusts the in-process call unconditionally — see the caveat block in
    ``agents/core/mcp/route_tools.py``.
    """
    from agents.core.mcp.route_tools import build_mutating_route_tools

    async def _invoke_memory_remember(args: dict):
        """Same write as ``POST /api/memory/remember`` (sans Request body parse)."""
        if not orch or not orch.memory:
            return {"error": "not initialized"}
        text = args.get("text", "")
        text = text.strip() if isinstance(text, str) else ""
        if not text:
            return {"error": "text required"}
        metadata = args.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        rid = await orch.memory.remember(text, metadata=metadata)
        return {"ok": rid is not None, "id": rid}

    invokers = {"memory_remember": _invoke_memory_remember}
    auditor = orch.audit if orch else None
    # ORIZONT-24 wave-3: mediate MCP writes through the Action Kernel (default-off).
    # A halted kill-switch / over-budget / runaway loop blocks the write after the
    # identity gate. None if the policy isn't reachable → kernel-less, unchanged.
    from agents.core.kernel.binding import make_action_kernel
    return build_mutating_route_tools(
        invokers, auditor=auditor, identity_check=_mcp_identity_check,
        kernel=make_action_kernel(orch),
    )


def _mcp_identity_check(token: Optional[str]) -> bool:
    """Per-identity gate for MCP mutating tools — the SAME rule as ``user_guard``.

    Reuses the HTTP guard's primitives so the rule is never forked:
      * If ``JARVIS_USER_TOKEN`` is UNSET → localhost-only dev posture: the HTTP
        guard trusts a localhost origin and needs no token, so the in-process MCP
        call (localhost-equivalent) is allowed with no credential. Dev unchanged.
      * If it is SET → require a credential that matches ``JARVIS_USER_TOKEN`` (or
        a matching ``JARVIS_ADMIN_TOKEN``, admin ⊇ user), exactly as the HTTP 401
        path checks it."""
    if not _user_token_required():
        return True
    return _user_credential_ok(user_supplied=token or "", admin_supplied=token or "")




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










# ── END H10.5 MCP Server endpoints ────────────────────────────────


# H9.3b Dataset Regression routes extracted to agents/core/routers/eval.py (CLN-3).


# /api/workflows list/run/traces extracted to routers/workflows.py (CLN-3).


# ── H9.1 Visual Workflow Builder store (singleton stays in web.py) ─
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


# /api/workflows CRUD (create/update/delete) extracted to routers/workflows.py (CLN-3).


# `/memory/{agent_id}` (per-agent memory context) lives in the memory_hud router (CLN-3).


# /plugins and /plugins/{plugin_id}/toggle extracted to agents/core/routers/plugins.py (CLN-3)


# /learning/stats extracted to agents/core/routers/learning.py (CLN-3)


# /security/status route extracted to agents/core/routers/security_hud.py (CLN-3).


# /bench/stats route extracted to agents/core/routers/bench.py (CLN-3).


# /heartbeat/* routes extracted to agents/core/routers/heartbeat.py (CLN-3).


# ... /api/status extracted to routers/status.py (CLN-3)

