"""Gemini needs semantic completion and clean EOF, never a guessed final count."""

import asyncio
import json

import httpx
import pytest

from tests.test_text_usage_propagation import agent_for, backend_for


def terminal(*, empty=False, blocked=False):
    data = {
        "usageMetadata": {
            "promptTokenCount": 123,
            "candidatesTokenCount": 0 if empty or blocked else 14,
            "thoughtsTokenCount": 0 if blocked else 3,
        },
        "responseId": "response-one",
    }
    if blocked:
        data["promptFeedback"] = {"blockReason": "SAFETY"}
    else:
        data["candidates"] = [
            {"finishReason": "STOP", "content": {"parts": [] if empty else [{"text": "answer"}]}}
        ]
    return data


class Stream(httpx.AsyncByteStream):
    def __init__(self, rows, *, wait=None, error=False, close_error=False):
        self.rows, self.wait, self.error, self.close_error = rows, wait, error, close_error

    async def __aiter__(self):
        for row in self.rows:
            yield (
                row if isinstance(row, bytes) else ("data: " + json.dumps(row) + "\n\n").encode()
            )
        if self.wait is not None:
            self.wait.set()
            await asyncio.Event().wait()
        if self.error:
            raise httpx.ReadError("interrupted")

    async def aclose(self):
        if self.close_error:
            raise httpx.ReadError("close failed")


async def invoke(rows, *, error=False, close_error=False):
    events, tokens, requests = [], [], []

    def handler(req):
        requests.append(json.loads(req.content))
        return httpx.Response(200, stream=Stream(rows, error=error, close_error=close_error))

    backend = await backend_for("gemini", handler)
    try:
        answer = await agent_for().generate_response(
            backend,
            "model",
            "hello",
            "",
            128,
            0.2,
            on_token=tokens.append,
            usage_sink=events.append,
        )
        return answer, events, tokens, requests
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["text", "empty", "blocked"])
async def test_terminal_local_usage_after_clean_eof(kind):
    answer, events, tokens, requests = await invoke(
        [terminal(empty=kind == "empty", blocked=kind == "blocked")]
    )
    assert answer == "".join(tokens) == ("answer" if kind == "text" else "")
    assert len(events) == 1 and events[0].input_tokens == 123
    assert events[0].output_tokens == {"text": 17, "empty": 3, "blocked": 0}[kind]
    assert "usage" not in requests[0] and "stream_options" not in requests[0]


@pytest.mark.asyncio
async def test_intermediate_usage_is_not_summed():
    first = terminal(empty=True)
    del first["candidates"][0]["finishReason"]
    first["usageMetadata"].update(candidatesTokenCount=9, thoughtsTokenCount=1)
    _, events, _, _ = await invoke([first, terminal()])
    assert len(events) == 1 and events[0].output_tokens == 17


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        {},
        {"promptTokenCount": 123},
        {"promptTokenCount": True, "candidatesTokenCount": 1},
        {"promptTokenCount": 123, "candidatesTokenCount": -1},
        {"promptTokenCount": 123, "candidatesTokenCount": 1, "thoughtsTokenCount": "2"},
    ],
)
async def test_invalid_terminal_usage_never_reuses_prior_snapshot(bad):
    first = terminal(empty=True)
    first["candidates"][0].pop("finishReason")
    last = terminal()
    last["usageMetadata"] = bad
    answer, events, _, _ = await invoke([first, last])
    assert answer == "answer" and events == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "trailer",
    [
        b'{"error":{"code":500}}\n',
        b'data: {"error":{"code":500}}\n\n',
        b"data: {broken\n\n",
        b"data: [DONE]\n\n",
        b"unknown body\n",
    ],
)
async def test_error_or_unproven_trailer_invalidates_terminal_usage(trailer):
    answer, events, _, _ = await invoke([terminal(), trailer])
    assert answer == "answer" and events == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    ["no-finish", "unknown-finish", "multiple", "usage-only-after", "id-change", "unknown-block"],
)
async def test_unresolved_terminal_cases_remain_unreported(kind):
    row = terminal()
    rows = [row]
    if kind == "no-finish":
        row["candidates"][0].pop("finishReason")
    elif kind == "unknown-finish":
        row["candidates"][0]["finishReason"] = "NEW_REASON"
    elif kind == "multiple":
        row["candidates"].append(dict(row["candidates"][0]))
    elif kind == "usage-only-after":
        rows.append({"usageMetadata": row["usageMetadata"]})
    elif kind == "id-change":
        rows.insert(0, {"responseId": "other"})
    else:
        rows = [terminal(blocked=True)]
        rows[0]["promptFeedback"]["blockReason"] = "NEW_REASON"
    _, events, _, _ = await invoke(rows)
    assert events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["transport", "close"])
