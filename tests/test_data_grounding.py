"""Anti-fabrication grounding (2026-07-24 QA blockers).

The QA run found agents (Pepper/calendar, Steve/system-health, Gecko/finance)
confidently fabricating data when the backing connector was absent — because the
gatherer stays silent on a disconnected tool, so the model saw only its
capability-describing SOUL + the question and confabulated. `_data_grounding_block`
now injects, every turn, what the model may actually read and a refuse-don't-invent
instruction. These tests pin the block's content and that it reaches the prompt on
every path (the wiring that would have caught the blocker).
"""

import re
import sys
from pathlib import Path
from types import SimpleNamespace

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.orchestrator import Orchestrator


def _orch():
    return Orchestrator.__new__(Orchestrator)


def test_empty_block_says_none_and_forbids_fabrication():
    b = _orch()._data_grounding_block({})
    assert "connected this turn: none" in b
    low = b.lower()
    # names the fabrication classes the QA run hit + the honest-fallback rule
    for token in ("not connected", "invent", "balance", "system", "service status",
                  "never claim you performed an action"):
        assert token in low, f"grounding block missing: {token!r}"


def test_block_names_only_truthy_connected_sources():
    b = _orch()._data_grounding_block({"calendar": "events…", "weather": "", "email": "msgs"})
    header = b.split("connected this turn:")[1].splitlines()[0]
    assert "calendar" in header and "email" in header
    assert "weather" not in header          # empty value → not a live source


async def test_grounding_flows_into_agent_turn_text():
    o = _orch()
    o._persona_prompt_block = lambda a: ""
    o._living_core_memory_block = lambda: ""

    async def _ctx(_aid):
        return ""
    o.memory = SimpleNamespace(get_agent_context=_ctx)

    # Emulate exactly what handle_input_stream / _call_agents_parallel now build.
    runtime_block = o._runtime_state_block() + o._data_grounding_block({})
    text = await o._build_agent_turn_text(
        "pepper", "Ce am pe agenda azi?",
        history="", plugin_block="", recall_block="", runtime_block=runtime_block,
    )
    assert "Data grounding" in text
    assert "not connected" in text.lower()
    assert "Ce am pe agenda azi?" in text        # the user question survives


def test_both_prompt_paths_wire_the_grounding():
    """Ratchet: every place runtime_block is built must append the data grounding,
    so a future edit can't silently drop it from the stream or parallel path."""
    src = (repo_root / "agents" / "core" / "orchestrator.py").read_text(encoding="utf-8")
    assigns = re.findall(r"runtime_block = self\._runtime_state_block\(\)[^\n]*", src)
    assert len(assigns) >= 2, f"expected ≥2 runtime_block build sites, found {len(assigns)}"
    for line in assigns:
        assert "_data_grounding_block" in line, f"prompt path missing grounding: {line.strip()}"
