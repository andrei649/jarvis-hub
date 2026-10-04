"""
memory/manager.py — Memory manager integrating conversation memory,
vector store, agent contexts, structured session persistence, and
knowledge graph.
"""

import asyncio
import hashlib
import json
import logging
import os
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from ..action_origin import INBOUND_ACTION_ORIGIN, origin_for_channel
from ..security import taint
from . import persistence
from .conversation import ConversationMemory, UnverifiedRewind
from .graph import KnowledgeGraph, create_graph
from .seed_graph import seed_graph
from .store import InMemoryVectorStore, VectorStore

logger = logging.getLogger("jarvis.memory")


class RewindRefused(RuntimeError):
    """The prepared conversation tail no longer has the same durable authority."""


@dataclass(frozen=True)
class RollbackRewindTicket:
    nonce: str
    session_id: str
    instance_id: str
    clock: object
    revision: int
    snapshot_digest: str
    tail_digest: str
    cut_index: int
    removed_turns: int
    expected_missing: bool = False


@dataclass(frozen=True)
class RollbackRewindResult:
    removed_turns: int
    revision: int


def _turn_digest(turns: list[dict]) -> str:
    return hashlib.sha256(json.dumps(turns, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class MemoryManager:
    def __init__(self, graph_backend: str = None, vector_backend: str = None):
        if vector_backend is None:
            vector_backend = os.getenv("VECTOR_BACKEND", "memory")
        # /admin → memory.max_turns / memory.persist (were hardcoded 100 / True).
        from ..settings_db import get_value
        self.conversation = ConversationMemory(
            max_turns=int(get_value("memory", "max_turns", 100)),
            persist=bool(get_value("memory", "persist", True)),
        )
        if vector_backend == "qdrant":
            self.vectors = self._init_qdrant()
        else:
            self.vectors = InMemoryVectorStore(dimension=768)
        self.agent_contexts: dict[str, dict] = {}
        self.graph: KnowledgeGraph = create_graph(graph_backend)
        # Two locks (H428). ``_lock`` guards the conversation and agent contexts;
        # ``_store_lock`` serialises the vector store and the knowledge graph, whose
        # blocking I/O runs on worker threads. A recall search stuck on a slow Qdrant
        # or Neo4j therefore holds only the store lock: saving the reply, reading the
        # context and every other session's turn go on while it finishes.
        self._lock = asyncio.Lock()
        self._store_lock = asyncio.Lock()
        # Turn embeddings are written in the background, one at a time, oldest first
        # (Hermes' sync_all: "never inline" — a provider write may block for minutes).
        self._embed_tail: asyncio.Task | None = None
        self._embed_pending: set[asyncio.Task] = set()
        # Bumped by a purge: a queued turn embedding from before it is never stored.
        self._embed_generation = 0
        # The same, per session: bumped by a permanent session delete (H218).
        self._session_epochs: dict[str, int] = {}
        self._rollback_tickets: dict[str, RollbackRewindTicket] = {}
        self._rewind_inconsistent: set[str] = set()
        # Real-embeddings recall (lazy: no network/import until first use).
        self._embedder = None
        from agents.core.env_config import env_flag
        self.embed_turns = env_flag("MEMORY_EMBED_TURNS")
        # No-op on a public box (H23.30): seed_graph() self-gates on
        # NERVA_PUBLIC_PROFILE so the owner's personal facts stay private.
        seed_graph(self.graph)

    def _init_qdrant(self) -> VectorStore:
        from ..env_config import env_int
        from .qdrant_store import QdrantVectorStore

        url = os.getenv("QDRANT_URL", "http://localhost:6333")
        dimension = env_int("VECTOR_DIMENSION", 768, minimum=1)
        return QdrantVectorStore(url=url, dimension=dimension)

    def set_checkpoint_manager(self, mgr):
        self._checkpoint_mgr = mgr
        self.conversation._rewind_checkpoint_mgr = mgr
        # The orchestrator binds this manager before checkpoint.initialize(). A
        # rewind is verified only when its own session is addressed, so a bad
        # inactive snapshot cannot stop unrelated sessions from booting.

    def _verified_rewind_document(self, sid):
        cp = getattr(self, "_checkpoint_mgr", None)
        if cp is None or cp._conn is None:
            raise RewindRefused("conversation rewind head unavailable")
        from ..session_continuation import history_identity, rewind_head

        with cp._lock:
            try:
                instance, _legacy = history_identity(cp._conn, sid)
                head = rewind_head(cp._conn, sid)
            except Exception as exc:
                raise RewindRefused("conversation rewind head unavailable") from exc
            try:
                document, digest = persistence.read_snapshot_for_rewind(sid)
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                raise RewindRefused("conversation rewind snapshot unavailable") from exc
        if (head is None or head[0] != instance
                or document.get("instance_id") != instance
                or document.get("rewound") is not True
                or document.get("revision", 0) != head[1]
                or digest != head[2]):
            raise RewindRefused("conversation rewind head unverified")
        return document

    def _load_pending_rewind(self, sid, *, activate: bool = True):
        document = self._verified_rewind_document(sid)
        try:
            current = self.conversation.current_session_id
            self.conversation.restore_verified_rewind(sid, document)
            if not activate:
                self.conversation.current_session_id = current
        except (KeyError, ValueError, TypeError) as exc:
            raise RewindRefused("conversation rewind snapshot unavailable") from exc

    def _quarantine_rewind(self, sid):
        self._rewind_inconsistent.add(sid)
        self.conversation.sessions.pop(sid, None)
        self.conversation.pending_rewinds.add(sid)
        self.conversation.invalidate_active_images(sid)

    def _ensure_rewind_ready(self, sid, *, load: bool = True,
                             activate: bool = False):
        """Verify only the addressed session; an invalid one stays quarantined."""
        if sid in getattr(self, "_rewind_inconsistent", ()):
            raise RewindRefused("conversation rewind needs recovery")
        cp = getattr(self, "_checkpoint_mgr", None)
        if cp is None or cp._conn is None:
            if (sid in getattr(self.conversation, "pending_rewinds", ())
                    or sid in getattr(self.conversation, "rewound_sessions", ())):
                raise RewindRefused("conversation rewind head unavailable")
            return
        from ..session_continuation import rewind_head

        try:
            with cp._lock:
                head = rewind_head(cp._conn, sid)
        except Exception as exc:
            raise RewindRefused("conversation rewind head unavailable") from exc
        if head is None:
            if (sid in getattr(self.conversation, "pending_rewinds", ())
                    or sid in getattr(self.conversation, "rewound_sessions", ())):
                self._quarantine_rewind(sid)
                raise RewindRefused("conversation rewind head unavailable")
            return
        try:
            if sid in self.conversation.sessions:
                self._check_rewind_head_before_append(sid)
            elif load:
                self._load_pending_rewind(sid, activate=activate)
            else:
                self._verified_rewind_document(sid)
        except RewindRefused:
            self._quarantine_rewind(sid)
            raise

    async def new_session(self, session_id: str = None) -> str:
        async with self._lock:
            if session_id is not None:
                self._ensure_rewind_ready(session_id)
            sid = await self.conversation.new_session(session_id)
            if hasattr(self, '_checkpoint_mgr') and self._checkpoint_mgr:
                self._checkpoint_mgr.create_session_record(sid)
                self._bind_history_instance(sid)
            return sid

    async def resume_session(self, session_id: str) -> bool:
        async with self._lock:
            self._ensure_rewind_ready(session_id, activate=True)
            manager = getattr(self, "_checkpoint_mgr", None)
            if manager is not None and manager._conn is not None:
                from types import SimpleNamespace

                from ..session_continuation import ContinuationStore, _load_locked
                if ContinuationStore(manager).seed(session_id) is not None:
                    async with self.conversation._lock:
                        _load_locked(SimpleNamespace(memory=self, checkpoints=manager), session_id)
                        self.conversation.current_session_id = session_id
                        return True
            try:
                resumed = await self.conversation.resume_session(session_id)
            except UnverifiedRewind:
                try:
                    self._load_pending_rewind(session_id)
                except RewindRefused:
                    self._quarantine_rewind(session_id)
                    raise
                resumed = True
            if resumed and session_id in self.conversation.rewound_sessions:
                self._check_rewind_head_before_append(session_id)
            return resumed

    def _bind_history_instance(self, sid):
        manager = getattr(self, '_checkpoint_mgr', None)
        if manager is None or manager._conn is None:
            return
        from ..session_continuation import ContinuationRefused, history_identity
        try:
            with manager._lock:
                instance, legacy = history_identity(manager._conn, sid)
        except ContinuationRefused:
            return  # Existing ordinary session semantics remain; explicit continuation refuses.
        known = self.conversation.instances.get(sid)
        if known == instance or (known is None and (legacy or not self.conversation.sessions.get(sid))):
            self.conversation.instances[sid] = instance

    def _check_rewind_head_before_append(self, sid):
        """A resumed stale process cannot write over a durable rewind."""
        cp = getattr(self, "_checkpoint_mgr", None)
        if cp is None or cp._conn is None:
            return
        from ..session_continuation import rewind_head

        with cp._lock:
            head = rewind_head(cp._conn, sid)
        if head is None:
            if sid in self.conversation.rewound_sessions:
                raise RewindRefused("conversation rewind head unavailable")
            return
        rows = [turn.to_dict() for turn in self.conversation.sessions.get(sid, [])]
        try:
            document, digest = persistence.read_snapshot_for_rewind(sid)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RewindRefused("conversation rewind head unavailable") from exc
        if (self.conversation.instances.get(sid) != head[0]
                or document.get("instance_id") != head[0]
                or document.get("rewound") is not True
                or document.get("revision", 0) != self.conversation.revisions.get(sid, 0)
                or document["turns"] != rows
                or document.get("revision", 0) != head[1]
                or digest != head[2]):
            raise RewindRefused("conversation changed after rewind")

    async def add_turn(self, session_id: str, role: str, content: str, agent_id: str = None,
                       channel: str = None, tools: list[str] | None = None,
                       media: dict | None = None):
        async with self._lock:
            self._ensure_rewind_ready(session_id)
            manager = getattr(self, "_checkpoint_mgr", None)
            if manager is not None and manager._conn is not None:
                with manager._lock:
                    continued = manager._conn.execute(
                        "SELECT 1 FROM session_continuations WHERE session_id=?", (session_id,)
                    ).fetchone()
                if continued is not None:
                    from types import SimpleNamespace

                    from ..session_continuation import _load_locked
                    async with self.conversation._lock:
                        _load_locked(SimpleNamespace(memory=self, checkpoints=manager), session_id)
            self._bind_history_instance(session_id)
            self._check_rewind_head_before_append(session_id)
            try:
                if tools or media is not None:
                    await self.conversation.add_turn(session_id, role, content, agent_id,
                                                     **({"tools": tools} if tools else {}),
                                                     **({"media": media} if media is not None else {}))
                else:
                    await self.conversation.add_turn(session_id, role, content, agent_id)
            except persistence.RewindPersistenceError as exc:
                if exc.inconsistent:
                    self._quarantine_rewind(session_id)
                raise RewindRefused("conversation rewind append not persisted") from exc

            if hasattr(self, '_checkpoint_mgr') and self._checkpoint_mgr:
                turn_count = len(self.conversation.sessions.get(session_id, []))
                self._checkpoint_mgr.update_session(session_id, turn_count=turn_count)

        # Long-term recall: embed the turn into the vector store so it can be
        # retrieved later via fused recall. Opt-in (MEMORY_EMBED_TURNS) and never
        # allowed to break the turn — remember() degrades to a no-op on failure.
        if self.embed_turns and content and content.strip():
            metadata = {
                "role": role, "agent": agent_id, "session": session_id,
            }
            if channel:
                origin = origin_for_channel(channel)
                metadata.update({"channel": channel, "origin": origin})
                if role == "user" and origin == INBOUND_ACTION_ORIGIN:
                    metadata = taint.mark(metadata, source=f"inbound:{channel}")
            self._queue_turn_embedding(content, metadata)

    async def prepare_rollback_rewind(self, session_id: str, expected_instance_id: str,
                                      expected_clock) -> RollbackRewindTicket:
        """Pin the current last user exchange before an authorized file restore.

        The selected filesystem checkpoint may be older; it does not select a chat turn.
        The root-owned command must hold the session turn lease and intercept before
        appending the `/rollback` command itself.
        """
        from ..session_continuation import ContinuationStore, history_identity

        async with self._lock, self.conversation._lock:
            cp = getattr(self, "_checkpoint_mgr", None)
            if (cp is None or cp._conn is None or not self.conversation.persist
                    or session_id in self._rewind_inconsistent
                    or type(expected_instance_id) is not str or not expected_instance_id):
                raise RewindRefused("conversation rewind unavailable")
            self._ensure_rewind_ready(session_id)
            current_clock = cp.clock_snapshot(session_id)
            if (current_clock is None or current_clock != expected_clock
                    or current_clock.instance_id != expected_instance_id):
                raise RewindRefused("conversation clock changed")
            with cp._lock:
                try:
                    instance, _legacy = history_identity(cp._conn, session_id)
                except Exception as exc:
                    raise RewindRefused("conversation identity changed") from exc
            turns = self.conversation.sessions.get(session_id)
            if (instance != expected_instance_id or turns is None
                    or self.conversation.instances.get(session_id) != instance):
                raise RewindRefused("conversation instance changed")
            rows = [turn.to_dict() for turn in turns]
            cut = next((i for i in range(len(rows) - 1, -1, -1)
                        if rows[i].get("role") == "user"), None)
            if cut is None:
                raise RewindRefused("no current user exchange")
            expected_missing = False
            try:
                snapshot, digest = persistence.read_snapshot_for_rewind(session_id)
            except FileNotFoundError:
                # A new continuation may still live only in its immutable seed.
                # This is a read-only preparation; commit creates the first JSON head.
                seed = ContinuationStore(cp).seed(session_id)
                if seed is None or seed != rows:
                    raise RewindRefused("conversation snapshot unavailable") from None
                snapshot = {"session_id": session_id, "turns": seed,
                            "instance_id": instance, "revision": 0}
                digest = ""
                expected_missing = True
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                raise RewindRefused("conversation snapshot unavailable") from exc
            revision = self.conversation.revisions.get(session_id, 0)
            if (snapshot.get("instance_id") != instance or snapshot.get("revision", 0) != revision
                    or snapshot["turns"] != rows):
                raise RewindRefused("conversation snapshot changed")
            ticket = RollbackRewindTicket(
                secrets.token_urlsafe(24), session_id, instance, expected_clock,
                revision, digest, _turn_digest(rows), cut, len(rows) - cut,
                expected_missing,
            )
            self._rollback_tickets[ticket.nonce] = ticket
            return ticket

    async def discard_rollback_rewind(self, ticket: RollbackRewindTicket) -> bool:
        """Release an exact unused ticket without changing the conversation."""
        async with self._lock:
            if (type(ticket) is not RollbackRewindTicket
                    or self._rollback_tickets.get(ticket.nonce) is not ticket):
                return False
            del self._rollback_tickets[ticket.nonce]
            return True

    async def commit_rollback_rewind(self, ticket: RollbackRewindTicket) -> RollbackRewindResult:
        """Commit a prepared suffix only after the filesystem restore succeeded."""
        from ..session_continuation import history_identity, identity

        async with self._lock, self.conversation._lock:
            if (type(ticket) is not RollbackRewindTicket
                    or self._rollback_tickets.pop(ticket.nonce, None) is not ticket):
                raise RewindRefused("conversation rewind ticket unavailable")
            sid = ticket.session_id
            cp = getattr(self, "_checkpoint_mgr", None)
            turns = self.conversation.sessions.get(sid)
            if (cp is None or cp._conn is None or turns is None
                    or sid in self._rewind_inconsistent
                    or self.conversation.instances.get(sid) != ticket.instance_id
                    or self.conversation.revisions.get(sid, 0) != ticket.revision):
                raise RewindRefused("conversation changed before rewind")
            rows = [turn.to_dict() for turn in turns]
            if (_turn_digest(rows) != ticket.tail_digest or ticket.cut_index >= len(rows)
                    or rows[ticket.cut_index].get("role") != "user"):
                raise RewindRefused("conversation tail changed")
            prefix = rows[:ticket.cut_index]
            previous = None
            new_digest = None
            replaced = False
            with cp._lock, persistence.session_snapshot_lock(sid):
                try:
                    conn = cp._conn
                    conn.execute("BEGIN IMMEDIATE")
                    bound, _legacy = history_identity(conn, sid)
                    clock = conn.execute(
                        "SELECT birth_at,revision,rebuilt_at,instance_id FROM session_clock "
                        "WHERE session_id=?", (sid,),
                    ).fetchone()
                    if (bound != ticket.instance_id
                            or identity(conn, sid) != (
                                ticket.clock.started_at, ticket.clock.instance_id)
                            or clock is None or clock[1] != ticket.clock.revision
                            or clock[2] != ticket.clock.rebuilt_at.isoformat()
                            or clock[3] != ticket.instance_id):
                        raise RewindRefused("conversation clock changed")
                    previous, new_digest = persistence.replace_memory_if_current(
                        sid, instance_id=ticket.instance_id, revision=ticket.revision,
                        digest=ticket.snapshot_digest, turns=prefix, already_locked=True,
                        expected_missing=ticket.expected_missing,
                    )
                    replaced = True
                    conn.execute(
                        "INSERT INTO session_history_rewinds "
                        "(session_id,instance_id,revision,snapshot_sha256) VALUES(?,?,?,?) "
                        "ON CONFLICT(session_id) DO UPDATE SET instance_id=excluded.instance_id,"
                        "revision=excluded.revision,snapshot_sha256=excluded.snapshot_sha256",
                        (sid, ticket.instance_id, ticket.revision + 1, new_digest),
                    )
                    conn.execute("UPDATE sessions SET turn_count=? WHERE id=? AND instance_id=?",
                                 (len(prefix), sid, ticket.instance_id))
                    conn.commit()
                except Exception as exc:
                    conn.rollback()
                    if replaced and not persistence.restore_memory_if_current(
                            sid, digest=new_digest, previous=previous, already_locked=True):
                        self._rewind_inconsistent.add(sid)
                        raise RewindRefused("conversation rewind needs recovery") from exc
                    raise RewindRefused("conversation rewind not persisted") from exc
            self.conversation.sessions[sid] = turns[:ticket.cut_index]
            self.conversation.revisions[sid] = ticket.revision + 1
            self.conversation.rewound_sessions.add(sid)
            self.conversation._dirty.add(sid)
            self.conversation.invalidate_active_images(sid)
            # Cancel only queued session embeddings by epoch; no provider operation.
            self._session_epochs[sid] = self._session_epochs.get(sid, 0) + 1
            return RollbackRewindResult(ticket.removed_turns, ticket.revision + 1)

    _EMBED_BACKLOG_MAX = 256

    def _queue_turn_embedding(self, content: str, metadata: dict) -> None:
        """Embed and store one turn in the background, after every earlier one (H428).

        The turn never waits on the embedder or the vector store: a hung backend
        cannot stall the conversation, only delay long-term memory. Past the backlog
        cap a turn is not embedded, with a warning, instead of piling up.
        """
        if len(self._embed_pending) >= self._EMBED_BACKLOG_MAX:
            logger.warning("turn embedding skipped: %d earlier turns still waiting on the embedder",
                           len(self._embed_pending))
            return
        loop = asyncio.get_running_loop()
        previous = self._embed_tail
        if previous is not None and (previous.done() or previous.get_loop() is not loop):
            previous = None
        generation = self._embed_generation
        epoch = self._session_epochs.get(metadata.get("session"), 0)

        async def _write() -> None:
            if previous is not None:
                await asyncio.wait({previous})
            try:
                if self._embedding_stale(generation, metadata, epoch):
                    return
                vector = await self.embed(content)
                await self._store_remembered(content, vector, metadata=metadata, generation=generation,
                                             epoch=epoch)
            except Exception:
                logger.warning("turn embedding failed", exc_info=True)

        task = loop.create_task(_write())
        self._embed_tail = task
        self._embed_pending.add(task)
        task.add_done_callback(self._embed_pending.discard)

    async def flush_embeddings(self) -> None:
        """Wait for every queued turn embedding (tests, shutdown)."""
        loop = asyncio.get_running_loop()
        while pending := {task for task in self._embed_pending if task.get_loop() is loop}:
            await asyncio.wait(pending)

    def discard_pending_embeddings(self) -> None:
        """A purge: every turn embedding queued before now is dropped, not stored."""
        self._embed_generation += 1

    def _embedding_stale(self, generation: int | None, metadata: dict | None, epoch: int | None) -> bool:
        """A purge, or a delete of the turn's session, ran since the embedding was queued."""
        if generation is not None and generation != self._embed_generation:
            return True
        return epoch is not None and self._session_epochs.get((metadata or {}).get("session"), 0) != epoch

    async def forget_session_embeddings(self, session_id: str) -> int:
        """H218 — a permanent session delete: every stored turn embedding of the session
        leaves the vector store, and one still queued for it is never stored. How many were
        removed; raises when the store could not remove them."""
        self._session_epochs[session_id] = self._session_epochs.get(session_id, 0) + 1
        async with self._store_lock:
            return await asyncio.to_thread(self.vectors.remove_where, "session", session_id)

    async def get_context(self, session_id: str, last_n: int = 10) -> str:
        async with self._lock:
            self._ensure_rewind_ready(session_id)
            return await self.conversation.get_context(session_id, last_n)

    async def get_history(self, session_id: str, last_n: int = None) -> list[dict]:
        async with self._lock:
            self._ensure_rewind_ready(session_id)
            return await self.conversation.get_history(session_id, last_n)

    async def update_agent_context(self, agent_id: str, key: str, value):
        async with self._lock:
            if agent_id not in self.agent_contexts:
                self.agent_contexts[agent_id] = {}
            self.agent_contexts[agent_id][key] = value

    async def get_agent_context(self, agent_id: str) -> dict:
        async with self._lock:
            return self.agent_contexts.get(agent_id, {})

    def _get_embedder(self):
        """Lazily build the recall embedder (LM Studio by default; see
        Embedder.from_env). Built on first use so plain MemoryManager()
        construction stays import-light and offline.

        H7.4: Embedder.from_env() now provides a non-None cache_dir by default,
        so the embedder always has an active disk cache for recall queries."""
        if self._embedder is None:
            from ..ingestion.embedder import Embedder
            self._embedder = Embedder.from_env()
        return self._embedder

    async def embed(self, text: str) -> Optional[list[float]]:
        """Embed text for recall. Returns None for empty input or on failure
        (caller degrades to keyword/graph-only retrieval)."""
        if not text or not text.strip():
            return None
        try:
            return await asyncio.to_thread(self._get_embedder().embed, text)
        except Exception as e:  # never let embedding break a request
            logger.warning(f"embed failed: {e}")
            return None

    async def remember(self, text: str, record_id: str = None, metadata: dict = None) -> Optional[str]:
        """Embed `text` and store it in the vector store for later recall.
        Returns the record id, or None if it could not be embedded/stored.

        Like a turn embedding it carries the purge generation it started under
        (H428): a purge that runs while it is being embedded wins."""
        generation = self._embed_generation
        vec = await self.embed(text)
        return await self._store_remembered(text, vec, record_id=record_id, metadata=metadata,
                                            generation=generation)

    async def _store_remembered(self, text: str, vec: Optional[list[float]], *, record_id: str = None,
                                metadata: dict = None, generation: int | None = None,
                                epoch: int | None = None) -> Optional[str]:
        if vec is None:
            return None
        expected = getattr(self.vectors, "dimension", len(vec))
        if len(vec) != expected:
            logger.warning(f"embedding dim {len(vec)} != store dim {expected}; skipping store")
            return None
        rid = record_id or f"mem-{uuid.uuid4().hex[:12]}"
        meta = dict(metadata or {})
        meta.setdefault("text", text)
        meta.setdefault("created_at", time.time())  # CDX-7: real age provenance on later recall
        stored = await self.store_embedding(rid, vec, meta, generation=generation, epoch=epoch)
        return rid if stored else None

    async def recall(self, query_text: str, top_k: int = 10, keyword: str = None) -> list:
        """Fused recall (vector ⊕ graph) for a natural-language query. Embeds the
        query, then runs RRF fusion; falls back to keyword/graph if embedding fails."""
        embedding = await self.embed(query_text)
        return await self.hybrid_search(
            embedding=embedding,
            keyword=keyword if keyword is not None else query_text,
            top_k=top_k,
        )

    async def store_embedding(self, record_id: str, vector: list[float], metadata: dict = None, *,
                              generation: int | None = None, epoch: int | None = None) -> bool:
        # Offload to a thread: with a networked backend (Qdrant) vectors.add is a
        # blocking httpx call that would otherwise stall the whole event loop for
        # every embedded turn. The store lock serialises vector-store access.
        async with self._store_lock:
            # A queued turn embedding re-checks its generation under the lock, right
            # before the write: a purge (or a delete of its session) that ran while it
            # was being embedded wins.
            if self._embedding_stale(generation, metadata, epoch):
                return False
            await asyncio.to_thread(self.vectors.add, record_id, vector, metadata)
            if self._embedding_stale(generation, metadata, epoch):
                # A purge gave up waiting for this lock (a backend slower than its
                # bounded wait) and wiped while the write was still inside the store:
                # take the record back out. The lock is still held, so no search saw it.
                try:
                    await asyncio.to_thread(self.vectors.remove, record_id)
                except Exception:
                    logger.error("a write that landed after a purge could not be removed (%s)",
                                 record_id, exc_info=True)
                return False
            return True

    async def search_similar(self, query: list[float], k: int = 5) -> list[dict]:
        async with self._store_lock:
            return await asyncio.to_thread(self.vectors.search, query, k)

    async def hybrid_search(self, embedding: list[float] = None, keyword: str = None,
                            top_k: int = 10) -> list:
        """Fuse vector similarity + knowledge-graph hits via Reciprocal Rank
        Fusion (H5.14). Returns a ranked list of `fusion.FusedHit`."""
        from .fusion import HybridRetriever
        async with self._store_lock:
            retriever = HybridRetriever(
                self.vectors, self.graph,
                k=getattr(self, "fusion_k", 60),
                vector_weight=getattr(self, "fusion_vector_weight", 1.0),
                graph_weight=getattr(self, "fusion_graph_weight", 1.0),
            )
            # retrieve() drives blocking vector+graph I/O (Qdrant/Neo4j httpx);
            # run it off the event loop so a slow backend can't freeze all sessions.
            return await asyncio.to_thread(
                retriever.retrieve, embedding=embedding, keyword=keyword, top_k=top_k
            )

    async def clear(self, session_id: str = None):
        async with self._lock:
            if session_id:
                await self.conversation.clear(session_id)
            else:
                await self.conversation.clear()

    def _vector_count(self) -> Optional[int]:
        """Number of stored vectors, or None if the backend could not be reached.

        BLOCKING with a networked backend: `QdrantVectorStore.__len__` first calls
        `_ensure_collection()` (a GET, then possibly a PUT) and then POSTs
        `/points/count`, all on a synchronous httpx client. `_collection_ready` is
        only set on success, so while Qdrant is down it is re-probed on every call.

        None rather than 0 on failure: zero is a claim ("nothing is stored"), and
        the caller renders it as one.
        """
        try:
            return len(self.vectors)
        except Exception:
            logger.warning("vector store unreachable — reporting an unknown count",
                           exc_info=True)
            return None

    async def get_session_stats(self) -> dict:
        # Off the event loop AND outside the lock. This was a plain `len(self.vectors)`
        # inside `async with self._lock` — its three neighbours above all wrap the same
        # store in `asyncio.to_thread` with comments about exactly this hazard, and this
        # one was missed. With Qdrant unreachable it blocked the whole event loop for up
        # to three 10s httpx timeouts per call, so every other in-flight request —
        # including ones that touch no memory at all — appeared to hang. Holding the
        # lock across it would additionally queue every other memory operation behind a
        # dead backend.
        vectors = await asyncio.to_thread(self._vector_count)
        async with self._lock:
            return {
                "sessions": len(self.conversation.sessions),
                "current_session": self.conversation.current_session_id,
                "total_turns": sum(len(t) for t in self.conversation.sessions.values()),
                "vectors": vectors,
                "agent_contexts": list(self.agent_contexts.keys()),
            }

    async def add_fact(self, name: str, entity_type: str = None, properties: dict = None, source: str = None, relation: str = None, target: str = None) -> bool:
        """Add a fact to the knowledge graph. Supports entity or relation creation."""
        async with self._store_lock:
            if source and relation and target:
                ok = self.graph.add_relation(source, relation, target, properties)
            elif name and entity_type:
                ok = self.graph.add_entity(name, entity_type, properties)
            else:
                return False
            return ok

    async def query_facts(self, cypher: str, params: dict = None) -> list[dict]:
        """Run a Cypher query against the knowledge graph."""
        async with self._store_lock:
            return self.graph.query(cypher, params)

    async def get_entity_info(self, name: str) -> Optional[dict]:
        """Get entity info from the knowledge graph."""
        async with self._store_lock:
            entity = self.graph.get_entity(name)
            if entity:
                entity["relations"] = self.graph.get_relations(name)
            return entity
