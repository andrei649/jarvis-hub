"""K1: `execute_code` on the tool surface, and every condition it refuses under.

K0 answered *on whose authority* a call from inside the sandbox is made. K1 is the
door that authority was built in front of. The pipeline underneath is unchanged, so
what these tests are about is almost entirely the conditions — the tool is only safe
to offer because each of the following is a refusal rather than a convention:

* it is not registered at all until the owner switches it on;
* it never runs model-written code on a host interpreter;
* a script cannot call `execute_code`, so one turn is one container;
* a script reaches exactly the tools *this turn* was offered — a guest's script gets
  a guest's reach, not the registry's;
* a gated tool called from inside still only enqueues, which is the single invariant
  that makes an ungated `execute_code` defensible.

The scripts here run for real, through the real file-RPC shim and the real
interpreter, on a sandbox whose isolation is faked to True. **What is therefore not
proven here is the isolation itself** — that is the Docker/WASM backend's own
contract, exercised by the sandbox suite and provable only on a host that has one.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import pytest

from agents.core import code_tools
from agents.core.code_tools import (
    AUTHORITY_UNAVAILABLE,
    DISABLED,
    NOT_ISOLATED,
    SANDBOX_UNAVAILABLE,
    TOOL,
    CodeExecutionTool,
    register_code_tools,
)
from agents.core.sandbox import Sandbox
from agents.core.tool_rpc import ToolRPCServer, ToolRPCValidationError, current_tool_actor

OWNER = SimpleNamespace(admin=True, channel="web")
GUEST = SimpleNamespace(admin=False, channel="web")


def _sandbox(tmp_path, *, isolated=True, timeout=10, max_output_bytes=50_000):
    """A real subprocess sandbox that *claims* isolation, so the circuit runs here.

    Faking `is_isolated` is the only fake: the script, the shim, the RPC files and the
    interpreter are all real. Nothing in this module should be read as evidence about
    a container.
    """
    sandbox = Sandbox(allow_subprocess=True, work_dir=str(tmp_path), timeout=timeout,
                      max_output_bytes=max_output_bytes)
    sandbox._has_docker = False
    sandbox._has_wasmtime = False
    sandbox.is_isolated = lambda: isolated
    return sandbox


def _server(*, gated_enqueued=None):
    async def echo(args):
        return {"echo": args.get("value")}

    async def send_email(args):  # pragma: no cover - must never run
        raise AssertionError("a gated tool executed from inside the sandbox")

    def enqueue(agent, kind, title, **kwargs):
        if gated_enqueued is not None:
            gated_enqueued.append((agent, kind, title))
        return 41

    server = ToolRPCServer(enqueue=enqueue)
    server.register_tool("echo", echo, description="Echo.", input_schema={
        "type": "object", "properties": {"value": {"type": "string"}}})
    server.register_tool("send_email", send_email, gated=True, description="Send.",
                         input_schema={"type": "object", "properties": {}})
    return server


def _settings(**overrides):
    values = {code_tools.SETTING: True}
    values.update(overrides)
    return lambda key, default: values.get(key, default)


def _tool(tmp_path, *, principal=OWNER, settings=None, sandbox=None, patterns=None,
          isolated=True, server=None):
    server = server if server is not None else _server()
    box = sandbox if sandbox is not None else _sandbox(tmp_path, isolated=isolated)
    return server, CodeExecutionTool(
        server,
        sandbox=lambda: box,
        settings=settings or _settings(),
        agent_patterns=(lambda agent: patterns),
        principal=lambda: principal,
        session_id=lambda: "session_k1",
    )


async def _run(tool, code):
    return await tool.execute({"code": code})


CALL = "print(jarvis_tool_call({tool!r}, {args!r}))"


# ── registration ─────────────────────────────────────────────────────────────

def test_the_tool_is_absent_until_the_owner_switches_it_on():
    server = _server()
    assert register_code_tools(
        server, sandbox=lambda: None, settings=lambda key, default: default) == []
    assert server.allows(TOOL) is False
    assert [row["name"] for row in server.tools()] == ["echo", "send_email"]


def test_an_unreadable_setting_leaves_it_off():
    def explode(key, default):
        raise RuntimeError("settings unavailable")

    server = _server()
    assert register_code_tools(server, sandbox=lambda: None, settings=explode) == []
    assert server.allows(TOOL) is False


def test_switched_on_it_registers_ungated_and_declares_untrusted_output(tmp_path):
    server = _server()
    assert register_code_tools(
        server, sandbox=lambda: _sandbox(tmp_path), settings=_settings()) == [TOOL]
    row = next(r for r in server.tools() if r["name"] == TOOL)
    assert row["gated"] is False
    assert row["untrusted_output"] is True
    assert row["capability_id"] == "tool:execute_code"
    assert "jarvis_tool_call" in row["description"]


# ── the arguments ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("args", [
    {}, {"code": ""}, {"code": "   "}, {"code": 7}, {"code": None},
    {"code": "print(1)", "agent": "root"}, {"code": "print(1)", "offered": ["x"]},
])
def test_preflight_refuses_anything_but_one_non_empty_script(tmp_path, args):
    _server_, tool = _tool(tmp_path)
    with pytest.raises(ToolRPCValidationError):
        tool.preflight(args)


def test_preflight_refuses_a_script_over_the_advertised_cap(tmp_path):
    _server_, tool = _tool(tmp_path)
    tool.preflight({"code": "#" * code_tools.MAX_CODE_CHARS})
    with pytest.raises(ToolRPCValidationError) as excinfo:
        tool.preflight({"code": "#" * (code_tools.MAX_CODE_CHARS + 1)})
    assert excinfo.value.reason == code_tools.CODE_TOO_LONG


# ── the refusals that make offering it safe ──────────────────────────────────

@pytest.mark.asyncio
async def test_a_host_without_an_isolated_backend_refuses_instead_of_running(tmp_path):
    marker = tmp_path / "ran.txt"
    _server_, tool = _tool(tmp_path, isolated=False)
    result = await _run(tool, f"open({str(marker)!r}, 'w').write('x')")
    assert result == {"ok": False, "reason": NOT_ISOLATED}
    # The point of the refusal: the script did not run on the host interpreter.
    assert not marker.exists()


@pytest.mark.asyncio
async def test_a_missing_sandbox_refuses(tmp_path):
    _server_, tool = _tool(tmp_path, sandbox=None)
    tool._sandbox = lambda: None
    assert await _run(tool, "print(1)") == {"ok": False, "reason": SANDBOX_UNAVAILABLE}


@pytest.mark.asyncio
async def test_an_unreadable_sandbox_refuses(tmp_path):
    _server_, tool = _tool(tmp_path)

    def explode():
        raise RuntimeError("no sandbox")

    tool._sandbox = explode
    assert await _run(tool, "print(1)") == {"ok": False, "reason": SANDBOX_UNAVAILABLE}


@pytest.mark.asyncio
async def test_the_setting_is_re_read_per_call_not_only_at_registration(tmp_path):
    live = {"on": True}
    settings = lambda key, default: live["on"] if key == code_tools.SETTING else default  # noqa: E731
    _server_, tool = _tool(tmp_path, settings=settings)
    assert (await _run(tool, "print('one')"))["ok"] is True
    live["on"] = False
    assert await _run(tool, "print('two')") == {"ok": False, "reason": DISABLED}


@pytest.mark.asyncio
async def test_a_failed_authority_binding_refuses_the_whole_call(tmp_path, monkeypatch):
    _server_, tool = _tool(tmp_path)
    monkeypatch.setattr(code_tools, "bind", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("no")))
    result = await _run(tool, "print('never')")
    # Not a run with no tools: a half-authority run is a confusing half-success.
    assert result == {"ok": False, "reason": AUTHORITY_UNAVAILABLE}


# ── what a script may reach ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_script_reaches_a_readonly_tool_and_its_result_never_round_trips(tmp_path):
    _server_, tool = _tool(tmp_path)
    result = await _run(tool, """
