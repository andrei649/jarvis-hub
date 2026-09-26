"""H681 — a child whose model call failed is failed, and a batch says why they all failed.

``Orchestrator.process`` answers a failed model call with ``""`` (or a degraded reply),
never an exception, and the sub-agent runner wrapped that as ``{"output": ""}``: the
manager recorded the child as ``done`` with ``ok: True``. A batch of ten children sent
to a model the provider does not know came back as ten empty successes. Now:

- the production runner asks ``Orchestrator.process_detailed`` for ``(text, error)`` and
  raises ``SubAgentProviderError`` on a failed turn; the manager records ``failed`` with
  ``{"error": "provider_failed", "detail", "failures"}``. An empty output from any
  runner is ``failed`` too;
- every backend notes a failed call (provider, the model it asked for, the HTTP status
  and a fixed kind) into a request-scoped list — never the provider's text, which can
  echo a key or a prompt;
- ``spawn_batch`` returns one notice, ``subagent_model_rejected``, when every child
  failed because the provider does not know the model ``autonomy.subagent_model``
  chose: naming the model, the setting and whether a fallback exists. A failure that
  names another model, a batch with one success, a child pinned explicitly, or a
  child refused at the gate does not raise it.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from agents.core.llm import provider_errors as pe
from agents.core.subagents import SubAgentManager, SubAgentProviderError

_NO_COST = dict


def _mgr(runner=None, **kw):
    kw.setdefault("cost_probe", _NO_COST)
    kw.setdefault("persist", False)
    return SubAgentManager(runner=runner, **kw)


def _missing(model, provider="openrouter", status=404):
    return pe.ProviderFailure(provider=provider, model=model, status=status, kind="model_not_found")


def _failing(*failures, detail="[OpenRouter error]"):
    async def runner(task, session_id, agent):
        raise SubAgentProviderError(detail, failures=list(failures))
    return runner


# ── failure honesty ────────────────────────────────────────────────────────────────

async def test_an_empty_output_is_a_failed_child_not_a_done_one():
    async def runner(task, session_id, agent):
        return {"output": "", "session_id": session_id}

    out = await _mgr(runner).spawn("t")
    assert out["ok"] is False and out["status"] == "failed"
    assert out["result"]["error"] == "provider_failed" and out["result"]["detail"] == "empty output"


@pytest.mark.parametrize("output", ["   ", "\n"])
async def test_a_blank_output_is_failed_too(output):
    async def runner(task, session_id, agent):
        return {"output": output}

    assert (await _mgr(runner).spawn("t"))["status"] == "failed"


async def test_a_result_without_an_output_key_is_left_as_it_was():
    async def runner(task, session_id, agent):
        return {"verdict": "yes"}                # typed hand-off, no free text

    out = await _mgr(runner).spawn("t", output_schema={"type": "object", "required": ["verdict"]})
    assert out["ok"] is True and out["result"] == {"verdict": "yes"}


async def test_a_provider_error_is_recorded_with_its_class_and_failures():
    out = await _mgr(_failing(_missing("foo"))).spawn("t")
    assert out["ok"] is False and out["status"] == "failed"
    result = out["result"]
    assert result["error"] == "provider_failed"
    assert result["detail"] == "[OpenRouter error]"
    assert result["failures"] == [{"provider": "openrouter", "model": "foo", "status": 404,
                                   "kind": "model_not_found",
                                   "message": "openrouter: model 'foo' not found (HTTP 404)"}]


async def test_a_long_detail_is_bounded():
    out = await _mgr(_failing(detail="x" * 5000)).spawn("t")
    assert len(out["result"]["detail"]) <= 500


# ── the production runner ─────────────────────────────────────────────────────────

class _Router:
    def __init__(self, refuse=None):
        self.refuse = refuse
        self.preflights = []

    def select_backend(self, agent, prompt):
        from agents.core.llm.job_selection import current_selection

        sel = current_selection()
        self.preflights.append((agent, sel.model if sel else None))
        if self.refuse:
            from agents.core.llm.job_selection import SelectionError
            raise SelectionError(self.refuse)
        return object(), sel.model if sel else "m", "local"


class _Orch:
    def __init__(self, reply="an answer", error=None, notes=(), router=None):
        self.agents = {"jarvis": object(), "vision": object()}
        self.llm_router = router or _Router()
        self._reply, self._error, self._notes = reply, error, notes
        self.calls = []

    async def process_detailed(self, prompt, agent="jarvis", channel="internal"):
        from agents.core.llm import request_context as rc
        from agents.core.llm.job_selection import current_selection

        sel = current_selection()
        ov = rc.current_overrides()
        self.calls.append({"prompt": prompt, "agent": agent, "channel": channel,
                           "model": sel.model if sel else None,
                           "max_tokens": ov.max_tokens if ov else None})
        for note in self._notes:
            pe.note_provider_failure(note["provider"], note["model"], kind=note.get("kind"),
                                     status=note.get("status"))
        return self._reply, self._error


def _runner(orch):
    from agents.core.autonomy_coordinator import make_subagent_runner
    return make_subagent_runner(orch)


async def test_the_runner_answers_with_the_turns_text():
    orch = _Orch()
    out = await _mgr(_runner(orch)).spawn("do it", agent="vision")
    assert out["ok"] is True and out["result"]["output"] == "an answer"
    assert orch.calls == [{"prompt": "do it", "agent": "vision", "channel": "subagent",
                           "model": None, "max_tokens": None}]


async def test_an_unknown_agent_runs_as_jarvis():
    orch = _Orch()
    await _mgr(_runner(orch)).spawn("t", agent="ghost")
    assert orch.calls[0]["agent"] == "jarvis"


async def test_the_runner_runs_the_child_under_its_pin_and_overrides():
    orch = _Orch()
    out = await _mgr(_runner(orch)).spawn("t", model="qwen3:8b", overrides={"max_tokens": 99})
    assert out["ok"] is True
    assert orch.calls[0]["model"] == "qwen3:8b" and orch.calls[0]["max_tokens"] == 99
    # The pin is checked against the governed router before any turn runs.
    assert orch.llm_router.preflights == [("jarvis", "qwen3:8b")]


async def test_a_pin_the_router_cannot_honor_fails_the_child_before_its_turn():
    orch = _Orch(router=_Router(refuse="requested provider is unavailable or not selected by agent policy"))
    out = await _mgr(_runner(orch)).spawn("t", provider="ollama")
    assert out["status"] == "failed" and out["result"]["error"] == "provider_failed"
    assert out["result"]["detail"].startswith("selection refused: requested provider is unavailable")
    assert orch.calls == []


async def test_a_pin_without_a_governed_router_is_refused():
    orch = _Orch()
    orch.llm_router = None
    out = await _mgr(_runner(orch)).spawn("t", model="m1")
    assert out["status"] == "failed" and "governed model router" in out["result"]["detail"]
    assert orch.calls == []


async def test_a_failed_turn_fails_the_child_with_the_backends_notes():
    orch = _Orch(reply="", error="[OpenRouter error]",
                 notes=[{"provider": "openrouter", "model": "foo", "status": 404, "kind": "model_not_found"}])
    out = await _mgr(_runner(orch)).spawn("t", model="foo")
    assert out["status"] == "failed"
    assert out["result"]["detail"] == "[OpenRouter error]"
    assert [(f["kind"], f["status"], f["model"]) for f in out["result"]["failures"]] == [
        ("model_not_found", 404, "foo")]


async def test_a_degraded_reply_with_text_is_still_a_failure():
    orch = _Orch(reply="⚠️ The local Ollama model hit an error and couldn't answer.",
                 error="⚠️ The local Ollama model hit an error and couldn't answer.")
    out = await _mgr(_runner(orch)).spawn("t")
    assert out["status"] == "failed" and out["result"]["detail"].startswith("⚠️")


async def test_notes_from_one_child_never_reach_another():
    gate = asyncio.Event()

    class _Slow(_Orch):
        async def process_detailed(self, prompt, agent="jarvis", channel="internal"):
            if prompt == "fails":
                pe.note_provider_failure("ollama", "foo", kind="model_not_found", status=404)
                gate.set()
                return "", "⚠️ failed"
            await gate.wait()
            return "fine", None

    m = _mgr(_runner(_Slow()), max_concurrent=4)
    a, b = await asyncio.gather(m.spawn("fails"), m.spawn("ok"))
    assert a["status"] == "failed" and b["status"] == "done"
    assert "failures" not in b["result"]


# ── Orchestrator.process_detailed ─────────────────────────────────────────────────

def _orch_with(responses=None, raises=None):
    from agents.core.orchestrator import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.agents = {"jarvis": object()}

    async def call(ids, prompt, a, b):
        if raises is not None:
            raise raises
        return responses

    orch._call_agents_parallel = call
    return orch


async def test_process_detailed_names_why_a_turn_produced_nothing(monkeypatch):
    from agents.core import orchestrator as o

    monkeypatch.setattr(o.power, "hold_for_turn", lambda orch: None)
    monkeypatch.setattr(o.power, "release_for_turn", lambda held: None)
    assert await _orch_with({"jarvis": "fine"}).process_detailed("p") == ("fine", None)
    assert await _orch_with({"jarvis": "[jarvis error: boom]"}).process_detailed("p") == ("", "[jarvis error: boom]")
    assert await _orch_with({"jarvis": "[jarvis timeout]"}).process_detailed("p") == ("", "[jarvis timeout]")
    assert await _orch_with({"jarvis": ""}).process_detailed("p") == ("", "empty reply")
    assert await _orch_with({}).process_detailed("p") == ("", "empty reply")
    text, err = await _orch_with({"jarvis": o.NO_MODEL_REPLY}).process_detailed("p")
    assert text == o.NO_MODEL_REPLY and err == o.NO_MODEL_REPLY
    degraded = "⚠️ The local Ollama model hit an error and couldn't answer. Check the Ollama server."
    assert await _orch_with({"jarvis": degraded}).process_detailed("p") == (degraded, degraded)
    assert await _orch_with(raises=RuntimeError("No LLM backend available")).process_detailed("p") == (
        "", "no model backend: No LLM backend available")
    text, err = await _orch_with(raises=ValueError("bad")).process_detailed("p")
    assert text == "" and err == "ValueError: bad"
    assert await _orch_with({"jarvis": "x"}).process_detailed("") == ("", "empty prompt")
    orch = _orch_with({"jarvis": "x"})
    orch.agents = {}
    assert await orch.process_detailed("p") == ("", "no agent available")


async def test_process_still_answers_exactly_as_before(monkeypatch):
    from agents.core import orchestrator as o

    monkeypatch.setattr(o.power, "hold_for_turn", lambda orch: None)
    monkeypatch.setattr(o.power, "release_for_turn", lambda held: None)
    assert await _orch_with({"jarvis": "fine"}).process("p") == "fine"
    assert await _orch_with({"jarvis": "[jarvis error: boom]"}).process("p") == ""
    assert await _orch_with({"jarvis": "[OpenRouter error]"}).process("p") == "[OpenRouter error]"
    assert await _orch_with({"jarvis": o.NO_MODEL_REPLY}).process("p") == o.NO_MODEL_REPLY
    assert await _orch_with(raises=RuntimeError("x")).process("p") == ""


# ── provider failure notes ───────────────────────────────────────────────────────────

def _status_error(status, body, url="https://api.test/v1/chat/completions"):
    request = httpx.Request("POST", url)
    response = httpx.Response(status, text=body, request=request)
    return httpx.HTTPStatusError(f"{status}", request=request, response=response)


@pytest.mark.parametrize("status,body,kind", [
    (404, '{"error":"model \\"foo\\" not found, try pulling it first"}', "model_not_found"),
    (400, '{"error":{"message":"foo is not a valid model ID","code":400}}', "model_not_found"),
    (404, '{"error":{"message":"The model `foo` does not exist or you do not have access to it."}}',
     "model_not_found"),
    (404, '{"type":"error","error":{"type":"not_found_error","message":"model: foo"}}', "model_not_found"),
    (404, '{"error":{"code":404,"message":"models/foo is not found for API version v1beta"}}', "model_not_found"),
    (400, '{"error":{"message":"Unknown model: foo"}}', "model_not_found"),
    (404, "<html>nginx: Not Found</html>", "not_found"),
    (401, '{"error":"invalid api key"}', "auth"),
    (403, "forbidden", "auth"),
    (429, "slow down", "rate_limited"),
    (500, "model runner crashed", "server_error"),
    (400, '{"error":"context length exceeded"}', "rejected"),
])
def test_a_failure_is_classified_without_keeping_the_providers_text(status, body, kind):
    with pe.provider_failure_scope() as notes:
        pe.note_provider_failure("openrouter", "foo", _status_error(status, body + " sk-or-SECRETSECRET"))
    [note] = notes
    assert (note.provider, note.model, note.status, note.kind) == ("openrouter", "foo", status, kind)
    assert "SECRET" not in repr(note) and "SECRET" not in json.dumps(note.as_dict())


def test_a_connection_failure_is_unreachable():
    with pe.provider_failure_scope() as notes:
        pe.note_provider_failure("lm-studio", "m", httpx.ConnectError("refused"))
        pe.note_provider_failure("lm-studio", "m", httpx.ReadTimeout("slow"))
        pe.note_provider_failure("lm-studio", "m", ValueError("odd"))
    assert [n.kind for n in notes] == ["unreachable", "unreachable", "error"]
    assert notes[2].status is None


def test_an_unread_streamed_body_is_classified_by_its_status():
    request = httpx.Request("POST", "https://api.test/x")

    class _Unread(httpx.Response):
        @property
        def text(self):
            raise httpx.ResponseNotRead()

    exc = httpx.HTTPStatusError("404", request=request, response=_Unread(404, request=request))
    with pe.provider_failure_scope() as notes:
        pe.note_provider_failure("anthropic", "claude-x", exc)
    assert notes[0].kind == "not_found"


def test_outside_a_scope_nothing_is_kept():
    pe.note_provider_failure("ollama", "m", httpx.ConnectError("x"))
    with pe.provider_failure_scope() as notes:
        pass
    assert notes == []


def test_the_message_is_composed_from_fields_only():
    assert _missing("vendor/m:free").message() == "openrouter: model 'vendor/m:free' not found (HTTP 404)"
    assert pe.ProviderFailure("ollama", "m", None, "unreachable").message() == "ollama: model 'm' unreachable"
    assert pe.ProviderFailure("gemini", None, 500, "server_error").message() == "gemini: server error (HTTP 500)"


# each backend notes its own failure

async def test_the_ollama_backend_notes_a_model_it_does_not_have():
    from agents.core.llm.base import OllamaBackend

    def handler(request):
        return httpx.Response(404, json={"error": 'model "foo" not found, try pulling it first'}, request=request)

    backend = OllamaBackend.__new__(OllamaBackend)
    backend.num_ctx, backend._context_windows, backend.base_url = 0, {}, "http://ollama.test"
    backend.client = httpx.AsyncClient(base_url=backend.base_url, transport=httpx.MockTransport(handler))
    with pe.provider_failure_scope() as notes:
        reply = await backend.generate("foo", "hi")
    assert reply.startswith("⚠️")
    assert [(n.provider, n.model, n.status, n.kind) for n in notes] == [("ollama", "foo", 404, "model_not_found")]


async def test_the_lm_studio_backend_notes_its_failure():
    from agents.core.llm.base import LMStudioBackend

    def handler(request):
        return httpx.Response(404, json={"error": {"message": 'Model "foo" not found'}}, request=request)

    backend = LMStudioBackend.__new__(LMStudioBackend)
    backend.base_url = "http://lms.test"
    backend.client = httpx.AsyncClient(base_url=backend.base_url, transport=httpx.MockTransport(handler))
    with pe.provider_failure_scope() as notes:
        reply = await backend.generate("foo", "hi")
    assert reply.startswith("⚠️")
    assert [(n.provider, n.model, n.kind) for n in notes] == [("lm-studio", "foo", "model_not_found")]


async def test_the_openrouter_backend_notes_its_failure():
    from agents.core.llm.openrouter import OpenRouterBackend

    def handler(request):
        return httpx.Response(400, json={"error": {"message": "foo is not a valid model ID", "code": 400}},
                              request=request)

    backend = OpenRouterBackend(api_key="sk-or-test", client=httpx.AsyncClient(
        base_url="https://openrouter.test/api/v1", transport=httpx.MockTransport(handler)))
    with pe.provider_failure_scope() as notes:
        assert await backend.generate("foo", "hi") == "[OpenRouter error]"
        turn = await backend.generate_tool_turn("foo", [{"role": "user", "content": "hi"}], [])
    assert turn.content == "[OpenRouter error]"
    assert [(n.provider, n.model, n.status, n.kind) for n in notes] == [
        ("openrouter", "foo", 400, "model_not_found")] * 2


async def test_the_claude_backend_notes_its_failure():
    from agents.core.llm.anthropic import ClaudeBackend

    def handler(request):
        return httpx.Response(404, json={"type": "error", "error": {"type": "not_found_error",
                                                                     "message": "model: claude-nope"}},
                              request=request)

    backend = ClaudeBackend.__new__(ClaudeBackend)
    backend.api_key, backend.model, backend.auth_pool = "sk-ant-test", "claude-nope", None
    backend.reasoning_effort, backend.effort_overrides = "", {}
    backend.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pe.provider_failure_scope() as notes:
        reply = await backend.generate("claude-nope", "hi")
    assert reply.startswith("[Claude API error")
    assert [(n.provider, n.model, n.status, n.kind) for n in notes] == [
        ("anthropic", "claude-nope", 404, "model_not_found")]


async def test_the_gemini_backend_notes_its_failure():
    from agents.core.llm.gemini import GeminiBackend

    def handler(request):
        return httpx.Response(404, json={"error": {"code": 404, "message":
                                                   "models/gemini-nope is not found for API version v1beta"}},
                              request=request)

    backend = GeminiBackend(api_key="gm-test")
    backend.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pe.provider_failure_scope() as notes:
        await backend.generate("gemini-nope", "hi")
    assert notes and {(n.provider, n.model, n.kind) for n in notes} == {("gemini", "gemini-nope", "model_not_found")}


async def test_the_responses_backend_notes_its_failure():
    from agents.core.llm.responses import MODELS, ResponsesBackend

    model = sorted(MODELS)[0]         # a model it knows, that this account cannot use

    async def body():                   # a real stream: nothing is read until someone reads it
        yield json.dumps({"error": {"message": f"The model `{model}` does not exist"}}).encode()

    def handler(request):
        return httpx.Response(404, content=body(), request=request)

    backend = ResponsesBackend("sk-test", transport=httpx.MockTransport(handler))
    with pe.provider_failure_scope() as notes:
        await backend.generate(model, "hi")
    # A streamed error body is read only up to its first 8 KB, to classify it.
    assert [(n.provider, n.model, n.status, n.kind) for n in notes] == [
        ("openai-responses", model, 404, "model_not_found")]


# ── the batch ────────────────────────────────────────────────────────────────────────

def _setting(model="foo", provider="openrouter"):
    return lambda: {"model": model, "provider": provider}


async def test_a_batch_runs_every_task_and_reports_each_child():
    async def runner(task, session_id, agent):
        return {"output": f"did {task}"}

    out = await _mgr(runner, max_concurrent=2).spawn_batch([{"task": "a"}, {"task": "b"}, {"task": "c"}])
    assert out["ok"] is True and out["notice"] is None
    assert [c["result"]["output"] for c in out["children"]] == ["did a", "did b", "did c"]
    assert out["summary"] == {"total": 3, "done": 3, "failed": 0, "refused": 0}


async def test_a_batch_waits_for_free_slots_instead_of_refusing():
    running, peak = 0, 0

    async def runner(task, session_id, agent):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return {"output": "ok"}

    out = await _mgr(runner, max_concurrent=2).spawn_batch([{"task": str(i)} for i in range(6)])
    assert out["summary"]["done"] == 6 and peak <= 2


async def test_all_children_rejected_for_the_configured_model_is_one_notice():
    m = _mgr(_failing(_missing("foo")), selection_defaults=_setting("foo"),
             fallback_probe=lambda rejected: "gemma-3-12b")
    out = await m.spawn_batch([{"task": "a"}, {"task": "b"}, {"task": "c"}])
    assert out["ok"] is False and out["summary"]["failed"] == 3
    assert out["notice"] == {
        "kind": "subagent_model_rejected", "model": "foo", "provider": "openrouter",
        "setting": "autonomy.subagent_model", "fallback": True, "fallback_model": "gemma-3-12b",
        "children": 3,
        "message": ("Every sub-agent in this batch failed: openrouter does not know the model 'foo' "
                    "that autonomy.subagent_model chooses. Clear the setting to run them on "
                    "'gemma-3-12b', or choose another model."),
    }


async def test_the_notice_says_when_there_is_no_fallback():
    m = _mgr(_failing(_missing("foo")), selection_defaults=_setting("foo"), fallback_probe=lambda r: None)
    notice = (await m.spawn_batch([{"task": "a"}, {"task": "b"}]))["notice"]
    assert notice["fallback"] is False and notice["fallback_model"] is None
    assert "no other model to fall back to" in notice["message"]


async def test_a_failing_fallback_probe_reads_as_no_fallback():
    def probe(rejected):
        raise RuntimeError("router gone")

    m = _mgr(_failing(_missing("foo")), selection_defaults=_setting("foo"), fallback_probe=probe)
    notice = (await m.spawn_batch([{"task": "a"}]))["notice"]
    assert notice["fallback"] is False


async def test_a_fallback_equal_to_the_rejected_model_is_no_fallback():
    m = _mgr(_failing(_missing("foo")), selection_defaults=_setting("foo"), fallback_probe=lambda r: "foo")
    assert (await m.spawn_batch([{"task": "a"}]))["notice"]["fallback"] is False


async def test_a_failure_naming_another_model_raises_no_notice():
    m = _mgr(_failing(_missing("bar")), selection_defaults=_setting("foo"))
    out = await m.spawn_batch([{"task": "a"}, {"task": "b"}])
    assert out["summary"]["failed"] == 2 and out["notice"] is None


async def test_a_model_whose_name_merely_contains_the_setting_raises_no_notice():
    m = _mgr(_failing(_missing("foo-large")), selection_defaults=_setting("foo"))
    assert (await m.spawn_batch([{"task": "a"}]))["notice"] is None


async def test_one_success_in_the_batch_raises_no_notice():
    async def runner(task, session_id, agent):
        if task == "b":
            return {"output": "fine"}
        raise SubAgentProviderError("[OpenRouter error]", failures=[_missing("foo")])

    m = _mgr(runner, selection_defaults=_setting("foo"))
    out = await m.spawn_batch([{"task": "a"}, {"task": "b"}])
    assert out["notice"] is None and out["summary"] == {"total": 2, "done": 1, "failed": 1, "refused": 0}


async def test_another_kind_of_failure_raises_no_notice():
    auth = pe.ProviderFailure("openrouter", "foo", 401, "auth")
    m = _mgr(_failing(auth), selection_defaults=_setting("foo"))
    assert (await m.spawn_batch([{"task": "a"}]))["notice"] is None


async def test_a_mixed_batch_where_one_child_failed_differently_raises_no_notice():
    async def runner(task, session_id, agent):
        if task == "b":
            raise SubAgentProviderError("timeout", failures=[pe.ProviderFailure("openrouter", "foo", None,
                                                                                 "unreachable")])
        raise SubAgentProviderError("[OpenRouter error]", failures=[_missing("foo")])

    m = _mgr(runner, selection_defaults=_setting("foo"))
    assert (await m.spawn_batch([{"task": "a"}, {"task": "b"}]))["notice"] is None


async def test_children_pinned_explicitly_do_not_blame_the_setting():
    m = _mgr(_failing(_missing("foo")), selection_defaults=_setting("foo"))
    out = await m.spawn_batch([{"task": "a", "model": "foo"}, {"task": "b", "model": "foo"}])
    assert out["summary"]["failed"] == 2 and out["notice"] is None


async def test_a_failure_detail_with_the_phrase_is_enough_without_notes():
    # A runner that only has the provider's own words (a local server's error line).
    m = _mgr(_failing(detail="model 'foo' not found, try pulling it first"), selection_defaults=_setting("foo"))
    assert (await m.spawn_batch([{"task": "a"}]))["notice"]["model"] == "foo"
    m = _mgr(_failing(detail="model 'foobar' not found"), selection_defaults=_setting("foo"))
    assert (await m.spawn_batch([{"task": "a"}]))["notice"] is None


async def test_children_refused_at_the_gate_are_not_model_failures():
    from agents.core.iteration_budget import IterationBudget

    m = _mgr(_failing(_missing("foo")), selection_defaults=_setting("foo"), budget=IterationBudget(1))
    out = await m.spawn_batch([{"task": "a"}, {"task": "b"}])
    assert out["summary"] == {"total": 2, "done": 0, "failed": 1, "refused": 1}
    assert out["children"][1]["reason"] == "spawn_budget_exhausted"
    assert out["notice"] is None


async def test_one_invalid_task_refuses_the_whole_batch_before_anything_runs():
    ran = []

    async def runner(task, session_id, agent):
        ran.append(task)
        return {"output": "ok"}

    m = _mgr(runner)
    out = await m.spawn_batch([{"task": "a"}, {"task": "b", "model": "bad model"}])
    assert out["ok"] is False and out["reason"] == "invalid_selection" and out["index"] == 1
    assert ran == [] and m.stats()["total"] == 0


@pytest.mark.parametrize("tasks,reason", [
    ([], "empty_batch"),
    ([{"task": str(i)} for i in range(17)], "batch_too_large"),
    ("not a list", "invalid_batch"),
    ([{"task": ""}], "invalid_batch"),
    ([{"nope": 1}], "invalid_batch"),
    ([{"task": "a", "output_schema": "x"}], "invalid_output_schema"),
])
async def test_a_malformed_batch_is_refused(tasks, reason):
    out = await _mgr().spawn_batch(tasks)
    assert out["ok"] is False and out["reason"] == reason


async def test_a_batch_with_per_child_settings_gives_each_its_own():
    from agents.core.llm.job_selection import current_selection

    seen = {}

    async def runner(task, session_id, agent):
        sel = current_selection()
        seen[task] = sel.model if sel else None
        return {"output": "ok"}

    m = _mgr(runner, selection_defaults=_setting("s1", ""), max_concurrent=3)
    await m.spawn_batch([{"task": "a", "model": "m1"}, {"task": "b"}, {"task": "c", "model": "m3"}])
    assert seen == {"a": "m1", "b": "s1", "c": "m3"}


# ── the batch route ─────────────────────────────────────────────────────────────────

def _client(manager, monkeypatch, audit=None):
    from fastapi import FastAPI

    from agents.core.routers import _component, mesh
    from agents.core.routers._deps import admin_guard, user_guard

    orch = SimpleNamespace(subagents=manager, audit=audit)
    monkeypatch.setattr(mesh, "get_orch", lambda: orch)
    monkeypatch.setattr(_component, "get_orch", lambda: orch)
    app = FastAPI()
    app.include_router(mesh.router)
    app.dependency_overrides[user_guard] = lambda: None
    app.dependency_overrides[admin_guard] = lambda: None
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_the_batch_route_returns_the_notice(monkeypatch):
    m = _mgr(_failing(_missing("foo")), selection_defaults=_setting("foo"), fallback_probe=lambda r: None)
    async with _client(m, monkeypatch) as client:
        r = await client.post("/api/subagents/batch", json={"tasks": [{"task": "a"}, {"task": "b"}]})
    assert r.status_code == 200
    body = r.json()
    assert body["notice"]["kind"] == "subagent_model_rejected" and body["summary"]["failed"] == 2


async def test_the_batch_route_bounds_and_validates(monkeypatch):
    async with _client(_mgr(), monkeypatch) as client:
        assert (await client.post("/api/subagents/batch", json={"tasks": []})).status_code == 422
        too_many = {"tasks": [{"task": str(i)} for i in range(17)]}
        assert (await client.post("/api/subagents/batch", json=too_many)).status_code == 422
        bad = {"tasks": [{"task": "a", "model": "bad model"}]}
        r = await client.post("/api/subagents/batch", json=bad)
        assert r.status_code == 422 and r.json()["reason"] == "invalid_selection"


async def test_the_batch_route_guards_every_model_it_chooses(monkeypatch):
    ran = []

    async def runner(task, session_id, agent):
        ran.append(task)
        return {"output": "ok"}

    class _Audit:
        rows = []

        def log(self, event):
            self.rows.append(event)

    body = {"tasks": [{"task": "a"}, {"task": "b", "model": "claude-fable-5"}]}
    async with _client(_mgr(runner), monkeypatch, _Audit()) as client:
        r = await client.post("/api/subagents/batch", json=body)
        assert r.status_code == 409 and r.json()["needs"] == ["confirm_expensive"] and ran == []
        r = await client.post("/api/subagents/batch", json={**body, "confirm_expensive": True})
    assert r.status_code == 200 and sorted(ran) == ["a", "b"]


async def test_the_spawn_route_reports_a_provider_failure_as_422(monkeypatch):
    async with _client(_mgr(_failing(_missing("foo"))), monkeypatch) as client:
        r = await client.post("/api/subagents/spawn", json={"task": "t"})
    assert r.status_code == 422 and r.json()["result"]["error"] == "provider_failed"


# ── the production wiring ───────────────────────────────────────────────────────────

def test_the_coordinator_names_the_model_the_router_would_pick():
    from agents.core.autonomy_coordinator import AutonomyCoordinator
    from agents.core.llm.job_selection import current_selection

    asked = []

    def select_backend(agent, prompt):
        asked.append((agent, prompt, current_selection()))
        return object(), "claude-sonnet-x", "cloud"

    coord = SimpleNamespace(_orch=SimpleNamespace(llm_router=SimpleNamespace(select_backend=select_backend)))
    assert AutonomyCoordinator._subagent_fallback_model(coord, "foo") == "claude-sonnet-x"
    assert asked == [("jarvis", "", None)]                   # asked outside any pin, for no task
    assert AutonomyCoordinator._subagent_fallback_model(coord, "claude-sonnet-x") is None

    def broken(agent, prompt):
        raise RuntimeError("No LLM backend available")

    coord._orch.llm_router = SimpleNamespace(select_backend=broken)
    assert AutonomyCoordinator._subagent_fallback_model(coord, "foo") is None
    coord._orch.llm_router = None
    assert AutonomyCoordinator._subagent_fallback_model(coord, "foo") is None


# ── edges (added by the mutation pass) ─────────────────────────────────────────────

def test_only_the_head_of_a_streamed_error_body_is_read():
    from agents.core.llm.provider_errors import ERROR_HEAD_BYTES, read_error_head

    reads = []

    class _Stream:
        async def aiter_bytes(self):
            for i in range(50):
                reads.append(i)
                yield b"x" * 1024 if i < 20 else b"model 'foo' not found"

    stream = _Stream()
    asyncio.run(read_error_head(stream))
    assert len(stream.nerva_error_head) == ERROR_HEAD_BYTES and "not found" not in stream.nerva_error_head
    assert len(reads) == ERROR_HEAD_BYTES // 1024          # never past the head


async def test_a_batch_of_exactly_the_maximum_runs():
    from agents.core.subagents import BATCH_MAX

    async def runner(task, session_id, agent):
        return {"output": "ok"}

    out = await _mgr(runner, max_concurrent=4).spawn_batch([{"task": str(i)} for i in range(BATCH_MAX)])
    assert out["summary"]["done"] == BATCH_MAX


async def test_a_child_whose_notes_mix_kinds_does_not_blame_the_model():
    both = [_missing("foo"), pe.ProviderFailure("openrouter", "foo", 503, "server_error")]
    m = _mgr(_failing(*both), selection_defaults=_setting("foo"))
    assert (await m.spawn_batch([{"task": "a"}]))["notice"] is None


async def test_a_detail_naming_a_longer_model_that_ends_in_the_setting_raises_no_notice():
    m = _mgr(_failing(detail="model 'xfoo' not found"), selection_defaults=_setting("foo"))
    assert (await m.spawn_batch([{"task": "a"}]))["notice"] is None


async def test_a_detail_naming_the_model_without_the_phrase_raises_no_notice():
    m = _mgr(_failing(detail="foo timed out after 30 s"), selection_defaults=_setting("foo"))
    assert (await m.spawn_batch([{"task": "a"}]))["notice"] is None


async def test_the_notice_names_the_provider_from_the_notes_when_the_setting_has_none():
    m = _mgr(_failing(_missing("foo", provider="ollama")), selection_defaults=_setting("foo", ""))
    notice = (await m.spawn_batch([{"task": "a"}]))["notice"]
    assert notice["provider"] == "ollama" and notice["message"].startswith(
        "Every sub-agent in this batch failed: ollama does not know")


async def test_one_confirmation_covers_a_model_named_by_several_children(monkeypatch):
    class _Audit:
        def __init__(self):
            self.rows = []

        def log(self, event):
            self.rows.append(event)

    async def runner(task, session_id, agent):
        return {"output": "ok"}

    audit = _Audit()
    body = {"tasks": [{"task": "a", "model": "claude-fable-5"}, {"task": "b", "model": "claude-fable-5"}],
            "confirm_expensive": True}
    async with _client(_mgr(runner), monkeypatch, audit) as client:
        r = await client.post("/api/subagents/batch", json=body)
    assert r.status_code == 200
    assert len([e for e in audit.rows if e.action_taken == "model_cost_confirmed"]) == 1


async def test_the_listing_carries_a_failed_childs_reason():
    m = _mgr(_failing(detail="x" * 900))
    await m.spawn("t")
    [row] = m.list()
    assert row["failure"] == {"error": "provider_failed", "detail": "x" * 200}
    assert "result" not in row


async def test_a_done_child_lists_no_failure():
    async def runner(task, session_id, agent):
        return {"output": "fine"}

    m = _mgr(runner)
    await m.spawn("t")
    assert "failure" not in m.list()[0]


def test_a_status_less_failure_is_classified_by_its_words():
    with pe.provider_failure_scope() as notes:
        pe.note_provider_failure("ollama", "foo", RuntimeError('model "foo" not found, try pulling it first'))
        pe.note_provider_failure("ollama", "foo", RuntimeError("out of memory"))
    assert [n.kind for n in notes] == ["model_not_found", "error"]


async def test_defaults_that_are_not_an_object_never_break_a_spawn():
    async def runner(task, session_id, agent):
        return {"output": "ok"}

    out = await _mgr(runner, selection_defaults=lambda: "qwen3:8b").spawn("t")
    assert out["ok"] is True and out["selection"]["source"] == "parent"


async def test_a_batch_item_with_an_unknown_key_is_refused():
    out = await _mgr().spawn_batch([{"task": "a", "priority": "high"}])
    assert out["ok"] is False and out["reason"] == "invalid_batch" and out["index"] == 0


async def test_an_invalid_batch_records_no_consent_even_when_confirmed(monkeypatch):
    class _Audit:
        def __init__(self):
            self.rows = []

        def log(self, event):
            self.rows.append(event)

    audit = _Audit()
    body = {"tasks": [{"task": "a", "model": "claude-fable-5", "overrides": {"temperature": 9}}],
            "confirm_expensive": True}
    async with _client(_mgr(), monkeypatch, audit) as client:
        r = await client.post("/api/subagents/batch", json=body)
    assert r.status_code == 422 and r.json()["reason"] == "invalid_selection"
    assert audit.rows == []


# ── review round (H681) ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("answer", ['["a.py", "b.py"]', "[1] first\n[2] second", "[docs](https://x.test) say so",
                                    "⚠️ careful: that deletes files"])
async def test_an_answer_that_opens_with_a_bracket_is_an_answer(monkeypatch, answer):
    from agents.core import orchestrator as o

    monkeypatch.setattr(o.power, "hold_for_turn", lambda orch: None)
    monkeypatch.setattr(o.power, "release_for_turn", lambda held: None)
    assert await _orch_with({"jarvis": answer}).process_detailed("p") == (answer, None)


@pytest.mark.parametrize("reply", [
    "[OpenRouter error]", "[Gemini error: provider request failed]", "[Claude API error: 404]",
    "[Claude API stream error: x]", "[OpenAI Responses error: request could not be completed]",
    "[xAI Responses error: request could not be completed]", "[VLM error]", "[Jarvis no LLM backend]",
    "⚠️ I can't reach the local Ollama model right now. Start it.",
    "⚠️ The local LM Studio model hit an error and couldn't answer. Check it.",
    "⚠️ No local language model is available. Start LM Studio or Ollama and try again.",
])
async def test_every_fixed_failure_reply_is_a_failure(monkeypatch, reply):
    from agents.core import orchestrator as o

    monkeypatch.setattr(o.power, "hold_for_turn", lambda orch: None)
    monkeypatch.setattr(o.power, "release_for_turn", lambda held: None)
    assert await _orch_with({"jarvis": reply}).process_detailed("p") == (reply, reply)


async def test_the_thinking_exhausted_reply_is_a_failure(monkeypatch):
    from agents.core import orchestrator as o
    from agents.core.llm.base import THINKING_EXHAUSTED_REPLY

    monkeypatch.setattr(o.power, "hold_for_turn", lambda orch: None)
    monkeypatch.setattr(o.power, "release_for_turn", lambda held: None)
    assert (await _orch_with({"jarvis": THINKING_EXHAUSTED_REPLY}).process_detailed("p"))[1] == THINKING_EXHAUSTED_REPLY


async def test_a_child_that_answers_with_a_json_array_is_done():
    orch = _Orch(reply='["a.py", "b.py"]', error=None)
    out = await _mgr(_runner(orch)).spawn("list them as JSON")
    assert out["status"] == "done" and out["result"]["output"] == '["a.py", "b.py"]'


async def test_a_vendor_prefixed_setting_matches_the_backends_bare_name():
    m = _mgr(_failing(pe.ProviderFailure("gemini", "gemini-9-pro", 404, "model_not_found")),
             selection_defaults=_setting("google/gemini-9-pro", "gemini"))
    notice = (await m.spawn_batch([{"task": "a"}]))["notice"]
    assert notice and notice["model"] == "google/gemini-9-pro"


async def test_a_whitespace_task_is_refused_before_any_consent(monkeypatch):
    class _Audit:
        def __init__(self):
            self.rows = []

        def log(self, event):
            self.rows.append(event)

    audit = _Audit()
    body = {"tasks": [{"task": "   ", "model": "claude-fable-5"}], "confirm_expensive": True}
    async with _client(_mgr(), monkeypatch, audit) as client:
        r = await client.post("/api/subagents/batch", json=body)
    assert r.status_code == 422 and audit.rows == []
