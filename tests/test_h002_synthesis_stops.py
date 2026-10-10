"""A real settled runtime stop remains incomplete across synthesis, HTTP and CLI."""

import io
import json

from fastapi.testclient import TestClient

from agents import web
from agents.cli.nerva import EXIT_FAILED, Context, main
from agents.core.agent_runtime import AgentToolRuntime
from agents.core.orchestrator import Orchestrator
from agents.core.tool_rpc import ToolRPCServer
from tests.h441_native_fixture import bind_native


def test_rewritten_runtime_stop_cannot_become_a_successful_oneshot(monkeypatch, tmp_path):
    class Backend:
        supports_tools = True

        async def generate_tool_turn(self, **kwargs):
            raise AssertionError("An empty tool registry must stop before inference")

    class Synthesizer:
        async def synthesize(self, responses, intent, *, in_character):
            assert responses["athena"] == "I can't use tools on this surface."
            return "Everything is ready."

    runtime = AgentToolRuntime(ToolRPCServer(), enabled=lambda: True)

    class StoppedOrchestrator:
        session_id = "h002_stopped_session"
        notes = None
        agents = {"jarvis": Synthesizer()}

        def _chat_outcome_block(self):
            return ""

        async def handle_input(self, *args, **kwargs):
            stopped = await runtime.run_result(
                agent_id="jarvis", backend=Backend(), model="synthetic", prompt="hello",
            )
            assert stopped.exit_reason == "no_tools"
            return await Orchestrator._synthesize(self, {"athena": stopped.reply}, None)

    orch = StoppedOrchestrator()
    bind_native(orch, monkeypatch, session_ids=(orch.session_id,))
    monkeypatch.setattr(web, "orch", orch)
    http = TestClient(web.app)
    seen = []

    class Client:
        def post(self, path, body):
            assert path == "/chat"  # No approval decision or second command.
            response = http.post(path, json=body)
            assert response.status_code == 200
            payload = response.json()
            seen.append(payload)
            return payload

    out, err = io.StringIO(), io.StringIO()
    receipt_path = tmp_path / "receipt.json"
    context = Context(environ={}, out=out, err=err, inp=io.StringIO(),
                      client_factory=lambda _: Client())
    code = main(["chat", "-z", "--usage-file", str(receipt_path), "hello"], context=context)
    receipt = json.loads(receipt_path.read_text())
    assert seen[0]["reply"] == "Everything is ready."
    assert seen[0]["runtime_stops"] == ["no_tools"]
    assert code == EXIT_FAILED and out.getvalue() == ""
    assert "no_tools" in err.getvalue()
    assert receipt["completed"] is False
    assert receipt["runtime_stops"] == ["no_tools"]
    assert receipt["session_id"] == orch.session_id
    assert len(seen) == 1