total = 0
for word in ["a", "bb", "ccc"]:
    reply = jarvis_tool_call("echo", {"value": word})
    total += len(reply["result"]["echo"])
print("TOTAL", total)
""")
    assert result["ok"] is True
    assert "TOTAL 6" in result["stdout"]
    # Three tool calls, one model turn: that is the whole point of the tool.
    assert result["tool_calls"] == 3


@pytest.mark.asyncio
async def test_a_script_cannot_start_another_script(tmp_path):
    server = _server()
    register_code_tools(server, sandbox=lambda: _sandbox(tmp_path), settings=_settings())
    _server_, tool = _tool(tmp_path, server=server)
    result = await _run(tool, CALL.format(tool=TOOL, args={"code": "print('inner')"}))
    assert result["ok"] is True
    assert "'tool_not_offered'" in result["stdout"]
    assert "inner" not in result["stdout"]
    # Registered, and still unreachable: the exclusion is in the offer, not the registry.
    assert server.allows(TOOL) is True
    assert TOOL not in result["offered_tools"]


@pytest.mark.asyncio
async def test_a_guests_script_gets_a_guests_reach_not_the_registrys(tmp_path):
    _server_, tool = _tool(tmp_path, principal=GUEST)
    result = await _run(tool, CALL.format(tool="send_email", args={}))
    assert result["ok"] is True
    assert "'tool_not_offered'" in result["stdout"]
    assert result["offered_tools"] == ["echo"]


@pytest.mark.asyncio
async def test_an_owners_gated_call_enqueues_and_never_executes(tmp_path):
    enqueued: list = []
    server = _server(gated_enqueued=enqueued)
    _server_, tool = _tool(tmp_path, server=server)
    result = await _run(tool, CALL.format(tool="send_email", args={}))
    assert result["ok"] is True
    # The invariant an ungated execute_code rests on: approval, never execution.
    assert "'approval_required'" in result["stdout"]
    assert "'task_id': 41" in result["stdout"]
    assert len(enqueued) == 1
    assert "send_email" in result["offered_tools"]


@pytest.mark.asyncio
async def test_a_per_agent_tools_list_narrows_the_scripts_reach(tmp_path):
    _server_, tool = _tool(tmp_path, patterns=["echo"])
    result = await _run(tool, CALL.format(tool="send_email", args={}))
    assert result["offered_tools"] == ["echo"]
    assert "'tool_not_offered'" in result["stdout"]


@pytest.mark.asyncio
async def test_the_call_budget_is_the_sandbox_setting_and_bounds_a_runaway_loop(tmp_path):
    _server_, tool = _tool(tmp_path, settings=_settings(**{
        "security.sandbox_max_tool_calls": 4}))
    result = await _run(tool, """
