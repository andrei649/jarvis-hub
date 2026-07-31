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
    ("/api/widget/", "interop"),  # embeddable widget runtime (managed under Interop)
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
    ("/api/desktop", "build"),  # governed desktop operator (H15.3)
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

_CLIENT_GLOBS = (
    "frontend/src/**/*.ts", "frontend/src/**/*.tsx",
    "mobile/**/*.ts", "mobile/**/*.tsx",
    "agents/web/static/**/*.js", "agents/web/templates/**/*.html",
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
    "/api/oauth/auth-url": "OAuth dance, driven by the provider/browser",
    "/api/oauth/callback": "OAuth redirect target",
    "/api/nodes": "node mesh peer registry",
    "/api/nodes/register": "node mesh peer registration",
    "/api/nodes/{node_id}": "node mesh peer",
    "/api/nodes/{node_id}/dispatch": "node mesh dispatch",
    "/api/sync": "device sync transport",
    "/api/sync/pull": "device sync transport",
    "/api/sync/push": "device sync transport",
    "/api/capture/ingest": "passive-capture agent ingest",
    "/api/capture/surfaces": "passive-capture agent",
    "/api/channels/webhook": "inbound channel webhook",
    "/api/channels/pairing/request": "inbound pairing request from a sender",
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
    "/api/status": "alias probe"
}

# Today's uncalled user-facing routes. A punch-list, not an allowance: seeded from a real
# measurement, and rule 2 above keeps it honest.
UNCALLED_BACKLOG: frozenset[str] = frozenset([
    "/api/actions/request",
    "/api/admin/agents/stats",
    "/api/admin/rotate-tokens",
    "/api/agents/history",
    "/api/arena/match/{match_id}",
    "/api/autonomy/call",
    "/api/brain/summary",
    "/api/canvas/clear",
    "/api/channels/inbox/status",
    "/api/coach/curriculum",
    "/api/coach/review",
    "/api/coach/session",
    "/api/codeintel/reindex",
    "/api/codeintel/search",
    "/api/codeintel/stats",
    "/api/cognition/ensemble",
    "/api/cognition/honesty",
    "/api/cognition/learning",
    "/api/cognition/memory",
    "/api/cognition/personality",
    "/api/cognition/status",
    "/api/context/compress",
    "/api/creative/export-packs",
    "/api/creative/plan",
    "/api/digest/run",
    "/api/integrations/writeback",
    "/api/kg/ingest",
    "/api/kg/relations",
    "/api/llm/moe/route",
    "/api/llm/openrouter",
    "/api/market/brief",
    "/api/media/generate",
    "/api/memory/consolidate",
    "/api/memory/decay/candidates",
    "/api/memory/eval/corpus",
    "/api/memory/eval/run",
    "/api/memory/remember",
    "/api/metrics/capabilities",
    "/api/osint/brief",
    "/api/osint/correlate",
    "/api/payments/mandates",
    "/api/payments/request",
    "/api/presence/owner",
    "/api/quality/scores",
    "/api/review/flag",
    "/api/review/stats",
    "/api/secrets/broker/redact",
    "/api/security-skills/frameworks",
    "/api/security-skills/map",
    "/api/security-skills/playbook",
    "/api/security/audit/action",
    "/api/security/audit/anchor",
    "/api/security/audit/anchors",
    "/api/security/spotlight",
    "/api/skills/marketplace/install-zip",
    "/api/skills/marketplace/publish",
    "/api/skills/marketplace/uninstall",
    "/api/skills/pending",
    "/api/subagents",
    "/api/subagents/spawn",
    "/api/support/bundle",
    "/api/vlm/describe",
    "/api/vlm/status",
    "/api/voice/wyoming",
    "/api/workflows/hierarchical",
    "/api/workflows/traces",
    "/api/worldview/status",
    "/autonomy/observer/run",
    "/autonomy/preferences/suggestions",
    "/autonomy/status",
    "/skills/import",
    "/skills/imported"
])


def _client_blob() -> str:
    parts = []
    for pattern in _CLIENT_GLOBS:
        for path in REPO.glob(pattern):
            text = str(path)
            if "node_modules" in text or "/dist/" in text:
                continue
            if path.name.endswith(_GENERATED_CLIENT_FILES):
                continue
            try:
                parts.append(path.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
    return "\n".join(parts)


def _snapshot_routes() -> list[str]:
    """Route paths from the auth snapshot — resolved FastAPI truth rather than a regex
    over decorators. Same ground truth the route-auth matrix uses, which the audit called
    the best gate in the repo."""
    snap = json.loads((REPO / "tests/_snapshots/route_auth.json").read_text(encoding="utf-8"))
    return sorted({key.split(" ", 1)[1] for key in snap})


def _has_caller(path: str, blob: str) -> bool:
    """Does any client source mention this route?

    Matches the stem before the first path parameter: clients build those URLs by
    interpolation (`/api/nodes/${id}`), so the literal template never appears.
    """
    stem = re.split(r"\{", path)[0].rstrip("/")
    return (stem in blob) if len(stem) > 5 else (path in blob)


def test_every_user_facing_route_has_a_caller_or_is_on_the_punch_list():
    """Coverage, not classification — the substance version of the parity gate."""
    blob = _client_blob()
    assert len(blob) > 100_000, "client sources did not load; this gate would pass vacuously"
    uncalled = [p for p in _snapshot_routes() if not _has_caller(p, blob)]
    unexplained = [p for p in uncalled
                   if p not in MACHINE_FACING and p not in UNCALLED_BACKLOG]
    assert not unexplained, (
        "these routes have no caller in any client and are not declared:\n  "
        + "\n  ".join(unexplained)
        + "\n\nWire one up, or add it to MACHINE_FACING with a reason (something other "
          "than our UI calls it), or to UNCALLED_BACKLOG if it is genuinely unfinished."
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


def test_the_classification_gate_cannot_stand_in_for_coverage():
    """Pins the defect itself, so nobody mistakes _classify for a coverage check again."""
    invented = "/api/admin/totally-invented-endpoint"
    assert _classify(invented) != "UNMAPPED", (
        "if this ever returns UNMAPPED, _classify has become a coverage check and this "
        "file's comments need rewriting"
    )
    assert not _has_caller(invented, _client_blob())
