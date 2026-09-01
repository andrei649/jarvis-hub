"""HUD v2 — parity gate (P4).

Every backend HTTP route must map to a v2 surface (a mode / chrome) **or** be
explicitly ``NOT_IN_HUD`` (machine-facing: well-known, MCP-server RPC, the
agent-callable memory tool). This fails if a new endpoint is added to
``agents/web.py`` without deciding where it lives in the HUD — so the v2 redesign
can't silently drop a capability we built.

Pure text analysis of ``web.py`` (no app import), so it runs anywhere pytest does.
See ``docs/design/HUD_V2_IMPLEMENTATION_PLAN.md`` §8 and the coverage map in
``docs/design/HUD_V2_COVERAGE_AND_PLAN.md``.
"""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_AGENTS = REPO / "agents"
WEB = _AGENTS / "web.py"
# CLN-3 moves routes out of the web.py god-object into per-domain APIRouters in
# agents/core/routers/. The parity gate must still see every route, so it scans
# both the inline @app.* routes in web.py AND the @router.* routes in those
# extracted modules — otherwise an extracted endpoint would silently escape the
# "every route has a v2 home" check.
ROUTERS = _AGENTS / "core" / "routers"
GAP = Path(__file__).resolve().parent.parent / "frontend" / "src" / "gap.tsx"
OPERATOR = Path(__file__).resolve().parent.parent / "frontend" / "src" / "operator-panel.tsx"

