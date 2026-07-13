"""H32.2 — deterministic reuse before research or generation."""

from __future__ import annotations

from agents.core.acquisition.resolver import (
    ReuseCandidate,
    ReuseDecisionStore,
    ReuseResolver,
    collect_reuse_candidates,
)
from agents.core.acquisition.runtime import AcquisitionRuntime
from agents.core.acquisition.store import CapabilityRequestStore


def _candidate(
    name: str,
    source: str,
    *,
    description: str = "normalize csv files",
    **overrides,
) -> ReuseCandidate:
    values = {
        "candidate_id": f"{source}:{name}",
        "name": name,
        "source": source,
        "description": description,
        "version": "1.0.0",
        "enabled": True,
        "trusted": True,
        "quarantined": False,
        "compatible": True,
        "reviewed": True,
        "governed": True,
        "execution_mode": "toolrpc",
    }
    values.update(overrides)
    return ReuseCandidate(**values)


def _request(tmp_path, goal="need a tool to normalize csv files"):
    store = CapabilityRequestStore(root=tmp_path / "requests")
    request = store.capture(goal, agent_id="jarvis", reason="tool_not_allowed")
    return store, request


def test_source_order_is_registry_then_installed_then_reviewed_marketplace(tmp_path):
    store, request = _request(tmp_path)
    decisions = ReuseDecisionStore(root=tmp_path / "decisions")
    candidates = [
        _candidate("exact", "installed", description=request.goal),
        _candidate("local", "registry", description="csv normalizer"),
        _candidate("market", "marketplace", description=request.goal, requires_install=True),
    ]

    decision = ReuseResolver(decision_store=decisions).resolve(
        request, candidates, request_store=store
    )

    assert decision.outcome == "reused"
    assert decision.candidate_id == "registry:local"
    assert decision.provenance == ["registry", "installed", "marketplace"]
    assert store.get(request.request_id).status.value == "reused"
    assert ReuseDecisionStore(root=tmp_path / "decisions").list()[0].candidate_id == decision.candidate_id


def test_semantic_ranking_and_ties_are_deterministic(tmp_path):
    _store, request = _request(tmp_path, "convert nested json to a flat table")
    candidates = [
        _candidate("zeta", "registry", description="flatten nested json into table rows"),
        _candidate("alpha", "registry", description="flatten nested json into table rows"),
        _candidate("noise", "registry", description="play music on speakers"),
    ]
    resolver = ReuseResolver(min_score=0.2)

    first = resolver.resolve(request, candidates)
    second = resolver.resolve(request, list(reversed(candidates)))

    assert first.candidate_id == second.candidate_id == "registry:alpha"
    assert first.score > 0.2


def test_disabled_untrusted_quarantined_incompatible_and_unreviewed_are_refused(tmp_path):
    _store, request = _request(tmp_path)
    candidates = [
        _candidate("disabled", "registry", enabled=False),
        _candidate("untrusted", "registry", trusted=False),
        _candidate("quarantined", "installed", quarantined=True),
        _candidate("old", "installed", compatible=False),
        _candidate("pending", "marketplace", reviewed=False, requires_install=True),
        _candidate("host", "registry", governed=False, execution_mode="in_process"),
    ]

    decision = ReuseResolver().resolve(request, candidates)

    assert decision.outcome == "no_reuse"
    assert decision.candidate_id is None
    assert set(decision.refused_reasons) == {
        "disabled",
        "untrusted",
        "quarantined",
        "incompatible",
        "review_required",
        "ungoverned_execution",
    }


def test_marketplace_match_requires_owner_install_approval(tmp_path):
    _store, request = _request(tmp_path)
    market = _candidate(
        "csv-pack",
        "marketplace",
        description=request.goal,
        requires_install=True,
    )

    decision = ReuseResolver().resolve(request, [market])

    assert decision.outcome == "install_approval_required"
    assert decision.candidate_id == market.candidate_id
    assert decision.requires_approval is True


def test_reuse_metric_excludes_blocked_and_abandoned_requests(tmp_path):
    decisions = ReuseDecisionStore(root=tmp_path)
    decisions.record_outcome("r1", "reused", candidate_id="registry:x")
    decisions.record_outcome("r2", "generated", candidate_id="acquired:y")
    decisions.record_outcome("r3", "blocked")
    decisions.record_outcome("r4", "blocked")
    decisions.record_outcome("r4", "abandoned")

    assert decisions.metrics() == {
        "reused": 1,
        "generated": 1,
        "blocked": 1,
        "abandoned": 1,
        "reuse_rate": 0.5,
    }


def test_resolver_has_no_research_network_or_generation_hooks(tmp_path):
    _store, request = _request(tmp_path)
    resolver = ReuseResolver()
    public_methods = {name for name in dir(resolver) if not name.startswith("_")}
    assert "research" not in public_methods
    assert "generate" not in public_methods
    assert resolver.resolve(request, [_candidate("csv", "registry")]).outcome == "reused"


def test_candidate_adapter_reads_existing_inventories_without_installing():
    class Marketplace:
        installed = False

        def list_skills(self):
            return [
                {"name": "", "review_status": "approved", "signed": True},
                {
                    "name": "reviewed-pack",
                    "version": "1.0.0",
                    "description": "reviewed sandbox pack",
                    "requires": ["sandbox"],
                    "review_status": "approved",
                    "signed": True,
                }
            ]

        def install_skill(self, _name):
            self.installed = True

    marketplace = Marketplace()
    orch = type("Orch", (), {"skills": type("Skills", (), {"skills": {}})(), "marketplace": marketplace})()
    snapshot = {
        "capabilities": [
            {
                "id": "tool:csv",
                "kind": "tool",
                "state": "wired",
                "description": "normalize csv",
                "detail": {"trusted": True},
            }
        ]
    }

    candidates = collect_reuse_candidates(orch, registry_snapshot=snapshot)

    assert [candidate.source for candidate in candidates] == ["registry", "marketplace"]
    assert candidates[0].execution_mode == "toolrpc"
    assert candidates[1].requires_install is True
    assert marketplace.installed is False


def test_runtime_runs_reuse_phase_over_real_registry_adapter(tmp_path):
    runtime = AcquisitionRuntime(enabled=lambda: True, root=tmp_path)
    request = runtime.capture_gap(
        {
            "goal": "need a tool to normalize csv",
            "agent_id": "jarvis",
            "reason": "tool_not_allowed",
        }
    )
    orch = type("Orch", (), {"skills": type("Skills", (), {"skills": {}})(), "marketplace": None})()
    snapshot = {
        "capabilities": [
            {
                "id": "tool:csv",
                "kind": "tool",
                "state": "wired",
                "description": "normalize csv",
                "detail": {},
            }
        ]
    }

    candidates = collect_reuse_candidates(orch, registry_snapshot=snapshot)
    decision = runtime.resolve_gap(request.request_id, orch, candidates=candidates)

    assert decision.outcome == "reused"
    assert runtime.request_store.get(request.request_id).status.value == "reused"
