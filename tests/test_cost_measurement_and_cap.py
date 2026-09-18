"""LLM spend: measured, persisted, and capped (adversarial audit 2026-07-25, ADV-078).

Three cost endpoints — GET /api/cost, GET /api/analytics/cost, GET /api/admin/apm — read
``cost_tracker`` and NOTHING wrote to it: ``record()`` had no caller outside its own
module, so all three rendered a confident 0.00 forever. The tracker was also
process-memory only, so even a fed meter reset at every boot and "what did this cost me
last month" stayed unanswerable. And no cap existed anywhere, so an unattended night-shift
loop on a cloud key had no ceiling and produced no signal until the invoice.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

import pytest
from fastapi import FastAPI

from agents.core import cost_tracker
from agents.core.llm.cost_estimator import estimate_cost


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    cost_tracker.reset()
    yield
    cost_tracker.reset()


# ── the meter has a producer ───────────────────────────────────────
def test_the_orchestrator_records_cost_for_every_agent_turn():
    """The producer that did not exist. Static, because the record site is one call.

    Reading the source is the honest test here: the alternative is booting a full
    orchestrator, and a mocked one would prove only that my mock calls my code.
    """
    src = (repo_root / "agents/core/orchestrator.py").read_text(encoding="utf-8")
    assert "cost_tracker.record(" in src, (
        "nothing feeds cost_tracker — /api/cost and its two siblings will render a "
        "confident 0.00 over real cloud traffic"
    )


def test_recorded_spend_is_priced_per_call_and_totalled():
    cost_tracker.record("stark", 1_000_000, 0, model="claude-sonnet")   # $2.00 in
    cost_tracker.record("athena", 0, 1_000_000, model="claude-sonnet")  # $10.00 out
    summary = cost_tracker.get_summary()
    assert summary["agents"]["stark"]["cost_usd"] == pytest.approx(2.0)
    assert summary["agents"]["athena"]["cost_usd"] == pytest.approx(10.0)
    assert summary["total_cost_usd"] == pytest.approx(12.0)


def test_a_local_turn_costs_nothing_but_is_still_counted():
    """0.00 must come from measuring zero, not from nobody counting."""
    cost_tracker.record("stark", 5000, 5000, model="local")
    summary = cost_tracker.get_summary()
    assert summary["total_cost_usd"] == 0.0
    assert summary["agents"]["stark"]["calls"] == 1
    assert summary["agents"]["stark"]["input_tokens"] == 5000


# ── it survives a restart ──────────────────────────────────────────
def test_spend_persists_across_a_restart(tmp_path, monkeypatch):
    """Process-memory only meant last month was unanswerable even once fed."""
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    cost_tracker.record("stark", 1_000_000, 0, model="claude-sonnet")
    assert cost_tracker.spend_today_usd() == pytest.approx(2.0)

    # simulate a reboot: drop every in-process counter, then read again
    cost_tracker._usage.clear()
    cost_tracker._daily.clear()
    cost_tracker._state["loaded"] = False

    assert cost_tracker.spend_today_usd() == pytest.approx(2.0), (
        "spend reset at boot — 'what did this cost me last month' is unanswerable"
    )
    assert cost_tracker.daily_spend(), "no per-day rollup to answer a monthly question"


# ── unpriced is not free ───────────────────────────────────────────
def test_an_unpriced_model_is_flagged_rather_than_reported_as_free():
    unpriced = estimate_cost("a-model-nobody-priced", 1000, 1000)
    assert unpriced["priced"] is False, (
        "an unpriced model reported as costing 0.00 is a confident answer to a question "
        "nobody can answer — dashboards must be able to say 'unknown'"
    )
    genuinely_free = estimate_cost("local", 1000, 1000)
    assert genuinely_free["priced"] is True and genuinely_free["total"] == 0.0
    paid = estimate_cost("gemini-2.5-pro", 1_000_000, 0)
    assert paid["priced"] is True and paid["total"] > 0


# ── the cap ────────────────────────────────────────────────────────
class _Router:
    """Minimal stand-in exercising HybridRouter's real cap logic."""

    def __init__(self, cap, available=True):
        from agents.core.llm.hybrid_router import HybridRouter

        self._cloud_available = available
        self._daily_cost_cap = cap
        self._cloud_permitted = HybridRouter._cloud_permitted.__get__(self)