# Ordered (prefix, surface); first match wins, so put the more specific prefixes
# first. Surfaces mirror the v2 modes + chrome. NOT_IN_HUD = surfaced nowhere by
# design (machine-facing). Keep this in sync with the v2 IA when adding routes.
RULES = [
    # served shells / infra
    ("/v2", "shell"),
    ("/v1", "shell"),
    ("/static", "shell"),
    ("/favicon", "shell"),
    ("/sw.js", "shell"),
    ("/admin", "admin"),
    # machine-facing — intentionally not a HUD surface
    ("/.well-known/", "NOT_IN_HUD"),
    ("/healthz", "NOT_IN_HUD"),  # H23.11 liveness probe (LB / systemd / Docker HEALTHCHECK)
    ("/readyz", "NOT_IN_HUD"),  # H23.11 readiness probe (503 until boot completes)
    ("/metrics", "NOT_IN_HUD"),  # AUD-17 Prometheus golden-signals scrape (machine-facing)
    ("/api/mcp/server", "NOT_IN_HUD"),
    ("/api/memory/tool-spec", "NOT_IN_HUD"),
    ("/api/memory/search-tool", "NOT_IN_HUD"),
    # T-0.29 PWA: fetched by the BROWSER (install prompt / SW registration), never
    # rendered as a panel — a HUD surface for them would be meaningless.
    ("/manifest.webmanifest", "NOT_IN_HUD"),
    ("/sw-v2.js", "NOT_IN_HUD"),
    # T-0.20 vault (Console → Memory), T-0.41 signals (Console → Interop),
    # T-0.53 design manifest (Console → Observe).
    ("/api/vault", "memory"),
    ("/api/signals/", "interop"),
    ("/api/packs", "interop"),          # T-0.58 typed Pack Manager inventory
    ("/api/design-manifest", "observe"),
    ("/api/widget/", "interop"),  # embeddable widget runtime (managed under Interop)
    ("/api/ops/estop", "admin"),  # global emergency stop (hermes v2026.8.27 port) — owner control
    # cockpit / conversation
    ("/chat", "cockpit"),
    ("/api/status", "cockpit"),
    ("/status", "cockpit"),
    ("/api/agents", "agents"),
    ("/agents", "agents"),
    ("/dashboard", "cockpit"),
    ("/api/dashboard", "cockpit"),  # P1 G1 unified "Today in Jarvis" feed (home narrative)
    ("/ticker", "cockpit"),
    ("/tasks", "cockpit"),
    ("/api/cognition", "cockpit"),
    ("/tts", "cockpit"),
    ("/sessions", "cockpit"),
    ("/memory/clear", "cockpit"),
    ("/api/canvas", "cockpit"),
    (
        "/api/onboarding",
        "cockpit",
    ),  # H23.20 first-run wizard + activation funnel (lands in the cockpit)
    ("/api/system/", "cockpit"),  # 0.62 System Profiles — usage-mode selector (system/home setting)
    ("/api/trust/status", "topbar"),
    # memory & knowledge
    ("/api/osint/", "knowledge"),  # P2 OSINT pack — the Knowledge/"Vision · OSINT" surface (modes4)
    ("/api/kg/", "memory"),
    ("/api/memory/", "memory"),
    ("/memory/stats", "memory"),
    ("/memory", "memory"),
    ("/api/local-docs", "memory"),
    ("/api/capture", "memory"),
    ("/api/context", "memory"),  # runtime context compression (H20.3)
    ("/api/ingestion/", "memory"),  # 0.37 ingestion-provenance audit ledger (Memory cluster panel)
    ("/api/coach/", "knowledge"),  # 0.43 Learning Coach pack — spaced repetition + curriculum
    # finance / market intel
    ("/api/market/", "finance"),  # P3 Market Intel pack — the Finance surface (modes4 "Gecko")
    # trust / security / payments
    (
        "/api/security-skills/",
        "trust",
    ),  # 0.42 Security Skills pack — curated ATT&CK/D3FEND/CSF knowledge
    ("/api/security/", "trust"),
    ("/security", "trust"),
    ("/api/secrets/", "trust"),
    ("/api/capabilities", "trust"),  # H27.8 capability registry → ReadinessPanel
    ("/api/payments", "trust"),
    # autonomy
    ("/autonomy/", "autonomy"),
    ("/api/autonomy/", "autonomy"),
    ("/api/presence", "autonomy"),  # H34.2 owner desk-presence → away-notify control
    ("/api/actions", "autonomy"),
    ("/api/missions", "autonomy"),  # Mission Workspaces (0.32) — long-horizon workspaces
    ("/api/reflection", "autonomy"),
    ("/api/schedule/parse", "autonomy"),
    ("/api/transcripts", "autonomy"),
    # build (workflows / skills / sandbox / grammar / creative pipeline)
    ("/api/creative/", "build"),  # P4 Creative pack — the Build surface (asset pipeline, modes2)
    ("/api/workflows", "build"),
    ("/api/skills", "build"),
    ("/skills", "build"),
    ("/sandbox", "build"),
    ("/api/llm/grammar", "build"),
    ("/api/browser", "build"),
    ("/api/toolrpc", "build"),  # governed Tool-RPC for sandboxed pipelines (H20.1)
    ("/api/codeintel/", "build"),  # 0.31 Code Intelligence — AST symbol index over the source
    ("/api/vlm", "build"),  # vision-language model adapter (H13.1)
    ("/api/screen/", "build"),  # T-0.25 ScreenReflex — Build/OperatorPanel neighbour, loopback-VLM only
    ("/api/desktop", "build"),  # governed desktop operator (H15.3)
    ("/api/operator", "build"),  # H28.2 action-hierarchy selection (DRA-22/DRA-42)
    ("/api/media", "build"),  # governed generation + live Media Director panel (H12.24/H29)
    ("/api/house", "home"),  # H30 House Brain state + governed proposals/owner ceremony
    ("/api/cameras", "home"),  # H31 local camera metadata + privacy-safe temporal search
    ("/api/ambient", "home"),  # H33 redacted live-monitor and decision transparency
    ("/api/acquisition", "build"),  # H32 governed capability lifecycle + hash-only audit
    # observe (traces / eval / quality / review / arena / resilience / bench / cost)
    ("/api/traces", "observe"),
    ("/api/eval", "observe"),
    ("/api/quality", "observe"),
    ("/api/review", "observe"),
    ("/api/arena", "observe"),
    ("/api/resilience", "observe"),
    ("/bench", "observe"),
    ("/api/cost", "observe"),
    ("/api/analytics", "observe"),
    ("/api/feedback", "observe"),  # H23.21 design-partner NPS/feedback (owner reviews it here)
    ("/api/self-improvement", "observe"),  # Self-Improvement dashboard: SelfImprovementPanel (Console → Observe)
    ("/api/support/", "observe"),  # 0.55 design-partner diagnostic bundle (triage surface)
    ("/api/metrics", "observe"),  # MOONSHOT §6 north-star meter (sibling of analytics/cost)
    ("/api/digest", "observe"),
    ("/brain", "observe"),
    ("/api/brain", "observe"),  # neural-mesh brain (live agents+models)
    ("/mission-control", "observe"),  # H34.1 Mission Control standalone page (swarm cockpit)
    ("/api/swarm", "observe"),  # H34.1 aggregated swarm feed driving Mission Control
    ("/map", "observe"),  # H34.7 Live System Map standalone page (topology + health)
    ("/api/system-map", "observe"),  # H34.7 subsystem-health feed driving the map
    ("/api/health/components", "observe"),
    # interop (a2a / mcp client mgmt / webhooks / external write-back + social)
    ("/api/a2a/", "interop"),
    ("/api/admin/mcp", "interop"),
    ("/api/admin/widgets", "interop"),
    ("/api/mcp", "interop"),
    ("/api/webhooks", "interop"),
    ("/api/integrations/", "interop"),
    ("/api/sync", "interop"),  # E2E device sync (H12.13)
    ("/api/nodes", "interop"),  # governed node mesh (H12.17)
    ("/api/worldview/", "interop"),  # WorldView bridge liveness — HUD World tab
    # comms (rooms / notes / channel sender pairing / mic satellites)
    ("/api/rooms", "comms"),
    ("/api/notes", "comms"),
    ("/api/channels/", "comms"),
    ("/api/satellites", "comms"),  # shared-GPU mic satellites (H12.8)
    # agent ops (heartbeat / learning / templates)
    ("/heartbeat", "agents"),
    ("/learning", "agents"),
    ("/api/learning", "agents"),
    ("/api/agent-templates", "agents"),
    ("/api/subagents", "agents"),  # H20.6
    # admin (settings / env / models / llm lifecycle / oauth / oracle / plugins / voice / prompts / stats)
    ("/api/admin/", "admin"),
    ("/plugins", "admin"),
    ("/api/models", "admin"),
    ("/api/llm/", "admin"),
    ("/api/oauth", "admin"),
    ("/api/oracle", "admin"),
    ("/api/voice", "admin"),
]

