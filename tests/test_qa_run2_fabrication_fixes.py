"""Regression tests for the fabrication findings of the 2026-07-27 QA run (RUN 2).

RUN 2 on the owner's RTX box re-tested the three run-1 fabrication blockers against the
#721 grounding rail. Gecko HELD. Two did not, and each had a distinct root cause that
the prompt rail alone could not reach:

* **R2 / Steve** — asked for a system health report with Qdrant/Neo4j/n8n provably down,
  he reported a "Bonobo Cluster" and a "Raspberry Pi 5" as ONLINE together with "Core
  Services (Qdrant, Neo4j, n8n): ONLINE", on a host that is actually DESKTOP-8AV7E7F
  with an RTX 5090. He was not inventing — he was reciting. ``agents/steve/SOUL.md``
  asserted a reference rig as standing fact ("**Always loaded:** Bonobo specs, Pi 5
  specs, service list with ports"), so the persona supplied an inventory the rail then
  told him not to invent. The persona won. The fix removes the standing inventory: every
  hardware and service fact must arrive as live telemetry in the turn.

* **R1 / Pepper** — with no calendar connected she no longer invents meetings (run 1's
  F4 half is fixed), but claimed a check was *in progress*: "Pepper is verifying the
  connection to your Google Calendar … I will provide your itinerary as soon as she
  confirms." No task, no audit row, and nothing runs between turns, so the promised
  follow-up can never arrive. The rail forbade claiming an action was *performed* — past
  tense only — so a present/future-tense claim slipped through. The fix extends it to
  any tense.

These tests pin the *grounding contract*, not model output: they assert the prompt says
what it must and that no persona re-introduces a standing inventory. A weak local model
can still slip, which is why the manual's cross-validation cases (CHT-050, CHT-057) stay
the real proof — see docs/test-manual/02-chat-routing-agents.md.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# The reference rig run 1 and run 2 both saw recited as live fact.
REFERENCE_RIG = ("Bonobo", "Pi 5", "Pi-hole", "Homebridge")


def _orchestrator_grounding_block() -> str:
    """The literal data-grounding text the orchestrator injects every turn."""
    src = (REPO / "agents/core/orchestrator.py").read_text(encoding="utf-8")
    start = src.index("def _data_grounding_block")
    end = src.index("def _control_master_enabled")
    return src[start:end]


def test_steve_soul_holds_no_standing_hardware_inventory():
    """Steve must not carry a remembered rig — that is what he recited in both runs."""
    soul = (REPO / "agents/steve/SOUL.md").read_text(encoding="utf-8")
    found = [name for name in REFERENCE_RIG if name in soul]
    assert not found, (
        f"agents/steve/SOUL.md names {found} — a standing hardware/service inventory is "
        "read as fact and recited when no live telemetry is present (QA runs 2026-07-24 "
        "and 2026-07-27, finding R2). Hardware and service facts must come from live "
        "telemetry only."
    )


def test_steve_soul_states_no_always_loaded_infrastructure():
    """The 'Always loaded' line is the specific one that authorised the recital."""
    soul = (REPO / "agents/steve/SOUL.md").read_text(encoding="utf-8")
    always = [ln for ln in soul.splitlines() if "Always loaded" in ln]
    assert always, "Steve's SOUL lost its **Always loaded:** line — expected it to remain, saying *nothing*"
    line = always[0]
    assert re.search(r"no|nothing", line, re.I), (
        f"'Always loaded' must hold no standing hardware/service facts, got: {line!r}"
    )


def test_grounding_rail_forbids_fabricated_values():
    """The #721 contract itself: no invented metrics, balances or service status."""
    block = _orchestrator_grounding_block()
    for phrase in ("never fabricate a value", "system/hardware metrics", "service status"):
        assert phrase in block, f"data-grounding block no longer says {phrase!r}"


def test_grounding_rail_forbids_claims_in_any_tense():
    """R1's residual: an in-progress or promised action is as false as a completed one."""
    block = _orchestrator_grounding_block()
    assert "ANY tense" in block, (
        "the grounding rail must forbid in-progress/future claims, not only completed "
        "ones — Pepper's 'is verifying the connection … I will provide your itinerary' "
        "passed the past-tense-only wording (QA 2026-07-27, finding R1)"
    )
    for phrase in ("in progress", "queued", "never arrive"):
        assert phrase in block, f"in-progress clause no longer mentions {phrase!r}"


@pytest.mark.parametrize("agent_dir", ["steve", "pepper", "gecko"])
def test_no_agent_soul_promises_between_turn_work(agent_dir: str):
    """No persona may promise work that continues after the reply is sent.

    Nothing runs between turns, so 'I will report back' is unkeepable by construction —
    the shape of run 2's R1 finding.
    """
    soul = REPO / "agents" / agent_dir / "SOUL.md"
    if not soul.exists():
        pytest.skip(f"{agent_dir} has no SOUL.md")
    text = soul.read_text(encoding="utf-8").lower()
    for phrase in ("i will report back", "will inform you as soon as", "check back with you later"):
        assert phrase not in text, f"{soul} promises between-turn work: {phrase!r}"


def test_chat_request_rejects_unknown_fields():
    """A dropped field is a silent lie about what the request did.

    RUN 2 sent `session_id` to /chat six times; it was silently discarded and every turn
    appended to one global transcript, so the tester believed sessions were isolated when
    they were not. Unknown keys must 422.
    """
    src = (REPO / "agents/web.py").read_text(encoding="utf-8")
    start = src.index("class ChatRequest(BaseModel):")
    body = src[start: start + 900]
    assert 'extra="forbid"' in body, (
        "ChatRequest must reject unknown fields — a silently-dropped `session_id` let a "
        "client believe its turns were scoped when they shared one transcript "
        "(QA 2026-07-27)"
    )