def test_no_cap_by_default_leaves_behaviour_unchanged():
    cost_tracker.record("stark", 1_000_000, 0, model="claude-sonnet")
    assert _Router(cap=0.0)._cloud_permitted() is True


def test_cloud_is_refused_once_the_daily_cap_is_reached():
    router = _Router(cap=1.0)
    assert router._cloud_permitted() is True
    cost_tracker.record("stark", 1_000_000, 0, model="claude-sonnet")   # $3.00 > $1.00
    assert router._cloud_permitted() is False, (
        "a cloud route was permitted over the daily cap — an unattended loop still has "
        "no ceiling"
    )


def test_the_cap_does_not_apply_when_cloud_is_unavailable_anyway():
    assert _Router(cap=1.0, available=False)._cloud_permitted() is False


def test_an_unreadable_meter_does_not_silently_disable_cloud(monkeypatch):
    """Failing closed here would take the box offline over a bookkeeping error."""
    monkeypatch.setattr(cost_tracker, "spend_today_usd",
                        lambda: (_ for _ in ()).throw(RuntimeError("store gone")))
    assert _Router(cap=1.0)._cloud_permitted() is True


def test_the_cap_setting_exists_and_defaults_to_off():
    from agents.core.settings_db import DEFAULTS

    row = next((r for r in DEFAULTS
                if r["category"] == "llm" and r["key"] == "daily_cost_cap_usd"), None)
    assert row is not None, "the cap has no /admin knob, so nobody can turn it on"
    assert row["value"] == 0, "the cap must be off by default — this is not a behaviour change"


# ── the meter is fed the model that ACTUALLY ran ───────────────────
#
# The producer above was wired, but it was wired to the wrong identity: it passed
# ``self.agents[agent_id].config["model"]``, and `AgentConfig.model` defaults to
# "google/gemma-4-31b-a4b" while not one of the 18 agents in agents/_system/agents.yaml
# declares a `model` — so that string was ALWAYS truthy, the `or agent_route` fallback
# beside it was unreachable, and every cloud turn priced at the local-model rate of
# $0.00. The meter was fed, and still read zero over real Claude traffic.
class _Turn:
    """Runs the real ``_record_interactions`` over one agent's answered turn.

    A stand-in rather than a booted orchestrator, for the reason the producer test
    above gives: a mocked orchestrator would prove only that the mock calls the code.
    This binds the actual method and supplies exactly the per-turn state it reads, so
    the assertions below are about the shipped record site, not about a fake.
    """

    def __init__(self, *, routed_model, input_tokens=1_000_000, output_tokens=0,
                 configured_model="google/gemma-4-31b-a4b", route="cloud"):
        from types import SimpleNamespace

        from agents.core.orchestrator import Orchestrator

        agent_id = "stark"
        self.agent_id = agent_id
        self.entities = None
        self.kg_updater = None
        self.run_history = None
        self.agents = {agent_id: SimpleNamespace(
            config={"model": configured_model}, should_demote=False)}
        self.learning = SimpleNamespace(record=lambda **kw: None)
        self.bench = SimpleNamespace(record=lambda **kw: None)
        self._last_latencies = {agent_id: 0.1}
        self._last_routes = {agent_id: route}
        self._last_models = {agent_id: routed_model} if routed_model else {}
        self._last_cached_tokens = {}
        self._last_prompt_tokens = {}
        self._last_reported_usage = {agent_id: SimpleNamespace(
            reported=True, input_tokens=input_tokens, output_tokens=output_tokens,
            cache_read=0, cache_write=0)}
        self.get_setting = lambda key, default=None: default
        self._record = Orchestrator._record_interactions.__get__(self)

    def run(self):
        # The record site is wrapped in a bare `except` so a bookkeeping error never
        # kills the turn that produced it — which would also swallow a broken harness.
        # Every test below therefore asserts the meter moved at all before asserting
        # what it says, so a silent no-op here reads as a harness fault, not a pass.
        self._record("what did that cost?", {self.agent_id: "Two dollars, sir."}, "")


def test_a_cloud_turn_is_metered_against_the_model_that_ran_not_the_yaml_default():
    _Turn(routed_model="claude-sonnet-5").run()
    summary = cost_tracker.get_summary()
    assert summary["agents"]["stark"]["calls"] == 1, "the meter was not fed at all"
    assert summary["total_cost_usd"] == pytest.approx(2.0), (
        "a 1M-token Claude turn metered at "
        f"{summary['total_cost_usd']} — the meter is being fed the agents.yaml default "
        "model, not the model the router actually bound"
    )


