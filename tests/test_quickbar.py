"""0.64 Floating Bar + Global Hotkey — offline command-service core.

The bar's brain resolves a typed line into a *plan* (navigate/summon/query/…) and never
performs the action. Grounded in the real HUD grammar (app.tsx modes + center tabs) and the
router's agent roster; honest (unmatched → unresolved, never guessed); bounded recall.
"""
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from core.quickbar import (  # noqa: E402
    AGENTS,
    HUD_MODES,
    CommandBar,
    help_commands,
    parse_command,
)


# ── slash + verb navigation (grounded destinations) ───────────────
def test_slash_navigation_maps_to_real_modes_and_tabs():
    assert parse_command("/memory") == {"kind": "navigate", "mode": "memory", "input": "/memory"}
    # a center tab opens inside the cockpit view
    p = parse_command("/artifacts")
    assert p["kind"] == "navigate" and p["mode"] == "cockpit" and p["tab"] == "artifacts"


def test_verb_navigation():
    for line in ("open artifacts", "go to memory", "show cognition"):
        assert parse_command(line)["kind"] == "navigate"
    # a verb we know pointed at a destination we don't → not a false navigate
    assert parse_command("open teleporter")["kind"] != "navigate"


def test_every_hud_mode_is_reachable_by_slash():
    for m in HUD_MODES:
        assert parse_command(f"/{m}")["kind"] == "navigate"


# ── direct agent summon (roster-grounded, honest on misses) ───────
def test_summon_by_at_and_colon():
    a = parse_command("@friday what's the weather in Cluj")
    assert a["kind"] == "summon" and a["agent"] == "friday"
    assert a["text"] == "what's the weather in Cluj"          # original casing preserved
    b = parse_command("gecko: how much did I spend")
    assert b["kind"] == "summon" and b["agent"] == "gecko" and b["text"] == "how much did I spend"


def test_unknown_agent_is_unresolved_never_guessed():
    p = parse_command("@nobody do a thing")
    assert p["kind"] == "unresolved" and "nobody" in p["reason"]


def test_bare_agent_name_is_a_query_not_a_summon():
    # "friday" with no colon/@ is ambiguous → treated as a query, not a hijacked summon.
    assert parse_command("friday")["kind"] == "query"


# ── natural query + routing hint from the shared INTENT_RULES ─────
def test_query_hint_is_grounded_in_router_rules():
    assert parse_command("what's the weather tomorrow")["route_hint"] == "friday"
    assert parse_command("show me my budget")["route_hint"] == "gecko"
    assert parse_command("any satellite overpass tonight")["route_hint"] == "argus"


def test_query_without_a_trigger_has_no_hint():
    p = parse_command("xylophone quokka zeppelin")
    assert p["kind"] == "query" and p["route_hint"] is None and p["matched"] == []


# ── help / empty / unknown slash / bounds ─────────────────────────
def test_help_and_empty_and_unknown_slash():
    assert parse_command("/help")["kind"] == "help"
    assert parse_command("   ")["kind"] == "empty"
    assert parse_command("/warpdrive")["kind"] == "unresolved"


def test_help_menu_lists_real_destinations():
    cmds = {c["command"] for c in help_commands()}
    assert "/memory" in cmds and "/artifacts" in cmds


def test_input_is_length_bounded():
    p = parse_command("x" * 5000)
    assert len(p["input"]) == 2000


def test_slash_agent_shorthand_summons():
    p = parse_command("/ultron scan the ports")
    assert p["kind"] == "summon" and p["agent"] == "ultron" and p["text"] == "scan the ports"


# ── CommandBar: bounded, deduped, actionable-only history ─────────
def test_history_records_only_actionable_and_is_bounded():
    bar = CommandBar(max_history=3)
    bar.resolve("/help")                 # not actionable → not recorded
    bar.resolve("   ")                   # empty → not recorded
    bar.resolve("what's the weather")    # query → recorded
    bar.resolve("/memory")               # navigate → recorded
    bar.resolve("@friday hi")            # summon → recorded
    bar.resolve("open artifacts")        # navigate → recorded (evicts oldest)
    hist = bar.history()
    assert len(hist) == 3                 # capped at max_history
    assert hist[0] == "open artifacts"    # most recent first
    assert "what's the weather" not in hist   # evicted


def test_history_dedupes_preserving_recency():
    bar = CommandBar()
    bar.resolve("/memory")
    bar.resolve("what's the weather")
    bar.resolve("/memory")               # repeat
    hist = bar.history()
    assert hist == ["/memory", "what's the weather"]
    bar.clear_history()
    assert bar.history() == []


def test_agents_roster_is_nonempty_and_from_router():
    assert "friday" in AGENTS and "gecko" in AGENTS and len(AGENTS) >= 10
