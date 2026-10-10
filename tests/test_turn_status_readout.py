"""H686: one request-owned, selected current-turn latency readout."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agents import web
from agents.core import settings_db
from agents.core.client_protocol import describe_client_protocol
from tests.h441_native_fixture import bind_native


def _events(body: str) -> list[dict]:
    return [json.loads(chunk[6:]) for chunk in body.split("\n\n") if chunk.startswith("data: ")]


def _orch(monkeypatch, *, fields=("latency",), measured=True, stream=False):
    class FakeOrch:
        session_id = "this_turn"
        notes = None

        def get_setting(self, key, default=None):
            assert key == "display.status_bar_fields"
            return list(fields)

        async def handle_input(self, *_args, **_kwargs):
            if measured:
                from agents.core.turn_outcome import record_turn_latency
                record_turn_latency(137)
            return "answer"

        async def handle_input_stream(self, *_args, **_kwargs):
            if measured:
                from agents.core.turn_outcome import record_turn_latency
                record_turn_latency(137)
            return "answer"

    orch = FakeOrch()
    bind_native(orch, monkeypatch, session_ids=(orch.session_id,))
    return orch


@pytest.mark.parametrize("stream", [False, True])
def test_http_returns_only_this_turns_selected_latency(monkeypatch, stream):
    monkeypatch.setattr(web, "orch", _orch(monkeypatch))
    path = "/chat/stream" if stream else "/chat"
    first = TestClient(web.app).post(path, json={"message": "hi"})
    assert first.status_code == 200
    payload = _events(first.text)[-1] if stream else first.json()
    assert payload["outcome"] == {"latency_ms": 137}
    assert payload["text" if stream else "reply"] == "answer"

    # A new uninstrumented turn must not inherit the previous one.
    monkeypatch.setattr(web, "orch", _orch(monkeypatch, measured=False))
    second = TestClient(web.app).post(path, json={"message": "later"})
    payload = _events(second.text)[-1] if stream else second.json()
    assert payload["outcome"] is None


@pytest.mark.parametrize("fields", [(), ("model",), ("latency", "tps")])
def test_server_selection_filters_unimplemented_or_hidden_fields(monkeypatch, fields):
    monkeypatch.setattr(web, "orch", _orch(monkeypatch, fields=fields))
    payload = TestClient(web.app).post("/chat", json={"message": "hi"}).json()
    assert payload["outcome"] == ({"latency_ms": 137} if "latency" in fields else None)
    assert "tps" not in (payload["outcome"] or {})


def test_invalid_or_unavailable_selection_does_not_break_answer(monkeypatch):
    fake = _orch(monkeypatch)
    fake.get_setting = lambda *_args: ["latency", "not-a-field"]
    monkeypatch.setattr(web, "orch", fake)
    payload = TestClient(web.app).post("/chat", json={"message": "hi"}).json()
    assert payload["reply"] == "answer"
    assert payload["outcome"] is None
    fake.get_setting = lambda *_args: (_ for _ in ()).throw(RuntimeError("settings unavailable"))
    payload = TestClient(web.app).post("/chat", json={"message": "hi"}).json()
    assert payload["reply"] == "answer"
    assert payload["outcome"] is None


def test_error_and_unavailable_paths_have_no_measured_outcome(monkeypatch):
    class Broken:
        session_id = "this_turn"
        notes = None

        async def handle_input(self, *_args, **_kwargs):
            raise RuntimeError("private exception")

        async def handle_input_stream(self, *_args, **_kwargs):
            raise RuntimeError("private exception")

    broken = Broken()
    bind_native(broken, monkeypatch, session_ids=(broken.session_id,))
    monkeypatch.setattr(web, "orch", broken)
    client = TestClient(web.app)
    reply = client.post("/chat", json={"message": "hi"}).json()
    event = _events(client.post("/chat/stream", json={"message": "hi"}).text)[-1]
    assert reply["reply"] == "Internal error." and reply["outcome"] is None
    assert event["text"] == "Eroare internă." and event["outcome"] is None
    monkeypatch.setattr(web, "orch", None)
    assert client.post("/chat", json={"message": "hi"}).json()["outcome"] is None


@pytest.mark.parametrize("stream", [False, True])
def test_busy_lease_has_no_duration_from_a_previous_turn(monkeypatch, stream):
    fake = _orch(monkeypatch)

    @asynccontextmanager
    async def busy(_session=None):
        yield False

    fake.turn_lease = busy
    monkeypatch.setattr(web, "orch", fake)
    response = TestClient(web.app).post("/chat/stream" if stream else "/chat", json={"message": "hi"})
    payload = _events(response.text)[-1] if stream else response.json()
    assert payload["outcome"] is None


def test_setting_is_declared_and_rejects_noncanonical_lists():
    row = next(r for r in settings_db.DEFAULTS if (r["category"], r["key"]) == ("display", "status_bar_fields"))
    assert row["value"] == ["latency"]
    assert row["kind"] == "tags"
    allowed = {"model", "context_pct", "cache_hit", "latency", "tps", "compressions", "bg_tasks", "duration"}
    assert set(row["opts"]) == allowed
    assert settings_db.validate_category("display", {"status_bar_fields": []}) == []
    assert settings_db.validate_category("display", {"status_bar_fields": list(allowed)}) == []
    for bad in (["latency", "latency"], ["unknown"], ["latency"] * 9, "latency", [1]):
        assert settings_db.validate_category("display", {"status_bar_fields": bad}), bad


def test_selected_setting_persists_and_invalid_stored_row_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_db, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(settings_db, "_initialized", False)
    settings_db.init_db(force=True)
    assert settings_db.get_value("display", "status_bar_fields") == ["latency"]
    assert settings_db.validate_category("display", {"status_bar_fields": []}) == []
    assert settings_db.put_category("display", {"status_bar_fields": []}) == (1, [])
    assert settings_db.get_value("display", "status_bar_fields") == []
    assert settings_db.selected_status_fields(["latency", "forged"]) is None


def test_protocol_end_declares_outcome_and_schema_is_self_contained():
    payload = describe_client_protocol(web.app)
    stream = next(row for row in payload["routes"] if row["path"] == "/chat/stream")
    assert "outcome" in stream["stream_events"]["end"]
    chat = next(row for row in payload["routes"] if row["path"] == "/chat")
    schema = payload["components"]["schemas"]["ChatResponse"]
    assert chat["response"]["schema"] == {"$ref": "#/components/schemas/ChatResponse"}
    assert "outcome" in schema["properties"]


@pytest.mark.asyncio
async def test_collector_claims_once_and_rejects_late_copied_context():
    from agents.core.turn_outcome import open_turn_outcome, record_turn_latency, reset_turn_outcome

    collector, token = open_turn_outcome()
    gate = asyncio.Event()

    async def late_child():
        await gate.wait()
        record_turn_latency(999)

    child = asyncio.create_task(late_child())
    try:
        assert record_turn_latency(20) is True
        assert record_turn_latency(900) is False
        assert collector.close() == {"latency_ms": 20}
        gate.set()
        await child
        assert collector.close() == {"latency_ms": 20}
    finally:
        reset_turn_outcome(token)


def test_nested_collector_reset_restores_outer_request():
    from agents.core.turn_outcome import open_turn_outcome, record_turn_latency, reset_turn_outcome

    outer, outer_token = open_turn_outcome()
    try:
        inner, inner_token = open_turn_outcome()
        try:
            assert record_turn_latency(5)
            assert inner.close() == {"latency_ms": 5}
        finally:
            reset_turn_outcome(inner_token)
        assert record_turn_latency(22)
        assert outer.close() == {"latency_ms": 22}
    finally:
        reset_turn_outcome(outer_token)


@pytest.mark.asyncio
async def test_parallel_collectors_are_isolated_and_failures_do_not_publish(monkeypatch):
    from agents.core import turn_outcome

    async def run(value, fail=False):
        collector, token = turn_outcome.open_turn_outcome()
        try:
            @turn_outcome.measure_turn_latency
            async def work():
                await asyncio.sleep(0)
                if fail:
                    raise RuntimeError("failed")
                return value

            if fail:
                with pytest.raises(RuntimeError):
                    await work()
            else:
                assert await work() == value
            return collector.close()
        finally:
            turn_outcome.reset_turn_outcome(token)

    outputs = await asyncio.gather(run("a"), run("b"), run("bad", fail=True))
    assert all(type(x["latency_ms"]) is int and x["latency_ms"] >= 0 for x in outputs[:2])
    assert outputs[2] is None


@pytest.mark.asyncio
async def test_outer_wrapper_keeps_ownership_over_nested_wrapper(monkeypatch):
    from agents.core import turn_outcome

    ticks = iter([1.0, 1.4])
    monkeypatch.setattr(turn_outcome, "time", SimpleNamespace(perf_counter=lambda: next(ticks)))
    collector, token = turn_outcome.open_turn_outcome()
    try:
        @turn_outcome.measure_turn_latency
        async def nested():
            return "inner"

        @turn_outcome.measure_turn_latency
        async def outer():
            assert await nested() == "inner"
            return "outer"

        assert await outer() == "outer"
        assert collector.close() == {"latency_ms": 400}
    finally:
        turn_outcome.reset_turn_outcome(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_real_public_wrapper_measures_after_cleanup_and_normal_refusal(monkeypatch, stream):
    from agents.core import orchestrator, turn_outcome
    from agents.core.conversation_clock import CONTEXT_REFUSED_REPLY, CompactionClockRefused

    instance = orchestrator.Orchestrator.__new__(orchestrator.Orchestrator)
    instance._start_title_upgrades = lambda _titles: None
    cleanup = {"done": False}
    monkeypatch.setattr(orchestrator.power, "hold_for_turn", lambda _orch: True)
    monkeypatch.setattr(orchestrator.power, "release_for_turn", lambda _held: cleanup.__setitem__("done", True))

    async def refused(*_args):
        raise CompactionClockRefused("internal details")

    instance._handle_input = refused
    instance._handle_input_stream = refused
    ticks = iter([1.0, 1.135])

    def clock():
        if cleanup["done"]:
            return 1.135
        return next(ticks)

    monkeypatch.setattr(turn_outcome, "time", SimpleNamespace(perf_counter=clock))
    collector, token = turn_outcome.open_turn_outcome()
    try:
        if stream:
            reply = await instance.handle_input_stream("hello", on_token=lambda _s: None)
        else:
            reply = await instance.handle_input("hello")
        assert reply == CONTEXT_REFUSED_REPLY
        assert cleanup["done"] is True
        assert collector.close() == {"latency_ms": 135}
    finally:
        turn_outcome.reset_turn_outcome(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_real_public_wrapper_measures_normal_command(monkeypatch, stream):
    from agents.core import orchestrator, turn_outcome

    instance = orchestrator.Orchestrator.__new__(orchestrator.Orchestrator)
    instance._start_title_upgrades = lambda _titles: None
    monkeypatch.setattr(orchestrator.power, "hold_for_turn", lambda _orch: False)
    monkeypatch.setattr(orchestrator.power, "release_for_turn", lambda _held: None)

    async def command(*_args):
        return "Started a new conversation."

    instance._handle_input = command
    instance._handle_input_stream = command
    ticks = iter([1.0, 1.05])
    monkeypatch.setattr(turn_outcome, "time", SimpleNamespace(perf_counter=lambda: next(ticks)))
    collector, token = turn_outcome.open_turn_outcome()
    try:
        reply = (await instance.handle_input_stream("/new", on_token=lambda _s: None)
                 if stream else await instance.handle_input("/new"))
        assert reply == "Started a new conversation."
        assert collector.close() == {"latency_ms": 50}
    finally:
        turn_outcome.reset_turn_outcome(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream,failed", [(False, True), (True, True), (False, False), (True, False)])
async def test_real_public_wrapper_errors_and_cancellation_do_not_publish(monkeypatch, stream, failed):
    from agents.core import orchestrator, turn_outcome

    instance = orchestrator.Orchestrator.__new__(orchestrator.Orchestrator)
    instance._start_title_upgrades = lambda _titles: None
    monkeypatch.setattr(orchestrator.power, "hold_for_turn", lambda _orch: False)
    monkeypatch.setattr(orchestrator.power, "release_for_turn", lambda _held: None)

    async def stopped(*_args):
        if failed:
            raise RuntimeError("unexpected")
        raise asyncio.CancelledError()

    instance._handle_input = stopped
    instance._handle_input_stream = stopped
    collector, token = turn_outcome.open_turn_outcome()
    try:
        with pytest.raises(RuntimeError if failed else asyncio.CancelledError):
            if stream:
                await instance.handle_input_stream("hello", on_token=lambda _s: None)
            else:
                await instance.handle_input("hello")
        assert collector.close() is None
    finally:
        turn_outcome.reset_turn_outcome(token)