def test_an_unpriced_model_is_flagged_by_the_meter_not_billed_at_the_default_row():
    """`cost_estimator` already answers "nobody priced this"; the meter must too.

    Falling through to the $3/$15 `default` row invents money: an owner reading
    /api/analytics/cost cannot tell that figure from a measured one.
    """
    cost_tracker.record("stark", 1_000_000, 0, model="a-model-nobody-priced")
    summary = cost_tracker.get_summary()
    assert summary["total_cost_usd"] == 0.0, (
        "an unpriced model was billed at the default row — the meter invented "
        f"${summary['total_cost_usd']}"
    )
    assert summary["agents"]["stark"]["priced"] is False
    assert summary["unpriced_calls"] == 1
    assert summary["agents"]["stark"]["input_tokens"] == 1_000_000, (
        "unpriced must still count tokens — the turn happened"
    )


def test_a_priced_turn_is_still_reported_as_priced():
    cost_tracker.record("stark", 1_000_000, 0, model="claude-sonnet-5")
    summary = cost_tracker.get_summary()
    assert summary["agents"]["stark"]["priced"] is True
    assert summary["unpriced_calls"] == 0


def test_a_turn_whose_model_is_unknowable_is_unpriced_rather_than_free():
    """A handoff, or a router that could not answer, leaves no model behind.

    Recording that as the $0.00 local rate is the same lie in the other direction, so
    the record site must name it unknown and let the surfaces say so.
    """
    _Turn(routed_model=None).run()
    summary = cost_tracker.get_summary()
    assert summary["agents"]["stark"]["calls"] == 1, "the meter was not fed at all"
    assert summary["unpriced_calls"] == 1, (
        "a turn with no known model was metered as a measured 0.00"
    )
    assert summary["agents"]["stark"]["model"] == cost_tracker.UNPRICED_MODEL


def test_the_apm_rollup_carries_the_unpriced_count():
    """/api/admin/apm renders currency; it must be able to caveat it."""
    cost_tracker.record("stark", 1_000_000, 0, model="claude-sonnet-5")
    cost_tracker.record("athena", 1_000_000, 0, model="a-model-nobody-priced")
    apm = cost_tracker.apm_summary()
    assert apm["totals"]["unpriced_calls"] == 1
    assert apm["totals"]["cost_usd"] == pytest.approx(2.0)
    by_model = {row["model"]: row for row in apm["by_model"]}
    assert by_model["a-model-nobody-priced"]["unpriced_calls"] == 1
    assert by_model["claude-sonnet-5"]["unpriced_calls"] == 0


def test_both_agent_running_paths_publish_the_routed_model_to_the_meter():
    """The record site reads ``_last_models``; the two paths that run agents fill it.

    Static, for the reason the producer test at the top of this file gives — but it
    guards a real regression, not a style: a record site reading a map nobody writes
    would meter every turn "unknown". That is honest and useless, and no assertion
    about ``_record_interactions`` alone can catch it, because the harness below
    supplies the map itself.
    """
    src = (repo_root / "agents/core/orchestrator.py").read_text(encoding="utf-8")
    assert 'getattr(self, "_last_models", {}).get(agent_id)' in src, (
        "the cost meter is no longer fed from the routed-model map"
    )
    # The streaming loop, beside the route it already publishes.
    assert 'self._last_models[agent_id] = model or ""' in src, (
        "the streaming turn does not publish the model it streamed on"
    )
    # The parallel fan-out (Telegram, Discord, voice, /chat, MCP, rooms, eval).
    assert 'self._last_models[agent_id] = model if route_name else ""' in src, (
        "the non-streaming turn does not publish the model the router bound"
    )
    # Re-inserted after the fan-out clears the maps, like route and latency.
    assert "self._last_models[agent_id] = primary_model" in src, (
        "a streamed primary with secondaries loses its model and meters as unknown"
    )
    assert src.count("self._last_models = {}") >= 2, (
        "the map must be cleared per turn on both paths, or one turn's model prices "
        "the next turn's tokens"
    )


