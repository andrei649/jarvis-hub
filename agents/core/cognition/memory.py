"""
memory.py — H21.3 Living, unlimited memory (cognition algorithm layer).

Greenfield cognitive-memory mechanisms over H14 (decay/bitemporal/consolidation).
Principles:

  * **Nothing is ever auto-deleted.** Forgetting = demotion across hot/warm/cold
    tiers + reduced activation; only the user explicitly forgets.
  * **Selective encoding** — a predictive-coding *surprise gate* + a 3-vector
    **neuromodulator** salience (DA/NE/ACh) decide what (and how strongly) to
    encode; pattern-separation keeps near-duplicates distinct on write,
    pattern-completion fills from a partial cue on read.
  * **Stays valuable over time** — **re-projection** re-embeds old records onto a
    better model (``embed_version``); a small **core** memory is always injected.
  * **TCM re-rank** nudges fused results by temporal context *after* fusion (it
    never touches the RRF stage).
  * Consolidation runs in two nightly phases (**NREM** stabilize/maintain, **REM**
    recombine).

Pure and offline-testable, gated behind ``cognition.memory_enabled``. Wiring into
the live MemoryManager / recall fusion / DailyReflector is the integration seam.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Callable, Optional

from agents.core.persistence import JsonStore

HOT, WARM, COLD = "hot", "warm", "cold"
logger = logging.getLogger("jarvis.cognition.memory")


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ── neuromodulators + encoding gate (predictive coding) ──────────────────────

def neuromodulators(reward: float = 0.0, surprise: float = 0.0, novelty: float = 0.0) -> dict:
    """3-vector salience: DA=reward/motivation, NE=surprise/arousal, ACh=novelty/attention."""
    return {"DA": round(_clamp01(reward), 3), "NE": round(_clamp01(surprise), 3),
            "ACh": round(_clamp01(novelty), 3)}


def salience(nm: dict) -> float:
    return round((nm["DA"] + nm["NE"] + nm["ACh"]) / 3, 3)


def surprise_score(observed, predicted) -> float:
    """Prediction error in [0,1]. Token-Jaccard for text; cosine-dist for vectors."""
    if isinstance(observed, (list, tuple)) and isinstance(predicted, (list, tuple)):
        a, b = list(observed), list(predicted)
        n = min(len(a), len(b))
        if n == 0:
            return 1.0
        dot = sum(a[i] * b[i] for i in range(n))
        na = math.sqrt(sum(x * x for x in a[:n])) or 1e-9
        nb = math.sqrt(sum(x * x for x in b[:n])) or 1e-9
        return round(_clamp01(1.0 - dot / (na * nb)), 3)
    sa = set(str(observed).lower().split())
    sb = set(str(predicted).lower().split())
    if not sa and not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb) or 1
    return round(1.0 - inter / union, 3)


def encoding_gate(surprise: float, threshold: float = 0.3) -> bool:
    """Predictive-coding gate: only surprising-enough observations are encoded."""
    return surprise >= threshold


def encoding_strength(surprise: float, nm: Optional[dict] = None) -> float:
    base = _clamp01(surprise)
    if nm:
        base = _clamp01(base + 0.3 * salience(nm))
    return round(base, 3)


# ── pattern separation (write) / completion (read) ───────────────────────────

def pattern_separate(vector: "list[float]", neighbors: "list[list[float]]",
                     strength: float = 0.1) -> "list[float]":
    """Nudge `vector` away from near neighbors so similar memories stay distinct."""
    if not neighbors:
        return list(vector)
    out = list(vector)
    for nb in neighbors:
        for i in range(min(len(out), len(nb))):
            out[i] += strength * (out[i] - nb[i])
    return [round(x, 6) for x in out]


def pattern_complete(cue: "list[float]", memories: "list[dict]") -> Optional[dict]:
    """Return the stored memory whose vector is closest to a partial `cue`."""
    best, best_d = None, float("inf")
    for m in memories or []:
        v = m.get("vector") or []
        n = min(len(cue), len(v))
        d = sum((cue[i] - v[i]) ** 2 for i in range(n)) + abs(len(cue) - len(v))
        if d < best_d:
            best, best_d = m, d
    return best


# ── temporal-context re-rank (post-fusion; does NOT touch RRF) ───────────────

def tcm_rerank(results: "list[dict]", context_ts: Optional[float] = None,
               half_life: float = 86_400.0, weight: float = 0.3) -> "list[dict]":
    """Re-rank fused results by temporal proximity to `context_ts` (recency-of-context)."""
    if context_ts is None:
        context_ts = time.time()
    ranked = []
    for r in results or []:
        base = float(r.get("score", 0.0))
        dt = abs(context_ts - float(r.get("ts", context_ts)))
        boost = math.exp(-dt / max(1.0, half_life))
        ranked.append({**r, "tcm_score": round(base + weight * boost, 4)})
    return sorted(ranked, key=lambda x: x["tcm_score"], reverse=True)


# ── tiered store: demote across tiers, NEVER auto-delete ─────────────────────

def tier_for(activation: float, hot: float = 0.5, warm: float = 0.2) -> str:
    return HOT if activation >= hot else (WARM if activation >= warm else COLD)


class TieredMemory(JsonStore):
    """Hot/warm/cold tiering by activation. Maintenance demotes; only the user deletes."""

    def __init__(self, decay: float = 0.5, path: str | Path | None = None) -> None:
        self.decay = decay
        super().__init__(path)

    def _serialize(self):
        return {"items": self._items}

    def _deserialize(self, raw) -> None:
        items = raw.get("items", {}) if isinstance(raw, dict) else {}
        self._items = {}
        if not isinstance(items, dict):
            return
        for key, value in items.items():
            if isinstance(value, dict):
                rec = dict(value)
                rec["id"] = str(rec.get("id") or key)
                rec["activation"] = round(float(rec.get("activation", 0.0) or 0.0), 3)
                rec["tier"] = rec.get("tier") or tier_for(rec["activation"])
                rec["accesses"] = int(rec.get("accesses", 0) or 0)
                rec["ts"] = float(rec.get("ts", 0.0) or 0.0)
                rec["embed_version"] = int(rec.get("embed_version", 1) or 1)
                self._items[str(key)] = rec

    def add(self, mem_id: str, content, activation: float = 1.0, embed_version: int = 1) -> dict:
        rec = {"id": mem_id, "content": content, "activation": round(activation, 3),
               "tier": tier_for(activation), "accesses": 0,
               "ts": time.time(), "embed_version": embed_version}
        with self._lock:
            self._items[mem_id] = rec
            self._save()
        return dict(rec)

    def access(self, mem_id: str) -> Optional[dict]:
        with self._lock:
            r = self._items.get(mem_id)
            if r is None:
                return None
            r["accesses"] += 1
            r["activation"] = round(min(1.0, r["activation"] + 0.2), 3)   # reactivate
            r["tier"] = tier_for(r["activation"])
            self._save()
            return dict(r)

    def maintain(self) -> dict:
        """Decay activation and re-tier. NEVER deletes — cold is the floor."""
        demoted = 0
        with self._lock:
            for r in self._items.values():
                r["activation"] = round(r["activation"] * self.decay, 3)
                new_tier = tier_for(r["activation"])
                if new_tier != r["tier"]:
                    demoted += 1
                r["tier"] = new_tier
            self._save()
            return {"demoted": demoted, "total": len(self._items)}

    def forget(self, mem_id: str) -> bool:
        """The ONLY deletion path — an explicit user action."""
        with self._lock:
            deleted = self._items.pop(mem_id, None) is not None
            if deleted:
                self._save()
            return deleted

    def clear(self) -> int:
        """Explicit user-forget path: remove all tiered records and persist empty state."""
        with self._lock:
            count = len(self._items)
            self._items = {}
            self._save()
            return count

    def by_tier(self) -> dict:
        out = {HOT: 0, WARM: 0, COLD: 0}
        with self._lock:
            for r in self._items.values():
                out[r["tier"]] += 1
        return out

    def get(self, mem_id: str) -> Optional[dict]:
        with self._lock:
            r = self._items.get(mem_id)
            return dict(r) if r else None

    def records(self, prefix: str = "", limit: int = 50) -> list[dict]:
        with self._lock:
            keys = sorted(self._items.keys())
            if prefix:
                keys = [k for k in keys if k.startswith(prefix)]
            return [dict(self._items[k]) for k in keys[:max(1, limit)]]

    def update_records(self, records: "list[dict]") -> int:
        """Persist updated records by id. Used by explicit re-projection only."""
        updated = 0
        with self._lock:
            for rec in records or []:
                mem_id = rec.get("id") if isinstance(rec, dict) else None
                if mem_id in self._items:
                    self._items[mem_id].update(rec)
                    updated += 1
            if updated:
                self._save()
            return updated


# ── re-projection (re-embed onto a better model) ─────────────────────────────

def needs_reprojection(record: dict, current_version: int) -> bool:
    return int(record.get("embed_version", 0)) < int(current_version)


def _embedding_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return json.dumps(content, sort_keys=True, ensure_ascii=False, default=str)


async def reproject(records: "list[dict]", current_version: int, embedder: Callable) -> dict:
    """Re-embed stale records via an injectable embedder; bump embed_version."""
    done = 0
    for r in records or []:
        if not needs_reprojection(r, current_version):
            continue
        try:
            vec = embedder(_embedding_text(r.get("content", "")))
            if hasattr(vec, "__await__"):
                vec = await vec
            r["vector"] = vec
            r["embed_version"] = current_version
            done += 1
        except Exception:
            logger.debug("LivingMemory reproject skipped a stale record", exc_info=True)
    return {"reprojected": done, "version": current_version}


# ── core (always-injected, bounded) ──────────────────────────────────────────

#: H423 — how long a core-ring writer waits for another writer's lock on the ring file.
LOCK_TIMEOUT_S = 5.0


class CoreMemoryLocked(TimeoutError):
    """Another writer held a core ring's file lock for longer than the wait allowed."""


