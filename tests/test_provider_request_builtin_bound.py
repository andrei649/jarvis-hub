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