def test_omitting_the_model_is_unpriced_not_a_three_dollar_guess():
    """The last way in for an invented figure: `record()`'s own default argument.

    It used to be "default", so a caller that simply did not know the model billed the
    $3/$15 placeholder row. Naming that row by hand is still a request for a placeholder
    rate; saying nothing is not.
    """
    cost_tracker.record("stark", 1_000_000, 1_000_000)
    summary = cost_tracker.get_summary()
    assert summary["total_cost_usd"] == 0.0, (
        f"a caller that named no model was billed ${summary['total_cost_usd']}"
    )
    assert summary["unpriced_calls"] == 1
    # Asked for by name, the placeholder row still prices — that is a choice, not a gap.
    cost_tracker.record("athena", 1_000_000, 1_000_000, model="default")
    assert cost_tracker.get_summary()["agents"]["athena"]["cost_usd"] == pytest.approx(18.0)


def test_an_unpriced_turn_is_its_own_tier_not_a_standard_one():
    """`/api/analytics/model-tiers` renders the meter, so it inherits the same rule.

    `classify_tier` ends in `return "standard"`, so an id the meter could not price
    used to land there — a surface reading "this agent runs a standard-tier cloud
    model" over a turn nobody measured. Unknown is not a tier; it is the absence of
    one, and the endpoint now says so in its own bucket.
    """
    from fastapi.testclient import TestClient

    from agents.core.routers.analytics import router

    cost_tracker.record("stark", 1_000, 1_000, model=cost_tracker.UNPRICED_MODEL)
    cost_tracker.record("athena", 1_000, 1_000, model="claude-sonnet-5")

    app = FastAPI()
    app.include_router(router)
    body = TestClient(app).get("/api/analytics/model-tiers").json()

    assert [a["agent"] for a in body["tiers"]["unknown"]] == ["stark"], (
        "a turn the meter could not price is missing from the unknown tier: "
        f"{body['tier_counts']}"
    )
    assert [a["agent"] for a in body["tiers"]["standard"]] == ["athena"], (
        "an unpriced turn is being counted as a standard-tier cloud model"
    )
    assert body["tier_counts"]["unknown"] == 1


# ── the review round: four ways this meter still lied ────────────────────────
#
# Every case below was reproduced against the delivered branch before it was fixed.

@pytest.mark.parametrize("model_id", [
    "deepseek/deepseek-chat",
    "mistralai/mistral-large-latest",
    "meta-llama/llama-3.3-70b-instruct",
    "qwen/qwen3-max",
])
def test_a_billed_cloud_model_named_like_a_local_family_is_not_a_measured_zero(model_id):
    """The headline bug, alive for a whole provider class.

    The zero rows (`local/gemma/qwen/deepseek/llama/mistral/phi`) took part in the
    family-substring scan, so these four — all sold for real money on OpenRouter, all
    reachable through the free-text `llm.compatible_model` setting — metered at $0.00
    with `priced: True`, which asserts the dollar figure covers the tokens. A measured
    zero for a billed turn is worse than no figure at all, and it never reached the
    daily cap either.
    """
    cost_tracker.record("stark", 1_000_000, 1_000_000, model=model_id)
    summary = cost_tracker.get_summary()

    assert summary["agents"]["stark"]["calls"] == 1, "the meter was not fed at all"
    assert summary["unpriced_calls"] == 1, (
        f"{model_id} was priced from a substring: the meter reports "
        f"${summary['total_cost_usd']} as a measurement"
    )
    assert summary["agents"]["stark"]["priced"] is False


def test_a_local_route_still_prices_at_a_measured_zero():
    """The route is what actually knows, and it has to keep working.

    `deepseek/deepseek-chat` reads exactly like an Ollama tag, so the id alone cannot
    say where a model ran. The route can, and a local one bills nothing whatever it ran.
    """
    cost_tracker.record("stark", 1_000_000, 1_000_000,
                        model="qwen2.5-coder:32b", route="local")
    cost_tracker.record("stark", 1_000_000, 1_000_000,
                        model="google/gemma-4-31b-a4b", route="local-deep")
    summary = cost_tracker.get_summary()

    assert summary["agents"]["stark"]["calls"] == 2, "the meter was not fed at all"
    assert summary["total_cost_usd"] == 0.0
    assert summary["unpriced_calls"] == 0, "a local route must be a measurement, not a shrug"


