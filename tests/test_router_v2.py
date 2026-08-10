"""
Tests for the rewritten intent router (agents/core/router.py).

Covers the regressions the v0.1 keyword stub shipped with — substring
misroutes, English-only matching, unordered multi-agent output, sloppy wake
words — plus the new scoring, canonical tags and optional LLM fallback.
"""

import asyncio
import sys
from pathlib import Path

import pytest

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agents.core.cortex_decision import (  # noqa: E402
    DecisionRecord,
    DecisionRejection,
    ShadowDecisionRouter,
)
from agents.core.router import Intent, IntentRouter  # noqa: E402


def _router(llm=None, writer=None):
    # Router only stores `config`; None keeps the test independent of JarvisConfig.
    router = IntentRouter(config=None, llm_classifier=llm)
    return ShadowDecisionRouter(router, writer) if writer else router


def _route(router, text: str) -> Intent:
    return asyncio.run(router.classify(text, {}))


# ── backward compatibility: the v0.1 behaviour the orchestrator relies on ──
def test_existing_weather_routes_to_friday():
    intent = _route(_router(), "weather in bucuresti")
    assert "friday" in intent.target_agents
    assert not intent.is_general


def test_existing_music_routes_to_jerome():
    intent = _route(_router(), "play some music")
    assert "jerome" in intent.target_agents


def test_intent_object_shape_is_preserved():
    records: list[DecisionRecord] = []
    router = _router(writer=records.append)
    intent = _route(router, "weather")
    second = _route(router, "weather")
    normalized_variant = _route(router, "  WEATHER  ")

    assert isinstance(intent.target_agents, list)
    assert isinstance(intent.is_general, bool)
    assert "source" in intent.context
    assert 0.0 <= intent.confidence <= 1.0
    assert intent.primary == intent.target_agents[0]
    assert second.target_agents == intent.target_agents
    assert normalized_variant.target_agents == intent.target_agents

    assert len(records) == 3
    assert records[0].schema == "nerva.decision.v1"
    assert records[0].authority == "route_selection_only"
    assert not records[0].can_authorize
    assert not records[0].can_execute
    assert not records[0].can_mark_complete
    assert records[0].replay_fingerprint == records[1].replay_fingerprint
    assert records[0].replay_fingerprint == records[2].replay_fingerprint
    assert records[0].request.text_length == len("weather")
    assert "weather" not in records[0].to_json()  # raw request is never persisted

    hard_rejection = DecisionRejection(
        route_id="cloud_router",
        code="private_data_local_only",
        category="privacy",
        source="privacy.policy",
    )
    assert hard_rejection.non_overridable

    rejected_intent = Intent(
        ["jarvis"],
        is_general=False,
        context={
            "source": "policy_test",
            "hard_constraint_rejections": [
                {
                    "route_id": "cloud_router",
                    "code": "private_data_local_only",
                    "category": "privacy",
                    "source": "privacy.policy",
                }
            ],
        },
        confidence=0.5,
    )
    rejected_record = DecisionRecord.from_intent(
        text="private request",
        agents={},
        intent=rejected_intent,
    )
    assert rejected_record.hard_constraint_rejections == (hard_rejection,)
    rejected_candidate = next(
        candidate
        for candidate in rejected_record.candidates
        if candidate.route_id == "cloud_router"
    )
    assert not rejected_candidate.selected


# ── the substring bug is gone (the headline regression) ────────────────────
@pytest.mark.parametrize("text,bad_agent,trap", [
    ("I was scared and the room was dark", "hephaestus", "car ⊄ scared"),
    ("we need maximum effort here", "frigga", "max ⊄ maximum"),
    ("container orchestration is hard", "gecko", "cont ⊄ container"),
    ("compostable packaging options", "veronica", "post removed / no substr"),
    ("I love programming in python", "pepper", "program ⊄ programming"),
])
def test_substring_traps_no_longer_misroute(text, bad_agent, trap):
    intent = _route(_router(), text)
    assert bad_agent not in (intent.target_agents or []), f"misroute via {trap}"


# ── bilingual RO/EN: the primary user talks in both languages ──────────────
@pytest.mark.parametrize("text,expected", [
    ("câți bani am?", "gecko"),
    ("cum am dormit azi noapte?", "hercules"),
    ("cum e vremea afară?", "friday"),
    ("adaugă o ședință mâine la 10", "pepper"),
    ("ce probleme de securitate avem?", "ultron"),
    ("vreau să cercetez piața auto", "vision"),
])
def test_romanian_queries_route_correctly(text, expected):
    intent = _route(_router(), text)
    assert expected in intent.target_agents, f"{text!r} -> {intent.target_agents}"
    assert not intent.is_general


def test_diacritics_are_folded():
    # "ședință" must match the diacritic-free trigger "sedinta".
    assert "pepper" in _route(_router(), "programează o ședință").target_agents


# ── wake word: exact token, not startswith ─────────────────────────────────
def test_wake_word_direct_address():
    records: list[DecisionRecord] = []
    intent = _route(_router(writer=records.append), "Jarvis, what's the weather?")
    assert intent.target_agents == ["jarvis"]
    assert intent.context["source"] == "wake_word"
    assert intent.confidence == 1.0
    assert records[0].source == "wake_word"
    assert records[0].selected_route == "jarvis"
    assert records[0].confidence.status == "measured"