for index in range(12):
    reply = jarvis_tool_call("echo", {"value": str(index)})
    if not reply.get("ok"):
        print("STOPPED", index, reply["reason"])
        break
""")
    assert result["max_tool_calls"] == 4
    assert "STOPPED 4 tool_call_limit_exceeded" in result["stdout"]
    assert result["tool_calls"] <= 4


# ── the identity the run is bound under ──────────────────────────────────────

@pytest.mark.asyncio
async def test_the_run_is_bound_as_the_calling_actor_not_the_servers_default(tmp_path):
    seen: list = []
    server = _server()

    def patterns(agent):
        seen.append(agent)
        return None

    tool = CodeExecutionTool(
        server, sandbox=lambda: _sandbox(tmp_path), settings=_settings(),
        agent_patterns=patterns, principal=lambda: OWNER, session_id=lambda: "s",
    )
    server.register_tool(TOOL, tool.execute, description="Run.",
                         input_schema=code_tools.INPUT_SCHEMA)
    response = await server.handle({"tool": TOOL, "args": {"code": "print('hi')"}},
                                   actor="friday")
    assert response["ok"] is True
    assert seen == ["friday"]
    # And the actor is scoped to the call: nothing leaks to whatever runs next.
    assert current_tool_actor() == ""


@pytest.mark.asyncio
async def test_unreadable_agent_patterns_narrow_rather_than_widen(tmp_path):
    server = _server()

    def explode(agent):
        raise RuntimeError("agents.yaml unreadable")

    tool = CodeExecutionTool(
        server, sandbox=lambda: _sandbox(tmp_path), settings=_settings(),
        agent_patterns=explode, principal=lambda: OWNER, session_id=lambda: "s",
    )
    result = await _run(tool, CALL.format(tool="echo", args={"value": "x"}))
    # An empty pattern list offers nothing; it must never fall back to "*".
    assert result["offered_tools"] == []
    assert "'tool_not_offered'" in result["stdout"]


@pytest.mark.asyncio
async def test_an_unreadable_principal_is_the_guest_posture_never_the_owners(tmp_path):
    server = _server()

    def explode():
        raise RuntimeError("no principal")

    tool = CodeExecutionTool(
        server, sandbox=lambda: _sandbox(tmp_path), settings=_settings(),
        agent_patterns=lambda agent: None, principal=explode, session_id=lambda: "s",
    )
    result = await _run(tool, "print('ok')")
    assert "send_email" not in result["offered_tools"]


# ── what comes back ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_sandboxs_own_cap_truncates_once_and_says_so_in_the_stream(tmp_path):
    """Default hosts: the sandbox is the tighter ceiling, so this layer stays out."""
    sandbox = _sandbox(tmp_path, max_output_bytes=4_000)
    _server_, tool = _tool(tmp_path, sandbox=sandbox)
    result = await _run(tool, "print('x' * 40000)")
    assert result["output_limit"] == 4_000
    # One truncation, one notice — this layer did not add a second.
    assert result["truncated"] is False
    assert result["stdout"].count("TRUNCATED") == 1
    assert "OUTPUT TRUNCATED" in result["stdout"]
    assert len(result["stdout"]) < 40_000


@pytest.mark.asyncio
async def test_a_generous_sandbox_still_meets_this_tools_own_ceiling(tmp_path):
    """A host configured to allow more than 50 KB does not get to flood the turn."""
    sandbox = _sandbox(tmp_path, max_output_bytes=10 * code_tools.MAX_OUTPUT_BYTES)
    _server_, tool = _tool(tmp_path, sandbox=sandbox)
    # Forty lines just under the per-line limit: a shape the line caps leave alone,
    # so what this test measures is the byte ceiling and nothing else. (A single
    # 70 KB line would now be elided by the line cap before the byte cap ever saw
    # it — still bounded, but it would stop testing the ceiling this test is named
    # for.)
    result = await _run(
        tool,
        f"print(('x' * ({code_tools.MAX_LINE_LENGTH} - 1) + chr(10)) * 40)",
    )
    assert result["output_limit"] == code_tools.MAX_OUTPUT_BYTES
    assert result["truncated"] is True
    assert "STDOUT TRUNCATED" in result["stdout"]
    assert "bytes omitted" in result["stdout"]
    assert result["stdout"].count("TRUNCATED") == 1


@pytest.mark.asyncio
async def test_a_run_that_stays_under_the_byte_budget_can_still_be_shaped(tmp_path):
    """H298: bytes are not a proxy for shape, and the sandbox's cap only sees bytes.

    Forty thousand short lines is well under 50 KB and still a wall nobody — model or
    owner — can read. The elision keeps both ends and says how many lines went.
    """
    _server_, tool = _tool(tmp_path)
    result = await _run(tool, "for i in range(40000): print(i)")

    assert result["truncated"] is True
    lines = result["stdout"].rstrip("\n").split("\n")
    assert len(lines) <= code_tools.MAX_OUTPUT_LINES + 1
    assert lines[0] == "0"
    assert lines[-1] == "39999", "the tail is the half that says what happened"
    # Two notices, and neither erased the other: the sandbox's byte cap ran first
    # over the whole 240 KB and left its record in the middle of the stream — which
    # is exactly where the line cap cuts — and the line cap kept it.
    assert "bytes omitted" in result["stdout"]
    assert "lines omitted out of" in result["stdout"]


@pytest.mark.asyncio
async def test_one_enormous_line_is_elided_in_the_middle_not_dropped(tmp_path):
    _server_, tool = _tool(tmp_path)
    result = await _run(tool, "print('a' + 'b' * 9000 + 'c')")

    assert result["truncated"] is True
    assert result["stdout"].startswith("ab")
    assert result["stdout"].rstrip("\n").endswith("bc")
    assert "chars omitted" in result["stdout"]
    assert len(result["stdout"]) < 9_002


@pytest.mark.asyncio
async def test_a_script_that_raises_reports_the_failure_without_pretending_it_worked(tmp_path):
    _server_, tool = _tool(tmp_path)
    result = await _run(tool, "raise ValueError('boom')")
    assert result["ok"] is False
    assert result["exit_code"] != 0
    assert "ValueError" in result["stderr"]
    assert result["timed_out"] is False


@pytest.mark.asyncio
async def test_an_unknown_tool_name_reads_the_same_as_a_hidden_one(tmp_path):
    """Probing must not map the registry: 'not registered' and 'not offered' agree."""
    _server_, tool = _tool(tmp_path, principal=GUEST)
    result = await _run(tool, """