async def test_terminal_followed_by_transport_failure_is_not_complete(failure):
    _, events, _, _ = await invoke(
        [terminal()], error=failure == "transport", close_error=failure == "close"
    )
    assert events == []


@pytest.mark.asyncio
async def test_cancel_after_terminal_before_eof_does_not_report():
    ready, events = asyncio.Event(), []
    backend = await backend_for(
        "gemini", lambda req: httpx.Response(200, stream=Stream([terminal()], wait=ready))
    )
    try:
        task = asyncio.create_task(
            agent_for().generate_response(
                backend,
                "model",
                "hello",
                "",
                128,
                0.2,
                on_token=lambda text: None,
                usage_sink=events.append,
            )
        )
        await asyncio.wait_for(ready.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert events == []
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("retry", ["cache", "auth"])
@pytest.mark.parametrize("valid", [True, False])
async def test_retry_uses_only_new_attempt_measurement(retry, valid):
    from contextlib import nullcontext

    from agents.core.llm.auth_rotation import AuthProfilePool
    from tests.test_gemini_request_context import _binding

    requests, events = [], []

    def handler(req):
        requests.append(req)
        row = terminal()
        if len(requests) == 1:
            row["usageMetadata"]["promptTokenCount"] = 9999
            return httpx.Response(400 if retry == "cache" else 429, json=row)
        if not valid:
            row.pop("usageMetadata")
        return httpx.Response(200, stream=Stream([row]))

    backend = await backend_for("gemini", handler)
    if retry == "auth":
        backend.auth_pool = AuthProfilePool(["old-key", "new-key"], "gemini")
    try:
        scope = (
            backend.request_scope(_binding(cache_name="cachedContents/rejected"))
            if retry == "cache"
            else nullcontext()
        )
        with scope:
            answer = await agent_for().generate_response(
                backend,
                "model",
                "hello",
                "",
                128,
                0.2,
                on_token=lambda text: None,
                usage_sink=events.append,
            )
        assert answer == "answer" and len(requests) == 2
        assert [u.input_tokens for u in events] == ([123] if valid else [])
        if retry == "cache":
            assert "cachedContent" not in json.loads(requests[1].content)
        else:
            assert [r.headers["x-goog-api-key"] for r in requests] == ["old-key", "new-key"]
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_concurrent_streams_keep_observers_separate():
    def handler(req):
        data = terminal()
        prompt = json.loads(req.content)["contents"][0]["parts"][0]["text"]
        data["usageMetadata"]["promptTokenCount"] = int(prompt)
        return httpx.Response(200, stream=Stream([data]))

    backend = await backend_for("gemini", handler)

    async def run(count):
        events = []
        await agent_for().generate_response(
            backend,
            "model",
            str(count),
            "",
            128,
            0.2,
            on_token=lambda text: None,
            usage_sink=events.append,
        )
        return [u.input_tokens for u in events]

    try:
        assert await asyncio.gather(run(123), run(456)) == [[123], [456]]
    finally:
        await backend.client.aclose()


@pytest.mark.asyncio
async def test_comments_do_not_erase_terminal_measurement():
    _, events, _, _ = await invoke(
        [terminal(), b": heartbeat\nevent: message\nid: 1\nretry: 1000\n\n"]
    )
    assert len(events) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("trailer", [b"event:error\n", b"event:   error\n"])
async def test_error_event_metadata_invalidates_accounting(trailer):
    answer, events, _, _ = await invoke([terminal(), trailer])
    assert answer == "answer" and events == []


@pytest.mark.asyncio
async def test_earlier_multiple_candidates_cannot_become_single_measured_response():
    first = terminal(empty=True)
    first["candidates"].append(dict(first["candidates"][0]))
    _, events, _, _ = await invoke([first, terminal()])
    assert events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [1, -1, True, "0", None, [], {}])
async def test_ambiguous_candidate_index_invalidates_whole_measurement(index):
    first = terminal()
    first["candidates"][0]["index"] = index
    last = terminal()
    last["candidates"][0]["index"] = 0
    answer, events, tokens, _ = await invoke([first, last])
    assert answer == "".join(tokens) == "answeranswer"
    assert events == []


@pytest.mark.asyncio
async def test_explicit_zero_candidate_index_remains_supported():
    row = terminal()
    row["candidates"][0]["index"] = 0
    _, events, _, _ = await invoke([row])
    assert len(events) == 1


@pytest.mark.asyncio
async def test_separate_singleton_frames_with_different_candidate_indices_are_unreported():
    first, last = terminal(), terminal()
    first["candidates"][0]["index"] = 0
    last["candidates"][0]["index"] = 1
    answer, events, tokens, _ = await invoke([first, last])
    assert answer == "".join(tokens) == "answeranswer"
    assert events == []
