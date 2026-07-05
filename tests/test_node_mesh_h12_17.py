"""H12.17 — Governed node mesh (execution nodes on H17.3). All offline."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

import pytest

from agents.core.automation_contracts import ContractDecision
import agents.core.node_mesh as node_mesh
from agents.core.node_mesh import NodeMesh, KIND
from agents.core.security.capability import CapabilityBroker, KillSwitch


class _FakeQueue:
    def __init__(self):
        self.calls = []

    def enqueue(self, agent, kind, title, payload=None, risk_tier=3,
                autonomy_level="ask", origin="generated"):
        self.calls.append(dict(kind=kind, payload=payload, risk_tier=risk_tier,
                               autonomy_level=autonomy_level))
        return len(self.calls)


class _Task:
    def __init__(self, payload):
        self.kind = KIND
        self.payload = payload


def _mesh(tmp_path, enqueue=None):
    return NodeMesh(capability_broker=CapabilityBroker(),
                    kill_switch=KillSwitch(path=str(tmp_path / "kill.json")),
                    enqueue=enqueue)


def test_register_mints_capability_token(tmp_path):
    mesh = _mesh(tmp_path)
    node = mesh.register_node("phone", ["notify", "read_clipboard"], {"os": "ios"})
    assert node["capabilities"] == ["notify", "read_clipboard"]
    assert node["token_issued"] is True
    assert "token_id" not in node            # token never exposed
    assert {n["id"] for n in mesh.nodes()} == {"phone"}


def test_register_without_broker_issues_no_token():
    mesh = NodeMesh(capability_broker=None)
    node = mesh.register_node("phone", ["notify"])
    assert node["token_issued"] is False


def test_dispatch_within_capability_enqueues_governed_task(tmp_path):
    q = _FakeQueue()
    mesh = _mesh(tmp_path, enqueue=q.enqueue)
    mesh.register_node("phone", ["notify"])
    out = mesh.dispatch("phone", "notify", action="ping")
    assert out["ok"] is True and out["queued"] is True and out["kind"] == KIND
    call = q.calls[0]
    assert call["autonomy_level"] == "ask" and call["risk_tier"] == 2
    assert call["payload"]["node"] == "phone" and call["payload"]["capability"] == "notify"


def test_dispatch_obeys_live_node_dispatch_contract(tmp_path, monkeypatch):
    q = _FakeQueue()
    mesh = _mesh(tmp_path, enqueue=q.enqueue)
    mesh.register_node("phone", ["notify"])

    class _Contract:
        def __init__(self):
            self.calls = []

        def evaluate(self, payload=None, **kwargs):
            self.calls.append((payload, kwargs))
            return ContractDecision(
                kind="node_dispatch",
                admissible=False,
                requires_approval=True,
                reason="contract_blocked",
            )

    contract = _Contract()
    monkeypatch.setattr(node_mesh, "NODE_DISPATCH_CONTRACT", contract, raising=False)

    out = mesh.dispatch("phone", "notify", action="ping", payload={"urgency": "low"})

    assert out == {"ok": False, "reason": "contract_blocked", "kind": KIND}
    assert q.calls == []
    assert contract.calls
    payload, kwargs = contract.calls[-1]
    assert payload["kind"] == KIND
    assert payload["node"] == "phone"
    assert payload["capability"] == "notify"
    assert payload["action"] == "ping"
    assert payload["args_keys"] == ["urgency"]
    assert kwargs.get("now") is not None


def test_dispatch_outside_capability_is_blocked(tmp_path):
    mesh = _mesh(tmp_path, enqueue=_FakeQueue().enqueue)
    mesh.register_node("phone", ["notify"])
    out = mesh.dispatch("phone", "wipe_disk", action="rm -rf")  # not granted
    assert out["ok"] is False and "capability" in out["reason"]


def test_dispatch_unknown_node_blocked(tmp_path):
    mesh = _mesh(tmp_path)
    out = mesh.dispatch("ghost", "notify")
    assert out["ok"] is False and out["reason"] == "unknown_node"


def test_dispatch_blocked_when_kill_switch_engaged(tmp_path):
    kill = KillSwitch(path=str(tmp_path / "kill.json"))
    mesh = NodeMesh(capability_broker=CapabilityBroker(), kill_switch=kill,
                    enqueue=_FakeQueue().enqueue)
    mesh.register_node("phone", ["notify"])
    kill.engage()  # global halt
    out = mesh.dispatch("phone", "notify")
    assert out["ok"] is False and "kill-switch" in out["reason"]


def test_revoke_removes_node_and_token(tmp_path):
    mesh = _mesh(tmp_path, enqueue=_FakeQueue().enqueue)
    mesh.register_node("phone", ["notify"])
    assert mesh.revoke("phone") is True
    assert mesh.get("phone") is None
    out = mesh.dispatch("phone", "notify")   # token revoked → unknown node
    assert out["ok"] is False


@pytest.mark.asyncio
async def test_execute_reauthorizes_at_action_time(tmp_path):
    mesh = _mesh(tmp_path)
    mesh.register_node("phone", ["notify"])
    task = _Task({"node": "phone", "capability": "notify", "action": "ping"})
    out = await mesh.execute(task)
    assert out["status"] == "ok" and out["dispatch"]["status"] == "deferred"

    # Revoke between queue and execute → re-auth fails, nothing handed to node.
    mesh.revoke("phone")
    out2 = await mesh.execute(task)
    assert out2["status"] == "failed"


@pytest.mark.asyncio
async def test_end_to_end_governed_dispatch(tmp_path):
    from agents.core.autonomy.queue import TaskQueue, TaskStatus
    from agents.core.autonomy.worker import AutonomyWorker
    from agents.core.autonomy.policy import AutonomyPolicy
    from agents.core.autonomy.executor import TaskExecutor

    q = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    try:
        mesh = NodeMesh(capability_broker=CapabilityBroker(),
                        kill_switch=KillSwitch(path=str(tmp_path / "kill.json")),
                        enqueue=q.enqueue)
        mesh.register_node("desktop", ["run_script"])
        out = mesh.dispatch("desktop", "run_script", action="backup.sh")
        tid = out["task_id"]
        assert q.get(tid).status == "proposed"

        q.transition(tid, TaskStatus.APPROVED, decided_by="andrei", decision="accept")
        executor = TaskExecutor()
        executor.register("node", mesh.execute)
        worker = AutonomyWorker(q, policy=AutonomyPolicy(), executor=executor.execute)
        summary = await worker.tick()

        assert summary["done"] == 1 and q.get(tid).status == "done"
    finally:
        q.close()
