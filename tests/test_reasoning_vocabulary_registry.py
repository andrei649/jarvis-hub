"""H679 — per-model reasoning-effort vocabularies, clamped by one canonical helper.

The row exists because two answers that look alike produce opposite request
bodies: "nobody has declared what this model takes" (leave the transport alone)
and "this model rejects every effort level" (omit the field). A two-state
contract loses the second one, and losing it is a 400 the owner reads as "Nerva
is broken".
"""

import pytest

from agents.core.llm.providers import get_profile
from agents.core.llm.reasoning_effort import (
    LADDER,
    apply_anthropic,
    clamp_reasoning_effort,
    declare_reasoning_efforts,
    forget_reasoning_efforts,
    supported_reasoning_efforts,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """No declaration outlives its test — a stale one would shadow the table."""
    forget_reasoning_efforts()
    yield
    forget_reasoning_efforts()


# ── the tri-state itself ─────────────────────────────────────────────────────

def test_an_undeclared_model_answers_none_not_empty():
    """The distinction the whole row is about. `None` is not `()`."""
    answer = supported_reasoning_efforts("gemini", "gemini-2.5-pro")
    assert answer is None
    assert answer != ()


def test_a_known_family_without_an_effort_vocabulary_answers_empty():
    """Sonnet 4.5 takes a thinking budget but errors on any effort level, so the
    honest answer is a declared empty tuple — 'omit the field', not 'unknown'."""
    assert supported_reasoning_efforts("anthropic", "claude-sonnet-4-5") == ()


def test_a_declared_family_answers_its_vocabulary_weakest_first():
    vocabulary = supported_reasoning_efforts("anthropic", "claude-opus-5")
    assert vocabulary == ("low", "medium", "high", "xhigh", "max")
    ranks = [LADDER.index(level) for level in vocabulary]
    assert ranks == sorted(ranks)


def test_an_unknown_model_id_is_undeclared_rather_than_rejecting():
    """A model this build has never seen must not be told 'you take nothing' —
    that would strip parameters from a wire we know nothing about."""
    assert supported_reasoning_efforts("anthropic", "claude-zeta-9") is None


# ── declaring, and the cold-cache rule ───────────────────────────────────────

def test_a_declaration_is_answered_from_cache_on_the_hot_path():
    declare_reasoning_efforts("gemini", "gemini-2.5-pro", ["low", "high"])
    assert supported_reasoning_efforts("gemini", "gemini-2.5-pro") == ("low", "high")


def test_a_cold_catalog_reads_as_undeclared_and_never_blocks():
    """Before anything declares it, the answer is None. The hot path asks and
    gets an answer immediately; it does not wait for a catalog to warm."""
    assert supported_reasoning_efforts("openrouter", "some/model") is None
    declare_reasoning_efforts("openrouter", "some/model", ["medium"])
    assert supported_reasoning_efforts("openrouter", "some/model") == ("medium",)


def test_declaring_an_empty_list_is_a_real_answer_not_a_reset():
    """This is how a catalog says 'this one rejects reasoning fields'."""
    declare_reasoning_efforts("gemini", "gemini-2.5-flash", [])
    assert supported_reasoning_efforts("gemini", "gemini-2.5-flash") == ()
    assert clamp_reasoning_effort("gemini", "gemini-2.5-flash", "high") == (None, "unsupported")


def test_a_declaration_overrides_the_built_in_table():
    """A family whose contract moves under us gets corrected without a release."""
    assert supported_reasoning_efforts("anthropic", "claude-opus-5")[-1] == "max"
    declare_reasoning_efforts("anthropic", "claude-opus-5", ["low", "medium"])
    assert supported_reasoning_efforts("anthropic", "claude-opus-5") == ("low", "medium")


def test_forgetting_one_provider_leaves_the_others_declared():
    declare_reasoning_efforts("gemini", "m", ["low"])
    declare_reasoning_efforts("openrouter", "m", ["high"])
    forget_reasoning_efforts("gemini")
    assert supported_reasoning_efforts("gemini", "m") is None
    assert supported_reasoning_efforts("openrouter", "m") == ("high",)


def test_a_declaration_accepts_a_written_list_and_drops_off_ladder_levels():
    """Operators write 'low, high'; a rung the clamp cannot rank is not a rung."""
    assert declare_reasoning_efforts("gemini", "m", "low, high") == ("low", "high")
    assert declare_reasoning_efforts("gemini", "n", ["low", "turbo", 7, None]) == ("low",)


def test_a_declaration_is_reordered_onto_the_ladder():
    """Weakest first is part of the contract, not the caller's problem."""
    assert declare_reasoning_efforts("gemini", "m", ["max", "low", "high"]) == (
        "low", "high", "max",
    )


# ── the canonical clamp ──────────────────────────────────────────────────────

def test_the_clamp_walks_down_and_never_escalates():
    declare_reasoning_efforts("gemini", "m", ["low", "medium"])
    assert clamp_reasoning_effort("gemini", "m", "max") == ("medium", "clamped")


def test_the_clamp_is_monotonic_across_the_whole_ladder():
    """The Nebius bug: a hand-rolled map had `ultra` fall through to `medium`
    while `xhigh` mapped to `high` — an inversion that is silent and spends more
    on the cheap request than on the expensive one."""
    declare_reasoning_efforts("gemini", "m", ["low", "medium", "high"])
    seen = [clamp_reasoning_effort("gemini", "m", level)[0] for level in LADDER[1:]]
    ranks = [LADDER.index(level) for level in seen if level is not None]
    assert ranks == sorted(ranks), seen
    assert clamp_reasoning_effort("gemini", "m", "ultra")[0] == "high"
    assert clamp_reasoning_effort("gemini", "m", "xhigh")[0] == "high"


def test_the_two_none_answers_are_told_apart_by_reason():
    """Both send no effort field, but for opposite reasons — and a transport has
    to treat them differently: leave defaults alone vs strip the field."""
    assert clamp_reasoning_effort("gemini", "unknown-model", "high") == (None, "undeclared")
    declare_reasoning_efforts("gemini", "declared", [])
    assert clamp_reasoning_effort("gemini", "declared", "high") == (None, "unsupported")


def test_an_unreadable_level_is_named_rather_than_guessed():
    declare_reasoning_efforts("gemini", "m", ["low", "high"])
    assert clamp_reasoning_effort("gemini", "m", "banana") == (None, "unreadable")


def test_an_exactly_supported_level_is_reported_as_exact():
    declare_reasoning_efforts("gemini", "m", ["low", "high"])
    assert clamp_reasoning_effort("gemini", "m", "high") == ("high", "exact")


def test_a_level_weaker_than_the_whole_vocabulary_floors():
    declare_reasoning_efforts("gemini", "m", ["high", "max"])
    assert clamp_reasoning_effort("gemini", "m", "minimal") == ("high", "floored")


# ── the hook on the provider profile ─────────────────────────────────────────

def test_the_profile_answers_the_tri_state_for_its_own_id():
    anthropic = get_profile("anthropic")
    assert anthropic.supported_reasoning_efforts("claude-opus-5")[-1] == "max"
    assert anthropic.supported_reasoning_efforts("claude-sonnet-4-5") == ()
    assert get_profile("gemini").supported_reasoning_efforts("gemini-2.5-pro") is None


def test_every_builtin_profile_answers_undeclared_before_anything_declares_it():
    """No profile may claim a vocabulary it has not been given — that claim is
    what produces the 400 this row is named after."""
    for provider_id in ("lm-studio", "ollama", "openrouter", "openai-compatible"):
        assert get_profile(provider_id).supported_reasoning_efforts("any-model") is None


def test_the_profile_clamps_through_the_same_helper():
    assert get_profile("anthropic").clamp_reasoning_effort("claude-opus-4-5", "ultra") == (
        "high", "clamped",
    )


def test_the_vendor_union_is_not_the_per_model_answer():
    """`reasoning_efforts` is a display-level union; an empty one says nothing
    about any particular model, which is why the hook exists at all."""
    gemini = get_profile("gemini")
    assert gemini.reasoning_efforts == ()
    assert gemini.supported_reasoning_efforts("gemini-2.5-pro") is None


# ── the hook is load-bearing on the request path ─────────────────────────────

def _payload(model="claude-opus-5"):
    return {"model": model, "max_tokens": 4096, "temperature": 0.7}


def test_a_declaration_reaches_the_anthropic_wire():
    """Not an interface: the declared vocabulary decides the request body."""
    before = _payload()
    apply_anthropic(before, "claude-opus-5", "max")
    assert before["output_config"]["effort"] == "max"

    declare_reasoning_efforts("anthropic", "claude-opus-5", ["low", "medium"])
    after = _payload()
    apply_anthropic(after, "claude-opus-5", "max")
    assert after["output_config"]["effort"] == "medium"


def test_declaring_a_model_empty_silences_the_effort_field_on_the_wire():
    declare_reasoning_efforts("anthropic", "claude-opus-5", [])
    payload = _payload()
    plan = apply_anthropic(payload, "claude-opus-5", "max")
    assert "output_config" not in payload
    assert plan.effort is None


def test_an_adaptive_family_with_no_vocabulary_is_not_called_a_budget():
    """It builds a thinking block and no effort field; calling that reason
    'budget' claimed a token budget that was never constructed."""
    declare_reasoning_efforts("anthropic", "claude-opus-5", [])
    payload = _payload()
    plan = apply_anthropic(payload, "claude-opus-5", "max")
    assert payload["thinking"] == {"type": "adaptive"}
    assert plan.reason == "thinking-only"


def test_forgetting_a_declaration_restores_the_built_in_table_on_the_wire():
    declare_reasoning_efforts("anthropic", "claude-opus-5", ["low"])
    forget_reasoning_efforts("anthropic")
    payload = _payload()
    apply_anthropic(payload, "claude-opus-5", "max")
    assert payload["output_config"]["effort"] == "max"


def test_an_undeclared_model_still_gets_the_request_it_always_got():
    """The no-regression floor: unknown id, nothing added, nothing stripped."""
    payload = {"model": "claude-zeta-9", "max_tokens": 4096, "temperature": 0.7}
    apply_anthropic(payload, "claude-zeta-9", "max")
    assert payload == {"model": "claude-zeta-9", "max_tokens": 4096, "temperature": 0.7}