def test_a_blank_route_is_unknowable_not_local():
    """`_route_for_agent` returns "" when it cannot answer, and `RunHistory.locality`
    counts that as `unknown` rather than local. Pricing it at zero would turn the
    router's own "I don't know" into a measured figure."""
    cost_tracker.record("stark", 1_000_000, 0, model="some-unknown-model", route="")

    assert cost_tracker.get_summary()["unpriced_calls"] == 1


def test_route_locality_agrees_with_run_history():
    """Two readings of "did this run here" must not drift apart.

    `RunHistory.locality` is the repo's existing classifier and backs the north-star
    `%-local` metric; the meter's is new. A route either bills nothing on both or on
    neither — otherwise the dashboard and the invoice tell different stories.
    """
    from agents.core.run_history import RunHistory

    rh = RunHistory()
    for route in ("local", "local-deep", "local-fallback", "ollama-howard",
                  "cloud", "cloud-flash", "cloud-compatible", "claude", "gemini"):
        rh.clear()
        rh.record(agent_id="stark", latency_ms=1.0, route=route)
        split = rh.locality()
        assert cost_tracker.route_bills_nothing(route) == bool(split["local"]), (
            f"route {route!r}: meter says bills_nothing="
            f"{cost_tracker.route_bills_nothing(route)}, RunHistory says local="
            f"{split['local']}"
        )


@pytest.mark.parametrize("model_id,expected_input", [
    ("anthropic/claude-sonnet-4-5", 3.00),   # exact row; the family row says 2.00
    ("openai/gpt-4o-2024-05-13", 5.00),      # exact row; the family row says 2.50
])
def test_a_vendor_prefixed_id_finds_its_exact_price(model_id, expected_input):
    """A routed cloud id usually arrives as "vendor/model".

    Neither exact table was ever consulted with the vendor segment stripped, so every
    one of these ids fell through to the coarse family row — under-billing Sonnet 4.5 by
    a third, which is precisely what `_price_for`'s docstring says cannot happen.
    `context_compressor` already strips the segment before matching, for this reason.
    """
    price = cost_tracker._price_for(model_id)

    assert price is not None and price["input"] == pytest.approx(expected_input), (
        f"{model_id} priced at {price} — the family row won over the exact one"
    )


def test_the_per_model_breakdown_names_the_model_that_is_missing_a_price():
    """`unpriced_calls` is a counter because one agent mixes models, and the APM
    docstring promises the per-model row "names the model to add to the table".

    Built from the agent's LAST model, it could not: one row, named after whichever id
    ran last, carrying the unpriced count — so the model actually missing a price had no
    row at all and an operator would have added a price for one that already had one.
    """
    cost_tracker.record("stark", 1_000_000, 0, model="grok-4.6")          # unpriced
    cost_tracker.record("stark", 1_000_000, 0, model="claude-sonnet-5")   # $2.00

    rows = {r["model"]: r for r in cost_tracker.apm_summary()["by_model"]}

    assert set(rows) == {"grok-4.6", "claude-sonnet-5"}
    assert rows["grok-4.6"]["unpriced_calls"] == 1
    assert rows["grok-4.6"]["cost_usd"] == 0.0
    assert rows["claude-sonnet-5"]["unpriced_calls"] == 0, (
        "the unpriced count landed on a model that IS priced"
    )
    assert rows["claude-sonnet-5"]["cost_usd"] == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_two_concurrent_turns_do_not_overwrite_each_others_meter_maps():
    """`turn_lease` keys on the SESSION, not the orchestrator.

    A Telegram chat and a /chat tab therefore hold different leases and run concurrently
    on the one `orch` `web.py` builds. Both turns used to reset and fill the same
    instance attribute, and the reset lands while the earlier turn is still awaiting
    `memory.add_turn`, `_maybe_checkpoint` and `_log_session` on its way to the record
    site — so the slower turn metered as unpriced, or, when both were answered by the
    same agent id, metered at the OTHER turn's model. A 1M-token Opus turn overlapped by
    a small Haiku one billed $1.00 instead of $5.00 with `priced: True`: a confident
    wrong figure, which is the one thing this meter exists to stop producing.
    """
    import asyncio

    from agents.core import orchestrator as orchestrator_module
    from agents.core.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    seen: dict[str, dict] = {}
    slower_may_finish = asyncio.Event()

    async def turn(name: str, model: str, *, slow: bool) -> None:
        token = orchestrator_module._TURN_METER_MAPS.set({})
        try:
            orch._last_models = {}                     # what every turn does first
            orch._last_models["stark"] = model
            if slow:
                await slower_may_finish.wait()         # still in flight...
            else:
                await asyncio.sleep(0)
                slower_may_finish.set()                # ...while this one runs and ends
            seen[name] = dict(orch._last_models)       # what the record site would read
        finally:
            orchestrator_module._TURN_METER_MAPS.reset(token)

    await asyncio.gather(
        turn("opus-turn", "claude-opus-5", slow=True),
        turn("haiku-turn", "claude-haiku-5", slow=False),
    )

    assert seen == {
        "opus-turn": {"stark": "claude-opus-5"},
        "haiku-turn": {"stark": "claude-haiku-5"},
    }, "a concurrent turn's reset reached into this turn's meter map"


