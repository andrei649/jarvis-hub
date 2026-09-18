"""Explicit continuation creation and actual addressed conversation boundaries."""

import json
from datetime import UTC, datetime, timezone

import pytest

from agents.core.checkpoint import CheckpointManager

SEED = [
    {
        "role": "user",
        "content": "Remember the blue door",
        "agent_id": None,
        "timestamp": "2026-09-01T10:00:00+00:00",
        "token_count": 6,
    }
]


def manager(path):
    value = CheckpointManager(str(path))
    value.initialize()
    return value


def test_two_generations_share_birth_and_restart_context(tmp_path):
    from agents.core.session_continuation import ContinuationStore

    path = tmp_path / "checkpoints.db"
    cp = manager(path)
    cp.create_session_record("source")
    cp._conn.execute("UPDATE sessions SET started_at=? WHERE id='source'", (SEED[0]["timestamp"],))
    cp._conn.commit()
    clock = cp.clock_snapshot("source")
    clock = cp.commit_clock(clock, "accepted summary", now=datetime(2026, 9, 10, tzinfo=UTC))
    store = ContinuationStore(cp)
    one = store.create("source", "00000000-0000-4000-8000-000000000001", SEED, clock)
    two = store.create(
        one["session_id"],
        "00000000-0000-4000-8000-000000000002",
        SEED,
        cp.clock_snapshot(one["session_id"]),
    )
    assert one["session_id"] != two["session_id"] != "source"
    assert two["root_session_id"] == "source" and two["parent_session_id"] == one["session_id"]
    assert cp.session_started_at(two["session_id"]) != SEED[0]["timestamp"]
    assert cp.clock_snapshot(two["session_id"]).started_at == clock.started_at
    assert cp.clock_snapshot(two["session_id"]).rebuilt_at == clock.rebuilt_at
    cp.close()
    cp = manager(path)
    assert ContinuationStore(cp).seed(two["session_id"]) == SEED
    assert cp.clock_snapshot(two["session_id"]).started_at == clock.started_at
    cp.close()


def test_request_replay_and_failed_transaction_do_not_create_extra_sessions(tmp_path):
    from agents.core.session_continuation import ContinuationRefused, ContinuationStore

    cp = manager(tmp_path / "cp.db")
    cp.create_session_record("source")
    store = ContinuationStore(cp)
    clock = cp.clock_snapshot("source")
    request = "00000000-0000-4000-8000-000000000001"
    result = store.create("source", request, SEED, clock)
    assert store.create("source", request, SEED, clock) == result
    with pytest.raises(ContinuationRefused):
        store.create("other", request, SEED, clock)
    before = cp._conn.execute("SELECT count(*) FROM sessions").fetchone()[0]
    cp._conn.execute(
        "CREATE TRIGGER fail_seed BEFORE INSERT ON session_continuations BEGIN SELECT RAISE(ABORT,'fail'); END"
    )
    with pytest.raises(ContinuationRefused):
        store.create("source", "00000000-0000-4000-8000-000000000003", SEED, clock)
    assert cp._conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == before
    cp.close()


