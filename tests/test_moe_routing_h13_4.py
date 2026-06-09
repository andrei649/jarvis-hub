"""H13.4 — MoE hybrid-reasoning routing. Offline."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

from agents.core.llm.moe_routing import decide_thinking_mode, route_moe, MOE_MODELS


def test_decide_thinking_mode():
    assert decide_thinking_mode("explain why the sky is blue") is True   # reasoning hint
    assert decide_thinking_mode("hi") is False                            # trivial
    assert decide_thinking_mode("x" * 300) is True                        # long
    assert decide_thinking_mode("what? really? sure?") is True            # multi-question


def test_route_moe_thinking():
    r = route_moe("debug this step by step", model="gpt-oss-20b")
    assert r["thinking"] is True and r["max_tokens"] == 8192 and r["directive"] == "/think"
    assert r["collapses_tiers"] is True


def test_route_moe_non_thinking():
    r = route_moe("hello", model="qwen3-30b-a3b")
    assert r["thinking"] is False and r["directive"] == "/no_think" and r["max_tokens"] == 1024


def test_route_moe_force_override():
    assert route_moe("hello", force=True)["thinking"] is True
    assert route_moe("explain why", force=False)["thinking"] is False


def test_unknown_model_no_thinking():
    r = route_moe("explain why in detail", model="some-dense-model")
    assert r["thinking"] is False and r["collapses_tiers"] is False
    assert set(MOE_MODELS) == {"gpt-oss-20b", "qwen3-30b-a3b"}
