"""H32 production glue — ``AcquisitionRuntime.synthesize_and_propose``.

BACKLOG: "a production path that creates a `PromotionProposal`". Every stage
this method composes (reuse resolution, strict-local generation, sandbox
verification, permanent-approval promotion) is independently covered by its
own H32.x test file; this file exercises only the NEW composition — that the
stages are wired in the right order, that each guardrail failure still stops
the chain (nothing is weakened), and that a clean run really does produce a
``PromotionProposal``. Offline throughout: the sandbox runner is a fake
(matching ``test_h32_generation_sandbox.py``'s ``_SequencedRunner`` pattern),
never real Docker.
"""

from __future__ import annotations

import pytest

from agents.core.acquisition.generator import CapabilityContract, ContractCase
from agents.core.acquisition.promotion import PromotionProposal
from agents.core.acquisition.runtime import AcquisitionRuntime
from agents.core.acquisition.sandbox_profile import AcquisitionSandboxProfile, SandboxExecution
from agents.core.skills.marketplace import SkillMarketplace
from agents.core.tool_rpc import ToolRPCServer

PINNED_IMAGE = "python:3.12-slim@sha256:" + "a" * 64
GOAL = "parse Acme API items into a normalized list"


class _SequencedRunner:
    def __init__(self, results):
        self.results = list(results)
        self.commands = []

    async def run(self, command, *, container_name):
        self.commands.append((list(command), container_name))
        return self.results.pop(0)


def _verified_sequence():
    return _SequencedRunner([
        SandboxExecution(0, "generated ok", "", False, 0.1),
        SandboxExecution(0, "contract ok", "", False, 0.1),
        SandboxExecution(1, "", "mutation detected", False, 0.1),
    ])


def _contract(goal=GOAL):
    return CapabilityContract(
        goal=goal,
        entrypoint="run",
        cases=(ContractCase(input={"items": [{"id": 1}]}, expected=[1]),),
    )


class _FakeResearch:
    def __init__(self, plan=None, *, raises=False):
        self.plan = plan if plan is not None else {"fully_grounded": True}
        self.raises = raises
        self.calls = 0

    async def run(self, request):
        self.calls += 1
        if self.raises:
            raise RuntimeError("research backend unavailable")
        from types import SimpleNamespace
        return SimpleNamespace(plan=self.plan)


async def _generate_ok(_prompt):
    return {
        "name": "acme_item_parser",
        "entrypoint": "run",
        "code": "def run(payload):\n    return [item['id'] for item in payload.get('items', [])]\n",
        "test": (
            "import unittest\nfrom main import run\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_items(self):\n"
            "        self.assertEqual(run({'items': [{'id': 2}]}), [2])\n"
        ),
    }


async def _generate_placeholder(_prompt):
    return {
        "name": "acme_item_parser",
        "entrypoint": "run",
        "code": "def run(payload):\n    pass\n",
        "test": (
            "import unittest\nfrom main import run\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_items(self):\n"
            "        self.assertIsNone(run({}))\n"
        ),
    }


def _runtime(tmp_path):
    runtime = AcquisitionRuntime(enabled=lambda: True, root=tmp_path)
    runtime.bind_promotion(
        tool_rpc=ToolRPCServer(),
        marketplace=SkillMarketplace(
            skills_dir=str(tmp_path / "skills"), db_path=str(tmp_path / "marketplace.db")
        ),
        profile=AcquisitionSandboxProfile(image=PINNED_IMAGE),
    )
    return runtime


def _fresh_request(runtime):
    request = runtime.capture_gap({"goal": GOAL, "agent_id": "jarvis", "reason": "tool_not_allowed"})
    assert request is not None
    return request


async def test_full_chain_produces_a_promotion_proposal(tmp_path):
    runtime = _runtime(tmp_path)
    request = _fresh_request(runtime)
    research = _FakeResearch()

    proposal = await runtime.synthesize_and_propose(
        request.request_id,
        contract=_contract(),
        research=research,
        generate=_generate_ok,
        runner=_verified_sequence(),
    )

    assert isinstance(proposal, PromotionProposal)
    assert proposal.name == "acme_item_parser"
    assert proposal.status == "pending"
    assert research.calls == 1
    updated = runtime.request_store.get(request.request_id)
    assert updated.status.value == "approval_pending"


async def test_disabled_refuses_without_touching_the_request(tmp_path):
    runtime = AcquisitionRuntime(enabled=lambda: False, root=tmp_path)
    out = await runtime.synthesize_and_propose(
        "does-not-matter", contract=_contract(), research=_FakeResearch(), generate=_generate_ok,
    )
    assert out is None


async def test_non_system_owned_or_mismatched_contract_is_refused(tmp_path):
    runtime = _runtime(tmp_path)
    request = _fresh_request(runtime)

    out = await runtime.synthesize_and_propose(
        request.request_id,
        contract=_contract(goal="a different goal entirely"),
        research=_FakeResearch(),
        generate=_generate_ok,
        runner=_verified_sequence(),
    )
    assert out is None
    # Refused before any state mutation — request never left MISSING.
    assert runtime.request_store.get(request.request_id).status.value == "missing"


async def test_research_failure_blocks_the_request(tmp_path):
    runtime = _runtime(tmp_path)
    request = _fresh_request(runtime)

    out = await runtime.synthesize_and_propose(
        request.request_id,
        contract=_contract(),
        research=_FakeResearch(raises=True),
        generate=_generate_ok,
        runner=_verified_sequence(),
    )
    assert out is None
    assert runtime.request_store.get(request.request_id).status.value == "blocked"


async def test_placeholder_generation_is_rejected_and_blocks_the_request(tmp_path):
    runtime = _runtime(tmp_path)
    request = _fresh_request(runtime)

    out = await runtime.synthesize_and_propose(
        request.request_id,
        contract=_contract(),
        research=_FakeResearch(),
        generate=_generate_placeholder,
        runner=_verified_sequence(),
    )
    assert out is None
    assert runtime.request_store.get(request.request_id).status.value == "blocked"


async def test_sandbox_verification_failure_stops_before_any_proposal(tmp_path):
    runtime = _runtime(tmp_path)
    request = _fresh_request(runtime)
    failing_runner = _SequencedRunner([
        SandboxExecution(1, "", "generated tests failed", False, 0.1),
    ])

    out = await runtime.synthesize_and_propose(
        request.request_id,
        contract=_contract(),
        research=_FakeResearch(),
        generate=_generate_ok,
        runner=failing_runner,
    )
    assert out is None
    # Quarantined but never approval-pending — no proposal was created.
    assert runtime.request_store.get(request.request_id).status.value == "quarantined"
    assert runtime.promotion_broker.proposals.get("anything") is None


async def test_already_researching_request_is_refused(tmp_path):
    runtime = _runtime(tmp_path)
    request = _fresh_request(runtime)
    runtime.request_store.transition(request.request_id, "researching", actor="other-caller")

    out = await runtime.synthesize_and_propose(
        request.request_id,
        contract=_contract(),
        research=_FakeResearch(),
        generate=_generate_ok,
        runner=_verified_sequence(),
    )
    assert out is None
