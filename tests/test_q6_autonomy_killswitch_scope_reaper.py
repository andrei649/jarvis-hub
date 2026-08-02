"""Q6 — kill-switch per-agent scope at the executor seam + stuck-RUNNING reaper.

The worker's halt gate only ever consulted the GLOBAL scope, so an owner
halting a single agent (`POST /api/security/kill-switch {"scope":"steve"}` —
ch07 GOV-178) still saw that agent's already-approved tasks execute on the
next tick. And a worker crash between the RUNNING transition and the terminal
one stranded the task in `running` forever (ch07 open gap #10 / GOV-224):
`runnable()` selects APPROVED only, so nothing ever picked it back up —
invisible to retries, the decision inbox, and metrics alike.
"""

import asyncio
import sys
import time
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.autonomy.policy import AutonomyPolicy  # noqa: E402
from agents.core.autonomy.queue import TaskQueue, TaskStatus  # noqa: E402
from agents.core.autonomy.worker import AutonomyWorker  # noqa: E402
from agents.core.security.capability import KillSwitch  # noqa: E402


class _AuditDouble:
    def __init__(self):
        self.events = []

    def log(self, event, payload):
        self.events.append((event, payload))


def _worker(tmp_path, kill_switch=None, clock=None, audit=None) -> AutonomyWorker:
    queue = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()

    async def executor(task):
        return {"ok": True, "echo": task.kind}

    kwargs = {}
    if clock is not None:
        kwargs["clock"] = clock
    return AutonomyWorker(queue, policy=AutonomyPolicy(), executor=executor,
                          kill_switch=kill_switch, audit=audit, **kwargs)


# ── per-agent scope at the executor seam ────────────────────────────────────

def test_tick_skips_only_the_halted_agents_tasks(tmp_path):
    ks = KillSwitch(path=tmp_path / "kill.json")
    w = _worker(tmp_path, kill_switch=ks)
    steve = w.queue.enqueue(agent="steve", kind="noop", title="s", payload={})
    pepper = w.queue.enqueue(agent="pepper", kind="noop", title="p", payload={})
    for task_id in (steve, pepper):
        w.queue.transition(task_id, TaskStatus.APPROVED, decided_by="owner", decision="accept")

    ks.engage(scope="steve", reason="misbehaving")
    summary = asyncio.run(w.tick())

    assert summary["held"] == 1 and summary["done"] == 1
    assert not summary.get("halted"), "a scoped halt must not read as a global one"
    assert w.queue.get(steve).status == TaskStatus.APPROVED.value, (
        "the halted agent's task must stay APPROVED (nothing lost)"
    )
    assert w.queue.get(pepper).status == TaskStatus.DONE.value, (
        "other agents must keep running under a scoped halt"
    )

    ks.disengage(scope="steve")
    assert asyncio.run(w.tick())["done"] == 1
    assert w.queue.get(steve).status == TaskStatus.DONE.value


def test_global_halt_still_stops_every_agent(tmp_path):
    ks = KillSwitch(path=tmp_path / "kill.json")
    w = _worker(tmp_path, kill_switch=ks)
    task_id = w.queue.enqueue(agent="pepper", kind="noop", title="x", payload={})
    w.queue.transition(task_id, TaskStatus.APPROVED)

    ks.engage(reason="halt all")
    summary = asyncio.run(w.tick())

    assert summary.get("halted") is True and summary["ran"] == 0
    assert summary["held"] == 0 and summary["reaped"] == 0
    assert w.queue.get(task_id).status == TaskStatus.APPROVED.value


# ── stuck-RUNNING TTL reaper ────────────────────────────────────────────────

def test_reap_stuck_running_fails_only_past_ttl(tmp_path):
    q = TaskQueue(db_path=str(tmp_path / "autonomy.db")).initialize()
    stuck = q.enqueue(agent="pepper", kind="noop", title="crashed mid-run", payload={})
    q.transition(stuck, TaskStatus.APPROVED)
    q.transition(stuck, TaskStatus.RUNNING)
    waiting = q.enqueue(agent="pepper", kind="noop", title="fine", payload={})
    q.transition(waiting, TaskStatus.APPROVED)

    assert q.reap_stuck_running(3600.0, now=time.time()) == [], (
        "a task inside its TTL must not be reaped"
    )
    reaped = q.reap_stuck_running(3600.0, now=time.time() + 7200)
    assert [t.id for t in reaped] == [stuck]
    failed = q.get(stuck)
    assert failed.status == TaskStatus.FAILED.value
    assert failed.result["error"] == "stuck_running_ttl"
    assert failed.result["stuck_since"]
    assert q.get(waiting).status == TaskStatus.APPROVED.value, (
        "APPROVED tasks are never the reaper's business"
    )
    q.close()


def test_tick_reaps_stuck_running_and_audits(tmp_path):
    audit = _AuditDouble()
    w = _worker(tmp_path, clock=lambda: time.time() + 7200, audit=audit)
    stuck = w.queue.enqueue(agent="pepper", kind="noop", title="crashed", payload={})
    w.queue.transition(stuck, TaskStatus.APPROVED)
    w.queue.transition(stuck, TaskStatus.RUNNING)

    summary = asyncio.run(w.tick())

    assert summary["reaped"] == 1
    assert summary["ran"] == 0, "a reaped task must not count as executed"
    assert w.queue.get(stuck).status == TaskStatus.FAILED.value
    assert any(ev == "autonomy.reaped" for ev, _ in audit.events)


def test_reaper_disabled_by_nonpositive_ttl(tmp_path):
    w = _worker(tmp_path, clock=lambda: time.time() + 7200)
    w.running_ttl_seconds = 0.0
    stuck = w.queue.enqueue(agent="pepper", kind="noop", title="crashed", payload={})
    w.queue.transition(stuck, TaskStatus.APPROVED)
    w.queue.transition(stuck, TaskStatus.RUNNING)

    summary = asyncio.run(w.tick())

    assert summary["reaped"] == 0
    assert w.queue.get(stuck).status == TaskStatus.RUNNING.value


async def test_worker_shares_the_orchestrators_kill_switch(monkeypatch, tmp_path):
    """The admin halt route mutates orch.kill_switch; a worker-built second
    instance never reloads its file, so every post-boot halt was invisible to
    the tick until a process restart."""
    from tests.golden_harness import make_golden_orchestrator

    orch, _ = await make_golden_orchestrator(monkeypatch, tmp_path)

    assert orch.autonomy is not None and orch.kill_switch is not None
    assert orch.autonomy._kill_switch is orch.kill_switch