CORE_SURFACES = [
    "cockpit",
    "agents",
    "memory",
    "trust",
    "autonomy",
    "build",
    "observe",
    "interop",
    "comms",
    "admin",
]


def _routes():
    app_pat = r'^@app\.(?:get|post|put|delete|patch)\("([^"]+)"'
    router_pat = r'^@router\.(?:get|post|put|delete|patch)\("([^"]+)"'
    found = set(re.findall(app_pat, WEB.read_text(encoding="utf-8"), re.M))
    for mod in sorted(ROUTERS.glob("*.py")):
        found |= set(re.findall(router_pat, mod.read_text(encoding="utf-8"), re.M))
    return sorted(found)


def _classify(path):
    if path == "/":
        return "cockpit"
    for prefix, surface in RULES:
        if path == prefix or path.startswith(prefix):
            return surface
    return "UNMAPPED"


def test_routes_extracted():
    routes = _routes()
    assert len(routes) > 150, f"expected the full route surface, got {len(routes)}"


def test_every_route_has_a_v2_home():
    unmapped = [p for p in _routes() if _classify(p) == "UNMAPPED"]
    assert not unmapped, (
        "HUD v2 parity gate: these backend routes have no v2 surface — add each to "
        "a mode or to NOT_IN_HUD in tests/test_hud_v2_parity.py:RULES:\n  " + "\n  ".join(unmapped)
    )


def test_core_surfaces_each_cover_a_route():
    covered = {_classify(p) for p in _routes()}
    missing = [s for s in CORE_SURFACES if s not in covered]
    assert not missing, f"v2 surfaces with no mapped route (IA regression?): {missing}"


def test_media_director_routes_have_a_live_build_surface():
    media_routes = {
        "/api/media/devices",
        "/api/media/devices/{device_id}",
        "/api/media/session",
        "/api/media/present",
        "/api/media/restore/{device_id}",
    }
    assert media_routes.issubset(set(_routes()))
    assert {_classify(path) for path in media_routes} == {"build"}

    source = GAP.read_text(encoding="utf-8")
    assert re.search(r"\['Build', \[[^\]]*\bMediaDirectorPanel\b", source)
    start = source.index("export function MediaDirectorPanel")
    end = source.index("/* 0.37", start)
    panel = source[start:end]
    for route in (
        "/api/media/devices",
        "/api/media/session",
        "/api/media/present",
        "/api/media/restore/",
    ):
        assert route in panel
    assert "ADMIN · DEVICE REGISTRY" in panel
    assert "<iframe" not in panel.lower()


def test_house_routes_have_a_live_home_surface():
    house_routes = {
        "/api/house/state",
        "/api/house/control/light",
        "/api/house/control/climate",
        "/api/house/control/security",
    }
    assert house_routes.issubset(set(_routes()))
    assert {_classify(path) for path in house_routes} == {"home"}

    source = GAP.read_text(encoding="utf-8")
    start = source.index("export function HousePanel")
    end = source.index("/* 0.37", start)
    panel = source[start:end]
    for route in house_routes:
        assert route in panel
    assert "/api/house/security/" in panel
    assert "ADMIN · STRONG CONFIRMATION" in panel
    assert "<iframe" not in panel.lower()


def test_camera_routes_have_a_metadata_only_home_surface():
    camera_routes = {
        "/api/cameras/status",
        "/api/cameras/events",
        "/api/cameras/search",
        "/api/cameras/onvif/discover",
    }
    assert camera_routes.issubset(set(_routes()))
    assert {_classify(path) for path in camera_routes} == {"home"}

    source = GAP.read_text(encoding="utf-8")
    assert re.search(r"\['Home', \[[^\]]*\bCameraPanel\b", source)
    start = source.index("export function CameraPanel")
    end = source.index("/* 0.37", start)
    panel = source[start:end]
    for route in ("/api/cameras/status", "/api/cameras/events", "/api/cameras/search"):
        assert route in panel
    assert all(tag not in panel.lower() for tag in ("<img", "<video", "<iframe"))