def test_upgrade_preserves_accepted_clock_and_reused_id_refuses_old_commit(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""CREATE TABLE sessions(id TEXT PRIMARY KEY,agent_id TEXT,started_at TEXT,ended_at TEXT,turn_count INTEGER DEFAULT 0,summary TEXT,metadata TEXT DEFAULT '{}');
    CREATE TABLE session_clock(session_id TEXT PRIMARY KEY,birth_at TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 0,rebuilt_at TEXT NOT NULL,compaction_sha256 TEXT NOT NULL DEFAULT '');
    INSERT INTO sessions(id,started_at) VALUES('a','2026-09-01T00:00:00+00:00');
    INSERT INTO session_clock VALUES('a','2026-09-01T00:00:00+00:00',4,'2026-09-10T00:00:00+00:00','hash');""")
    conn.close()
    cp = manager(path)
    old = cp.clock_snapshot("a")
    assert old.revision == 4 and old.rebuilt_at.day == 10
    cp._conn.execute("DELETE FROM sessions WHERE id='a'")
    cp._conn.execute("INSERT INTO sessions(id,started_at) VALUES('a','2026-09-01T00:00:00+00:00')")
    cp._conn.commit()
    assert cp.clock_snapshot("a").instance_id != old.instance_id
    assert cp.commit_clock(old, "stale") is None
    cp.close()


@pytest.mark.asyncio
async def test_coordinator_carries_timestamps_without_switching_defaults_and_prefers_newer_snapshot(
    tmp_path, monkeypatch
):
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from agents.core.memory import persistence
    from agents.core.memory.manager import MemoryManager
    from agents.core.session_continuation import create_continuation, prepare_session

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    cp = manager(tmp_path / "cp.db")
    cp.create_session_record("source")
    persistence.save_memory("source", SEED, instance_id=cp.clock_snapshot("source").instance_id)
    memory = MemoryManager()
    memory.conversation.current_session_id = "default"

    @asynccontextmanager
    async def lease(sid):
        assert sid == "source"
        yield True

    orch = SimpleNamespace(memory=memory, checkpoints=cp, session_id="default", turn_lease=lease)
    result = await create_continuation(orch, "source", "00000000-0000-4000-8000-000000000001")
    child = result["session_id"]
    await prepare_session(orch, child)
    assert await memory.get_history(child) == SEED
    assert orch.session_id == memory.conversation.current_session_id == "default"
    newer = [*SEED, {**SEED[0], "content": "new child turn"}]
    persistence.save_memory(child, newer, instance_id=cp.clock_snapshot(child).instance_id)
    memory.conversation.sessions.pop(child)
    await prepare_session(orch, child)
    assert await memory.get_history(child) == newer
    cp.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("restart", [False, True])
@pytest.mark.parametrize("reasoning", [None, "low"])
async def test_owner_route_to_actual_explicit_session_turn(tmp_path, monkeypatch, stream, restart, reasoning):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import httpx

    import agents.web as web
    from agents.core.agent import Agent
    from agents.core.config import JarvisConfig
    from agents.core.llm.base import LLMBackend
    from agents.core.memory import persistence
    from agents.core.orchestrator import Orchestrator

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    orch = Orchestrator(JarvisConfig())
    orch.checkpoints = manager(tmp_path / "cp.db")
    orch.checkpoints.create_session_record("source")
    orch.checkpoints._conn.execute(
        "UPDATE sessions SET started_at=? WHERE id='source'", (SEED[0]["timestamp"],)
    )
    orch.checkpoints._conn.commit()
    persistence.save_memory(
        "source", SEED, instance_id=orch.checkpoints.clock_snapshot("source").instance_id
    )
    orch._session_id_default = "default"
    orch.memory.conversation.current_session_id = "default"
    seen = []
    wire = []
    provider = None
    if reasoning is not None:
        from agents.core.llm.openrouter import OpenRouterBackend
        from agents.core.llm.providers import ProviderProfile
        from agents.core.llm.request_context import current_session

        def respond(request):
            wire.append((current_session(), json.loads(request.content)))
            return httpx.Response(200, json={"choices": [{
                "message": {"content": "The blue door"}, "finish_reason": "stop",
            }]})

        provider = OpenRouterBackend(
            client=httpx.AsyncClient(transport=httpx.MockTransport(respond), base_url="https://fixture.invalid"),
            profile=ProviderProfile("compatible", "fixture", "openai-compatible", capabilities={"reasoning-effort"}),
            reasoning_effort="high", effort_declarations={"fixture": ["low", "high"]},
        )

    class Backend(LLMBackend):
        async def generate(self, model, prompt, system="", max_tokens=1024, temperature=0.7):
            seen.append((orch.session_id, prompt, system))
            if provider is not None:
                return await provider.generate(model, prompt, system=system, max_tokens=max_tokens, temperature=temperature)
            return "The blue door"

    backend = Backend()
    orch.llm_router = SimpleNamespace(
        select_backend=lambda *args: (backend, "fixture", "local"), model_manager=None
    )
    agent = Agent("jarvis", {}, orch.llm_router)
    agent.soul = {"content": "Fixture assistant"}
    agent._checkpoint_manager = orch.checkpoints
    orch.agents = {"jarvis": agent}
    orch.router.classify = AsyncMock(
        return_value=SimpleNamespace(
            target_agents=["jarvis"], is_general=True, context={}, confidence=1
        )
    )
    orch._dispatch_command = AsyncMock(return_value=None)
    orch._chat_control_enabled = lambda: False
    orch._gather_plugin_data = AsyncMock(return_value={})
    orch._recall_block = AsyncMock(return_value="")
    orch._complete_llm_turn = AsyncMock()
    orch._agent_gen_params = lambda *args: (256, 0)
    agent._gen_params = lambda *args: (256, 0)
    monkeypatch.setattr(web, "orch", orch)
    monkeypatch.setattr(web, "_admin_env_token", lambda: "fixture")
    monkeypatch.setattr(web, "_env_admin_active", lambda: True)
    monkeypatch.setattr(web.app, "root_path", "/nerva")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web.app), base_url="http://localhost"
    ) as client:
        denied = await client.post(
            "/sessions/continue",
            json={
                "source_session_id": "source",
                "request_id": "00000000-0000-4000-8000-000000000001",
            },
        )
        assert denied.status_code == 401
        created = await client.post(
            "/sessions/continue",
            headers={"x-admin-token": "fixture"},
            json={
                "source_session_id": "source",
                "request_id": "00000000-0000-4000-8000-000000000001",
            },
        )
        assert created.status_code == 201, created.text
        child = created.json()["session_id"]
        if restart:
            grandchild = await client.post(
                "/sessions/continue",
                headers={"x-admin-token": "fixture"},
                json={
                    "source_session_id": child,
                    "request_id": "00000000-0000-4000-8000-000000000002",
                },
            )
            assert grandchild.status_code == 201, grandchild.text
            child = grandchild.json()["session_id"]
            orch.checkpoints.close()
            orch.checkpoints = manager(tmp_path / "cp.db")
            from agents.core.memory.manager import MemoryManager

            orch.memory = MemoryManager()
            orch.memory.conversation.current_session_id = "default"
            orch.memory.set_checkpoint_manager(orch.checkpoints)
            agent._checkpoint_manager = orch.checkpoints
        response = await client.post(
            "/chat/stream" if stream else "/chat",
            json={"message": "Which door?", "session_id": child, **({"reasoning": reasoning} if reasoning else {})},
        )
        assert response.status_code == 200 and "The blue door" in response.text
        assert seen and seen[-1][0] == child
        assert "Remember the blue door" in seen[-1][1] and "September 01" in seen[-1][2]
        assert orch._session_id_default == orch.memory.conversation.current_session_id == "default"
        if provider is not None:
            assert wire and wire[-1][0] == child
            assert wire[-1][1]["reasoning_effort"] == "low"
            assert "Remember the blue door" in json.dumps(wire[-1][1]["messages"])
            assert provider.reasoning_effort == "high"
            followup = await client.post(
                "/chat/stream" if stream else "/chat",
                json={"message": "Again?", "session_id": child},
            )
            assert followup.status_code == 200 and "The blue door" in followup.text
            assert wire[-1][0] == child and wire[-1][1]["reasoning_effort"] == "high"
            assert orch._session_id_default == orch.memory.conversation.current_session_id == "default"
    if provider is not None:
        await provider.aclose()
    orch.checkpoints.close()


@pytest.mark.parametrize("reasoning", [None, "low"])
def test_cli_authored_continuation_and_explicit_chat(reasoning):
    import io

    from agents.cli.nerva import Context, main

    calls = []

    class Client:
        def post(self, path, body):
            calls.append((path, body))
            return {"session_id": "session_child", "reply": "ok"}

    ctx = Context(
        environ={}, out=io.StringIO(), err=io.StringIO(), client_factory=lambda env: Client()
    )
    request = "00000000-0000-4000-8000-000000000001"
    assert main(["sessions", "continue", "source", "--request-id", request], context=ctx) == 0
    assert main(["chat", "--session", "session_child", "next", *(["--reasoning", reasoning] if reasoning else [])], context=ctx) == 0
    assert calls == [
        ("/sessions/continue", {"source_session_id": "source", "request_id": request}),
        ("/chat", {"message": "next", "session_id": "session_child", **({"reasoning": reasoning} if reasoning else {})}),
    ]


@pytest.mark.parametrize(
    "corruption", ["cycle", "missing_parent", "root_mismatch", "reused_parent"]
)
def test_ancestry_corruption_refuses_new_child(tmp_path, corruption):
    from agents.core.session_continuation import ContinuationRefused, ContinuationStore

    cp = manager(tmp_path / "cp.db")
    cp.create_session_record("source")
    store = ContinuationStore(cp)
    one = store.create(
        "source", "00000000-0000-4000-8000-000000000001", SEED, cp.clock_snapshot("source")
    )
    child = one["session_id"]
    clock = cp.clock_snapshot(child)
    if corruption == "cycle":
        cp._conn.execute(
            "UPDATE session_continuations SET parent_id=session_id,parent_instance_id=instance_id"
        )
    elif corruption == "missing_parent":
        cp._conn.execute("DELETE FROM sessions WHERE id='source'")
    elif corruption == "root_mismatch":
        cp._conn.execute("UPDATE session_continuations SET root_id='unrelated'")
    else:
        birth = cp.session_started_at("source")
        cp._conn.execute("DELETE FROM sessions WHERE id='source'")
        cp._conn.execute("INSERT INTO sessions(id,started_at) VALUES('source',?)", (birth,))
    cp._conn.commit()
    with pytest.raises(ContinuationRefused):
        store.create(child, "00000000-0000-4000-8000-000000000002", SEED, clock)
    assert cp._conn.execute("SELECT count(*) FROM session_continuations").fetchone()[0] == 1
    cp.close()


def test_two_connections_same_request_create_one_child_and_no_execution_checkpoint(tmp_path):
    from agents.core.session_continuation import ContinuationStore

    path = tmp_path / "cp.db"
    cp, other = manager(path), manager(path)
    cp.create_session_record("source")
    cp.save_agent_execution("jarvis", "source", "old executable task prompt")
    clock = cp.clock_snapshot("source")
    request = "00000000-0000-4000-8000-000000000001"
    one = ContinuationStore(cp).create("source", request, SEED, clock)
    two = ContinuationStore(other).create("source", request, SEED, clock)
    assert one == two and other.load("jarvis", one["session_id"]) is None
    assert other._conn.execute("SELECT count(*) FROM session_continuations").fetchone()[0] == 1
    cp.close()
    other.close()


def test_ambiguous_commit_recovers_same_receipt(tmp_path):
    import sqlite3

    from agents.core.session_continuation import ContinuationStore

    cp = manager(tmp_path / "cp.db")
    cp.create_session_record("source")
    clock = cp.clock_snapshot("source")
    real = cp._conn

    class Ambiguous:
        def __getattr__(self, key):
            return getattr(real, key)

        def __enter__(self):
            real.__enter__()
            return self

        def __exit__(self, *args):
            real.__exit__(*args)
            raise sqlite3.OperationalError("simulated lost commit acknowledgement")

    cp._conn = Ambiguous()
    result = ContinuationStore(cp).create(
        "source", "00000000-0000-4000-8000-000000000001", SEED, clock
    )
    cp._conn = real
    assert ContinuationStore(cp).seed(result["session_id"]) == SEED
    assert real.execute("SELECT count(*) FROM session_continuations").fetchone()[0] == 1
    cp.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["busy", "cancel"])
async def test_busy_or_cancelled_creation_has_no_child(tmp_path, mode):
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from agents.core.memory.manager import MemoryManager
    from agents.core.session_continuation import ContinuationRefused, create_continuation

    cp = manager(tmp_path / "cp.db")
    cp.create_session_record("source")
    memory = MemoryManager()
    entered = asyncio.Event()

    @asynccontextmanager
    async def lease(sid):
        entered.set()
        yield mode != "busy"

    orch = SimpleNamespace(checkpoints=cp, memory=memory, turn_lease=lease)
    if mode == "cancel":
        await memory._lock.acquire()
        task = asyncio.create_task(
            create_continuation(orch, "source", "00000000-0000-4000-8000-000000000001")
        )
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        memory._lock.release()
    else:
        with pytest.raises(ContinuationRefused, match="source_busy"):
            await create_continuation(orch, "source", "00000000-0000-4000-8000-000000000001")
    assert cp._conn.execute("SELECT count(*) FROM session_continuations").fetchone()[0] == 0
    cp.close()


@pytest.mark.parametrize("mode", ["empty", "huge", "bad_timestamp", "bad_role"])
def test_invalid_retained_seed_fails_before_child_creation(tmp_path, mode):
    from agents.core.session_continuation import ContinuationRefused, ContinuationStore

    cp = manager(tmp_path / "cp.db")
    cp.create_session_record("source")
    turns = json.loads(json.dumps(SEED))
    if mode == "empty":
        turns = []
    elif mode == "huge":
        turns[0]["content"] = "x" * (512 * 1024 + 1)
    elif mode == "bad_timestamp":
        turns[0]["timestamp"] = "invented"
    else:
        turns[0]["role"] = "tool"
    with pytest.raises(ContinuationRefused):
        ContinuationStore(cp).create(
            "source", "00000000-0000-4000-8000-000000000001", turns, cp.clock_snapshot("source")
        )
    assert cp._conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 1
    cp.close()


@pytest.mark.asyncio
async def test_seed_only_child_resumes_after_restart_without_materialized_json(
    tmp_path, monkeypatch
):
    from agents.core.memory import persistence
    from agents.core.memory.manager import MemoryManager
    from agents.core.session_continuation import ContinuationStore

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    cp = manager(tmp_path / "cp.db")
    cp.create_session_record("source")
    child = ContinuationStore(cp).create(
        "source", "00000000-0000-4000-8000-000000000001", SEED, cp.clock_snapshot("source")
    )["session_id"]
    assert not (tmp_path / f"{child}.json").exists()
    memory = MemoryManager()
    memory.set_checkpoint_manager(cp)
    assert await memory.resume_session(child)
    assert await memory.get_history(child) == SEED
    cp.close()


@pytest.mark.asyncio
async def test_corrupt_newer_snapshot_refuses_instead_of_replaying_seed(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from agents.core.memory import persistence
    from agents.core.memory.manager import MemoryManager
    from agents.core.session_continuation import (
        ContinuationRefused,
        ContinuationStore,
        prepare_session,
    )

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    cp = manager(tmp_path / "cp.db")
    cp.create_session_record("source")
    child = ContinuationStore(cp).create(
        "source", "00000000-0000-4000-8000-000000000001", SEED, cp.clock_snapshot("source")
    )["session_id"]
    (tmp_path / f"{child}.json").write_text("{truncated")
    memory = MemoryManager()
    memory.set_checkpoint_manager(cp)
    with pytest.raises(ContinuationRefused, match="invalid_history"):
        await prepare_session(SimpleNamespace(memory=memory, checkpoints=cp), child)
    with pytest.raises(ContinuationRefused, match="invalid_history"):
        await memory.resume_session(child)
    assert child not in memory.conversation.sessions
    cp.close()


def test_actual_forget_erases_seed_bytes(tmp_path):
    from agents.core.data_purge import purge_data
    from agents.core.session_continuation import ContinuationStore

    path = tmp_path / "checkpoints.db"
    cp = manager(path)
    cp.create_session_record("source")
    ContinuationStore(cp).create(
        "source", "00000000-0000-4000-8000-000000000001", SEED, cp.clock_snapshot("source")
    )
    cp.close()
    report = purge_data(source_root=str(tmp_path), backup_first=False)
    assert report["ok"] is True
    assert b"Remember the blue door" not in path.read_bytes()
    cp = manager(path)
    assert cp._conn.execute("SELECT count(*) FROM session_continuations").fetchone()[0] == 0
    cp.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cached", [False, True])
async def test_recreated_source_cannot_inherit_old_cached_or_disk_history(
    tmp_path, monkeypatch, cached
):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from agents.core.memory import persistence
    from agents.core.memory.manager import MemoryManager
    from agents.core.session_continuation import (
        ContinuationRefused,
        create_continuation,
        prepare_session,
    )

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    cp = manager(tmp_path / "cp.db")
    cp.create_session_record("source")
    persistence.save_memory("source", SEED, instance_id=cp.clock_snapshot("source").instance_id)
    memory = MemoryManager()
    if not cached:
        memory.conversation.sessions.clear()
    birth = cp.session_started_at("source")
    cp._conn.execute("DELETE FROM sessions WHERE id='source'")
    cp._conn.execute("INSERT INTO sessions(id,started_at) VALUES('source',?)", (birth,))
    cp._conn.commit()

    @asynccontextmanager
    async def lease(sid):
        yield True

    orch = SimpleNamespace(memory=memory, checkpoints=cp, turn_lease=lease)
    with pytest.raises(ContinuationRefused, match="history_identity_changed"):
        await create_continuation(orch, "source", "00000000-0000-4000-8000-000000000001")
    with pytest.raises(ContinuationRefused, match="history_identity_changed"):
        await prepare_session(orch, "source")
    assert cp._conn.execute("SELECT count(*) FROM session_continuations").fetchone()[0] == 0
    cp.close()


def test_corrupt_seed_cannot_return_successful_idempotent_receipt(tmp_path):
    from agents.core.session_continuation import ContinuationRefused, ContinuationStore

    cp = manager(tmp_path / "cp.db")
    cp.create_session_record("source")
    clock = cp.clock_snapshot("source")
    store = ContinuationStore(cp)
    request = "00000000-0000-4000-8000-000000000001"
    child = store.create("source", request, SEED, clock)["session_id"]
    cp._conn.execute("UPDATE session_continuations SET seed_json='[]'")
    cp._conn.commit()
    with pytest.raises(ContinuationRefused, match="invalid_history"):
        store.replay("source", request)
    with pytest.raises(ContinuationRefused, match="invalid_history"):
        store.seed(child)
    cp.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("migrated_row", [False, True])
async def test_legacy_history_requires_row_present_at_migration(
    tmp_path, monkeypatch, migrated_row
):
    import sqlite3
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from agents.core.memory import persistence
    from agents.core.memory.manager import MemoryManager
    from agents.core.session_continuation import (
        ContinuationRefused,
        create_continuation,
        prepare_session,
    )

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    persistence.save_memory("legacy", SEED)
    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE sessions(id TEXT PRIMARY KEY,agent_id TEXT,started_at TEXT,ended_at TEXT,turn_count INTEGER DEFAULT 0,summary TEXT,metadata TEXT DEFAULT '{}')"
    )
    if migrated_row:
        connection.execute(
            "INSERT INTO sessions(id,started_at) VALUES('legacy',?)", (SEED[0]["timestamp"],)
        )
    connection.commit()
    connection.close()
    cp = manager(path)
    if not migrated_row:
        cp.create_session_record("legacy")
    memory = MemoryManager()

    @asynccontextmanager
    async def lease(sid):
        yield True

    orch = SimpleNamespace(memory=memory, checkpoints=cp, turn_lease=lease)
    if migrated_row:
        await prepare_session(orch, "legacy")
        created = await create_continuation(orch, "legacy", "00000000-0000-4000-8000-000000000001")
        assert created["carried_turns"] == 1
    else:
        with pytest.raises(ContinuationRefused, match="history_identity_changed"):
            await prepare_session(orch, "legacy")
        with pytest.raises(ContinuationRefused, match="history_identity_changed"):
            await create_continuation(orch, "legacy", "00000000-0000-4000-8000-000000000001")
    cp.close()


@pytest.mark.asyncio
async def test_new_memory_snapshot_persists_exact_instance_and_can_continue_after_restart(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from agents.core.memory import persistence
    from agents.core.memory.manager import MemoryManager
    from agents.core.session_continuation import prepare_session

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    cp = manager(tmp_path / "cp.db")
    memory = MemoryManager()
    memory.set_checkpoint_manager(cp)
    sid = await memory.new_session("session_fresh")
    await memory.add_turn(sid, "user", "fresh context")
    original = await memory.get_history(sid)
    payload = json.loads((tmp_path / f"{sid}.json").read_text())
    assert payload["instance_id"] == cp.clock_snapshot(sid).instance_id
    fresh = MemoryManager()
    await prepare_session(SimpleNamespace(memory=fresh, checkpoints=cp), sid)
    assert await fresh.get_history(sid) == original
    cp.close()


@pytest.mark.asyncio
async def test_actual_turn_lease_refuses_independent_request_while_source_turn_active(tmp_path):
    import asyncio
    from contextvars import Context

    from agents.core.memory.manager import MemoryManager
    from agents.core.orchestrator import Orchestrator
    from agents.core.session_continuation import ContinuationRefused, create_continuation

    orch = Orchestrator.__new__(Orchestrator)
    orch._session_id_default = "default"
    orch._turn_lease_max_wait = 0.01
    orch._turn_leases = {}
    orch.memory = MemoryManager()
    orch.checkpoints = manager(tmp_path / "cp.db")
    orch.checkpoints.create_session_record("source")
    async with orch.turn_lease("source") as acquired:
        assert acquired
        task = asyncio.create_task(
            create_continuation(orch, "source", "00000000-0000-4000-8000-000000000001"),
            context=Context(),
        )
        with pytest.raises(ContinuationRefused, match="source_busy"):
            await task
    assert (
        orch.checkpoints._conn.execute("SELECT count(*) FROM session_continuations").fetchone()[0]
        == 0
    )
    orch.checkpoints.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["../outside", "", "x/y", 17])
async def test_explicit_session_validation_rejects_before_orchestrator(invalid, monkeypatch):
    import httpx

    import agents.web as web

    monkeypatch.setattr(web, "orch", None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=web.app), base_url="http://localhost"
    ) as client:
        for path in ("/chat", "/chat/stream"):
            response = await client.post(path, json={"message": "hello", "session_id": invalid})
            assert response.status_code == 422


def test_existing_child_keeps_known_birth_after_root_deletion(tmp_path):
    from agents.core.session_continuation import ContinuationStore

    cp = manager(tmp_path / "cp.db")
    cp.create_session_record("source")
    original = cp.clock_snapshot("source")
    store = ContinuationStore(cp)
    child = store.create("source", "00000000-0000-4000-8000-000000000001", SEED, original)[
        "session_id"
    ]
    cp._conn.execute("DELETE FROM sessions WHERE id='source'")
    cp._conn.commit()
    assert cp.clock_snapshot(child).started_at == original.started_at
    assert store.seed(child) == SEED
    cp.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True, "process", "observe"])
@pytest.mark.parametrize("failure", ["corrupt", "generation"])
async def test_failed_startup_resume_blocks_default_turn(tmp_path, monkeypatch, stream, failure):
    from unittest.mock import AsyncMock

    from agents.core.config import JarvisConfig
    from agents.core.memory import persistence
    from agents.core.orchestrator import _SESSION_UNSET, Orchestrator, _active_session
    from agents.core.session_continuation import (
        CONTINUATION_REFUSED_REPLY,
        ContinuationRefused,
        ContinuationStore,
    )

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    orch = Orchestrator(JarvisConfig())
    cp = manager(tmp_path / "cp.db")
    cp.create_session_record("source")
    child = ContinuationStore(cp).create(
        "source", "00000000-0000-4000-8000-000000000001", SEED, cp.clock_snapshot("source")
    )["session_id"]
    path = tmp_path / f"{child}.json"
    path.write_text("{truncated")
    if failure == "generation":
        cp._conn.execute("UPDATE sessions SET instance_id='replacement' WHERE id=?", (child,))
        cp._conn.commit()
    cp.close()
    orch.checkpoints = manager(tmp_path / "cp.db")
    orch.memory.set_checkpoint_manager(orch.checkpoints)
    orch._session_id_default = child
    with pytest.raises(ContinuationRefused):
        await orch.memory.resume_session(child)
    # Startup retains the selected ID after catching resume failure. Exercise
    # actual ordinary dispatch without an explicit session parameter.
    if stream != "observe":
        orch.memory.add_turn = AsyncMock()
    orch._dispatch_command = AsyncMock(side_effect=AssertionError("dispatched after invalid resume"))
    token = _active_session.set(_SESSION_UNSET)
    try:
        if stream == "observe":
            with pytest.raises(ContinuationRefused):
                await orch._channel_turn("next", "telegram", observe_only=True)
        elif stream == "process":
            orch.agents = {"jarvis": object()}
            orch._recall_block = AsyncMock(return_value="")
            assert await orch.process("next") == ""
            orch._recall_block.assert_not_called()
        else:
            method = orch.handle_input_stream if stream else orch.handle_input
            assert await method("next", channel="web") == CONTINUATION_REFUSED_REPLY
    finally:
        _active_session.reset(token)
    if stream != "observe":
        orch.memory.add_turn.assert_not_called()
    orch._dispatch_command.assert_not_called()
    assert path.read_text() == "{truncated"
    orch.checkpoints.close()


@pytest.mark.asyncio
async def test_observe_only_hydrates_seed_before_appending(tmp_path, monkeypatch):
    from agents.core.config import JarvisConfig
    from agents.core.memory import persistence
    from agents.core.orchestrator import _SESSION_UNSET, Orchestrator, _active_session
    from agents.core.session_continuation import ContinuationStore

    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    orch = Orchestrator(JarvisConfig())
    cp = manager(tmp_path / "cp.db")
    cp.create_session_record("source")
    child = ContinuationStore(cp).create(
        "source", "00000000-0000-4000-8000-000000000001", SEED, cp.clock_snapshot("source")
    )["session_id"]
    orch.checkpoints = cp
    orch.memory.set_checkpoint_manager(cp)
    orch._session_id_default = child
    token = _active_session.set(_SESSION_UNSET)
    try:
        assert await orch._channel_turn("observed", "telegram", observe_only=True) is None
    finally:
        _active_session.reset(token)
    history = await orch.memory.get_history(child)
    assert history[0] == SEED[0] and history[1]["content"] == "observed"
    snapshot = persistence.load_memory_snapshot(child)
    assert snapshot["turns"] == history
    assert snapshot["instance_id"] == cp.clock_snapshot(child).instance_id
    cp.close()
