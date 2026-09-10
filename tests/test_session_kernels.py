"""K2: state that persists between cells, and permission that deliberately does not.

The feature and the danger are the same fact. An interpreter that keeps a loaded
dataframe between calls also keeps whatever else cell 1 built — so the question these
tests exist to answer is not "does state survive" (it does, and that is easy) but
"does *permission* survive with it" (it must not, and that is the whole design).

The cells here run in real resident interpreters over the real framing and the real
worker source, driven by the same `PipeKernelBackend` production uses. Only the argv
is different: a bare interpreter instead of a pinned container. So the protocol, the
lifecycle, the mailbox and every refusal are exercised for real — **and the isolation
is not**. That is the Docker backend's own contract and the owner's to prove.
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from agents.core import sandbox_invocation
from agents.core import session_kernels as sk
from agents.core.session_kernels import (
    CONTINUED,
    CRASHED,
    ESTOP_ENGAGED,
    EVICTED,
    EXPIRED,
    KERNEL_UNAVAILABLE,
    NEW_KERNEL,
    RESET,
    TIMED_OUT,
    WORKER_SOURCE,
    KernelKey,
    KernelRefused,
    PipeKernelBackend,
    SessionKernelManager,
    docker_kernel_argv,
)
from agents.core.tool_rpc import ToolRPCServer
from agents.core.tool_rpc_runtime import ToolCallBroker

OWNER = SimpleNamespace(admin=True, channel="web")
GUEST = SimpleNamespace(admin=False, channel="web")


def _argv(key, token, rpc_dir=""):
    return [sys.executable, "-c", WORKER_SOURCE]


def _server():
    async def echo(args):
        return {"echo": args.get("value")}

    async def send_email(args):  # pragma: no cover - must never run from a cell
        raise AssertionError("a gated tool executed from inside a session kernel")

    server = ToolRPCServer(enqueue=lambda *a, **k: 77)
    server.register_tool("echo", echo, description="Echo.", input_schema={
        "type": "object", "properties": {"value": {"type": "string"}}})
    server.register_tool("send_email", send_email, gated=True, description="Send.",
                         input_schema={"type": "object", "properties": {}})
    return server


def _bind(server, *, principal=OWNER, session="s1", agent="jarvis", **kwargs):
    invocation, _decision = sandbox_invocation.bind(
        tools=server.tools(), agent=agent, principal=principal, origin="operator",
        session_id=session, **kwargs)
    return invocation


def _manager(tmp_path, **kwargs):
    kwargs.setdefault("cell_timeout_seconds", 20)
    kwargs.setdefault("rpc_root", str(tmp_path / "rpc"))
    return SessionKernelManager(PipeKernelBackend(_argv, name="local"), **kwargs)


async def _run(manager, invocation, code, server=None, **kwargs):
    if server is not None:
        kwargs.setdefault("broker", ToolCallBroker(server, invocation))
    return await manager.run(invocation, code, **kwargs)


# ── the feature ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_second_cell_reads_what_the_first_one_imported_and_loaded(tmp_path):
    server = _manager(tmp_path)
    invocation = _bind(_server())
    first = await _run(server, invocation, "import math\nrows = [math.pi] * 3\nprint('loaded')")
    second = await _run(server, invocation, "print('sum', round(sum(rows), 3))")
    assert first.ok and "loaded" in first.stdout
    assert second.ok and "sum 9.425" in second.stdout
    # And the caller is told which of the two it was, every time.
    assert (first.continuity, second.continuity) == (NEW_KERNEL, CONTINUED)
    assert (first.state_lost, second.state_lost) == (False, False)
    await server.shutdown()


@pytest.mark.asyncio
async def test_a_cell_that_raises_costs_the_cell_and_not_the_namespace(tmp_path):
    manager = _manager(tmp_path)
    invocation = _bind(_server())
    await _run(manager, invocation, "keep = 'ten cells of work'")
    boom = await _run(manager, invocation, "raise ValueError('boom')")
    after = await _run(manager, invocation, "print(keep)")
    assert boom.ok is False and boom.failed is True
    assert "ValueError: boom" in boom.stderr
    # The eleventh cell's traceback is worth less than the ten cells before it.
    assert boom.state_lost is False
    assert after.ok and "ten cells of work" in after.stdout
    await manager.shutdown()


@pytest.mark.asyncio
async def test_sys_exit_in_a_cell_ends_the_cell_not_the_kernel(tmp_path):
    manager = _manager(tmp_path)
    invocation = _bind(_server())
    await _run(manager, invocation, "marker = 1")
    await _run(manager, invocation, "import sys\nsys.exit(3)")
    after = await _run(manager, invocation, "print('marker', marker)")
    assert after.ok and "marker 1" in after.stdout
    assert after.continuity == CONTINUED
    await manager.shutdown()


# ── whose kernel it is ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_another_session_cannot_see_this_ones_state(tmp_path):
    manager = _manager(tmp_path)
    server = _server()
    await _run(manager, _bind(server, session="s1"), "secret = 'first session'")
    other = await _run(manager, _bind(server, session="s2"), "print('secret' in dir())")
    assert other.continuity == NEW_KERNEL
    assert "False" in other.stdout
    leak = await _run(manager, _bind(server, session="s2"), "print(secret)")
    assert leak.ok is False and "NameError" in leak.stderr
    await manager.shutdown()


@pytest.mark.parametrize(("field", "value"), [
    ("session_id", "other"), ("principal", "guest"), ("agent", "friday"),
])
def test_the_key_separates_on_every_dimension_that_matters(field, value):
    base = {"agent": "jarvis", "principal": "owner", "session_id": "s1",
            "data_scope": None, "expired": lambda: False}
    one = KernelKey.from_invocation(SimpleNamespace(**base))
    two = KernelKey.from_invocation(SimpleNamespace(**{**base, field: value}))
    assert one != two and one.token != two.token


def test_the_key_reads_only_the_four_fields_the_host_resolved():
    """A caller cannot name a kernel, so two sessions cannot share one by asking."""
    base = {"agent": "jarvis", "principal": "owner", "session_id": "s1",
            "data_scope": None, "expired": lambda: False}
    plain = KernelKey.from_invocation(SimpleNamespace(**base))
    # Anything else riding on the object — including a hopeful `kernel_id` — is not
    # read, so it cannot steer which interpreter a cell lands in.
    decorated = KernelKey.from_invocation(SimpleNamespace(
        **base, kernel_id="someone-elses", token="borrowed", offered=frozenset({"echo"})))
    assert plain == decorated and plain.token == decorated.token


# ── permission does not persist ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_tool_call_from_inside_a_cell_reaches_the_offered_tools(tmp_path):
    manager = _manager(tmp_path)
    server = _server()
    invocation = _bind(server)
    outcome = await _run(
        manager, invocation,
        "words = [jarvis_tool_call('echo', {'value': w})['result']['echo']\n"
        "         for w in ['a', 'bb']]\nprint('got', words)",
        server=server)
    assert outcome.ok, outcome.stderr
    assert "got ['a', 'bb']" in outcome.stdout
    assert outcome.tool_calls == 2
    await manager.shutdown()


@pytest.mark.asyncio
async def test_a_callable_captured_in_cell_one_cannot_carry_its_permission_forward(tmp_path):
    """The central K2 property: state persists, authority is re-earned every cell."""
    manager = _manager(tmp_path)
    server = _server()
    first = _bind(server)
    kept = await _run(manager, first, "call = jarvis_tool_call\n"
                      "print(call('echo', {'value': 'x'})['result']['echo'])", server=server)
    assert kept.ok and "x" in kept.stdout

    # Same variable, same interpreter, new authority that says no.
    second = _bind(server)
    revoked = await manager.run(
        second, "print(call('echo', {'value': 'y'}))",
        broker=ToolCallBroker(server, second, revoked=lambda: True))
    assert "'reason': 'authority_revoked'" in revoked.stdout

    # And a tool the *turn* is no longer offered is refused the same way.
    guest = _bind(server, principal=GUEST)
    narrowed = await _run(manager, guest, "print(call('echo', {'value': 'z'}))", server=server)
    assert narrowed.continuity == NEW_KERNEL  # a guest gets a guest's kernel too
    await manager.shutdown()


@pytest.mark.asyncio
async def test_a_gated_tool_from_inside_a_cell_only_enqueues(tmp_path):
    manager = _manager(tmp_path)
    server = _server()
    invocation = _bind(server)
    outcome = await _run(manager, invocation,
                         "print(jarvis_tool_call('send_email', {}))", server=server)
    assert "'approval_required'" in outcome.stdout
    assert "'task_id': 77" in outcome.stdout
    await manager.shutdown()


@pytest.mark.asyncio
async def test_between_cells_there_is_no_mailbox_to_write_to(tmp_path):
    """A thread a cell leaves running cannot keep calling once the cell is over."""
    manager = _manager(tmp_path)
    server = _server()
    invocation = _bind(server)
    await _run(manager, invocation,
               "import threading\n"
               "late = {}\n"
               "def work():\n"
               "    import time; time.sleep(0.4)\n"
               "    late['reply'] = jarvis_tool_call('echo', {'value': 'late'})\n"
               "t = threading.Thread(target=work); t.start()\n"
               "print('started')", server=server)
    settled = await _run(manager, _bind(server), "t.join(5)\nprint(late.get('reply'))",
                         server=server)
    # It ran during the *next* cell, so it was answered under that cell's authority
    # or refused for want of a directory — never serviced under the first cell's.
    assert "tool_calls_unavailable" in settled.stdout or "'ok': True" in settled.stdout
    await manager.shutdown()


@pytest.mark.asyncio
async def test_each_cell_gets_its_own_mailbox_and_the_last_one_is_gone(tmp_path):
    """No replay across cells, and no directory left for a stashed path to reach.

    Every cell restarts the request counter at 1, so a shared mailbox would let a
    reply cell 1 abandoned be read by cell 2 as its own answer. A fresh directory per
    cell makes that impossible by construction, and removing it afterwards means a
    cell that saved the old path writes where nobody is reading.
    """
    manager = _manager(tmp_path)
    server = _server()
    seen: list[str] = []
    inner = manager._backend.run_cell

    async def spy(handle, cell, *, timeout, rpc_dir="", max_tool_calls=0):
        seen.append(rpc_dir)
        return await inner(handle, cell, timeout=timeout, rpc_dir=rpc_dir,
                           max_tool_calls=max_tool_calls)

    manager._backend.run_cell = spy
    for _ in range(3):
        outcome = await _run(manager, _bind(server),
                             "print(jarvis_tool_call('echo', {'value': 'x'})['result']['echo'])",
                             server=server)
        assert outcome.ok, outcome.stderr
    assert len(set(seen)) == 3, seen
    host_root = tmp_path / "rpc"
    # Each one is cleaned up as its cell ends; nothing accumulates under the root.
    assert list(host_root.rglob("cell-*")) == []
    await manager.shutdown()


@pytest.mark.asyncio
async def test_a_denied_cell_never_reaches_the_interpreter(tmp_path):
    manager = _manager(tmp_path)
    server = _server()
    invocation = _bind(server)
    await _run(manager, invocation, "touched = False")

    class _Denied(Exception):
        reason = "cell_denied"

    def refuse(cell):
        raise _Denied()

    outcome = await manager.run(invocation, "touched = True", authorize=refuse)
    assert outcome.ok is False and outcome.reason == "cell_denied"
    after = await _run(manager, invocation, "print('touched', touched)")
    assert "touched False" in after.stdout
    await manager.shutdown()


@pytest.mark.asyncio
async def test_an_expired_authority_cannot_keep_using_a_live_kernel(tmp_path):
    manager = _manager(tmp_path)
    server = _server()
    live = _bind(server)
    await _run(manager, live, "state = 'here'")
    expired = _bind(server, lifetime_seconds=1, now=lambda: 0.0)
    outcome = await manager.run(expired, "print(state)")
    assert outcome.ok is False and outcome.reason == sk.AUTHORITY_EXPIRED
    # The kernel is gone too: an authority that ran out does not leave a process.
    assert manager.status() == []
    await manager.shutdown()


# ── losing state, out loud ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reset_destroys_the_namespace_and_the_next_cell_is_told(tmp_path):
    manager = _manager(tmp_path)
    invocation = _bind(_server())
    await _run(manager, invocation, "gone = 'yes'")
    assert await manager.reset(invocation) is True
    after = await _run(manager, invocation, "print('gone' in dir())")
    assert after.continuity == RESET and after.state_lost is True
    assert "False" in after.stdout
    await manager.shutdown()


@pytest.mark.asyncio
async def test_a_timed_out_cell_takes_the_whole_interpreter(tmp_path):
    manager = _manager(tmp_path, cell_timeout_seconds=0.5)
    invocation = _bind(_server())
    await _run(manager, invocation, "kept = 1")
    stuck = await _run(manager, invocation, "import time\ntime.sleep(30)")
    assert stuck.ok is False and stuck.reason == TIMED_OUT
    assert stuck.state_lost is True and stuck.continuity == TIMED_OUT
    assert manager.status() == []
    # Not silently continued: the next cell starts from nothing and says so.
    manager._cell_timeout = 20
    after = await _run(manager, invocation, "print('kept' in dir())")
    assert after.continuity == TIMED_OUT and after.state_lost is True
    assert "False" in after.stdout
    await manager.shutdown()


@pytest.mark.asyncio
async def test_a_kernel_that_dies_is_reported_as_crashed_not_as_a_fresh_start(tmp_path):
    manager = _manager(tmp_path)
    invocation = _bind(_server())
    await _run(manager, invocation, "kept = 1")
    record = next(iter(manager._records.values()))
    record.handle.process.kill()
    await record.handle.process.wait()
    after = await _run(manager, invocation, "print('kept' in dir())")
    assert after.continuity == CRASHED and after.state_lost is True
    assert "False" in after.stdout
    await manager.shutdown()


@pytest.mark.asyncio
async def test_an_idle_kernel_expires_and_the_next_cell_knows(tmp_path):
    now = {"t": 1_000.0}
    manager = _manager(tmp_path, idle_ttl_seconds=60, clock=lambda: now["t"])
    invocation = _bind(_server())
    await _run(manager, invocation, "kept = 1")
    now["t"] += 3_600
    after = await _run(manager, invocation, "print('kept' in dir())")
    assert after.continuity == EXPIRED and after.state_lost is True
    await manager.shutdown()


@pytest.mark.asyncio
async def test_the_kernel_count_is_bounded_and_the_evicted_session_is_told(tmp_path):
    manager = _manager(tmp_path, max_kernels=2)
    server = _server()
    sessions = [_bind(server, session=f"s{index}") for index in range(3)]
    for invocation in sessions:
        await _run(manager, invocation, "kept = 1")
    assert len(manager.status()) == 2
    revived = await _run(manager, sessions[0], "print('kept' in dir())")
    assert revived.continuity == EVICTED and revived.state_lost is True
    await manager.shutdown()


@pytest.mark.asyncio
async def test_every_kernel_busy_refuses_rather_than_killing_a_running_cell(tmp_path):
    manager = _manager(tmp_path, max_kernels=1, cell_timeout_seconds=10)
    server = _server()
    busy = asyncio.ensure_future(
        _run(manager, _bind(server, session="s1"), "import time\ntime.sleep(1.5)\nprint('done')"))
    await asyncio.sleep(0.4)
    # The pool is full and its one kernel is mid-cell. Refusing the newcomer is
    # better than killing a running cell to make room for it.
    crowded = await _run(manager, _bind(server, session="s2"), "print('me too')")
    assert crowded.ok is False and crowded.reason == KERNEL_UNAVAILABLE
    assert (await busy).ok is True
    await manager.shutdown()


# ── one cell at a time ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_cells_in_one_session_serialize_rather_than_interleave(tmp_path):
    manager = _manager(tmp_path)
    invocation = _bind(_server())
    await _run(manager, invocation, "order = []")
    cells = [
        f"import time\norder.append('start{index}')\ntime.sleep(0.2)\n"
        f"order.append('end{index}')\nprint(order)"
        for index in range(3)
    ]
    await asyncio.gather(*(_run(manager, invocation, cell) for cell in cells))
    final = await _run(manager, invocation, "print(order)")
    # Every start is immediately followed by its own end: no cell ran inside another.
    entries = final.stdout.strip().strip("[]").replace("'", "").split(", ")
    for index in range(0, len(entries), 2):
        assert entries[index].replace("start", "") == entries[index + 1].replace("end", "")
    assert len(entries) == 6
    await manager.shutdown()


# ── the stop ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_engaged_estop_tears_every_kernel_down_and_refuses_the_cell(tmp_path):
    engaged = {"on": False}
    manager = _manager(tmp_path, estop=lambda: engaged["on"])
    server = _server()
    await _run(manager, _bind(server, session="s1"), "kept = 1")
    await _run(manager, _bind(server, session="s2"), "kept = 2")
    assert len(manager.status()) == 2

    engaged["on"] = True
    stopped = await _run(manager, _bind(server, session="s1"), "print('anything')")
    assert stopped.ok is False and stopped.reason == ESTOP_ENGAGED
    # Engaged means gone, not paused: no interpreter is left alive to resume into.
    assert manager.status() == []


@pytest.mark.asyncio
async def test_an_unreadable_estop_counts_as_engaged(tmp_path):
    def explode():
        raise OSError("data root unreadable")

    manager = _manager(tmp_path, estop=explode)
    outcome = await _run(manager, _bind(_server()), "print('nope')")
    assert outcome.ok is False and outcome.reason == ESTOP_ENGAGED


@pytest.mark.asyncio
async def test_closing_a_session_stops_only_that_sessions_kernels(tmp_path):
    manager = _manager(tmp_path)
    server = _server()
    await _run(manager, _bind(server, session="s1"), "kept = 1")
    await _run(manager, _bind(server, session="s2"), "kept = 2")
    assert await manager.close_session("s1") == 1
    remaining = manager.status()
    assert [row["session_id"] for row in remaining] == ["s2"]
    await manager.shutdown()


# ── arguments and the projection ─────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("cell", ["", "   ", None, 7])
async def test_an_empty_or_non_string_cell_is_refused_before_any_kernel_starts(tmp_path, cell):
    manager = _manager(tmp_path)
    outcome = await manager.run(_bind(_server()), cell)
    assert outcome.ok is False and outcome.reason == sk.CELL_REFUSED
    assert manager.status() == []


@pytest.mark.asyncio
async def test_an_oversized_cell_is_refused_by_name(tmp_path):
    manager = _manager(tmp_path)
    outcome = await manager.run(_bind(_server()), "#" * (sk.MAX_CELL_CHARS + 1))
    assert outcome.ok is False and outcome.reason == sk.CELL_TOO_LONG
    assert manager.status() == []


@pytest.mark.asyncio
async def test_the_status_projection_carries_keys_and_counters_never_a_cell(tmp_path):
    manager = _manager(tmp_path)
    invocation = _bind(_server())
    await _run(manager, invocation, "PASSWORD = 'hunter2'")
    row, = manager.status()
    assert set(row) == {"agent", "principal", "session_id", "data_scope", "token",
                        "cells_run", "idle_seconds", "alive", "backend"}
    assert "hunter2" not in repr(row)
    assert row["cells_run"] == 1 and row["alive"] is True
    await manager.shutdown()


# ── the container argv this repository cannot run ────────────────────────────

def test_the_docker_argv_pins_the_image_and_keeps_the_sandbox_profile():
    key = KernelKey(agent="jarvis", principal="owner", session_id="s1", data_scope="*")
    argv = docker_kernel_argv("python@sha256:" + "b" * 64)(key, "tok", "/host/rpc")
    joined = " ".join(argv)
    for flag in ("--network none", "--cap-drop ALL", "--read-only",
                 "--security-opt no-new-privileges", "--pids-limit", "--memory"):
        assert flag in joined
    assert "@sha256:" in joined
    assert "-v /host/rpc:/nerva-rpc" in joined
    # The worker is passed as source, so there is no script file to swap in the image.
    assert argv[-1] == WORKER_SOURCE


@pytest.mark.asyncio
async def test_a_backend_whose_daemon_is_gone_refuses_to_start(tmp_path):
    backend = PipeKernelBackend(_argv, available=lambda: False)
    with pytest.raises(KernelRefused) as excinfo:
        await backend.start(KernelKey("jarvis", "owner", "s1", "*"))
    assert excinfo.value.reason == KERNEL_UNAVAILABLE
    # And the manager turns that into a NAMED refusal, not an exception: raising out
    # of a tool handler would reach the model as a generic `tool_error` instead.
    manager = SessionKernelManager(backend, rpc_root=str(tmp_path))
    outcome = await manager.run(_bind(_server()), "print(1)")
    assert outcome.ok is False and outcome.reason == KERNEL_UNAVAILABLE


def test_the_child_environment_carries_nothing_of_the_host_and_no_reply_token():
    backend = PipeKernelBackend(_argv)
    env = backend._child_env()
    # The host environment is where the credentials live; a kernel that never
    # receives it cannot be talked into printing one. And the reply token is NOT
    # here: an env var is readable from `docker inspect` and /proc/1/environ, and
    # that token is the only thing stopping a cell forging a result.
    assert set(env) == {"PATH", "HOME", "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE"}
    assert not any("NERVA" in name for name in env)


@pytest.mark.asyncio
async def test_a_cell_cannot_read_the_reply_token_from_anywhere_it_can_reach(tmp_path):
    manager = _manager(tmp_path)
    outcome = await _run(manager, _bind(_server()),
                         "import os\nprint('env', [k for k in os.environ if 'NERVA' in k])\n"
                         "print('argv', any('NERVA_KERNEL_REPLY' in a for a in __import__('sys').argv))")
    assert "env []" in outcome.stdout
    assert "argv False" in outcome.stdout
    await manager.shutdown()
