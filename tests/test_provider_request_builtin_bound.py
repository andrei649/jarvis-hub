"""Built-in providers keep large prompts (Codex review, #1321).

``prepare_profile_messages`` defaulted to 256 KiB, so a 270 KB prompt that fits a
200K-token window raised ``ProfileRequestRefused`` on Claude, Gemini and OpenRouter.
Built-ins now default to ``BUILTIN_PROFILE_MESSAGE_BYTES``; isolated provider hooks
still pass their own 512 KiB bound.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agents.core.llm.provider_request import (
    BUILTIN_PROFILE_MESSAGE_BYTES,
    ProfileRequestRefused,
    prepare_profile_messages,
)

_PROFILE = SimpleNamespace(id="builtin-test", prepare_messages=lambda rows: rows)


def _prompt(size: int) -> list[dict]:
    return [{"role": "user", "content": "x" * size}]


def test_a_prompt_above_256_kib_reaches_a_builtin_provider():
    rows = prepare_profile_messages(_PROFILE, _prompt(270_000))
    assert rows == _prompt(270_000)


def test_the_builtin_bound_still_refuses_an_unbounded_request():
    with pytest.raises(ProfileRequestRefused):
        prepare_profile_messages(_PROFILE, _prompt(BUILTIN_PROFILE_MESSAGE_BYTES + 1))


def test_an_isolated_hook_bound_is_still_honoured():
    with pytest.raises(ProfileRequestRefused):
        prepare_profile_messages(_PROFILE, _prompt(600_000), maximum=512 * 1024)


# ── the row count (review of #1321) ──────────────────────────────────────────────
# A tool loop raised to its 32-round cap adds up to ten rows a round (one assistant row,
# eight calls and one overflow), so round 27 carries 262 rows; main sent it, the 256-row
# cap refused it on every built-in provider.

def _tool_history(rounds: int) -> list[dict]:
    rows = [{"role": "system", "content": "s"}, {"role": "user", "content": "go"}]
    for r in range(rounds):
        calls = [{"id": f"c{r}_{i}", "type": "function",
                  "function": {"name": "read_file", "arguments": "{}"}} for i in range(9)]
        rows.append({"role": "assistant", "content": "", "tool_calls": calls})
        rows += [{"role": "tool", "tool_call_id": c["id"], "content": "ok"} for c in calls]
    return rows


def test_a_long_tool_loop_history_reaches_a_builtin_provider():
    history = _tool_history(26)
    assert len(history) == 262
    assert len(prepare_profile_messages(_PROFILE, history)) == 262


def test_claude_builds_the_round_27_tool_request_of_a_long_loop():
    import asyncio

    from agents.core.llm.anthropic import ClaudeBackend

    payload = asyncio.run(ClaudeBackend("sk-test")._tool_payload(
        "claude-test", _tool_history(26), [], 256, 0.0))
    assert len(payload[0]["messages"]) > 26


def test_the_builtin_row_bound_and_the_hook_row_bound_still_refuse():
    from agents.core.llm.provider_request import (
        BUILTIN_PROFILE_MESSAGE_ROWS,
        HOOK_PROFILE_MESSAGE_ROWS,
    )

    rows = [{"role": "user", "content": "x"}]
    with pytest.raises(ProfileRequestRefused):
        prepare_profile_messages(_PROFILE, rows * (BUILTIN_PROFILE_MESSAGE_ROWS + 1))
    with pytest.raises(ProfileRequestRefused):
        prepare_profile_messages(_PROFILE, rows * (HOOK_PROFILE_MESSAGE_ROWS + 1),
                                 rows=HOOK_PROFILE_MESSAGE_ROWS)