def test_model_tiers_puts_a_really_unpriced_agent_in_the_unknown_bucket():
    """The bucket has to follow the FLAG, not the id.

    Classifying on the model string alone only ever caught the literal sentinel, so an
    agent that ran `grok-4.6` — a real model nobody here has priced — landed under
    `standard` with a $0.00 cost: a surface claiming a mid-priced cloud model whose
    spend was never measured, which is the same confident-wrong answer the meter itself
    stopped giving.
    """
    from fastapi.testclient import TestClient

    from agents.core.routers.analytics import router

    cost_tracker.record("stark", 1_000_000, 0, model="grok-4.6")
    app = FastAPI()
    app.include_router(router)
    body = TestClient(app).get("/api/analytics/model-tiers").json()

    assert [a["agent"] for a in body["tiers"]["unknown"]] == ["stark"], (
        f"an unpriced model landed in a priced tier: {body['tier_counts']}"
    )
    assert body["tiers"]["unknown"][0]["priced"] is False
    assert body["tiers"]["unknown"][0]["unpriced_calls"] == 1
    assert body["unpriced_calls"] == 1, (
        "the endpoint prints a dollar total with no way to say what it does not cover"
    )


def test_every_model_tier_bucket_is_rendered_by_the_admin_page():
    """The endpoint's buckets and the only UI that renders them must not drift.

    `admin.js`'s CostPage builds every card, row and section by mapping over `tierDefs`,
    so a bucket missing from that literal is an agent that appears nowhere — and the
    page does not even look broken, because `allEmpty` is false. When this PR added the
    `unknown` bucket it updated the Python pin and not the consumer it ships with.
    """
    import re

    from fastapi.testclient import TestClient

    from agents.core.routers.analytics import router

    app = FastAPI()
    app.include_router(router)
    served = set(TestClient(app).get("/api/analytics/model-tiers").json()["tier_counts"])

    admin_js = (repo_root / "agents/web/static/admin.js").read_text(encoding="utf-8")
    block = admin_js.split("const tierDefs = [", 1)[1].split("];", 1)[0]
    rendered = set(re.findall(r"key:\s*'([a-z]+)'", block))

    assert served == rendered, (
        f"tiers the endpoint returns but the admin page never renders: {served - rendered}; "
        f"tiers the page renders but the endpoint never returns: {rendered - served}"
    )


def test_the_cost_surfaces_read_the_persisted_rollup_after_a_restart(tmp_path, monkeypatch):
    """A restart must not turn recorded spend into a confident $0.00.

    `record()` and `spend_today_usd()` fault the rollup in; `get_summary()` did not, and
    all three cost endpoints are built on it. So a fresh process answered
    `total_cost_usd: 0.0, unpriced_calls: 0` — a measured-looking zero over money
    already on disk — until some unrelated call happened to load the file.
    """
    cost_tracker.record("stark", 1_000_000, 0, model="claude-sonnet-5")
    assert cost_tracker.get_summary()["total_cost_usd"] == pytest.approx(2.0)

    # A new process against the same JARVIS_HOME: in-memory state gone, file intact.
    cost_tracker._usage.clear()
    cost_tracker._daily.clear()
    cost_tracker._state["loaded"] = False

    summary = cost_tracker.get_summary()

    assert summary["total_cost_usd"] == pytest.approx(2.0), (
        "the meter reported a confident zero over spend sitting in the rollup"
    )
    assert summary["agents"]["stark"]["calls"] == 1