def test_acquisition_routes_have_a_live_hash_only_build_surface():
    acquisition_routes = {
        "/api/acquisition/status",
        "/api/acquisition/events",
        "/api/acquisition/ledger/export",
        "/api/acquisition/ledger/purge",
        "/api/acquisition/{name}/revoke",
        "/api/acquisition/{name}/rollback",
    }
    assert acquisition_routes.issubset(set(_routes()))
    assert {_classify(path) for path in acquisition_routes} == {"build"}

    source = GAP.read_text(encoding="utf-8")
    assert re.search(r"\['Build', \[[^\]]*\bAcquisitionPanel\b", source)
    start = source.index("export function AcquisitionPanel")
    end = source.index("/* 0.37", start)
    panel = source[start:end]
    for route in (
        "/api/acquisition/status",
        "/api/acquisition/events",
        "/api/acquisition/ledger/export",
        "/api/acquisition/ledger/purge",
        "/api/acquisition/",
    ):
        assert route in panel
    assert "request_hash" not in panel
    assert "detail_hash" not in panel


def test_operator_routes_have_a_governed_build_caller():
    operator_routes = {
        "/api/browser/check",
        "/api/browser/plan/preview",
        "/api/desktop/preview",
        "/api/desktop/run",
    }
    assert operator_routes.issubset(set(_routes()))
    assert {_classify(path) for path in operator_routes} == {"build"}

    gap_source = GAP.read_text(encoding="utf-8")
    assert re.search(
        r"import\s+\{\s*OperatorPanel\s*\}\s+from\s+['\"]\./operator-panel['\"]", gap_source
    )
    assert re.search(r"\['Build', \[[^\]]*\bOperatorPanel\b", gap_source)

    operator_source = OPERATOR.read_text(encoding="utf-8")
    for route in operator_routes:
        assert re.search(
            rf"\bapiPost\s*\(\s*['\"]{re.escape(route)}['\"]\s*,",
            operator_source,
        ), f"OperatorPanel must call {route} through apiPost"

    forbidden = {
        "direct fetch": r"\bfetch\s*\(",
        "admin option": r"\{\s*admin\s*:\s*true\s*\}",
        "admin token": r"\b(?:getAdminToken|X-Admin-Token|admin_token)\b",
        "caller approval": r"\b(?:approved|caller_approved)\s*:",
        "typecheck bypass": r"@ts-nocheck",
    }
    for label, pattern in forbidden.items():
        assert not re.search(pattern, operator_source), f"OperatorPanel contains forbidden {label}"


# ── AUDIT: coverage, not classification ───────────────────────────────────────
# The gate above (`test_every_route_has_a_v2_home`) asks whether a path matches a prefix
# in RULES. It never asks whether anything CALLS the route, so
# `_classify("/api/admin/totally-invented-endpoint")` returns 'admin' and the gate goes
# green for an endpoint nobody wrote. The adversarial audit (2026-07-25) named this as one
# of five instances of the same reflex: build a gate, watch it go green, write the green
# into STATUS.md.
#
# What follows is the substance version, and it is a GENERALISATION of the per-feature
# tests further down this file — which already do the right thing, greping the client
# source for each route a panel should call. Nothing was invented here; the good pattern
# was already present and simply had not been applied to everything.
#
# Two rules, and the second is what makes it a ratchet rather than a snapshot:
#   1. a user-facing route with no caller must be in UNCALLED_BACKLOG or MACHINE_FACING;
#   2. every UNCALLED_BACKLOG entry must still be a real, still-uncalled route — so wiring
#      one up FORCES its removal from the list, and the list can only shrink.

# Generated files list every route by construction, so counting them makes this gate
# vacuous: schema.gen.ts alone took the uncalled count from 102 to 3. Found while writing
# this, which is a fair measure of how easy the shape-not-substance mistake is to make.
_GENERATED_CLIENT_FILES = ("schema.gen.ts",)

