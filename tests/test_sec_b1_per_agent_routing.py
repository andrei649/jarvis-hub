"""SEC-B1 + per-agent route attribution — the adversarial audit's §15.4 and §15.5.

Both are the same structural defect seen from two ends: the turn collapsed per-agent
identity into a scalar, and two consumers read the scalar as if it described everyone.

* ``Agent.synthesize`` embedded every responder's RAW text in one prompt and routed as
  ``self.id`` ("jarvis"), so ``LOCAL_ONLY_AGENTS`` was enforced on the agent that
  *answered* and never on the pass that merged the answers.
* ``_record_interactions`` received one ``route_name`` computed from
  ``target_agents[0]`` and stamped it on every agent that answered, so a half-cloud turn
  could be recorded as fully local — and ``local_pct`` gates a 50% floor on the release.

The synthesis half also has behavioural coverage in
``tests/test_route_preserving_guardrails.py``; this file pins the seam itself.
"""

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.agent import Agent


# ── SEC-B1: the floor is over contributors ─────────────────────────
def test_strict_local_contributors_are_detected_from_the_live_set():
    from agents.core.llm.hybrid_router import LOCAL_ONLY_AGENTS

    assert LOCAL_ONLY_AGENTS, "the strict-local set is empty — nothing to enforce"
    pinned = next(iter(LOCAL_ONLY_AGENTS))

    found = Agent._strict_local_contributors({pinned: "family report", "stark": "ok"})
    assert found == {pinned}

    # no strict-local contributor → no floor, normal routing applies
    assert Agent._strict_local_contributors({"stark": "a", "athena": "b"}) == set()


def test_an_empty_response_from_a_strict_local_agent_does_not_trigger_the_floor():
    """Nothing of theirs is in the prompt, so there is nothing to protect."""
    from agents.core.llm.hybrid_router import LOCAL_ONLY_AGENTS

    pinned = next(iter(LOCAL_ONLY_AGENTS))
    assert Agent._strict_local_contributors({pinned: "", "stark": "answer"}) == set()


def test_the_two_strict_local_definitions_agree():
    """A security-relevant set defined twice is a divergence waiting to happen.

    ``hybrid_router`` decides routing and ``kernel.capabilities`` gates capabilities; if
    they drift, one of the two answers is wrong and nothing says which.
    """
    from agents.core.kernel.capabilities import LOCAL_ONLY_AGENTS as kernel_set
    from agents.core.llm.hybrid_router import LOCAL_ONLY_AGENTS as router_set

    assert set(router_set) == set(kernel_set), (
        f"strict-local sets disagree: router={sorted(router_set)} "
        f"kernel={sorted(kernel_set)}"
    )


# ── per-agent route attribution ────────────────────────────────────
class _TwoRouteRouter:
    """stark routes local, athena routes cloud — the audit's exact reproduction."""

    ROUTES = {"stark": "local", "athena": "cloud"}

    def select_backend(self, agent_id, prompt):
        return object(), f"{agent_id}-model", self.ROUTES.get(agent_id, "local")


def test_route_is_resolved_per_agent_not_from_the_primary():
    from agents.core.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.llm_router = _TwoRouteRouter()

    assert orch._route_for_agent("stark", "q") == "local"
    assert orch._route_for_agent("athena", "q") == "cloud", (
        "athena's cloud route was reported as the primary's — this is the "
        "mis-attribution that lets the privacy dashboard read 100% local on a turn "
        "where half the conversation went to a cloud provider"
    )


def test_an_unknowable_route_is_blank_rather_than_guessed():
    """RunHistory.locality excludes unrouted rows; a guess would fabricate a split."""
    from agents.core.orchestrator import Orchestrator

    class _Broken:
        def select_backend(self, agent_id, prompt):
            raise RuntimeError("no backend")

    orch = Orchestrator.__new__(Orchestrator)
    orch.llm_router = _Broken()
    assert orch._route_for_agent("stark", "q") == ""

    orch.llm_router = None
    assert orch._route_for_agent("stark", "q") == ""


def test_locality_counts_a_mixed_turn_honestly(tmp_path):
    """End of the chain: the metric that gates the release must reflect reality."""
    from agents.core.run_history import RunHistory

    # Own store: RunHistory defaults to data_path("run_history.json"), which is shared
    # process-wide, so a bare RunHistory() reads whatever earlier tests recorded and this
    # assertion becomes order-dependent.
    history = RunHistory(path=tmp_path / "run_history.json")
    history.record(agent_id="stark", input_text="q", output_text="a",
                   latency_ms=1.0, ok=True, route="local")
    history.record(agent_id="athena", input_text="q", output_text="a",
                   latency_ms=1.0, ok=True, route="cloud")

    locality = history.locality()
    assert locality["local"] == 1
    assert locality["cloud"] == 1
    assert locality["local_pct"] == 50.0, (
        f"a half-cloud turn reported {locality['local_pct']}% local"
    )
