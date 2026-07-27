"""AUD-2 — 'forget me' also erases the memory subsystem at rest.

Builds a data root with the memory stores (graph/entities/decay), an embedding
cache, conversation transcripts, AND non-memory files that must survive, then
exercises purge_data(memory=True). Asserts the memory PII is gone while config
JSON and the non-session journals are preserved, and that the live in-memory
stores are cleared first (so a running orchestrator can't re-persist them).
"""
import json
import sqlite3
from pathlib import Path

from agents.core import data_purge as dp


def _seed_memory_root(tmp_path) -> Path:
    root = tmp_path / "data"
    root.mkdir(parents=True, exist_ok=True)
    # Memory at rest (PII) — must be erased.
    (root / "bitemporal_kg.json").write_text('{"facts": [{"subject": "Alice"}]}', encoding="utf-8")
    (root / "entities.json").write_text('{"Alice": {"type": "person"}}', encoding="utf-8")
    (root / "decay.json").write_text('{"items": {"x": 1}}', encoding="utf-8")
    (root / "cognition").mkdir(parents=True, exist_ok=True)
    (root / "cognition" / "core_memory.json").write_text(
        '{"facts": ["Alice lives in Bucharest"]}',
        encoding="utf-8",
    )
    (root / "cognition" / "living_tiers.json").write_text(
        '{"items": {"turn:1": {"content": "Alice secret", "activation": 1.0}}}',
        encoding="utf-8",
    )
    (root / "house").mkdir(parents=True, exist_ok=True)
    (root / "house" / "private_graph.enc").write_text(
        '{"ciphertext": "private-house-pii"}', encoding="utf-8"
    )
    (root / "house" / "private_graph.cipher.salt").write_bytes(b"private-store-salt")
    (root / "embedding_cache" / "recall").mkdir(parents=True, exist_ok=True)
    (root / "embedding_cache" / "recall" / "v.json").write_text("[1,2,3]", encoding="utf-8")
    # Conversation transcripts (session-keyed) — must be erased.
    (root / "convo-1.jsonl").write_text('{"role": "user", "content": "secret"}\n', encoding="utf-8")
    (root / "convo-1.json").write_text('{"session_id": "convo-1", "turns": []}', encoding="utf-8")
    (root / "live-sess.jsonl").write_text('{"role": "user", "content": "hi"}\n', encoding="utf-8")
    (root / "live-sess.json").write_text('{"session_id": "live-sess", "turns": []}', encoding="utf-8")
    # Non-memory files — must SURVIVE the memory purge.
    (root / "canvas.json").write_text('{"elements": ["keep me"]}', encoding="utf-8")
    (root / "autonomy_journal.jsonl").write_text('{"event": "keep"}\n', encoding="utf-8")
    (root / "problems.jsonl").write_text('{"problem": "keep"}\n', encoding="utf-8")
    return root


def test_memory_at_rest_is_erased(tmp_path):
    root = _seed_memory_root(tmp_path)
    report = dp.purge_data(source_root=str(root), backup_first=False, memory=True,
                           session_ids=["live-sess"])
    mem = report["purged"]["memory"]
    # fixed memory stores + embedding cache gone
    assert not (root / "bitemporal_kg.json").exists()
    assert not (root / "entities.json").exists()
    assert not (root / "decay.json").exists()
    assert not (root / "cognition" / "core_memory.json").exists()
    assert not (root / "cognition" / "living_tiers.json").exists()
    assert not (root / "house" / "private_graph.enc").exists()
    assert not (root / "house" / "private_graph.cipher.salt").exists()
    assert not (root / "embedding_cache").exists()
    assert set(mem["files"]) == {
        "bitemporal_kg.json",
        "entities.json",
        "decay.json",
        "cognition/core_memory.json",
        "cognition/living_tiers.json",
        "house/private_graph.enc",
        "house/private_graph.cipher.salt",
    }
    assert mem["dirs"] == ["embedding_cache"]
    # conversation transcripts gone (both the glob-discovered and the live one)
    assert not (root / "convo-1.jsonl").exists()
    assert not (root / "convo-1.json").exists()
    assert not (root / "live-sess.jsonl").exists()
    assert not (root / "live-sess.json").exists()
    assert set(mem["sessions"]) == {"convo-1", "live-sess"}


def test_non_memory_files_survive(tmp_path):
    root = _seed_memory_root(tmp_path)
    dp.purge_data(source_root=str(root), backup_first=False, memory=True)
    # the non-session journals are NOT user memory → untouched
    assert (root / "autonomy_journal.jsonl").exists()
    assert (root / "problems.jsonl").exists()