for name in ["no_such_tool_at_all", "send_email"]:
    print(name, jarvis_tool_call(name, {}).get("reason"))
""")
    assert "no_such_tool_at_all tool_not_offered" in result["stdout"]
    assert "send_email tool_not_offered" in result["stdout"]


# ── the acceptance clause: a real tool loop, end to end ──────────────────────

@pytest.mark.asyncio
async def test_a_real_tool_loop_selects_the_tool_and_gets_bounded_filtered_stdout(tmp_path):
    """The plan's K1 acceptance, run *through* `AgentToolRuntime` rather than around it.

    The model asks for one script; the script makes three tool calls and prints a
    summary; the loop hands back one observation. The intermediate results never
    enter the transcript — which is the entire reason this tool exists.
    """
    from agents.core.agent_runtime import AgentToolRuntime
    from agents.core.llm.tool_protocol import ToolCall, ToolTurn

    server = _server()
    register_code_tools(
        server, sandbox=lambda: _sandbox(tmp_path), settings=_settings(),
        agent_patterns=lambda agent: None, principal=lambda: OWNER,
        session_id=lambda: "session_k1",
    )
    script = (
        'sizes = [len(jarvis_tool_call("echo", {"value": w})["result"]["echo"])\n'
        '         for w in ["a", "bb", "ccc"]]\n'
        'print("LONGEST", max(sizes))\n'
    )

    class _Backend:
        supports_tools = True

        def __init__(self):
            self.turns = [
                ToolTurn(tool_calls=(ToolCall(
                    id="call-code", name=TOOL,
                    raw_arguments=json.dumps({"code": script}),
                    arguments={"code": script},
                ),), finish_reason="tool_calls"),
                ToolTurn(content="The longest was 3 characters.", finish_reason="stop"),
            ]
            self.offered: list = []
            self.messages: list = []

        async def generate_tool_turn(self, **kwargs):
            self.offered.append([spec.name for spec in (kwargs.get("tools") or ())])
            self.messages.append([dict(message) for message in kwargs["messages"]])
            return self.turns.pop(0)

    backend = _Backend()
    answer = await AgentToolRuntime(server, enabled=lambda: True).run(
        agent_id="jarvis", backend=backend, model="local-model",
        prompt="how long is the longest word", system="You are Jarvis.",
        max_tokens=256, temperature=0.2,
    )

    assert answer == "The longest was 3 characters."
    assert TOOL in backend.offered[0]
    observation = "".join(
        str(message.get("content") or "")
        for message in backend.messages[-1] if message.get("role") == "tool")
    # One bounded observation carrying the script's summary...
    assert "LONGEST 3" in observation
    # ...and not the three intermediate results it was computed from.
    assert "bb" not in observation


# ── K2: the session path, from the tool's side ───────────────────────────────

def _kernels(tmp_path, **kwargs):
    from agents.core.session_kernels import (
        WORKER_SOURCE,
        PipeKernelBackend,
        SessionKernelManager,
    )

    kwargs.setdefault("cell_timeout_seconds", 20)
    kwargs.setdefault("rpc_root", str(tmp_path / "kernel-rpc"))
    return SessionKernelManager(
        PipeKernelBackend(lambda key, token, rpc_dir="": [sys.executable, "-c", WORKER_SOURCE],
                          name="local"),
        **kwargs)


def _session_tool(tmp_path, *, on=True, authorizer=None, **kwargs):
    settings = _settings(**{code_tools.SESSION_SETTING: on})
    server, tool = _tool(tmp_path, settings=settings, **kwargs)
    tool._kernels = _kernels(tmp_path)
    tool._authorizer = authorizer
    return server, tool


def test_the_reset_argument_exists_only_where_a_kernel_is_behind_the_tool(tmp_path):
    _server_, off = _tool(tmp_path)
    with pytest.raises(ToolRPCValidationError):
        off.preflight({"code": "print(1)", "reset": True})
    _server2, on = _session_tool(tmp_path)
    assert on.preflight({"code": "print(1)", "reset": True}) == {"code": "print(1)", "reset": True}
    assert on.preflight({"code": "print(1)"}) == {"code": "print(1)"}


def test_a_registration_advertises_persistence_only_when_it_can_keep_it(tmp_path):
    plain = _server()
    register_code_tools(plain, sandbox=lambda: _sandbox(tmp_path), settings=_settings())
    row = next(r for r in plain.tools() if r["name"] == TOOL)
    assert sorted(row["input_schema"]["properties"]) == ["code"]
    assert "persist" not in row["description"]

    sessions = _server()
    register_code_tools(
        sessions, sandbox=lambda: _sandbox(tmp_path),
        settings=_settings(**{code_tools.SESSION_SETTING: True}),
        kernels=_kernels(tmp_path))
    row = next(r for r in sessions.tools() if r["name"] == TOOL)
    assert sorted(row["input_schema"]["properties"]) == ["code", "reset"]
    assert "persist" in row["description"]


@pytest.mark.asyncio
async def test_the_session_path_keeps_state_between_two_tool_calls(tmp_path):
    _server_, tool = _session_tool(tmp_path)
    first = await _run(tool, "import math\nvalue = math.tau\nprint('set')")
    second = await _run(tool, "print('tau', round(value, 3))")
    assert first["session"] is True and first["continuity"] == "new"
    assert second["continuity"] == "continued" and "tau 6.283" in second["stdout"]
    assert second["state_lost"] is False
    await tool._kernels.shutdown()


@pytest.mark.asyncio
async def test_reset_starts_over_and_says_so(tmp_path):
    _server_, tool = _session_tool(tmp_path)
    await _run(tool, "kept = 'yes'")
    after = await tool.execute({"code": "print('kept' in dir())", "reset": True})
    assert after["continuity"] == "reset" and after["state_lost"] is True
    assert "False" in after["stdout"]
    await tool._kernels.shutdown()


@pytest.mark.asyncio
async def test_a_cell_the_kernel_denies_never_runs(tmp_path):
    from agents.core.kernel import Decision, Verdict

    denials = {"on": False}

    def authorizer(action, capability=None):
        return Decision(Verdict.DENY if denials["on"] else Verdict.GRANT, reason="test")

    _server_, tool = _session_tool(tmp_path, authorizer=authorizer)
    await _run(tool, "touched = False")
    denials["on"] = True
    denied = await _run(tool, "touched = True")
    assert denied["ok"] is False and denied["reason"] == code_tools.SESSION_DENIED
    denials["on"] = False
    after = await _run(tool, "print('touched', touched)")
    assert "touched False" in after["stdout"]
    await tool._kernels.shutdown()


@pytest.mark.asyncio
async def test_a_cell_reaches_the_same_tools_the_one_shot_script_would(tmp_path):
    _server_, tool = _session_tool(tmp_path)
    outcome = await _run(tool, CALL.format(tool="echo", args={"value": "hi"}))
    assert "'echo': 'hi'" in outcome["stdout"]
    gated = await _run(tool, CALL.format(tool="send_email", args={}))
    assert "'approval_required'" in gated["stdout"]
    recursive = await _run(tool, CALL.format(tool=TOOL, args={"code": "print('inner')"}))
    assert "'tool_not_offered'" in recursive["stdout"]
    await tool._kernels.shutdown()


@pytest.mark.asyncio
async def test_sessions_switched_off_mid_flight_fall_back_to_one_shot(tmp_path):
    live = {"sessions": True}
    settings = lambda key, default: (  # noqa: E731
        True if key == code_tools.SETTING else
        live["sessions"] if key == code_tools.SESSION_SETTING else default)
    server, tool = _tool(tmp_path, settings=settings)
    tool._kernels = _kernels(tmp_path)
    kept = await _run(tool, "kept = 1\nprint('session')")
    assert kept["session"] is True
    live["sessions"] = False
    plain = await _run(tool, "print('kept' in dir())")
    # Named, not silent: the one-shot result has no continuity to report at all.
    assert "session" not in plain and "continuity" not in plain
    assert "False" in plain["stdout"]
    await tool._kernels.shutdown()
