"""H32.4 real Docker proof for generated-package verification.

This runs only in the dedicated sandbox CI lane. The lane resolves the pulled
Python image to a repository digest first, so the exact runtime under test is
also the runtime bound into the immutable receipt.
"""

from __future__ import annotations

import os

import pytest

from agents.core.acquisition.generator import (
    CapabilityContract,
    ContractCase,
    StrictLocalGenerator,
)
from agents.core.acquisition.quarantine import QuarantineStore
from agents.core.acquisition.sandbox_profile import (
    AcquisitionSandboxProfile,
    SandboxVerifier,
)
from agents.core.acquisition.store import CapabilityRequestStore

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SANDBOX_ISOLATION") != "1",
    reason="acquisition containment runs only in the dedicated Docker CI lane",
)


@pytest.mark.asyncio
async def test_generated_package_passes_real_contract_and_mutation_proof(tmp_path):
    image = os.environ.get("JARVIS_ACQUISITION_SANDBOX_IMAGE", "")
    profile = AcquisitionSandboxProfile(image=image, timeout_seconds=60)
    request = CapabilityRequestStore(root=tmp_path / "requests").capture(
        "parse Acme API items into a normalized list",
        agent_id="jarvis",
        reason="tool_not_allowed",
    )
    contract = CapabilityContract(
        goal=request.goal,
        entrypoint="run",
        cases=(
            ContractCase(
                input={"items": [{"id": 1}, {"id": 2}]},
                expected=[1, 2],
            ),
        ),
    )

    async def local_fixture(_prompt):
        return {
            "name": "acme_item_parser",
            "entrypoint": "run",
            "code": (
                "def run(payload):\n"
                "    return [item['id'] for item in payload.get('items', [])]\n"
            ),
            "test": (
                "import unittest\n"
                "from main import run\n\n"
                "class GeneratedTest(unittest.TestCase):\n"
                "    def test_items(self):\n"
                "        self.assertEqual(run({'items': [{'id': 3}]}), [3])\n"
            ),
        }

    package = await StrictLocalGenerator(
        generate=local_fixture,
        route="strict-local",
    ).generate(
        request=request,
        grounded_plan={"fully_grounded": True, "source_fixture_hash": "f" * 64},
        contract=contract,
    )
    runtime = tmp_path / "runtime"
    quarantine = QuarantineStore(root=tmp_path / "quarantine")
    quarantine.put(package)
    outcome = await SandboxVerifier(
        profile=profile,
        runtime_root=runtime,
    ).verify_quarantined(
        store=quarantine,
        artifact_id=package.artifact_id,
        contract=contract,
    )

    assert outcome.verified is True, outcome.reason
    assert outcome.receipt is not None
    assert outcome.receipt.runtime_image == image
    assert outcome.receipt.generated_test_exit == 0
    assert outcome.receipt.contract_exit == 0
    assert outcome.receipt.mutation_exit != 0
    assert quarantine.get_record(package.artifact_id).status == "verified"
    assert not any(runtime.iterdir())