# Same shape-not-substance trap, one step along: a *test* for a panel names every route the
# panel calls, so a test file alone can satisfy "this route has a client caller" — a route
# would read as wired with no shipping UI behind it. Found the honest way, by red-proofing
# DRA-17: reverting the panel left the gate green because the panel's own test still
# mentioned the routes. Excluding tests was NOT a no-op: two routes
# (/api/missions/{mission_id}/pause, /api/payments/{payment_id}/settle) were being satisfied
# only by their panel tests, and the exclusion is what made that visible. Both have real
# computed-URL callers, so both are declared in COMPUTED_URL_CALLERS below rather than added
# to the punch list — the hole was already in use, not merely reachable.
# KNOWN HOLE, and it has already bitten once. `_has_caller` matches the route text
# anywhere in a client file, so a path written in a COMMENT counts as a caller. During the
# 2026-09-01 sprint a panel documented, in its header, why it REFUSED to wire
# /api/context/compress — and that documentation alone was enough to make the entry look
# called, so delisting it passed this gate while no UI existed. The entry was restored and
# the comment reworded to avoid the literal.
#
# Until the matcher strips comments, the rule for anyone writing a panel is: NEVER spell a
# route path in prose inside a client file unless the panel actually calls it. Put the
# reasoning on the entry here instead, where it cannot be mistaken for a call. That is why
# several entries below carry long justifications that would more naturally live next to
# the code that refused them.

_TEST_FILE_SUFFIXES = (".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")


def _is_test_client_file(path) -> bool:
    posix = path.as_posix()
    return posix.endswith(_TEST_FILE_SUFFIXES) or "/test/" in posix or "/tests/" in posix

_CLIENT_GLOBS = (
    "frontend/src/**/*.ts", "frontend/src/**/*.tsx",
    "mobile/**/*.ts", "mobile/**/*.tsx",
    "agents/web/static/**/*.js", "agents/web/templates/**/*.html",
    # agents/web/*.html — the four hand-written pages the backend serves directly
    # (brain.html, index.html, mission_control.html, system_map.html). They were missing
    # from this tuple, so their real fetches did not count as callers: brain.html:578
    # fetches /api/brain/summary, which therefore sat on UNCALLED_BACKLOG as "no UI" while
    # a shipping page had been calling it all along. A route the operator can already reach
    # is not a gap, and listing it as one sends the next reader to build a duplicate panel.
    "agents/web/*.html",
    "worldview/frontend/**/*.ts", "worldview/frontend/**/*.tsx",
    "desktop/**/*.ts", "desktop/**/*.tsx",
)

# Routes with no UI caller BY DESIGN — something other than our own client calls them.
# Each carries its reason, so the next reader can judge whether it still holds instead of
# inheriting a bare list. The audit's own count came down from 86 to 68 precisely because
# entries like these had been miscounted as missing UI.
MACHINE_FACING: dict[str, str] = {
    "/.well-known/agent-card": "agent discovery, fetched by other agents",
    "/.well-known/oauth-protected-resource": "OAuth resource metadata, fetched by clients",
    "/api/a2a/card": "agent-to-agent discovery",
    "/api/a2a/task": "agent-to-agent task submission",
    "/api/mcp/server/rpc": "MCP transport \u2014 remote MCP clients, not our UI",
    "/manifest.webmanifest": "PWA install prompt, fetched by the browser",
    "/v2/manifest.webmanifest": "PWA install prompt, fetched by the browser",
    "/sw-v2.js": "service-worker registration, fetched by the browser",
    "/v2/sw-v2.js": "service-worker registration, fetched by the browser",
    "/api/oauth/auth-url": "OAuth dance, driven by the provider/browser",
    "/api/oauth/callback": "OAuth redirect target",
    "/api/nodes": "node mesh peer registry",
    "/api/nodes/register": "node mesh peer registration",
    "/api/nodes/{node_id}": "node mesh peer",
    "/api/nodes/{node_id}/dispatch": "node mesh dispatch",
    "/api/satellites/{satellite_id}/dispatch":
        "mic satellite submits to the shared inference rail \u2014 the exact twin of "
        "/api/nodes/{node_id}/dispatch above; the HUD does pairing only",
    "/api/sync": "device sync transport",
    "/api/sync/pull": "device sync transport",
    "/api/sync/push": "device sync transport",
    "/api/capture/ingest": "passive-capture agent ingest",
    "/api/capture/surfaces": "passive-capture agent",
    "/api/channels/webhook": "inbound channel webhook",
    "/api/channels/pairing/request": "inbound pairing request from a sender",
    "/api/channels/{channel_id}/inbound": "inbound webhook delivered by the provider/bridge",
    "/api/widget/{token}/message": "embed snippet, running on a third-party page",
    "/api/toolrpc/call": "ToolRPC transport",
    "/api/toolrpc/tools": "ToolRPC transport",
    "/api/memory/tool-spec": "tool schema, consumed by models not humans",
    "/api/memory/search-tool": "agentic-RAG tool path",
    "/readyz": "liveness probe",
    "/favicon.ico": "browser-issued",
    "/v1": "API version root",
    "/docs/oauth2-redirect": "FastAPI docs UI",
    "/redoc": "FastAPI docs UI",
    "/v2/{path:path}": "SPA catch-all \u2014 serves the client, is not called by it",
    "/mission-control": "server-rendered page, navigated to rather than fetched",
    "/map": "server-rendered page, navigated to rather than fetched",
    "/api/status": "alias probe"
}