def test_forget_me_resets_canvas(tmp_path):
    """Saved assistant replies (Canvas artifacts) are user content: a forget must
    reset canvas.json, and the post-purge file must load as an EMPTY CanvasStore."""
    from agents.core.canvas import CanvasStore

    root = _seed_memory_root(tmp_path)
    report = dp.purge_data(source_root=str(root), backup_first=False)  # base purge
    assert "canvas.json" in report["purged"]
    assert (root / "canvas.json").exists()          # reset, not unlinked (live handles)
    assert CanvasStore(path=str(root / "canvas.json")).list() == []


def test_memory_flag_off_leaves_memory_intact(tmp_path):
    root = _seed_memory_root(tmp_path)
    report = dp.purge_data(source_root=str(root), backup_first=False)  # memory=False default
    assert "memory" not in report["purged"]
    assert (root / "entities.json").exists()
    assert (root / "convo-1.jsonl").exists()


# ── clear_live_memory orchestration ────────────────────────────────
class _Spy:
    def __init__(self):
        self.cleared = False

    def clear(self):
        self.cleared = True


class _FakeConv:
    def __init__(self):
        self.sessions = {"s1": [], "s2": []}


class _FakeMem:
    def __init__(self):
        self.conversation = _FakeConv()
        self.graph = _Spy()
        self.vectors = _Spy()
        self.cleared = False

    async def clear(self, session_id=None):
        self.cleared = True


class _CanvasSpy:
    def __init__(self):
        self.memory_cleared = False
        self.persisting_clear_called = False

    def clear_memory(self):
        self.memory_cleared = True

    def clear(self, agent=None, *, keep_pinned=True):
        # must NOT be used by the forget flow: it persists canvas.json before
        # the pre-forget backup, dropping artifacts from the recovery archive
        self.persisting_clear_called = True
        return 1


class _FakeOrch:
    def __init__(self, cognition=None):
        self.memory = _FakeMem()
        self.entities = _Spy()
        self.decay = _Spy()
        self.canvas = _CanvasSpy()
        self.cognition = cognition


class _FakeCognition:
    def __init__(self, living_memory):
        self._living_memory = living_memory

    def module(self, name):
        return self._living_memory if name == "memory" else None


async def test_clear_live_memory_clears_all_stores():
    from agents.core.cognition.memory import LivingMemory

    living = LivingMemory()
    living.core.put("Alice lives in Bucharest")
    living.encode("turn:1", {"summary": "Alice secret"}, surprise=1.0)
    orch = _FakeOrch(cognition=_FakeCognition(living))
    cleared, failed = await dp.clear_live_memory(orch)
    assert failed == [], f"a store failed to clear: {failed}"
    assert orch.memory.cleared is True
    assert orch.memory.graph.cleared is True
    assert orch.memory.vectors.cleared is True
    assert orch.entities.cleared is True
    assert orch.decay.cleared is True
    assert living.core.list() == []
    assert living.records() == []
    # the live canvas store is cleared too (in-memory only — the persisting
    # clear would empty canvas.json before the pre-forget backup captures it),
    # so a running orchestrator can't re-save forgotten replies
    assert orch.canvas.memory_cleared is True
    assert orch.canvas.persisting_clear_called is False
    assert set(cleared) == {
        "conversation",
        "graph",
        "vectors",
        "entities",
        "decay",
        "canvas",
        "cognition_memory",
    }


async def test_clear_live_memory_is_defensive_on_missing_stores():
    class _Bare:
        pass
    # No memory/entities/decay attributes at all → no crash, nothing cleared, nothing failed.
    assert await dp.clear_live_memory(_Bare()) == ([], [])


# ── AUDIT-2: the wipe is a real contract, and a failed one is reported ──────
def test_clear_is_abstract_on_both_base_classes():
    """A missing implementation must be an import error, not a silent no-op.

    The whole finding: clear_live_memory called store.clear() behind `hasattr`, and NO
    implementation defined it — so under the documented qdrant/neo4j backends the wipe
    was unreachable, failed silently, and the purge still reported ok.
    """
    from agents.core.memory.graph import KnowledgeGraph
    from agents.core.memory.store import VectorStore

    assert "clear" in VectorStore.__abstractmethods__
    assert "clear" in KnowledgeGraph.__abstractmethods__


