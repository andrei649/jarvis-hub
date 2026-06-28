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
import re
from pathlib import Path

_AGENTS = Path(__file__).resolve().parent.parent / "agents"
WEB = _AGENTS / "web.py"
# CLN-3 moves routes out of the web.py god-object into per-domain APIRouters in
# agents/core/routers/. The parity gate must still see every route, so it scans
# both the inline @app.* routes in web.py AND the @router.* routes in those
# extracted modules — otherwise an extracted endpoint would silently escape the
# "every route has a v2 home" check.
ROUTERS = _AGENTS / "core" / "routers"

# Ordered (prefix, surface); first match wins, so put the more specific prefixes
# first. Surfaces mirror the v2 modes + chrome. NOT_IN_HUD = surfaced nowhere by
# design (machine-facing). Keep this in sync with the v2 IA when adding routes.
RULES = [
    # served shells / infra
    ("/v2", "shell"), ("/v1", "shell"), ("/static", "shell"), ("/favicon", "shell"), ("/sw.js", "shell"),
    ("/admin", "admin"),
    # machine-facing — intentionally not a HUD surface
    ("/.well-known/", "NOT_IN_HUD"),
    ("/healthz", "NOT_IN_HUD"),  # H23.11 liveness probe (LB / systemd / Docker HEALTHCHECK)
    ("/readyz", "NOT_IN_HUD"),   # H23.11 readiness probe (503 until boot completes)
    ("/metrics", "NOT_IN_HUD"),  # AUD-17 Prometheus golden-signals scrape (machine-facing)
    ("/api/mcp/server", "NOT_IN_HUD"),
    ("/api/memory/tool-spec", "NOT_IN_HUD"),
    ("/api/memory/search-tool", "NOT_IN_HUD"),
    ("/api/widget/", "interop"),  # embeddable widget runtime (managed under Interop)
    # cockpit / conversation
    ("/chat", "cockpit"), ("/api/status", "cockpit"), ("/status", "cockpit"),
    ("/api/agents", "agents"), ("/agents", "agents"), ("/dashboard", "cockpit"),
    ("/api/dashboard", "cockpit"),  # P1 G1 unified "Today in Jarvis" feed (home narrative)
    ("/ticker", "cockpit"), ("/tasks", "cockpit"), ("/api/cognition", "cockpit"),
    ("/tts", "cockpit"), ("/sessions", "cockpit"), ("/memory/clear", "cockpit"),
    ("/api/canvas", "cockpit"),
    ("/api/onboarding", "cockpit"),  # H23.20 first-run wizard + activation funnel (lands in the cockpit)
    ("/api/system/", "cockpit"),  # 0.62 System Profiles — usage-mode selector (system/home setting)
    ("/api/trust/status", "topbar"),
    # memory & knowledge
    ("/api/osint/", "knowledge"),  # P2 OSINT pack — the Knowledge/"Vision · OSINT" surface (modes4)
    ("/api/kg/", "memory"), ("/api/memory/", "memory"), ("/memory/stats", "memory"),
    ("/memory", "memory"), ("/api/local-docs", "memory"), ("/api/capture", "memory"),
    ("/api/context", "memory"),  # runtime context compression (H20.3)
    ("/api/coach/", "knowledge"),  # 0.43 Learning Coach pack — spaced repetition + curriculum
    # finance / market intel
    ("/api/market/", "finance"),  # P3 Market Intel pack — the Finance surface (modes4 "Gecko")
    # trust / security / payments
    ("/api/security-skills/", "trust"),  # 0.42 Security Skills pack — curated ATT&CK/D3FEND/CSF knowledge
    ("/api/security/", "trust"), ("/security", "trust"), ("/api/secrets/", "trust"),
    ("/api/payments", "trust"),
    # autonomy
    ("/autonomy/", "autonomy"), ("/api/autonomy/", "autonomy"), ("/api/actions", "autonomy"),
    ("/api/missions", "autonomy"),  # Mission Workspaces (0.32) — long-horizon workspaces
    ("/api/reflection", "autonomy"), ("/api/schedule/parse", "autonomy"),
    ("/api/transcripts", "autonomy"),
    # build (workflows / skills / sandbox / grammar / creative pipeline)
    ("/api/creative/", "build"),  # P4 Creative pack — the Build surface (asset pipeline, modes2)
    ("/api/workflows", "build"), ("/api/skills", "build"), ("/skills", "build"),
    ("/sandbox", "build"), ("/api/llm/grammar", "build"), ("/api/browser", "build"),
    ("/api/toolrpc", "build"),  # governed Tool-RPC for sandboxed pipelines (H20.1)
    ("/api/vlm", "build"),  # vision-language model adapter (H13.1)
    ("/api/desktop", "build"),  # governed desktop operator (H15.3)
    ("/api/media", "build"),  # governed media generation (H12.24)
    # observe (traces / eval / quality / review / arena / resilience / bench / cost)
    ("/api/traces", "observe"), ("/api/eval", "observe"), ("/api/quality", "observe"),
    ("/api/review", "observe"), ("/api/arena", "observe"), ("/api/resilience", "observe"),
    ("/bench", "observe"), ("/api/cost", "observe"), ("/api/analytics", "observe"),
    ("/api/feedback", "observe"),  # H23.21 design-partner NPS/feedback (owner reviews it here)
    ("/api/metrics", "observe"),  # MOONSHOT §6 north-star meter (sibling of analytics/cost)
    ("/api/digest", "observe"),
    ("/brain", "observe"), ("/api/brain", "observe"),  # neural-mesh brain (live agents+models)
    ("/api/health/components", "observe"),
    # interop (a2a / mcp client mgmt / webhooks / external write-back + social)
    ("/api/a2a/", "interop"), ("/api/admin/mcp", "interop"), ("/api/admin/widgets", "interop"),
    ("/api/mcp", "interop"), ("/api/webhooks", "interop"), ("/api/integrations/", "interop"),
    ("/api/sync", "interop"),  # E2E device sync (H12.13)
    ("/api/nodes", "interop"),  # governed node mesh (H12.17)
    # comms (rooms / notes / channel sender pairing / mic satellites)
    ("/api/rooms", "comms"), ("/api/notes", "comms"), ("/api/channels/", "comms"),
    ("/api/satellites", "comms"),  # shared-GPU mic satellites (H12.8)
    # agent ops (heartbeat / learning / templates)
    ("/heartbeat", "agents"), ("/learning", "agents"), ("/api/learning", "agents"),
    ("/api/agent-templates", "agents"), ("/api/subagents", "agents"),  # H20.6
    # admin (settings / env / models / llm lifecycle / oauth / oracle / plugins / voice / prompts / stats)
    ("/api/admin/", "admin"), ("/plugins", "admin"), ("/api/models", "admin"),
    ("/api/llm/", "admin"), ("/api/oauth", "admin"), ("/api/oracle", "admin"),
    ("/api/voice", "admin"),
]

CORE_SURFACES = ["cockpit", "agents", "memory", "trust", "autonomy", "build",
                 "observe", "interop", "comms", "admin"]


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
        "a mode or to NOT_IN_HUD in tests/test_hud_v2_parity.py:RULES:\n  "
        + "\n  ".join(unmapped)
    )


def test_core_surfaces_each_cover_a_route():
    covered = {_classify(p) for p in _routes()}
    missing = [s for s in CORE_SURFACES if s not in covered]
    assert not missing, f"v2 surfaces with no mapped route (IA regression?): {missing}"
