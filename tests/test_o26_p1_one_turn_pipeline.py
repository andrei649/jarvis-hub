"""O26-P1.1 — chat and stream share the same LLM-turn pipeline seams."""

import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))
sys.path.insert(0, str(repo_root / "tests"))

from golden_harness import make_golden_orchestrator  # noqa: E402

TURN = "Andrei Popescu lives in Bucharest and works at Innoveo."


def _enable_affect(orch) -> None:
    orch._runtime_settings.update({
        "cognition.enabled": True,
        "cognition.affect_enabled": True,
    })


@pytest.mark.parametrize("mode", ["plain", "stream"])
async def test_prompt_blocks_match_across_chat_modes(monkeypatch, tmp_path, mode):
    """Persona + runtime truth belong to the one turn prompt, not one surface."""
    orch, fake = await make_golden_orchestrator(monkeypatch, tmp_path)
    _enable_affect(orch)
    sid = await orch.memory.new_session(f"o26_p1_prompt_{mode}")

    if mode == "plain":
        await orch.handle_input(TURN, channel="web", session_id=sid)
    else:
        await orch.handle_input_stream(
            TURN, channel="web", on_token=lambda _t: None, session_id=sid)

    prompt = fake.calls[-1]["prompt"]
    assert "[persona]" in prompt
    assert "System runtime (ground truth" in prompt
    assert "LLM backend: fake-local" in prompt


async def test_completed_llm_turn_nudges_persona_affect(monkeypatch, tmp_path):
    orch, _fake = await make_golden_orchestrator(monkeypatch, tmp_path)
    _enable_affect(orch)
    sid = await orch.memory.new_session("o26_p1_persona_nudge")
    persona = orch.cognition.module("persona")

    before = persona.affect("jarvis")
    await orch.handle_input(TURN, channel="web", session_id=sid)
    after = persona.affect("jarvis")

    assert after != before
    assert after["arousal"] > before["arousal"]
