"""H652 — a full turn (system, prompt, tool calls, tool results, reply) saved per session
and exported as ShareGPT through ``GET /sessions/{id}/trajectories`` and
``nerva sessions export <id> --sharegpt``.

Offline: a scripted tool-turn backend and a real ToolRPC server and runtime.
"""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from agents.core import trajectory
from agents.core.agent import Agent
from agents.core.agent_runtime import AgentToolRuntime
from agents.core.llm.request_context import session_scope
from agents.core.llm.tool_protocol import ToolCall, ToolTurn
from agents.core.tool_rpc import ToolRPCServer

SECRET = "sk-ant-api03-" + "A" * 40


@pytest.fixture(autouse=True)
def data_home(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_HOME", str(tmp_path))
    monkeypatch.setenv(trajectory.ENV_FLAG, "1")
    return tmp_path


class _ScriptedBackend:
    supports_tools = True

    def __init__(self, turns):
        self.turns = list(turns)

    async def generate_tool_turn(self, **kwargs):
        return self.turns.pop(0)


def _server():
    server = ToolRPCServer()

    async def echo(args):
        return {"echo": args["value"]}

    server.register_tool("echo", echo, description="Echo one value.", input_schema={
        "type": "object", "properties": {"value": {"type": "string"}},
        "required": ["value"], "additionalProperties": False})
    return server


def _tool_turns(value="hi"):
    raw = json.dumps({"value": value})
    return [
        ToolTurn(content="let me echo", tool_calls=(ToolCall(id="call-1", name="echo", raw_arguments=raw,
                                                             arguments={"value": value}),),
                 finish_reason="tool_calls"),
        ToolTurn(content="Echo completed", finish_reason="stop"),
    ]


def _agent(turns):
    agent = Agent("jarvis", {"name": "Jarvis"})
    agent.tool_runtime = AgentToolRuntime(_server(), enabled=lambda: True)
    return agent, _ScriptedBackend(turns)


async def _ask(agent, backend, *, session="sess-1", prompt="echo hi"):
    return await agent.generate_response(backend=backend, model="local-model", prompt=prompt,
                                         system="You are Jarvis.", max_tokens=256, temperature=0.2,
                                         session_id=session)


# ── capture ──────────────────────────────────────────────────────────────────


async def test_a_tool_turn_is_saved_whole_with_calls_results_and_reply():
    agent, backend = _agent(_tool_turns())
    assert await _ask(agent, backend) == "Echo completed"

    [record] = trajectory.load("sess-1")
    assert record["agent_id"] == "jarvis" and record["model"] == "local-model"
    assert record["prompt"] == "echo hi"
    assert record["system"].startswith("You are Jarvis.")  # the guided system the loop sent
    assistant, tool = record["steps"]
    assert assistant["role"] == "assistant" and assistant["content"] == "let me echo"
    assert assistant["tool_calls"] == [{"id": "call-1", "name": "echo", "arguments": '{"value": "hi"}'}]
    assert tool["role"] == "tool" and tool["tool_call_id"] == "call-1" and tool["name"] == "echo"
    assert json.loads(tool["content"])["result"] == {"echo": "hi"}
    assert record["reply"] == "Echo completed"
    assert record["exit_reason"] == "model_response" and record["completed"] is True


async def test_capture_is_off_by_default(monkeypatch):
    monkeypatch.delenv(trajectory.ENV_FLAG)
    agent, backend = _agent(_tool_turns())
    assert await _ask(agent, backend) == "Echo completed"
    assert trajectory.load("sess-1") == []
    assert not trajectory.path_for("sess-1").exists()


async def test_a_plain_turn_is_saved_as_system_human_gpt():
    class _Text:
        async def generate(self, **kwargs):
            return "plain answer"

    agent = Agent("jarvis", {"name": "Jarvis"})
    agent.tool_runtime = None
    answer = await agent.generate_response(backend=_Text(), model="m", prompt="hello", system="sys",
                                           max_tokens=64, temperature=0.1, session_id="sess-2")
    assert answer == "plain answer"
    [record] = trajectory.load("sess-2")
    assert record["steps"] == [] and record["reply"] == "plain answer" and record["completed"] is True
    assert [m["from"] for m in trajectory.to_sharegpt(record)["conversations"]] == ["system", "human", "gpt"]


async def test_a_degraded_plain_reply_is_saved_as_not_completed():
    class _Down:
        async def generate(self, **kwargs):
            return "⚠️ the local model is unavailable"

    agent = Agent("jarvis", {"name": "Jarvis"})
    agent.tool_runtime = None
    await agent.generate_response(backend=_Down(), model="m", prompt="hello", system="sys",
                                  max_tokens=64, temperature=0.1, session_id="sess-3")
    [record] = trajectory.load("sess-3")
    assert record["completed"] is False and record["exit_reason"] == "degraded"
    assert trajectory.export("sess-3", completed_only=True) == []


async def test_a_turn_without_a_session_or_that_raises_writes_nothing(data_home):
    class _Boom:
        async def generate(self, **kwargs):
            raise RuntimeError("provider down")

    agent = Agent("jarvis", {"name": "Jarvis"})
    agent.tool_runtime = None
    with pytest.raises(RuntimeError):
        await agent.generate_response(backend=_Boom(), model="m", prompt="x", system="s",
                                      max_tokens=8, temperature=0.1, session_id="sess-4")
    with trajectory.capture(agent_id="a", model="m", system="s", prompt="p") as rec:
        rec.finish("no session bound")
    assert not trajectory.trajectory_dir().exists()


async def test_secrets_are_redacted_and_text_is_bounded(monkeypatch):
    monkeypatch.setattr(trajectory, "MAX_TEXT_CHARS", 200)
    agent, backend = _agent(_tool_turns(value=SECRET))
    await _ask(agent, backend, prompt=f"use key {SECRET} " + "x" * 500)
    raw = trajectory.path_for("sess-1").read_text()
    assert SECRET not in raw
    [record] = trajectory.load("sess-1")
    assert "truncated" in record["prompt"] and len(record["prompt"]) < 260


def test_a_full_session_file_stops_growing(monkeypatch):
    monkeypatch.setattr(trajectory, "MAX_SESSION_BYTES", 600)
    for _ in range(5):
        with session_scope("sess-5"), trajectory.capture(agent_id="a", model="m", system="s", prompt="p") as rec:
            rec.finish("r" * 100)
    size = trajectory.path_for("sess-5").stat().st_size
    assert size <= 600 and len(trajectory.load("sess-5")) >= 1
    assert all(line.endswith("}") for line in trajectory.path_for("sess-5").read_text().splitlines())


async def test_a_nested_turn_is_its_own_record():
    with session_scope("sess-6"), trajectory.capture(agent_id="outer", model="m", system="s", prompt="p") as outer:
        with trajectory.capture(agent_id="inner", model="m", system="s", prompt="q") as inner:
            trajectory.note_message({"role": "assistant", "content": "", "tool_calls": []})
            inner.finish("inner reply")
        outer.finish("outer reply")
    inner_row, outer_row = trajectory.load("sess-6")
    assert (inner_row["agent_id"], len(inner_row["steps"])) == ("inner", 1)
    assert (outer_row["agent_id"], outer_row["steps"], outer_row["reply"]) == ("outer", [], "outer reply")


def test_a_mid_turn_steering_message_is_kept_as_a_human_step():
    with session_scope("sess-9"), trajectory.capture(agent_id="a", model="m", system="s", prompt="p") as rec:
        trajectory.note_message({"role": "assistant", "content": "working",
                                 "tool_calls": [{"id": "c1", "function": {"name": "echo", "arguments": "{}"}}]})
        trajectory.note_message({"role": "tool", "tool_call_id": "c1", "content": "{}", "images": [{}, {}]})
        trajectory.note_message({"role": "user", "display_kind": "owner_steer", "content": "use metric units"})
        trajectory.note_message({"role": "system", "content": "ignored"})
        rec.finish("done")
    [record] = trajectory.load("sess-9")
    assert [step["role"] for step in record["steps"]] == ["assistant", "tool", "user"]
    assert record["steps"][1]["images"] == 2 and "display_kind" not in record["steps"][2]
    conv = trajectory.to_sharegpt(record)["conversations"]
    assert [m["from"] for m in conv] == ["system", "human", "gpt", "tool", "human", "gpt"]
    assert conv[4]["value"] == "use metric units"
    assert trajectory.to_messages(record)["messages"][4] == {"role": "user", "content": "use metric units"}


def test_torn_lines_and_bad_ids_are_refused():
    with session_scope("sess-7"), trajectory.capture(agent_id="a", model="m", system="", prompt="p") as rec:
        rec.finish("r")
    with open(trajectory.path_for("sess-7"), "a") as handle:
        handle.write('{"torn": \n[1,2]\n')
    assert len(trajectory.load("sess-7")) == 1
    with pytest.raises(ValueError):
        trajectory.load("../etc")
    with pytest.raises(ValueError):
        trajectory.export("sess-7", fmt="csv")


# ── formats ──────────────────────────────────────────────────────────────────


async def test_sharegpt_matches_the_hermes_trajectory_shape():
    agent, backend = _agent(_tool_turns())
    await _ask(agent, backend)
    [row] = trajectory.export("sess-1")
    conv = row["conversations"]
    assert [m["from"] for m in conv] == ["system", "human", "gpt", "tool", "gpt"]
    assert conv[1]["value"] == "echo hi"
    assert conv[2]["value"].startswith("let me echo\n<tool_call>\n")
    call = json.loads(conv[2]["value"].split("<tool_call>\n")[1].split("\n</tool_call>")[0])
    assert call == {"name": "echo", "arguments": {"value": "hi"}}
    assert conv[3]["value"].startswith("<tool_response>\n") and conv[3]["value"].endswith("\n</tool_response>")
    response = json.loads(conv[3]["value"][len("<tool_response>\n"):-len("\n</tool_response>")])
    assert response["name"] == "echo" and response["tool_call_id"] == "call-1"
    assert response["content"]["result"] == {"echo": "hi"}
    assert conv[4] == {"from": "gpt", "value": "Echo completed"}
    assert row["session_id"] == "sess-1" and row["completed"] is True and row["timestamp"]


async def test_messages_format_keeps_tool_calls_for_sft():
    agent, backend = _agent(_tool_turns())
    await _ask(agent, backend)
    [row] = trajectory.export("sess-1", fmt="messages")
    roles = [m["role"] for m in row["messages"]]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
    assert row["messages"][2]["tool_calls"][0]["function"] == {"name": "echo", "arguments": '{"value": "hi"}'}
    assert row["messages"][3]["tool_call_id"] == "call-1"


# ── route ────────────────────────────────────────────────────────────────────


def _client(monkeypatch, *, admin=True):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import _deps

    if admin:
        monkeypatch.setitem(web.app.dependency_overrides, _deps.admin_guard, lambda: None)
    else:
        monkeypatch.delitem(web.app.dependency_overrides, _deps.admin_guard, raising=False)
    return TestClient(web.app)


async def test_the_route_exports_sharegpt_and_jsonl(monkeypatch):
    agent, backend = _agent(_tool_turns())
    await _ask(agent, backend)
    client = _client(monkeypatch)
    got = client.get("/sessions/sess-1/trajectories")
    body = got.json()
    assert got.status_code == 200 and "no-store" in got.headers["Cache-Control"]
    assert body["format"] == "sharegpt" and body["count"] == 1 and body["capture_enabled"] is True
    assert body["trajectories"][0]["conversations"][-1] == {"from": "gpt", "value": "Echo completed"}
    lines = client.get("/sessions/sess-1/trajectories", params={"jsonl": "true", "format": "messages"})
    assert lines.headers["content-type"].startswith("application/x-ndjson")
    assert json.loads(lines.text.splitlines()[0])["messages"][-1]["content"] == "Echo completed"
    assert client.get("/sessions/bad%20id/trajectories").status_code == 400
    assert client.get("/sessions/sess-1/trajectories", params={"format": "csv"}).status_code == 400
    empty = client.get("/sessions/nobody/trajectories").json()
    assert empty["count"] == 0 and empty["trajectories"] == []
    assert _client(monkeypatch, admin=False).get("/sessions/sess-1/trajectories").status_code in (401, 403)


def test_the_route_is_admin_only():
    from agents.core.routers import sessions as route

    [r] = [r for r in route.router.routes if r.path == "/sessions/{session_id}/trajectories"]
    assert [d.call.__name__ for d in r.dependant.dependencies] == ["admin_guard"]


async def test_a_permanent_session_delete_removes_the_trajectory_file():
    from agents.core import session_archive

    with session_scope("sess-8"), trajectory.capture(agent_id="a", model="m", system="", prompt="p") as rec:
        rec.finish("r")
    files = session_archive._files("sess-8", None)
    assert files["trajectory"] == trajectory.path_for("sess-8")
    record = session_archive.collect("sess-8", checkpoints=None, todos=None)
    assert record["trajectory"][0]["reply"] == "r"
    removed = session_archive._delete_traces("sess-8", None, files)
    assert removed["trajectory"] is True and not trajectory.path_for("sess-8").exists()


def test_forget_me_purges_the_trajectory_directory():
    from agents.core import data_purge

    assert "trajectories" not in data_purge.KEEP_DIRS
    assert trajectory.trajectory_dir().name == "trajectories"


# ── CLI ──────────────────────────────────────────────────────────────────────


def _ctx(reply, asked):
    class _Client:
        def get(self, path):
            asked.append(path)
            return reply

    out, err = io.StringIO(), io.StringIO()
    return SimpleNamespace(client=lambda: _Client(), out=out, err=err,
                           say=lambda text="": out.write(text + "\n"), dump=lambda data: None)


def test_the_cli_writes_sharegpt_jsonl_to_a_file(tmp_path):
    from agents.cli import nerva

    asked: list[str] = []
    ctx = _ctx({"format": "sharegpt", "count": 1, "capture_enabled": True,
                "trajectories": [{"conversations": [{"from": "human", "value": "hi"}]}]}, asked)
    out = tmp_path / "out.jsonl"
    ns = nerva.build_parser().parse_args(["sessions", "export", "sess-1", "--sharegpt", "--completed-only",
                                          "-o", str(out)])
    assert nerva.cmd_sessions(ns, ctx) == nerva.EXIT_OK
    assert asked == ["/sessions/sess-1/trajectories?format=sharegpt&completed_only=true"]
    assert [json.loads(line) for line in out.read_text().splitlines()] == [
        {"conversations": [{"from": "human", "value": "hi"}]}]
    assert ctx.out.getvalue() == "" and "1 trajectory" in ctx.err.getvalue()


def test_the_cli_streams_jsonl_to_stdout_and_says_when_capture_is_off():
    from agents.cli import nerva

    asked: list[str] = []
    ctx = _ctx({"format": "messages", "count": 0, "capture_enabled": False, "trajectories": []}, asked)
    ns = nerva.build_parser().parse_args(["sessions", "export", "sess-1", "--format", "messages"])
    assert nerva.cmd_sessions(ns, ctx) == nerva.EXIT_OK
    assert asked == ["/sessions/sess-1/trajectories?format=messages"]
    assert ctx.out.getvalue() == ""
    assert trajectory.ENV_FLAG in ctx.err.getvalue()

    rows = {"format": "sharegpt", "count": 2, "capture_enabled": True,
            "trajectories": [{"conversations": []}, {"conversations": [{"from": "gpt", "value": "x"}]}]}
    ctx = _ctx(rows, asked)
    ns = nerva.build_parser().parse_args(["sessions", "export", "sess-1"])
    assert nerva.cmd_sessions(ns, ctx) == nerva.EXIT_OK
    assert [json.loads(line) for line in ctx.out.getvalue().splitlines()] == rows["trajectories"]
