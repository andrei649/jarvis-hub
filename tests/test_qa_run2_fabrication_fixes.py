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


# ── the test/prod bleeds and the shared rails they exposed ────────────────────

def test_memory_dir_is_resolved_lazily_not_at_import():
    """RUN 2 found `install_smoke` restored as the owner's live session every boot.

    `scripts/install_smoke.py` DOES redirect JARVIS_HOME to a temp dir, but
    `memory/{conversation,persistence}.py` bound `MEMORY_DIR = data_root()` at import —
    before the redirect — so the fixture session was written into the live store and
    reloaded forever after. Same class as the autonomy.db leak fixed in #723.
    """
    for mod in ("agents/core/memory/conversation.py", "agents/core/memory/persistence.py"):
        src = (REPO / mod).read_text(encoding="utf-8")
        # anchored to column 0 so the explanatory comment (which quotes the old
        # binding) does not trip this — a naive substring match did exactly that.
        assert not re.search(r"^MEMORY_DIR = data_root\(\)", src, re.M), (
            f"{mod} binds the memory root at import — a caller redirecting JARVIS_HOME "
            "afterwards (install_smoke, any test) still writes into the live store"
        )
        assert "def memory_dir()" in src, f"{mod} must expose a lazily-resolved memory_dir()"


def test_install_smoke_state_stays_out_of_the_live_store(tmp_path, monkeypatch):
    """With JARVIS_HOME redirected, a session must land there — not in the repo."""
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    from agents.core.memory import persistence

    monkeypatch.setattr(persistence, "MEMORY_DIR", None)   # no override: follow the env
    assert persistence.memory_dir() == tmp_path, (
        f"memory_dir() ignored JARVIS_HOME: {persistence.memory_dir()} != {tmp_path}"
    )


def test_language_mirroring_is_a_shared_rail_not_a_persona_line():
    """RUN 2 finding CHT-070: a Romanian prompt to Steve came back entirely in English.

    "Romanian in, Romanian out" lived only in agents/jarvis/SOUL.md, so an agent-pinned
    turn never saw it. A cross-cutting rule cannot live in one persona.
    """
    src = (REPO / "agents/core/orchestrator.py").read_text(encoding="utf-8")
    assert "def _language_block" in src, "no shared language rail on the prompt path"
    start = src.index("def _language_block")
    block = src[start: src.index("def _data_grounding_block")]
    assert "SAME language" in block, "the language rail must require mirroring"
    # and it must actually be injected, at every assembly site
    assert src.count("self._language_block()") >= 2, (
        "the language rail is defined but not wired into every runtime_block assembly"
    )