def test_every_shipped_store_and_graph_implements_clear():
    from agents.core.memory.graph import InMemoryGraph, Neo4jGraph
    from agents.core.memory.qdrant_store import QdrantVectorStore
    from agents.core.memory.store import InMemoryVectorStore

    for cls in (InMemoryVectorStore, QdrantVectorStore, InMemoryGraph, Neo4jGraph):
        assert callable(getattr(cls, "clear", None)), f"{cls.__name__} has no clear()"
        assert not getattr(cls, "__abstractmethods__", frozenset()), (
            f"{cls.__name__} is still abstract — it cannot be instantiated as a store"
        )


def test_in_memory_stores_actually_empty_on_clear():
    from agents.core.memory.graph import InMemoryGraph
    from agents.core.memory.store import InMemoryVectorStore

    store = InMemoryVectorStore(dimension=3)
    store.add("a", [1.0, 0.0, 0.0], {"text": "secret"})
    store.add("b", [0.0, 1.0, 0.0], {"text": "also secret"})
    assert len(store) == 2
    store.clear()
    assert len(store) == 0
    assert store.search([1.0, 0.0, 0.0], k=5) == []
    # and the id index went with it, so a re-add cannot resurrect a stale offset
    store.add("c", [0.0, 0.0, 1.0])
    assert len(store) == 1

    graph = InMemoryGraph()
    graph.add_entity("Alice", "Person")
    graph.add_relation("Alice", "LIVES_IN", "Bucharest")
    graph.clear()
    assert graph.list_entities() == []
    assert graph.get_relations("Alice") == []


async def test_a_failed_wipe_reaches_the_caller_instead_of_the_log():
    """The F5 shape: the API said ok:true while the data was still there."""
    import agents.core.data_purge as dp

    class _Boom:
        def clear(self):
            raise RuntimeError("Qdrant at http://127.0.0.1:6333 is unreachable")

    class _Mem:
        graph = _Boom()
        vectors = _Boom()

        async def clear(self):
            return None

    class _Orch:
        memory = _Mem()

    cleared, failed = await dp.clear_live_memory(_Orch())
    assert cleared == ["conversation"]
    assert len(failed) == 2, f"a failed wipe was swallowed: {failed}"
    assert all("unreachable" in f for f in failed)
    assert any(f.startswith("graph:") for f in failed)
    assert any(f.startswith("vectors:") for f in failed)


async def test_forget_route_reports_what_it_could_not_erase(monkeypatch):
    """ok must describe the WHOLE forget, not just the file half."""
    from agents.core.routers import backup as backup_router

    async def _clear(_orch):
        return (["conversation"], ["vectors: Qdrant unreachable"])

    def _purge(**_kw):
        return {"ok": True, "backup": None, "purged": {}, "total_rows": 0}

    monkeypatch.setattr(backup_router._purge, "clear_live_memory", _clear)
    monkeypatch.setattr(backup_router._purge, "purge_data", _purge)
    monkeypatch.setattr(backup_router._purge, "purge_contract_denial", lambda **_k: None)
    monkeypatch.setattr(backup_router, "get_orch", lambda: object())

    class _Req:
        async def json(self):
            return {"confirm": "FORGET"}

    resp = await backup_router.forget_data(_Req())
    body = json.loads(resp.body)
    assert body["ok"] is False, (
        "the forget reported success while a store still held the user's data — this is "
        "the F5 case (a claimed completed action that did not complete) on the one "
        "operation the user cannot verify for themselves"
    )
    assert body["not_erased"] == ["vectors: Qdrant unreachable"]
    assert "NOT ERASED" in body["warning"]


# ── AUDIT-2: the twelve stores that used to survive a forget ───────────────
_SURVIVORS = {
    # the audit's list, each seeded with a recognisable marker
    "run_history.json": '{"agent": [{"input_preview": "MARKER-run", "output_preview": "MARKER-out"}]}',
    "channel_inbox.json": '{"t1": {"messages": [{"body": "MARKER-inbox full message body"}]}}',
    "intent_log.json": '{"entries": ["MARKER-intent"]}',
    "passive_capture.json": '{"seen": ["MARKER-capture"]}',
    "rooms.json": '{"kitchen": {"note": "MARKER-room"}}',
    "review_queue.json": '{"items": [{"text_preview": "MARKER-review"}]}',
    "data_spaces.json": '{"space": {"docs": ["MARKER-space"]}}',
    "arena.json": '{"runs": ["MARKER-arena"]}',
    "autonomy_journal.jsonl": '{"note": "MARKER-journal"}\n',
    "problems.jsonl": '{"problem": "MARKER-problem"}\n',
}
_SURVIVOR_DBS = ("feedback.db", "notes.db", "checkpoints.db")