# Today's uncalled user-facing routes. A punch-list, not an allowance: seeded from a real
# measurement, and rule 2 above keeps it honest.
UNCALLED_BACKLOG: frozenset[str] = frozenset([
    # STAYS UNWIRED ON PURPOSE (verified 2026-09-01). Its docstring calls it a
    # "/model hot-swap", but models_llm.py:69-77 swaps nothing: it parses the command
    # string and returns `base` (a hardcoded module constant) plus `configured` (an
    # OPENROUTER_API_KEY boolean). OpenRouterBackend is constructed nowhere outside
    # tests, and LLMRouter.backend_type is auto|lm-studio|ollama with no openrouter
    # branch — so that key has no consumer. Every byte a panel could render is the
    # operator's own input echoed back, a constant, or a flag for a backend that never
    # runs. A control here would report a hot-swap that cannot happen.
    # STAYS UNWIRED ON PURPOSE (verified 2026-09-01, mission-canvas lane). Its entire
    # request is `turns: list[dict]` — a transcript produced by a running session, never
    # typed by a person, so a textarea asking the owner to paste JSON turns is a fake
    # surface. No honest read can source it either: /sessions returns checkpoint metadata
    # with no turns, /api/agents/history returns run rollups, and the only route yielding
    # real turns (POST /sessions/resume) REASSIGNS orch.session_id — a destructive side
    # effect disguised as a read. The route also persists nothing: it builds a throwaway
    # ContextCompressor and returns. Production compression is in-process
    # (orchestrator.get_context, orchestrator.py:2241) behind memory.context_compression,
    # which no route exposes — so a button here could not enable, tune or influence it.
    # RESTORED 2026-09-01. This branch moved it to MACHINE_FACING; the adversarial review
    # showed that was wrong on the bucket's own terms. MACHINE_FACING means "something other
    # than our own client calls them", but the producers here are IN-PROCESS python
    # (browser_agent.py:134 and learning/background_review.py:324 call approvals.request(...)
    # directly) — the opposite of an external HTTP caller. Nothing calls this route. The human
    # half IS wired (/api/actions/pending + /decide, tools.js:79,81), but those are different
    # routes and do not make this one called. Uncalled work, so it belongs on the ratchet.
    "/api/actions/request",
    "/api/context/compress",
    # RESTORED 2026-09-01, same correction as /api/actions/request. Agent-consumed via an
    # IN-PROCESS import (autonomy_coordinator.py:499 `from .desktop_control import plan`),
    # not over HTTP, so MACHINE_FACING was the wrong bucket. This file's own notes further
    # down already said "punch list, not MACHINE_FACING" — the branch moved the two routes
    # its own retained prose says must not move. Deliberately-open UI work: a HUD form over a
    # plan the agent produces is the degenerate-surface trap (BACKLOG DRA-15).
    "/api/desktop/plan",
    "/api/llm/openrouter",
    "/api/media/generate",
    "/api/memory/consolidate",
    # STAYS UNWIRED ON PURPOSE (verified 2026-09-01). It is a legacy ALIAS, not a gap:
    # analytics.py:208-221 and analytics.py:224-235 return the identical `snapshot(orch)`,
    # and /api/capabilities' own docstring says it "extends the legacy metrics surface
    # without removing it". The HUD already renders that snapshot — ReadinessPanel,
    # gap.tsx:838, useApi('/api/capabilities'). A panel here would duplicate a shipped one
    # over a byte-identical payload. Whether to keep the alias or delete the route is an
    # API decision for the owner, not something to paper over with a second panel.
    "/api/metrics/capabilities",
    # STAYS UNWIRED ON PURPOSE (verified 2026-09-01). A strict SUBSET of
    # /api/worldview/overview, which returns {**status, "recon": ...} (worldview.py:34-49)
    # and is what the World tab actually renders (frontend/src/modes_world.tsx:22). Its
    # docstring aims it at "the HUD World tab", but the HUD chose the superset. A status
    # chip would re-render data already on screen.
    # RESTORED 2026-09-01 — see /api/desktop/plan. In-process consumer at
    # autonomy_coordinator.py:535 `from .operator_router import plan_payload`.
    "/api/operator/plan",
    # RESTORED 2026-09-01. Moved to MACHINE_FACING on a DESIGN judgment ("a HUD form letting a
    # human hand-type provenance into a tamper-evident intent log is worse than no control",
    # BACKLOG DRA-36) — the same kind of argument kept on THIS list for /api/context/compress
    # and /api/llm/openrouter, and not a claim that anything calls the route. Nothing does.
    "/api/security/audit/action",
    # RESTORED 2026-09-01. The MACHINE_FACING reason given was factually wrong: widget.py:158-166
    # render_snippet inlines colour/title/greeting INTO the emitted snippet, and the snippet's
    # only fetch (widget.py:118) posts to the /message route. Nothing fetches the config read.
    "/api/widget/{token}/config",
    "/api/worldview/status",
])

