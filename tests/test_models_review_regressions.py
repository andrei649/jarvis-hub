"""Regressions from independent review of the model/session delivery."""
import os
import time
from datetime import UTC, datetime

import pytest

from agents.core.context_compressor import CompactionPolicy, ContextCompressor
from agents.core.conversation_clock import clock_block, parse_started_at
from agents.core.llm.gemini import GeminiBackend
from agents.core.llm.openrouter import OpenRouterBackend
from agents.core.llm.provider_request import compatible_parameters
from agents.core.llm.providers import ProviderProfile
from agents.core.llm.reasoning_effort import forget_reasoning_efforts
from agents.core.llm.request_context import current_session, session_scope


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="host timezone switching requires tzset")
@pytest.mark.parametrize(("birth", "rebuild", "expected"), [
    ("2026-09-15T12:00:00+00:00", datetime(2026, 11, 2, 21, 30, tzinfo=UTC), "Monday, November 02, 2026"),
    ("2026-01-15T12:00:00+00:00", datetime(2026, 4, 1, 21, 30, tzinfo=UTC), "Thursday, April 02, 2026"),
])
def test_persisted_local_birth_retains_day_across_dst(birth, rebuild, expected):
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Bucharest"
    time.tzset()
    try:
        # Both real callers use this .astimezone() conversion from stored UTC.
        born = parse_started_at(birth).astimezone()
        assert rebuild.astimezone().day == 2
        assert expected in clock_block(born, rebuild)
    finally:
        if previous is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = previous
        time.tzset()


@pytest.mark.asyncio
async def test_compatible_reconnect_can_remove_declarations():
    forget_reasoning_efforts("review-compatible")
    profile = ProviderProfile("review-compatible", "Review", "openai-compatible",
                              capabilities={"reasoning-effort"})
    original = OpenRouterBackend(profile=profile, reasoning_effort="high",
                                 effort_declarations={"review-model": ["high"]})
    await original.aclose()
    refreshed = OpenRouterBackend(profile=profile, reasoning_effort="high",
                                  effort_declarations={})
    try:
        assert compatible_parameters(refreshed.profile, "review-model", "high") == {}
    finally:
        await refreshed.aclose()
        forget_reasoning_efforts("review-compatible")


@pytest.mark.asyncio
async def test_another_gemini_constructor_preserves_admin_suppression():
    forget_reasoning_efforts("gemini")
    first = GeminiBackend("test", model="gemini-3.1-pro", reasoning_effort="high",
                          effort_declarations={"gemini-3.1-pro": []})
    second = None
    try:
        assert "thinkingConfig" not in first._build_payload("hi")["generationConfig"]
        second = GeminiBackend("test")
        assert "thinkingConfig" not in first._build_payload("hi")["generationConfig"]
    finally:
        await first.close()
        if second is not None:
            await second.close()
        forget_reasoning_efforts("gemini")


@pytest.mark.asyncio
@pytest.mark.parametrize(("soft", "hard"), [(.9, 1), (1, 1), (.85, .85), (.5, .5)])
async def test_hard_cap_causes_compaction_when_soft_is_above_85_percent(soft, hard):
    policy = CompactionPolicy(soft=soft, hard=hard, per_model={"m": 1000},
                              protect_head=0, protect_last_n=1)
    compressor = ContextCompressor(max_tokens=10000)
    turns = [{"role": "user", "content": str(i) + "x" * 343} for i in range(10)]
    assert compressor._used(turns) == 860
    result = await compressor.compact(turns, model="m", policy=policy)
    assert result["tier"] == "summarize"
    assert result["compressed"]
    assert result["tokens"] < compressor._used(turns)
    assert result["kept"] == turns[-1:]
    assert policy.soft <= policy.hard <= .85


def test_session_scope_restores_outer_identity_after_exception():
    assert current_session() is None
    with session_scope("outer"):
        with pytest.raises(RuntimeError), session_scope("inner"):
            assert current_session() == "inner"
            raise RuntimeError("simulated cancellation boundary")
        assert current_session() == "outer"
    assert current_session() is None


@pytest.mark.asyncio
async def test_live_compatible_snapshots_do_not_leak_or_follow_mutable_inputs():
    from agents.core.llm.reasoning_effort import declare_reasoning_efforts

    profile = ProviderProfile("review-compatible", "Review", "openai-compatible",
                              capabilities={"reasoning-effort"})
    declarations = {"review-model": ["low"]}
    first = OpenRouterBackend(profile=profile, effort_declarations=declarations)
    second = OpenRouterBackend(profile=profile, effort_declarations={"review-model": ["high"]})
    empty = OpenRouterBackend(profile=profile, effort_declarations={})
    try:
        declarations["review-model"].append("high")
        declare_reasoning_efforts(profile.id, "review-model", ["medium"])
        assert compatible_parameters(first.profile, "review-model", "ultra") == {"reasoning_effort": "low"}
        assert compatible_parameters(second.profile, "review-model", "ultra") == {"reasoning_effort": "high"}
        assert compatible_parameters(empty.profile, "review-model", "ultra") == {}
        with pytest.raises(TypeError):
            first.profile.reasoning_declarations["review-model"] = ("high",)
    finally:
        await first.aclose()
        await second.aclose()
        await empty.aclose()
        forget_reasoning_efforts(profile.id)