def _seed_survivors(root: Path) -> None:
    for name, content in _SURVIVORS.items():
        (root / name).write_text(content, encoding="utf-8")
    for name in _SURVIVOR_DBS:
        conn = sqlite3.connect(str(root / name))
        try:
            conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, body TEXT)")
            conn.execute("INSERT INTO items (body) VALUES (?)", (f"MARKER-{name}",))
            conn.commit()
        finally:
            conn.close()


def _surviving_markers(root: Path) -> list[str]:
    """Every file under root still containing a MARKER, by name."""
    hits = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        try:
            blob = p.read_bytes()
        except OSError:
            continue
        if b"MARKER-" in blob:
            hits.append(p.relative_to(root).as_posix())
    return hits


def test_forget_erases_the_stores_the_allowlist_used_to_miss(tmp_path):
    """The AUDIT-2 finding, as an end-to-end measurement rather than a code reading.

    docs/PRIVACY.md promises forget "erases memory, transcripts, vectors, and the
    knowledge graph at rest". Under the old PURGE_* allowlists, twelve user-content
    stores were simply not named in any of them and survived every forget — including
    per-agent input/output previews and full inbound message bodies from other people.
    Two were also on NON_SESSION_STEMS, so the transcript pass refused to treat them as
    sessions and nothing deleted them ever.
    """
    root = tmp_path / "data"
    root.mkdir()
    _seed_survivors(root)
    assert len(_surviving_markers(root)) == len(_SURVIVORS) + len(_SURVIVOR_DBS)

    dp.purge_data(source_root=str(root), backup_first=False, memory=True)

    left = _surviving_markers(root)
    assert left == [], f"a forget left the user's content behind in: {left}"


def test_forget_keeps_exactly_what_the_keep_list_names(tmp_path):
    """The inversion must not erase config, credentials or the audit chain."""
    root = tmp_path / "data"
    (root / "security").mkdir(parents=True)
    (root / "backups").mkdir()
    (root / "security" / "audit.db").write_text("KEEP-audit", encoding="utf-8")
    (root / "backups" / "pre-forget.tar.gz").write_text("KEEP-archive", encoding="utf-8")
    (root / "marketplace.db").write_text("KEEP-marketplace", encoding="utf-8")
    conn = sqlite3.connect(str(root / "settings.db"))
    try:
        conn.execute("CREATE TABLE settings (k TEXT, v TEXT)")
        conn.execute("INSERT INTO settings VALUES ('token', 'KEEP-secret')")
        conn.commit()
    finally:
        conn.close()
    _seed_survivors(root)

    dp.purge_data(source_root=str(root), backup_first=False, memory=True)

    assert _surviving_markers(root) == []                      # user content gone
    assert (root / "security" / "audit.db").read_text() == "KEEP-audit"
    assert (root / "backups" / "pre-forget.tar.gz").read_text() == "KEEP-archive"
    assert (root / "marketplace.db").read_text() == "KEEP-marketplace"
    conn = sqlite3.connect(str(root / "settings.db"))
    try:
        assert conn.execute("SELECT v FROM settings").fetchone()[0] == "KEEP-secret"
    finally:
        conn.close()


def test_a_store_nobody_thought_of_is_forgotten_by_default(tmp_path):
    """The property the inversion buys, stated directly.

    Under the allowlist, a store added next week is retained until someone remembers to
    extend a tuple. Under KEEP, it is erased unless someone deliberately exempts it — so
    the failure mode of forgetting flips from "silently keeps personal data" to "erases
    something we meant to keep", which is loud and recoverable from the pre-forget archive.
    """
    root = tmp_path / "data"
    root.mkdir()
    (root / "a_store_invented_after_this_test.json").write_text(
        '{"private": "MARKER-future"}', encoding="utf-8")
    (root / "nested" / "deeper").mkdir(parents=True)
    (root / "nested" / "deeper" / "notes.jsonl").write_text(
        '{"body": "MARKER-nested"}\n', encoding="utf-8")

    dp.purge_data(source_root=str(root), backup_first=False, memory=True)

    assert _surviving_markers(root) == []


def test_json_stores_keep_their_container_type(tmp_path):
    """Resetting a list-shaped store to {} turns a forget into a crash on next boot."""
    root = tmp_path / "data"
    root.mkdir()
    (root / "listy.json").write_text('[{"body": "MARKER-list"}]', encoding="utf-8")
    (root / "dicty.json").write_text('{"k": "MARKER-dict"}', encoding="utf-8")

    dp.purge_data(source_root=str(root), backup_first=False, memory=True)

    assert json.loads((root / "listy.json").read_text()) == []
    assert json.loads((root / "dicty.json").read_text()) == {}