# Routes whose client call is BUILT rather than written: the last segment comes from a
# variable (`'/api/missions/' + id + '/' + action`), so no literal template exists for the
# matcher above to find. Each entry names the client file that builds it, and
# test_computed_url_callers_stay_real RE-DERIVES the claim — the named file must contain
# the route's stem and every static segment — so this cannot become a parking lot. Write
# the URL literally and the entry must be deleted, exactly like the punch list. These are
# NOT unfinished work: putting them on the punch list would record a false statement and
# send a future reader to build controls that already exist.
COMPUTED_URL_CALLERS: dict[str, str] = {
    # AcquisitionPanel: apiPost(`/api/acquisition/${…}/${action}`), action from the buttons
    "/api/acquisition/{name}/revoke": "frontend/src/gap.tsx",
    "/api/acquisition/{name}/rollback": "frontend/src/gap.tsx",
    # MCP panel: afetch(`/api/admin/mcp/${…}/${action}`), action = connected ? … : …
    "/api/admin/mcp/{name}/connect": "agents/web/static/admin.js",
    "/api/admin/mcp/{name}/disconnect": "agents/web/static/admin.js",
    # PromptsPanel: `const base = '/api/admin/prompts/' + agent`, then base + suffix
    "/api/admin/prompts/{agent_id}/ab": "frontend/src/gap.tsx",
    "/api/admin/prompts/{agent_id}/commit": "frontend/src/gap.tsx",
    "/api/admin/prompts/{agent_id}/diff": "frontend/src/gap.tsx",
    "/api/admin/prompts/{agent_id}/preview": "frontend/src/gap.tsx",
    "/api/admin/prompts/{agent_id}/rollback": "frontend/src/gap.tsx",
    "/api/admin/prompts/{agent_id}/version/{version}": "frontend/src/gap.tsx",
    # MissionsPanel: act('/api/missions/' + m.id + '/' + a), a from actionsFor(status)
    "/api/missions/{mission_id}/cancel": "frontend/src/gap.tsx",
    "/api/missions/{mission_id}/complete": "frontend/src/gap.tsx",
    # `pause` and `settle` below belong to groups already declared here; both were missing
    # and were being covered by their own panel tests instead. Excluding test files from the
    # client corpus (above) is what made that visible.
    "/api/missions/{mission_id}/pause": "frontend/src/gap.tsx",
    "/api/missions/{mission_id}/resume": "frontend/src/gap.tsx",
    "/api/missions/{mission_id}/start": "frontend/src/gap.tsx",
    # decidePayment: '/api/payments/' + id + '/' + action ('approve'|'reject'|'settle')
    "/api/payments/{payment_id}/reject": "frontend/src/api/actions.ts",
    "/api/payments/{payment_id}/settle": "frontend/src/api/actions.ts",
}


def _client_files() -> dict[str, str]:
    """Client sources by repo-relative path — the corpus every coverage check reads."""
    files: dict[str, str] = {}
    for pattern in _CLIENT_GLOBS:
        for path in REPO.glob(pattern):
            text = str(path)
            if "node_modules" in text or "/dist/" in text:
                continue
            if path.name.endswith(_GENERATED_CLIENT_FILES):
                continue
            if _is_test_client_file(path):
                continue
            try:
                files[path.relative_to(REPO).as_posix()] = path.read_text(
                    encoding="utf-8", errors="ignore")
            except OSError:
                continue
    return files


def _client_blob() -> str:
    return "\n".join(_client_files().values())


def _snapshot_routes() -> list[str]:
    """Route paths from the auth snapshot — resolved FastAPI truth rather than a regex
    over decorators. Same ground truth the route-auth matrix uses, which the audit called
    the best gate in the repo."""
    snap = json.loads((REPO / "tests/_snapshots/route_auth.json").read_text(encoding="utf-8"))
    return sorted({key.split(" ", 1)[1] for key in snap})


_PATH_PARAM = re.compile(r"\{[^}]*\}")
# A URL expression is written on one line. The longest interpolation any client actually
# uses is 38 chars (`/autonomy/tasks/${encodeURIComponent(String(taskId))}/decision`), so
# 60 is headroom rather than a tuning knob: every bound from 40 to 200 gives the identical
# verdict on all 394 routes.
_INTERPOLATION = r"[^\n]{0,60}?"


