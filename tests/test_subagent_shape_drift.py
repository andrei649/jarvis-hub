"""V3 — the drift guard for contracts nobody declared.

`tests/test_interface_contract_drift.py` snapshots the *declared* contracts:
dataclasses, pydantic models, enums. It cannot see the ones that matter most for
a fleet of parallel agents, because a subagent's answer is a **plain dict built
at runtime**. Nothing declares its keys, so nothing notices when they change —
and every caller reading `result["ok"]` breaks silently and simultaneously.

The difference is the whole reason this file exists: that gate **introspects**,
this one **calls**. It drives the real `SubAgentManager` through each of its
outcomes and snapshots the key set that actually came back. A shape can only
change here by someone changing the code and re-reading this snapshot.

Two properties make the capture trustworthy rather than decorative:

* **Every refusal is exercised, not just the happy path.** The refusals are where
  callers get lazy — `result.get("reason")` on a dict that no longer has one —
  and they are the shapes least likely to be covered by an ordinary test.
* **The guard guards itself.** A capture that silently returned `{}` for
  everything would make drift invisible while looking green, so a teeth test
  asserts the captured shapes are non-empty and contain the keys the product's
  own callers read.

Hermetic: an injected runner, a tmp_path data root. Nothing spawns a real agent.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
# Importable when run directly (`python tests/test_subagent_shape_drift.py --update`)
# as well as under pytest, which conftest already arranges.
for path in (REPO, REPO / "agents"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

SNAP = Path(__file__).parent / "_snapshots" / "subagent_shapes.json"

# The keys real callers read off a spawn result. Pinned separately from the
# snapshot: the snapshot records what the code DOES, and this records what the
# rest of the product DEPENDS ON. A snapshot regenerated without thinking still
# fails here if it dropped one of these.
CALLER_KEYS = {
    "spawn.ok": {"ok", "id", "session_id", "status", "result", "cost"},
    "spawn.recursion_depth_cap": {"ok", "reason", "depth", "max_depth"},
    "spawn.concurrency_cap": {"ok", "reason", "active", "cap"},
    "spawn.spawn_budget_exhausted": {"ok", "reason", "used", "max_total"},
    "spawn.invalid_output_schema": {"ok", "reason"},
}


async def _runner(task, session_id, agent, **_kw):
    return {"output": f"[{agent}] {task}", "session_id": session_id}


def _runtime(tmp_path, **kw):
    from agents.core.subagents import SubAgentManager

    kw.setdefault("runner", _runner)
    # The spawn log goes to tmp_path, never the real data root — and persistence
    # is off, so a capture cannot leave anything behind.
    kw.setdefault("spawn_log", tmp_path / "spawns.jsonl")
    kw.setdefault("persist", False)
    return SubAgentManager(**kw)


def _shape(payload) -> list[str]:
    """The key set, sorted. Values are deliberately NOT captured: a snapshot of
    values would churn on every timestamp and id, and would be re-generated so
    often that nobody would read the diff — which is how a shape gate stops
    being a gate."""
    return sorted(payload) if isinstance(payload, dict) else []



def _refused(payload: dict, reason: str, problems: list[str]) -> dict:
    """Record whether the guard actually fired, and never raise.

    Two things depend on this. Without the check, a capture that quietly took the
    happy path would bake the SUCCESS keys into the snapshot as the refusal's,
    and the gate would defend the wrong shape forever while looking green. And
    without the *never raising*, one drift turns into a dozen fixture ERRORs
    instead of one readable failure — which is the difference between a gate
    people fix and a gate people delete.
    """
    if payload.get("ok") is not False or payload.get("reason") != reason:
        problems.append(
            f"{reason}: the guard did not refuse — got {payload.get('reason') or sorted(payload)!r}"
        )
    return payload


def _capture_concurrency_cap(tmp_path, problems: list[str]) -> dict:
    """Hold one spawn open so `_active` is genuinely at the cap.

    `max_concurrent` is clamped to at least 1, so the only honest way to reach
    this refusal is to occupy the one slot — which is exactly how production
    reaches it too.
    """
    release = asyncio.Event()

    async def _slow(task, session_id, agent, **_kw):
        await release.wait()
        return {"output": task, "session_id": session_id}

    async def _drive() -> dict:
        runtime = _runtime(tmp_path, runner=_slow, max_concurrent=1)
        held = asyncio.create_task(runtime.spawn("holds the slot"))
        # Let the held spawn reach the runner and take the slot.
        for _ in range(50):
            await asyncio.sleep(0)
            if runtime._active >= 1:
                break
        try:
            # Bounded: if the guard stops firing, this spawn reaches the blocked
            # runner and waits on `release`, which is only set afterwards — a
            # deadlock. A gate that HANGS when the thing it guards breaks is a
            # gate someone will disable, so it fails fast and says why instead.
            refused = await asyncio.wait_for(runtime.spawn("no room"), timeout=5)
        except TimeoutError:
            problems.append(
                "concurrency_cap: the guard did not refuse — the second spawn ran"
            )
            refused = {}
        finally:
            release.set()
            await held
        return _refused(refused, "concurrency_cap", problems) if refused else {}

    return asyncio.run(_drive())


def _capture(tmp_path) -> tuple[dict, list[str]]:
    """Drive the runtime through every outcome; return the shapes and any problems.

    Never raises. A capture that crashed on the first drift would report one
    failure as a dozen fixture errors, and the message a reader needs would be
    buried in a traceback rather than stated.
    """
    from agents.core.iteration_budget import IterationBudget

    shapes: dict[str, list[str]] = {}
    problems: list[str] = []

    # ── the happy path ───────────────────────────────────────────────
    ok = asyncio.run(_runtime(tmp_path).spawn("do a thing", agent="scribe"))
    shapes["spawn.ok"] = _shape(ok)

    # ── each refusal, driven through its real guard ──────────────────
    # Both caps are CLAMPED by the constructor — `max_depth=0` becomes None
    # (unbounded) and `max_concurrent=0` becomes 1 — so passing 0 to "force" a
    # refusal quietly captures the SUCCESS shape instead, and the snapshot would
    # record the wrong keys as the refusal's. Each guard is therefore reached the
    # way production reaches it, and `_assert_refused` below proves it was.

    # Depth: one real spawn, then a child of it, against a cap of 1.
    deep = _runtime(tmp_path, max_depth=1)
    # `.get`, not `[...]`: if the SUCCESS shape is what drifted, this capture must
    # still run so the gate can REPORT that drift. A capture that raised a
    # KeyError here would turn one readable failure into twelve fixture errors.
    first = asyncio.run(deep.spawn("level one"))
    shapes["spawn.recursion_depth_cap"] = _shape(
        _refused(
            asyncio.run(deep.spawn("too deep", parent=str(first.get("id") or ""))),
            "recursion_depth_cap",
            problems,
        )
    )

    # Concurrency: one spawn held open, so `_active` is genuinely at the cap.
    shapes["spawn.concurrency_cap"] = _shape(_capture_concurrency_cap(tmp_path, problems))

    spent = _runtime(tmp_path, budget=IterationBudget(0))
    shapes["spawn.spawn_budget_exhausted"] = _shape(
        _refused(asyncio.run(spent.spawn("no budget")), "spawn_budget_exhausted", problems)
    )

    bad_schema = _runtime(tmp_path)
    shapes["spawn.invalid_output_schema"] = _shape(
        _refused(
            asyncio.run(bad_schema.spawn("bad schema", output_schema="not a dict")),
            "invalid_output_schema",
            problems,
        )
    )

    # ── the control surfaces ─────────────────────────────────────────
    runtime = _runtime(tmp_path)
    spawned = asyncio.run(runtime.spawn("steer me", agent="scribe"))
    shapes["steer.unknown"] = _shape(runtime.steer("nope", "hello"))
    shapes["stop.unknown"] = _shape(runtime.stop("nope"))
    shapes["stop.not_running"] = _shape(runtime.stop(str(spawned.get("id") or "")))
    shapes["stats"] = _shape(runtime.stats())
    record = runtime.get(str(spawned.get("id") or ""))
    shapes["record"] = _shape(record)
    return shapes, problems


@pytest.fixture
def capture(tmp_path):
    return _capture(tmp_path)


@pytest.fixture
def captured(capture):
    return capture[0]


# ── the gate ─────────────────────────────────────────────────────────────────

def test_the_snapshot_exists_and_is_readable():
    assert SNAP.is_file(), (
        "no subagent shape snapshot. Generate it with:\n"
        "  python tests/test_subagent_shape_drift.py --update"
    )
    assert json.loads(SNAP.read_text())


def test_no_subagent_return_shape_has_drifted(captured):
    """A subagent's answer is a plain dict nobody declares, so a renamed key
    breaks every caller at once and no type checker sees it."""
    snap = json.loads(SNAP.read_text())
    problems = []
    for name in sorted(set(captured) & set(snap)):
        gone = sorted(set(snap[name]) - set(captured[name]))
        new = sorted(set(captured[name]) - set(snap[name]))
        if gone:
            problems.append(f"{name}: removed/renamed key(s) {gone}")
        if new:
            problems.append(f"{name}: new key(s) {new}")
    assert not problems, (
        "Subagent return shape changed. If intended, regenerate with:\n"
        "  python tests/test_subagent_shape_drift.py --update\n" + "\n".join(problems)
    )


def test_no_outcome_vanished_from_the_captured_surface(captured):
    """An outcome that stops being reachable is itself drift — a refusal nobody
    can trigger any more is a guard that quietly stopped guarding."""
    snap = json.loads(SNAP.read_text())
    missing = sorted(set(snap) - set(captured))
    added = sorted(set(captured) - set(snap))
    assert not missing, f"outcome(s) no longer reachable: {missing}"
    assert not added, (
        f"NEW outcome(s) not in the snapshot: {added}. If intended, regenerate with:\n"
        "  python tests/test_subagent_shape_drift.py --update"
    )


# ── guarding the guard ───────────────────────────────────────────────────────

def test_every_guard_still_fires(capture):
    """A refusal that stopped refusing is the most dangerous drift here: the
    capture would record the SUCCESS keys as that refusal's shape, and the gate
    would then defend the wrong contract while looking green."""
    _shapes, problems = capture
    assert problems == []


def test_the_capture_actually_captured_something(captured):
    """A capture that silently returned {} would make drift invisible while
    looking perfectly green."""
    assert captured
    assert all(shape for shape in captured.values()), (
        f"empty shape(s): {[k for k, v in captured.items() if not v]}"
    )


@pytest.mark.parametrize("outcome", sorted(CALLER_KEYS))
def test_every_key_the_product_reads_is_still_there(captured, outcome):
    """The snapshot records what the code DOES; this records what the rest of the
    product DEPENDS ON. A snapshot regenerated without thinking still fails here."""
    missing = CALLER_KEYS[outcome] - set(captured[outcome])
    assert not missing, f"{outcome} no longer returns {sorted(missing)}"


def test_every_refusal_is_exercised_not_just_the_happy_path(captured):
    """Refusals are where callers get lazy — `.get("reason")` on a dict that no
    longer has one — and the shapes least likely to be covered elsewhere."""
    refusals = [k for k in captured if k.startswith("spawn.") and k != "spawn.ok"]
    assert len(refusals) >= 4
    for name in refusals:
        assert "reason" in captured[name], f"{name} carries no reason"
        assert "ok" in captured[name], f"{name} carries no ok"


def test_a_refusal_and_a_success_are_told_apart_by_the_same_key(captured):
    """If `ok` were absent from either, a caller would have to know which
    outcome it was looking at before it could tell whether it worked."""
    assert "ok" in captured["spawn.ok"]
    assert "ok" in captured["spawn.concurrency_cap"]


def test_values_are_not_captured_only_keys(captured):
    """A snapshot of values would churn on every timestamp and id, be regenerated
    constantly, and stop being read — which is how a shape gate stops being one."""
    for shape in captured.values():
        assert all(isinstance(key, str) for key in shape)


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        shapes, problems = _capture(Path(tmp))
    if problems:
        # Refusing to write a snapshot from a broken capture: it would bake the
        # wrong shapes in and the gate would defend them from then on.
        print("\n".join(problems), file=sys.stderr)
        raise SystemExit(1)
    if "--update" in sys.argv:
        SNAP.parent.mkdir(parents=True, exist_ok=True)
        SNAP.write_text(json.dumps(shapes, indent=2, sort_keys=True) + "\n")
        print(f"wrote {SNAP}")
    else:
        print(json.dumps(shapes, indent=2, sort_keys=True))
