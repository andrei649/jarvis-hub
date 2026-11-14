"""V64 retained text preview/export through real storage and the owner route."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from agents.core.checkpoint import CheckpointManager
from agents.core.memory import conversation, persistence
from agents.core.memory.manager import MemoryManager
from agents.core.orchestrator import Orchestrator


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setattr(persistence, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(conversation, "MEMORY_DIR", tmp_path)
    cp = CheckpointManager(str(tmp_path / "cp.db"))
    cp.initialize()
    memory = MemoryManager()
    memory.set_checkpoint_manager(cp)
    orch = Orchestrator.__new__(Orchestrator)
    orch.checkpoints, orch.memory = cp, memory
    orch._session_id_default = "existing-default"
    orch._turn_lease_max_wait = .01
    yield orch, tmp_path
    cp.close()


async def seed(orch, sid="chosen", text="chosen text"):
    orch.checkpoints.create_session_record(sid)
    await orch.memory.new_session(sid)
    await orch.memory.add_turn(sid, "user", text)
    await orch.memory.add_turn(sid, "assistant", "answer", agent_id="jarvis")
    return sid


def client(monkeypatch, orch):
    from fastapi.testclient import TestClient

    from agents import web
    from agents.core.routers import sessions
    monkeypatch.setattr(sessions, "get_orch", lambda: orch)
    monkeypatch.setenv("JARVIS_ADMIN_TOKEN", "owner-secret")
    monkeypatch.setenv("JARVIS_USER_TOKEN", "guest-secret")
    return TestClient(web.app, client=("192.0.2.10", 4000))


@pytest.mark.asyncio
async def test_preview_download_exact_session_redacted_read_only_and_owner_auth(host, monkeypatch):
    orch, root = host
    secret = "sk-" + "A" * 44
    await seed(orch, text=f"chosen {secret}")
    await seed(orch, "other", "never export other")
    orch.checkpoints.set_archived("chosen", True)
    before_files = {p.name: p.read_bytes() for p in root.glob("chosen.*")}
    before_row = tuple(orch.checkpoints._conn.execute("SELECT * FROM sessions WHERE id='chosen'").fetchone())
    active = orch.memory.conversation.current_session_id
    http = client(monkeypatch, orch)
    for headers in ({}, {"X-User-Token": "guest-secret"}):
        assert http.get("/sessions/chosen/transcript", headers=headers).status_code in (401, 403)
    preview = http.get("/sessions/chosen/transcript", headers={"X-Admin-Token": "owner-secret"})
    assert preview.status_code == 200
    body = preview.json()
    assert body == {"schema_version": 1, "session_id": "chosen", "scope": "retained_current_history",
                    "redacted": True, "turn_count": 2,
                    "turns": [{k: row[k] for k in ("role", "content", "agent_id", "timestamp")}
                              for row in body["turns"]]}
    assert body["turns"][0]["content"] == "chosen [REDACTED:openai_key]"
    assert secret not in preview.text and "never export other" not in preview.text
    download = http.get("/sessions/chosen/transcript?download=true", headers={"X-Admin-Token": "owner-secret"})
    assert download.content == preview.content
    assert download.headers["content-disposition"] == 'attachment; filename="session-chosen-transcript.json"'
    assert preview.headers["cache-control"] == download.headers["cache-control"] == "no-store"
    assert orch.session_id == "existing-default"
    assert orch.memory.conversation.current_session_id == active
    assert before_files == {p.name: p.read_bytes() for p in root.glob("chosen.*")}
    assert before_row == tuple(orch.checkpoints._conn.execute("SELECT * FROM sessions WHERE id='chosen'").fetchone())


@pytest.mark.asyncio
async def test_only_projected_text_no_system_tools_or_media(host):
    from agents.core.session_transcript import read_transcript
    orch, _ = host
    await seed(orch)
    await orch.memory.add_turn("chosen", "system", "hidden system")
    turn = orch.memory.conversation.sessions["chosen"][1]
    turn.tools = ["private_tool"]
    turn.media = {"kind": "image", "count": 1, "model": "private-image-model",
                  "backend": "local", "local": True}
    raw = await read_transcript(orch, "chosen")
    assert b"hidden system" not in raw and b"private_tool" not in raw
    assert b"private-image-model" not in raw
    assert all(set(row) == {"role", "content", "agent_id", "timestamp"} for row in json.loads(raw)["turns"])


@pytest.mark.asyncio
async def test_cold_snapshot_missing_corrupt_and_identity_refuse(host, monkeypatch):
    orch, root = host
    await seed(orch)
    orch.memory = MemoryManager()
    orch.memory.set_checkpoint_manager(orch.checkpoints)
    http = client(monkeypatch, orch)
    headers = {"X-Admin-Token": "owner-secret"}
    assert http.get("/sessions/chosen/transcript", headers=headers).status_code == 200
    assert http.get("/sessions/absent/transcript", headers=headers).status_code == 404
    orch.memory.conversation.sessions.clear()
    (root / "chosen.json").write_text("{broken")
    corrupt = http.get("/sessions/chosen/transcript", headers=headers)
    assert corrupt.status_code == 409 and corrupt.json()["error"] == "invalid_history"
    assert corrupt.headers["cache-control"] == "no-store"
    (root / "chosen.json").unlink()
    assert http.get("/sessions/chosen/transcript", headers=headers).status_code == 404


@pytest.mark.asyncio
async def test_busy_real_lease_refuses_without_history_read(host):
    from agents.core.session_continuation import ContinuationRefused
    from agents.core.session_transcript import read_transcript
    orch, _ = host
    await seed(orch)
    entered, release = asyncio.Event(), asyncio.Event()
    async def hold():
        async with orch.turn_lease("chosen") as acquired:
            assert acquired
            entered.set()
            await release.wait()
    task = asyncio.create_task(hold())
    await entered.wait()
    try:
        with pytest.raises(ContinuationRefused, match="source_busy"):
            await read_transcript(orch, "chosen")
    finally:
        release.set()
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["raises", "nonstring", "expands"])
async def test_redaction_failure_closed_and_final_bound(host, monkeypatch, failure):
    from agents.core import session_transcript as transcript
    orch, _ = host
    await seed(orch)
    def redact(self, text):
        if failure == "raises":
            raise RuntimeError("private exception")
        return None if failure == "nonstring" else "x" * transcript.MAX_TRANSCRIPT_BYTES
    monkeypatch.setattr(transcript, "SecretScanner", lambda: SimpleNamespace(redact=lambda text: redact(None, text)))
    response = client(monkeypatch, orch).get("/sessions/chosen/transcript", headers={"X-Admin-Token": "owner-secret"})
    assert response.status_code == (413 if failure == "expands" else 503)
    assert response.json() == {"error": "transcript_too_large" if failure == "expands" else "transcript_unavailable"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_projection_prebound_and_turn_limit_do_not_scan(host, monkeypatch):
    from agents.core import session_transcript as transcript
    from agents.core.session_continuation import ContinuationRefused
    orch, _ = host
    await seed(orch)
    def forbidden(*args):
        pytest.fail("oversize input reached redaction")
    monkeypatch.setattr(transcript, "SecretScanner", lambda: SimpleNamespace(redact=forbidden))
    monkeypatch.setattr(transcript, "MAX_TRANSCRIPT_BYTES", 100)
    with pytest.raises(ContinuationRefused, match="transcript_too_large"):
        await transcript.read_transcript(orch, "chosen")
    monkeypatch.setattr(transcript, "MAX_TRANSCRIPT_BYTES", 2 * 1024 * 1024)
    monkeypatch.setattr(transcript, "MAX_TRANSCRIPT_TURNS", 1)
    with pytest.raises(ContinuationRefused, match="transcript_too_large"):
        await transcript.read_transcript(orch, "chosen")


@pytest.mark.asyncio
async def test_identity_change_during_projection_fails_closed(host, monkeypatch):
    from agents.core import session_transcript as transcript
    from agents.core.session_continuation import ContinuationRefused
    orch, _ = host
    await seed(orch)
    def redact(self, text):
        orch.checkpoints._conn.execute("UPDATE sessions SET instance_id='replacement' WHERE id='chosen'")
        return text
    monkeypatch.setattr(transcript, "SecretScanner", lambda: SimpleNamespace(redact=lambda text: redact(None, text)))
    with pytest.raises(ContinuationRefused, match="history_identity_changed"):
        await transcript.read_transcript(orch, "chosen")


@pytest.mark.asyncio
async def test_rewind_export_uses_only_current_retained_head_after_restart(host):
    from agents.core.session_transcript import read_transcript
    orch, root = host
    await seed(orch)
    await orch.memory.add_turn("chosen", "user", "removed request")
    await orch.memory.add_turn("chosen", "assistant", "removed answer")
    clock = orch.checkpoints.clock_snapshot("chosen")
    ticket = await orch.memory.prepare_rollback_rewind("chosen", clock.instance_id, clock)
    await orch.memory.commit_rollback_rewind(ticket)
    before = (root / "chosen.json").read_bytes()
    orch.memory = MemoryManager()
    orch.memory.set_checkpoint_manager(orch.checkpoints)
    result = json.loads(await read_transcript(orch, "chosen"))
    assert [row["content"] for row in result["turns"]] == ["chosen text", "answer"]
    assert (root / "chosen.json").read_bytes() == before
    # A missing rewound snapshot cannot fall back to an earlier seed or append log.
    orch.memory = MemoryManager()
    orch.memory.set_checkpoint_manager(orch.checkpoints)
    (root / "chosen.json").unlink()
    from agents.core.session_continuation import ContinuationRefused
    with pytest.raises(ContinuationRefused, match="invalid_history"):
        await read_transcript(orch, "chosen")


@pytest.mark.asyncio
async def test_imported_seed_is_explicitly_addressed_and_never_copied_to_disk(host):
    from agents.core.session_import import import_turns
    from agents.core.session_transcript import read_transcript
    orch, root = host
    imported = import_turns(orch.checkpoints, source="codex", external_id="external",
        turns=[{"role": "user", "content": "imported request", "timestamp": "2026-11-13T10:00:00+00:00"}],
        request_id="00000000-0000-4000-8000-000000000064")
    sid = imported["session_id"]
    before = orch.checkpoints._conn.execute("SELECT seed_json FROM session_imports WHERE session_id=?", (sid,)).fetchone()[0]
    result = json.loads(await read_transcript(orch, sid))
    assert result["session_id"] == sid
    assert result["turns"][0]["content"] == "imported request"
    assert not (root / f"{sid}.json").exists()
    assert before == orch.checkpoints._conn.execute("SELECT seed_json FROM session_imports WHERE session_id=?", (sid,)).fetchone()[0]


@pytest.mark.asyncio
async def test_cancelled_projection_releases_real_lease_without_switch(host, monkeypatch):
    from agents.core import session_transcript as transcript
    orch, _ = host
    await seed(orch)
    await seed(orch, 'other')
    active = orch.memory.conversation.current_session_id
    entered = asyncio.Event()
    original = transcript.prepare_session

    async def blocked(*args):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(transcript, 'prepare_session', blocked)
    task = asyncio.create_task(transcript.read_transcript(orch, 'chosen'))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    monkeypatch.setattr(transcript, 'prepare_session', original)
    assert json.loads(await transcript.read_transcript(orch, 'chosen'))['turn_count'] == 2
    assert orch.memory.conversation.current_session_id == active
    assert orch.session_id == 'existing-default'


@pytest.mark.asyncio
async def test_unavailable_storage_is_opaque_and_uncached(host, monkeypatch):
    orch, _ = host
    await seed(orch)
    orch.checkpoints.close()
    response = client(monkeypatch, orch).get('/sessions/chosen/transcript',
                                           headers={'X-Admin-Token': 'owner-secret'})
    assert response.status_code == 503
    assert response.json() == {'error': 'continuation_unavailable'}
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.asyncio
async def test_cli_hubclient_through_asgi_reads_real_retained_storage(host, monkeypatch):
    import io
    from urllib.parse import urlsplit

    from agents.cli.client import HubClient
    from agents.cli.nerva import EXIT_OK, Context, main

    orch, root = host
    secret = 'sk-' + 'Z' * 44
    await seed(orch, text='kept ' + secret)
    await seed(orch, 'other', 'unselected text')
    http = client(monkeypatch, orch)
    calls = []

    def opener(request, **kwargs):
        calls.append((request.method, urlsplit(request.full_url).path))
        response = http.request(request.method, urlsplit(request.full_url).path,
                                headers=dict(request.header_items()))
        assert response.status_code == 200
        return io.BytesIO(response.content)

    hub = HubClient(admin_token='owner-secret', opener=opener)
    out, err = io.StringIO(), io.StringIO()
    ctx = Context(environ={}, out=out, err=err, inp=io.StringIO())
    monkeypatch.setattr(ctx, 'client', lambda: hub)
    active = orch.memory.conversation.current_session_id
    target = root / 'export.json'
    assert main(['sessions', 'transcript', 'chosen', '-o', str(target)], context=ctx) == EXIT_OK
    result = json.loads(target.read_bytes())
    assert result['turns'][0]['content'] == 'kept [REDACTED:openai_key]'
    assert secret not in target.read_text() and 'unselected text' not in target.read_text()
    assert not out.getvalue()
    assert calls == [('GET', '/sessions/chosen/transcript')]
    assert orch.memory.conversation.current_session_id == active