def test_wake_word_with_particle():
    intent = _route(_router(), "hey friday, any news?")
    assert intent.target_agents == ["friday"]
    assert intent.context["source"] == "wake_word"


@pytest.mark.parametrize("text", ["visionary ideas for tomorrow", "steven will call later"])
def test_wake_word_no_false_prefix(text):
    # "visionary" must not wake Vision; "steven" must not wake Steve.
    intent = _route(_router(), text)
    assert intent.context["source"] != "wake_word"


# ── scoring, ordering, confidence ──────────────────────────────────────────
def test_strongest_signal_is_primary():
    intent = _route(_router(), "research the raiffeisen kpi numbers")
    assert intent.target_agents[0] == "stark"   # raiffeisen+kpi (4.0) > research (1.0)
    assert "vision" in intent.target_agents
    assert intent.confidence == 1.0
    assert intent.context["scores"]["stark"] > intent.context["scores"]["vision"]


def test_multi_agent_email_is_ordered_and_deterministic():
    records: list[DecisionRecord] = []
    router = _router(writer=records.append)
    a = _route(router, "check my inbox").target_agents
    b = _route(router, "check my inbox").target_agents
    assert a == b                       # deterministic
    assert set(a) >= {"pepper", "veronica", "stark"}
    assert records[0].source == "keyword_match"
    assert records[0].selected_route == a[0]
    assert records[0].fallbacks == tuple(a[1:])
    assert [candidate.route_id for candidate in records[0].candidates] == a
    assert all(candidate.score.status == "measured" for candidate in records[0].candidates)


# ── canonical keyword tags (what the orchestrator pre-fetches plugins on) ───
@pytest.mark.parametrize("text,tag", [
    ("cum e vremea", "weather"),
    ("ce am în inbox", "email"),
    ("research the market", "research"),
    ("adaugă un eveniment", "calendar"),
])
def test_keywords_found_are_canonical_and_language_independent(text, tag):
    intent = _route(_router(), text)
    assert tag in intent.context["keywords_found"]


# ── general fallback ───────────────────────────────────────────────────────
@pytest.mark.parametrize("text", ["", "   ", "asdfqwer zzz blorp"])
def test_unmatched_input_is_general_jarvis(text):
    records: list[DecisionRecord] = []
    intent = _route(_router(writer=records.append), text)
    assert intent.target_agents == ["jarvis"]
    assert intent.is_general
    assert intent.confidence == 0.0
    assert records[0].source == "general"
    assert records[0].candidates[0].score.status == "not_measured"
    assert records[0].candidates[0].quality.status == "not_measured"
    assert records[0].candidates[0].cost.status == "not_measured"


# ── optional LLM fallback: deterministic-first, LLM only for the ambiguous ──
class _FakeClassifier:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    async def __call__(self, text, candidates):
        self.calls += 1
        return self.result


def test_llm_fallback_used_when_nothing_matches():
    clf = _FakeClassifier(["athena"])
    records: list[DecisionRecord] = []
    intent = _route(_router(llm=clf, writer=records.append), "ponder the meaning of my quarter")
    assert clf.calls == 1
    assert intent.target_agents == ["athena"]
    assert intent.context["source"] == "llm"
    assert records[0].source == "llm"
    assert records[0].candidates[0].score.status == "not_measured"


def test_llm_fallback_not_used_for_confident_match():
    clf = _FakeClassifier(["athena"])
    intent = _route(_router(llm=clf), "weather in bucuresti")
    assert clf.calls == 0                       # confident keyword match wins
    assert intent.context["source"] == "keyword_match"


def test_llm_fallback_consulted_for_low_confidence_greeting():
    clf = _FakeClassifier(["pepper"])
    records: list[DecisionRecord] = []
    intent = _route(_router(llm=clf, writer=records.append), "help")
    assert clf.calls == 1
    assert intent.target_agents == ["pepper"]
    assert [candidate.route_id for candidate in records[0].candidates] == [
        "pepper",
        "jarvis",
    ]
    assert records[0].selected_route == "pepper"
    assert not records[0].candidates[1].selected


def test_llm_fallback_failure_is_swallowed():
    class _Boom:
        async def __call__(self, text, candidates):
            raise RuntimeError("model offline")

    intent = _route(_router(llm=_Boom()), "ponder something unmappable")
    assert intent.is_general                     # degrades to general, never raises

    def broken_writer(_record):
        raise RuntimeError("trace store offline")

    routed = _route(_router(writer=broken_writer), "weather")
    assert routed.target_agents == ["friday"]    # shadow failure never changes route


# ── ROUTING_TABLE isolation + bench-agent promotion (orchestrator contract) ─
def test_routing_table_is_instance_scoped():
    r1, r2 = _router(), _router()
    r1.ROUTING_TABLE["bruce"] = ["bruce"]
    assert "bruce" not in r2.ROUTING_TABLE
    assert "bruce" not in IntentRouter.ROUTING_TABLE


def test_promoted_bench_agent_becomes_wake_routable():
    r = _router()
    r.ROUTING_TABLE["bruce"] = ["bruce"]
    intent = _route(r, "bruce, run the analysis")
    assert intent.target_agents == ["bruce"]
    assert intent.context["source"] == "wake_word"