# ── AUDIT-2c: the pre-forget archive ───────────────────────────────
def test_pre_forget_archive_lands_outside_the_purged_root(tmp_path, monkeypatch):
    """A forget must not leave a full copy inside the folder it just cleaned.

    The old default put it in <data_root>/backups, so a forget CONCENTRATED what was
    scattered across the root into one grab-and-go file and left it in place. The
    adversarial audit recovered every planted marker from it, including a settings.db
    token.
    """
    from agents.core import backup as _backup

    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.delenv("JARVIS_FORGET_ARCHIVE_DIR", raising=False)
    monkeypatch.setenv("JARVIS_KEY_DIR", str(tmp_path / "keys"))
    _seed_survivors(root)

    report = dp.purge_data(source_root=str(root), backup_first=True, memory=True)

    archive = Path(report["backup"]["archive"])
    assert archive.exists()
    assert root not in archive.parents and archive.parent != root, (
        f"the pre-forget archive is inside the purged root: {archive}"
    )
    assert archive.parent == _backup.pre_forget_dir(root)
    # and nothing archive-shaped was left behind inside the data root
    assert list(root.rglob("*.tar.gz")) == []
    assert list(root.rglob("*.tar.gz.enc")) == []


def test_pre_forget_archive_is_encrypted_even_with_no_key_configured(tmp_path, monkeypatch):
    """Unconditional, because this archive is the most concentrated copy that will exist."""
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.delenv("JARVIS_BACKUP_KEY", raising=False)
    monkeypatch.delenv("JARVIS_FORGET_ARCHIVE_DIR", raising=False)
    monkeypatch.setenv("JARVIS_KEY_DIR", str(tmp_path / "keys"))
    (root / "notes.json").write_text('{"body": "MARKER-notes"}', encoding="utf-8")

    report = dp.purge_data(source_root=str(root), backup_first=True, memory=True)

    archive = Path(report["backup"]["archive"])
    assert archive.name.endswith(".enc"), f"pre-forget archive is plaintext: {archive.name}"
    assert report["backup"]["encrypted"] is True
    assert b"MARKER-notes" not in archive.read_bytes(), (
        "the marker is readable in the archive bytes — it is not actually encrypted"
    )
    # the key lives outside the archive, so a stolen archive does not ship its own key
    assert (tmp_path / "keys").is_dir()


def test_pre_forget_archives_are_pruned(tmp_path, monkeypatch):
    """Retaining N full copies of data the owner asked to delete is not a safety net."""
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.delenv("JARVIS_FORGET_ARCHIVE_DIR", raising=False)
    monkeypatch.setenv("JARVIS_KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.setenv("JARVIS_FORGET_ARCHIVE_KEEP", "1")

    from agents.core import backup as _backup

    for i in range(3):
        (root / "notes.json").write_text(f'{{"n": {i}}}', encoding="utf-8")
        dp.purge_data(source_root=str(root), backup_first=True, memory=True)

    kept = list(_backup.pre_forget_dir(root).glob("*.tar.gz.enc"))
    assert len(kept) == 1, f"pre-forget archives accumulate unbounded: {len(kept)}"


async def test_forget_route_backup_first_is_settable(monkeypatch):
    from agents.core.routers import backup as backup_router

    seen = {}

    async def _clear(_orch):
        return ([], [])

    def _purge(**kw):
        seen.update(kw)
        return {"ok": True, "backup": None, "purged": {}, "total_rows": 0}

    monkeypatch.setattr(backup_router._purge, "clear_live_memory", _clear)
    monkeypatch.setattr(backup_router._purge, "purge_data", _purge)
    monkeypatch.setattr(backup_router._purge, "purge_contract_denial", lambda **_k: None)
    monkeypatch.setattr(backup_router, "get_orch", lambda: None)

    class _Req:
        def __init__(self, body):
            self._body = body

        async def json(self):
            return self._body

    # default stays backup-first — an accidental forget with no way back is worse
    await backup_router.forget_data(_Req({"confirm": "FORGET"}))
    assert seen["backup_first"] is True

    await backup_router.forget_data(_Req({"confirm": "FORGET", "backup_first": False}))
    assert seen["backup_first"] is False, (
        "the route still hardcodes backup_first — a user who wants deletion cannot get "
        "deletion through the product"
    )

    resp = await backup_router.forget_data(_Req({"confirm": "FORGET", "backup_first": "no"}))
    assert resp.status_code == 400