class CoreMemoryDrift(RuntimeError):
    """A core ring's file was edited outside Nerva. ``bak`` is the owner-only copy kept of
    it; ``problem`` says why the edit cannot be taken as the ring (None when it was
    taken, and the caller should only learn that the ring moved)."""

    def __init__(self, path: Path, bak: "Path | None", problem: "str | None") -> None:
        self.path, self.bak, self.problem = path, bak, problem
        super().__init__(f"{path.name} was edited outside Nerva"
                         + (f" and {problem}" if problem else "")
                         + (f"; a copy is kept at {bak}" if bak else ""))


class _PathLock:
    """One ring file's cross-process lock, shared by every CoreMemory of this process on
    that file: a thread-reentrant lock in front of one ``flock`` descriptor, so a writer
    that already holds it (the memory tool, then its compare-and-set) does not wait on
    itself, and two threads of this process are serialised like two processes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._rlock = threading.RLock()
        self._fd: "int | None" = None
        self._depth = 0

    def acquire(self, timeout: float) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        if not self._rlock.acquire(timeout=max(0.0, timeout)):
            raise CoreMemoryLocked(f"{self.path.name} is held by another writer")
        try:
            if self._depth == 0:
                self._fd = _flock(self.path, deadline)
            self._depth += 1
        except BaseException:
            self._rlock.release()
            raise

    def release(self) -> None:
        self._depth -= 1
        if self._depth == 0 and self._fd is not None:
            os.close(self._fd)          # closing the descriptor releases the flock
            self._fd = None
        self._rlock.release()


_PATH_LOCKS: "dict[str, _PathLock]" = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(path: Path) -> _PathLock:
    key = os.path.abspath(path)
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = _PATH_LOCKS[key] = _PathLock(Path(key))
        return lock


def _flock(path: Path, deadline: float) -> int:
    """An exclusive ``flock`` on *path* (created owner-only), polled until *deadline*."""
    try:
        import fcntl
    except ImportError:          # no POSIX locks (Windows): the in-process lock is all there is
        fcntl = None
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    if fcntl is None:
        return fd
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            if time.monotonic() >= deadline:
                os.close(fd)
                raise CoreMemoryLocked(f"{path.name} is held by another writer") from None
            time.sleep(0.02)


class CoreMemory(JsonStore):
    """A small set of always-injected core facts (bounded ring).

    H423: the file is shared by every Nerva writer (the model's ``memory`` tool, the
    post-turn review, the daily reflection, a forget) and by the owner's editor. Every
    mutation therefore runs under the ring file's lock (:meth:`locked`), rereads the file
    first, and saves the ring and the sha256 of its bytes (``<ring>.json.sha256``) under
    that same lock. A file whose bytes no longer match the recorded digest was edited by
    hand: it is copied to an owner-only ``.bak`` and, when it reads back exactly (valid
    JSON, distinct one-line facts, within the cap), taken as the ring; otherwise
    :class:`CoreMemoryDrift` is raised and nothing is written over it until it is fixed."""

    def __init__(self, cap: int = 20, path: str | Path | None = None) -> None:
        self.cap = cap
        super().__init__(path)
        self._baseline()

    def _serialize(self):
        return {"facts": self._facts[-self.cap:]}

    def digest_path(self) -> "Path | None":
        """H423 — the sidecar holding the sha256 of the bytes this ring last wrote, so a
        writer can tell a file edited by hand from one a Nerva process saved."""
        return None if self.path is None else self.path.with_name(self.path.name + ".sha256")

    def lock_path(self) -> "Path | None":
        """H423 — the file every writer of this ring locks (``<ring>.json.lock``)."""
        return None if self.path is None else self.path.with_name(self.path.name + ".lock")

    @contextmanager
    def locked(self, timeout: "float | None" = None) -> Iterator[None]:
        """Hold this ring file's cross-process lock (reentrant in the holding thread).
        Raises :class:`CoreMemoryLocked` after *timeout* seconds (:data:`LOCK_TIMEOUT_S`)."""
        lock_path = self.lock_path()
        if lock_path is None:
            yield
            return
        lock = _path_lock(lock_path)
        lock.acquire(LOCK_TIMEOUT_S if timeout is None else timeout)
        try:
            yield
        finally:
            lock.release()

    def _save(self) -> None:
        # Called only under locked(): the ring and its digest never tear for a reader that
        # holds the lock.
        super()._save()
        if self.path is None:
            return
        try:
            self._write_digest(hashlib.sha256(self.path.read_bytes()).hexdigest())
        except OSError:
            # The ring is saved; a stale digest only makes the next write keep a copy of
            # it and take it as the ring, which is the safe side.
            logger.warning("core memory: the digest of %s could not be saved", self.path, exc_info=True)

    def _write_digest(self, digest: str) -> None:
        from agents.core.persistence import json_store

        json_store.atomic_write_json(self.digest_path(), {"sha256": digest})

    def _recorded_digest(self) -> "str | None":
        try:
            raw = json.loads(self.digest_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        value = raw.get("sha256") if isinstance(raw, dict) else None
        return value if isinstance(value, str) else None

    def _strict_facts(self, data: bytes) -> "tuple[list[str], str | None]":
        """The facts in *data* exactly as written, or why they cannot be taken as the ring
        without dropping one (the lenient :meth:`_deserialize` would)."""
        try:
            raw = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return [], "it is not valid JSON"
        facts = raw.get("facts") if isinstance(raw, dict) else raw
        if not isinstance(facts, list) or not all(isinstance(f, str) for f in facts):
            return [], 'it does not hold "facts" as a list of text lines'
        cleaned = [f.strip() for f in facts]
        if any(not f for f in cleaned):
            return [], "it holds an empty fact"
        seen: set = set()
        for fact in cleaned:
            if fact in seen:
                return [], f"it holds the fact {fact[:60]!r} twice"
            seen.add(fact)
        if len(cleaned) > self.cap:
            return [], f"it holds {len(cleaned)} facts, over its cap of {self.cap}"
        return cleaned, None

    def _keep_copy(self, data: bytes, digest: str) -> Path:
        """An owner-only copy of a hand-edited file, one per distinct content."""
        path = self.path
        existing = sorted(path.parent.glob(f"{path.name}.*-{digest[:12]}.bak"))
        if existing:
            return existing[0]
        bak = path.with_name(f"{path.name}.{time.strftime('%Y%m%dT%H%M%S')}-{digest[:12]}.bak")
        try:
            fd = os.open(bak, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as out:
                out.write(data)
        except OSError:
            logger.warning("core memory: the hand-edited %s could not be copied", path, exc_info=True)
            raise CoreMemoryDrift(path, None, "a copy of it could not be kept") from None
        logger.warning("core memory: %s was edited outside Nerva; kept a copy at %s", path, bak)
        return bak

    def _sync_locked(self) -> "Path | None":
        """Under :meth:`locked` and ``self._lock``: make the in-memory ring the file's.
        Returns the ``.bak`` kept of a hand edit that was taken as the ring, else None.
        Raises :class:`CoreMemoryDrift` (with ``problem``) over an edit that cannot be."""
        path = self.path
        if path is None:
            return None
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            self._facts = []             # no file: an empty ring
            return None
        except OSError as exc:
            raise CoreMemoryDrift(path, None, f"it cannot be read ({exc.strerror})") from None
        digest = hashlib.sha256(data).hexdigest()
        recorded = self._recorded_digest()
        facts, problem = self._strict_facts(data)
        if recorded == digest and problem is None:
            self._facts = facts          # a Nerva save, maybe another process's
            return None
        # No digest yet (a ring saved before H423) is taken as a baseline when the file
        # reads back exactly; anything else is a hand edit and is kept first.
        bak = self._keep_copy(data, digest) if (recorded is not None or problem is not None) else None
        if problem is not None:
            raise CoreMemoryDrift(path, bak, problem)
        self._facts = facts
        try:
            self._write_digest(digest)
        except OSError:
            logger.warning("core memory: the digest of %s could not be saved", path, exc_info=True)
        return bak

    def sync_from_disk(self) -> "Path | None":
        """H423 — reread the ring from its file under its lock, taking a hand edit as the
        ring when it reads back exactly. Returns the ``.bak`` kept of such an edit."""
        with self.locked(), self._lock:
            return self._sync_locked()

    def _baseline(self) -> None:
        """A ring file saved before digests existed gets one on load, so a hand edit made
        after this process read it is told apart from it."""
        if self.path is None or not self.path.exists() or self.digest_path().exists():
            return
        try:
            with self.locked(), self._lock:
                if not self.digest_path().exists():
                    self._sync_locked()
        except (CoreMemoryLocked, CoreMemoryDrift):
            logger.warning("core memory: no baseline digest for %s yet", self.path, exc_info=True)

    def reload(self) -> None:
        """H423 — reread the ring from its file: another process may have written it."""
        with self._lock:
            self._load()

    def _deserialize(self, raw) -> None:
        facts = raw.get("facts", []) if isinstance(raw, dict) else raw
        self._facts = []
        if not isinstance(facts, list):
            return
        for fact in facts:
            f = str(fact or "").strip()
            if f and f not in self._facts:
                self._facts.append(f)
        self._facts = self._facts[-self.cap:]

    def put(self, fact: str) -> bool:
        """Add *fact* on top of the ring as it is on disk (the oldest rotates out at the
        cap: this is the post-turn review's and the reflection's bounded ring; the model's
        ``memory`` tool refuses at the cap instead). True when the ring changed. Raises
        :class:`CoreMemoryLocked`, or :class:`CoreMemoryDrift` over a hand edit that
        cannot be taken as the ring (nothing is written over it)."""
        f = (fact or "").strip()
        if not f:
            return False
        with self.locked(), self._lock:
            self._sync_locked()
            if f in self._facts:
                return False
            self._facts.append(f)
            if len(self._facts) > self.cap:
                self._facts.pop(0)
            self._save()
            return True

    def list(self) -> "list[str]":
        with self._lock:
            return list(self._facts)

    def compare_and_set(self, expected: "list[str]", facts: "list[str]") -> bool:
        """H314 — replace the whole ring with *facts*, only if it still holds *expected*.

        The model's ``memory`` tool computes a new ring from one it read; a forget (or
        another write) that ran in between must win, so a stale ring is never written
        back over it. Returns False, and changes nothing, when the ring moved.

        H423: the ring is reread from its file under its lock first, so a move made by
        another process counts too. A hand edit raises :class:`CoreMemoryDrift` (its
        ``bak`` names the copy kept), and nothing is written over it."""
        cleaned = [str(f).strip() for f in facts if str(f or "").strip()]
        if len(cleaned) > self.cap or len(set(cleaned)) != len(cleaned):
            raise ValueError("a core ring holds at most `cap` distinct facts")
        with self.locked(), self._lock:
            bak = self._sync_locked()
            if bak is not None:
                raise CoreMemoryDrift(self.path, bak, None)
            if self._facts != list(expected):
                return False
            previous, self._facts = self._facts, cleaned
            try:
                self._save()
            except Exception:
                self._facts = previous   # a ring that could not be saved did not change
                raise
            return True

    def render(self) -> str:
        facts = self.list()
        return "" if not facts else "[core memory]\n" + "\n".join(f"- {f}" for f in facts)

    def clear(self) -> int:
        """Explicit user-forget path: remove all core facts and persist empty state.

        H423: a forget wins over a hand edit (it is not kept) and deletes the ``.bak``
        copies of earlier ones; it waits for the ring lock but does not give up on it."""
        try:
            with self.locked():
                return self._clear()
        except CoreMemoryLocked:
            logger.warning("core memory: %s stayed locked; forgetting it anyway", self.path)
            return self._clear()

    def _clear(self) -> int:
        with self._lock:
            with suppress(CoreMemoryDrift):   # a hand edit is forgotten below either way
                self._sync_locked()
            count = len(self._facts)
            self._facts = []
            self._save()
            if self.path is not None:
                for bak in self.path.parent.glob(f"{self.path.name}.*.bak"):
                    try:
                        bak.unlink()
                    except OSError:
                        logger.warning("core memory: %s could not be deleted", bak, exc_info=True)
            return count


# ── the module ────────────────────────────────────────────────────────────────

class LivingMemory:
    """Ties encoding, tiering, core and consolidation into one cognition module."""

    def __init__(
        self,
        embed_version: int = 1,
        encode_threshold: float = 0.3,
        core_path: str | Path | None = None,
        tiers_path: str | Path | None = None,
        user_path: str | Path | None = None,
    ) -> None:
        self.tiers = TieredMemory(path=tiers_path)
        self.core = CoreMemory(path=core_path)
        # H20/H21 bridge: a second bounded core for *user* facts (who the user
        # is — hermes USER.md analog), distinct from agent-learned facts. Same
        # ring semantics; rendered as its own prompt section.
        self.user_core = CoreMemory(path=user_path)
        self.embed_version = embed_version
        self.encode_threshold = encode_threshold

    def encode(self, mem_id: str, content, surprise: float, nm: Optional[dict] = None) -> dict:
        """Gate on surprise; encode with neuromodulator-boosted strength."""
        if not encoding_gate(surprise, self.encode_threshold):
            return {"encoded": False, "reason": "below_surprise_gate"}
        strength = encoding_strength(surprise, nm)
        rec = self.tiers.add(mem_id, content, activation=strength, embed_version=self.embed_version)
        return {"encoded": True, "strength": strength, "tier": rec["tier"]}

    async def consolidate(self, phase: str = "nrem") -> dict:
        """NREM = stabilize/maintain (demote, never delete); REM = recombine."""
        if phase == "nrem":
            return {"phase": "nrem", **self.tiers.maintain()}
        return {"phase": "rem", "recombined": len(self.tiers.by_tier())}

    def records(self, prefix: str = "", limit: int = 50) -> "list[dict]":
        """Inspectable records for integration tests/API callers; no mutation."""
        return self.tiers.records(prefix=prefix, limit=limit)

    def has_text_digest(self, text_sha256: str, prefix: str = "turn:", limit: int = 1000) -> bool:
        """Return whether a recent metadata record already carries this digest."""
        needle = str(text_sha256 or "")
        if not needle:
            return False
        for record in self.records(prefix=prefix, limit=limit):
            content = record.get("content") if isinstance(record, dict) else None
            if isinstance(content, dict) and str(content.get("text_sha256") or "") == needle:
                return True
        return False

    def access(self, mem_id: str) -> Optional[dict]:
        """Reactivate a remembered trace when recall uses it."""
        return self.tiers.access(mem_id)

    async def reproject_stale(
        self,
        embedder: Optional[Callable] = None,
        current_version: Optional[int] = None,
        limit: int = 100,
    ) -> dict:
        """Re-embed stale tier records when an embedder is explicitly supplied."""
        target_version = int(current_version or self.embed_version)
        if embedder is None:
            return {
                "available": False,
                "reason": "embedder_unavailable",
                "checked": 0,
                "reprojected": 0,
                "updated": 0,
                "version": target_version,
            }
        records = self.tiers.records(limit=limit)
        stale = [dict(r) for r in records if needs_reprojection(r, target_version)]
        if not stale:
            return {
                "available": True,
                "checked": len(records),
                "reprojected": 0,
                "updated": 0,
                "version": target_version,
            }
        result = await reproject(stale, current_version=target_version, embedder=embedder)
        changed = [r for r in stale if not needs_reprojection(r, target_version)]
        updated = self.tiers.update_records(changed)
        return {"available": True, "checked": len(records), "updated": updated, **result}

    def clear(self) -> dict:
        """Explicit user-forget path for live cognition memory."""
        return {"core": self.core.clear(), "tiers": self.tiers.clear(),
                "user_core": self.user_core.clear()}

    def status(self) -> dict:
        return {"available": True, "tiers": self.tiers.by_tier(),
                "core": len(self.core.list()),
                "user_core": len(self.user_core.list()),
                "embed_version": self.embed_version}
