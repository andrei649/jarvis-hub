"""H32.6 — tamper-evident, bounded acquisition audit ledger."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from agents.core.acquisition.audit import AcquisitionAuditError, AcquisitionLedger
from agents.core.acquisition.generator import CapabilityContract, ContractCase, StrictLocalGenerator
from agents.core.acquisition.quarantine import QuarantineStore
from agents.core.acquisition.research import ResearchStore
from agents.core.acquisition.resolver import ReuseDecisionStore
from agents.core.acquisition.store import CapabilityRequestStore


def test_ledger_is_encrypted_hash_chained_and_never_exports_raw_detail(tmp_path):
    ledger = AcquisitionLedger(root=tmp_path / "ledger", clock=lambda: 100.0)
    first = ledger.emit(
        "request.created",
        actor="agent-runtime",
        request_id="request-1",
        task_id="task-7",
        status="missing",
        details={"goal": "call https://private.example/path", "secret": "sk-secret-value"},
    )
    second = ledger.emit(
        "research.completed",
        actor="research",
        request_id="request-1",
        status="researching",
        details={"source_url": "https://private.example/path", "sources": 2},
    )

    raw = ledger.path.read_bytes()
    assert b"private.example" not in raw
    assert b"sk-secret-value" not in raw
    assert second.previous_hash == first.event_hash
    assert ledger.health() == {
        "status": "healthy",
        "events": 2,
        "summarized_events": 0,
        "chain_valid": True,
    }

    public = ledger.export_public()
    encoded = json.dumps(public, sort_keys=True)
    assert public["events"][0]["request_hash"]
    assert public["events"][0]["task_id"] == "task-7"
    assert "details" not in public["events"][0]
    assert "private.example" not in encoded
    assert "sk-secret-value" not in encoded
    assert AcquisitionLedger(root=tmp_path / "ledger").health()["chain_valid"] is True


def test_ledger_detects_decrypted_chain_tamper(tmp_path):
    ledger = AcquisitionLedger(root=tmp_path / "ledger")
    ledger.emit("request.created", actor="runtime", request_id="request-1", status="missing")
    payload = json.loads(ledger._cipher.decrypt_bytes(ledger.path.read_bytes()).decode("utf-8"))
    payload["events"][0]["status"] = "installed"
    ledger.path.write_bytes(
        ledger._cipher.encrypt_bytes(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
    )

    with pytest.raises(AcquisitionAuditError, match="hash chain"):
        AcquisitionLedger(root=tmp_path / "ledger").health()


def test_retention_capacity_and_owner_purge_preserve_hash_only_summary(tmp_path):
    now = [0.0]
    ledger = AcquisitionLedger(
        root=tmp_path / "ledger",
        clock=lambda: now[0],
        retention_days=1,
        max_rows=3,
        max_bytes=32 * 1024,
    )
    for index in range(5):
        now[0] = float(index)
        ledger.emit(
            "execution.completed",
            actor="sandbox",
            task_id=f"task-{index}",
            status="succeeded",
            details={"output": "x" * 100},
        )

    health = ledger.health()
    assert health["events"] == 3
    assert health["summarized_events"] == 2

    result = ledger.purge_details(actor="owner")
    assert result == {"purged": 3, "summarized_events": 5}
    assert ledger.list_public(limit=100) == []
    assert ledger.health()["chain_valid"] is True


def test_concurrent_append_keeps_one_valid_bounded_chain(tmp_path):
    ledger = AcquisitionLedger(root=tmp_path / "ledger", max_rows=100)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda index: ledger.emit(
                    "execution.completed",
                    actor="sandbox",
                    task_id=f"task-{index}",
                    status="succeeded",
                ),
                range(40),
            )
        )
    events = ledger.list_public(limit=100)
    assert len(events) == 40
    assert len({event["sequence"] for event in events}) == 40
    assert ledger.health()["chain_valid"] is True


@pytest.mark.asyncio
async def test_lifecycle_stores_emit_hash_only_audit_events(tmp_path):
    ledger = AcquisitionLedger(root=tmp_path / "ledger")
    requests = CapabilityRequestStore(root=tmp_path / "requests", event_sink=ledger.emit)
    request = requests.capture(
        "parse Acme items",
        agent_id="jarvis",
        reason="tool_not_allowed",
    )
    decisions = ReuseDecisionStore(root=tmp_path / "reuse", event_sink=ledger.emit)
    decisions.record_outcome(request.request_id, "generated")
    ResearchStore(root=tmp_path / "research", event_sink=ledger.emit).put_raw(
        request_id=request.request_id,
        backend="searxng",
        sources=[{"url": "https://private.example/doc", "extract": "bounded docs"}],
        plan={"steps": [{"source_id": "src-1"}]},
    )
    contract = CapabilityContract(
        goal=request.goal,
        entrypoint="run",
        cases=(ContractCase(input={"items": [{"id": 1}]}, expected=[1]),),
    )

    async def generate(_prompt):
        return {
            "name": "acme_parser",
            "entrypoint": "run",
            "code": "def run(payload):\n    return [item['id'] for item in payload['items']]\n",
            "test": (
                "import unittest\nfrom main import run\n"
                "class T(unittest.TestCase):\n"
                "    def test_run(self): self.assertEqual(run({'items': [{'id': 1}]}), [1])\n"
            ),
        }

    package = await StrictLocalGenerator(
        generate=generate,
        route="strict-local",
        event_sink=ledger.emit,
    ).generate(
        request=request,
        grounded_plan={"fully_grounded": True, "source_hash": "a" * 64},
        contract=contract,
    )
    quarantine = QuarantineStore(root=tmp_path / "quarantine", event_sink=ledger.emit)
    quarantine.put(package)
    quarantine.transition(package.artifact_id, "rejected")

    event_types = {row["event_type"] for row in ledger.list_public(limit=100)}
    assert {
        "request.created",
        "reuse.generated",
        "research.completed",
        "generation.completed",
        "quarantine.created",
        "sandbox.rejected",
    } <= event_types
    assert "private.example" not in json.dumps(ledger.export_public())