def _route_parts(path: str) -> tuple[str, list[str]]:
    """(stem before the first path parameter, the static chunks that follow it)."""
    chunks = _PATH_PARAM.split(path)
    return chunks[0].rstrip("/"), [c for c in chunks[1:] if c]


def _has_caller(path: str, blob: str) -> bool:
    """Does any client source mention this route?

    Clients build these URLs by interpolation (`/api/nodes/${id}/dispatch`), so the literal
    template never appears. Matching only the stem before the first parameter meant that
    once ANY route under a prefix was called, every parameterized route beneath it passed
    for free — 70 of them, seven with no caller anywhere. So the match must reach the
    route's LAST static segment: the stem, then each remaining chunk in order, on one line.
    """
    stem, tail = _route_parts(path)
    if len(stem) <= 5:
        return path in blob
    if not tail:
        return stem in blob
    pattern = re.escape(stem) + _INTERPOLATION + _INTERPOLATION.join(
        re.escape(chunk) for chunk in tail)
    return re.search(pattern, blob) is not None


def test_every_user_facing_route_has_a_caller_or_is_on_the_punch_list():
    """Coverage, not classification — the substance version of the parity gate."""
    blob = _client_blob()
    assert len(blob) > 100_000, "client sources did not load; this gate would pass vacuously"
    uncalled = [p for p in _snapshot_routes() if not _has_caller(p, blob)]
    unexplained = [p for p in uncalled
                   if p not in MACHINE_FACING and p not in UNCALLED_BACKLOG
                   and p not in COMPUTED_URL_CALLERS]
    assert not unexplained, (
        "these routes have no caller in any client and are not declared:\n  "
        + "\n  ".join(unexplained)
        + "\n\nWire one up, or add it to MACHINE_FACING with a reason (something other "
          "than our UI calls it), or to UNCALLED_BACKLOG if it is genuinely unfinished, "
          "or to COMPUTED_URL_CALLERS naming the client file that builds the URL."
    )


def test_the_uncalled_backlog_only_shrinks():
    """A punch-list that never shrinks is an allowance with extra steps.

    An entry that is now called, or no longer exists, must be REMOVED — otherwise the list
    quietly converts finished work into permanent permission.
    """
    blob = _client_blob()
    routes = set(_snapshot_routes())
    stale = sorted(p for p in UNCALLED_BACKLOG
                   if p not in routes or _has_caller(p, blob))
    assert not stale, (
        "these are on UNCALLED_BACKLOG but are now called or no longer exist — delete "
        "them from the list:\n  " + "\n  ".join(stale)
    )


def test_computed_url_callers_stay_real():
    """Same ratchet as the punch list. An entry must still be a route, its named client
    must still exist and still mention the stem AND every static segment, and the URL must
    still be built rather than written — the moment it is written literally the matcher
    sees it and the entry has to go.
    """
    blob = _client_blob()
    files = _client_files()
    routes = set(_snapshot_routes())
    problems = []
    for path, client in sorted(COMPUTED_URL_CALLERS.items()):
        source = files.get(client)
        stem, tail = _route_parts(path)
        words = [w for chunk in tail for w in chunk.split("/") if w]
        if path not in routes:
            problems.append(f"{path}: no longer a route")
        elif source is None:
            problems.append(f"{path}: {client} is not in the client corpus")
        elif stem not in source:
            problems.append(f"{path}: {client} never mentions {stem}")
        elif any(not re.search(rf"\b{re.escape(w)}\b", source) for w in words):
            problems.append(f"{path}: {client} never mentions its static segments")
        elif _has_caller(path, blob):
            problems.append(f"{path}: now written literally — delete the entry")
    assert not problems, "COMPUTED_URL_CALLERS has rotted:\n  " + "\n  ".join(problems)


def test_a_sub_route_cannot_ride_in_on_a_called_prefix():
    """The hole this gate had: matching only the stem before the first path parameter meant
    that once ANY route under a prefix was called, every parameterized route beneath it
    passed for free — 70 of them, seven with no caller anywhere.
    """
    blob = _client_blob()
    assert _has_caller("/api/review/queue", blob)           # the prefix really is wired
    assert not _has_caller("/api/review/{item_id}/a-suffix-nobody-calls", blob)
    assert _has_caller("/api/review/{item_id}/vote", blob)  # a real sub-route still counts


def test_the_classification_gate_cannot_stand_in_for_coverage():
    """Pins the defect itself, so nobody mistakes _classify for a coverage check again."""
    invented = "/api/admin/totally-invented-endpoint"
    assert _classify(invented) != "UNMAPPED", (
        "if this ever returns UNMAPPED, _classify has become a coverage check and this "
        "file's comments need rewriting"
    )
    assert not _has_caller(invented, _client_blob())
