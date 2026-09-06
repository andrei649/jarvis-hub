#!/usr/bin/env python3
"""nerva_import.py — one-command migration from Hermes Agent / OpenClaw / Claude Code.

    python scripts/nerva_import.py --from hermes            # dry run: plan only
    python scripts/nerva_import.py --from all --apply       # write, still gated

What each foreign artefact becomes (and what it never becomes):

* **skills**   → copied into the skills tree **quarantined** (``PENDING_REVIEW``):
  registered for owner review, never exec'd in-process until approved (CDX-8).
* **persona**  (SOUL.md / USER.md / IDENTITY.md / CLAUDE.md) → a *preview* file under
  ``data/imports/<source>/persona_preview.md``. It never overwrites an agent's
  ``SOUL.local.md`` — adopting a persona stays an owner edit.
* **memory**   (MEMORY.md) → facts marked **tainted** (``security.taint``) that each
  cross the ``kg.write`` kernel kind through an *injected* authorizer. The default
  authorizer only ever QUEUEs: facts land in a pending store the owner approves;
  nothing self-authorizes a knowledge-graph write. Injection-flagged lines are
  denied at the contract and reported, not queued.
* **tokens**   (.env / openclaw.json / settings.json env) → ``SecretStore`` under the
  original name, never printed (reports carry a masked form only).

Default is a dry run that writes nothing; ``--apply`` is the owner's explicit
opt-in. No network, no subprocesses, no symlink following.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sqlite3
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.automation_contracts import (  # noqa: E402
    ContractTemplate,
    contract_denial,
    predicate,
)
from agents.core.security import quarantine, taint  # noqa: E402
from agents.core.skills.importer import (  # noqa: E402
    MIGRATION_SOURCES,
    DetectedSource,
    SkillImporter,
    detect_sources,
)

KG_WRITE_KIND = "kg.write"
IMPORT_ORIGIN = "external"
SECTIONS: tuple[str, ...] = ("skills", "persona", "memory", "tokens")

_MAX_FACTS_PER_FILE = 200
_MAX_OBJECT_CHARS = 500
_MAX_PERSONA_CHARS = 64 * 1024
_PREDICATE_RE = re.compile(r"[^a-z0-9]+")
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
_KV_RE = re.compile(r"^\**([A-Za-z][A-Za-z0-9 _/-]{0,63})\**\s*[:=]\s*(.+)$")
_ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
_SECRET_NAME_RE = re.compile(r"(token|secret|password|passwd|api[_-]?key|_key$|^key$)", re.I)


# ── kg.write contract for imported (tainted) memory ──────────────────────────


def _memory_import_contract() -> ContractTemplate:
    """Admissibility for an imported memory fact presented as a ``kg.write``.

    Sits *in front of* the injected authorizer: a fact must be an ``add_fact``,
    must carry the taint flag (imported text is untrusted by construction), must
    name an ``import:<source>`` origin, and must be free of injection patterns.
    ``requires_approval=True`` — an admissible fact is still QUEUE-tier.
    """

    def kg_write_kind(view, now):
        return view.get("kind") == KG_WRITE_KIND

    def add_fact_op(view, now):
        return view.get("op") == "add_fact"

    def tainted(view, now):
        return view.get(taint.TAINT_KEY) is True

    def import_origin(view, now):
        source = view.get("taint_source") or ""
        return source.startswith("import:") and source[len("import:"):] in MIGRATION_SOURCES

    def clean(view, now):
        return not view.get("injection_flags")

    return ContractTemplate(
        kind=KG_WRITE_KIND,
        constraints=(
            predicate("kg_write_kind", kg_write_kind, reason="invalid_kind"),
            predicate("add_fact_operation", add_fact_op, reason="unknown_operation"),
            predicate("tainted_import", tainted, reason="untainted_import"),
            predicate("import_origin", import_origin, reason="unknown_import_origin"),
            predicate("no_injection", clean, reason="injection_detected"),
        ),
        requires_approval=True,
        description="Imported memory facts (tainted) proposed as knowledge-graph writes.",
    )


MEMORY_IMPORT_CONTRACT = _memory_import_contract()


# ── memory facts ─────────────────────────────────────────────────────────────


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class MemoryFact:
    """One line of a foreign MEMORY.md, as a tainted knowledge-graph proposal."""

    subject: str
    predicate: str
    object: str
    source: str
    origin_file: str
    injection_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.source not in MIGRATION_SOURCES:
            raise ValueError(f"unknown migration source: {self.source!r}")
        if not self.subject or not self.predicate or not self.object:
            raise ValueError("subject, predicate and object must be non-empty")
        if len(self.object) > _MAX_OBJECT_CHARS:
            raise ValueError("object exceeds the import bound")
        if not isinstance(self.injection_flags, tuple):
            raise TypeError("injection_flags must be a tuple")

    @property
    def taint_source(self) -> str:
        return f"import:{self.source}"

    @property
    def fingerprint(self) -> str:
        body = _canonical({
            "subject": self.subject, "predicate": self.predicate,
            "object": self.object, "source": self.source,
        })
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def kernel_payload(self) -> dict:
        """Keys/ids only — never the object value (audit-PII hygiene, as memory_kg)."""
        return {
            "op": "add_fact",
            "subject": self.subject,
            "predicate": self.predicate,
            "fingerprint": self.fingerprint,
            taint.TAINT_KEY: True,
            "taint_source": self.taint_source,
            "injection_flags": list(self.injection_flags),
        }

    def as_dict(self) -> dict:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "source": self.source,
            "origin_file": self.origin_file,
            "fingerprint": self.fingerprint,
            "injection_flags": list(self.injection_flags),
            "metadata": taint.mark({}, self.taint_source),
        }


def _predicate_slug(key: str) -> str:
    slug = _PREDICATE_RE.sub("_", key.strip().lower()).strip("_")
    return slug[:64] or "note"


def parse_memory_facts(text: str, source: str, origin_file: str = "") -> tuple[MemoryFact, ...]:
    """MEMORY.md → tainted facts. ``- Key: value`` becomes ``owner <key> value``;
    any other non-empty line (bullet or paragraph) becomes ``owner note <text>``.
    Headings, code fences and blank lines are skipped; output is bounded."""
    facts: list[MemoryFact] = []
    in_fence = False
    for raw_line in (text or "").splitlines():
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not line.strip() or line.lstrip().startswith("#"):
            continue
        bullet = _BULLET_RE.match(line)
        body = (bullet.group(1) if bullet else line).strip()
        if not body:
            continue
        kv = _KV_RE.match(body)
        if kv and kv.group(2).strip():
            pred, obj = _predicate_slug(kv.group(1)), kv.group(2).strip()
        else:
            pred, obj = "note", body
        obj = obj[:_MAX_OBJECT_CHARS]
        facts.append(MemoryFact(
            subject="owner", predicate=pred, object=obj, source=source,
            origin_file=origin_file,
            injection_flags=tuple(quarantine.detect_injection(obj)),
        ))
        if len(facts) >= _MAX_FACTS_PER_FILE:
            break
    return tuple(facts)


# ── tokens ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TokenCandidate:
    name: str
    value: str = field(repr=False)
    origin_file: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", self.name):
            raise ValueError("token name must be an identifier")
        if not self.value:
            raise ValueError("token value must be non-empty")

    @property
    def masked(self) -> str:
        return f"{self.value[:3]}…({len(self.value)} chars)"

    def as_dict(self) -> dict:
        return {"name": self.name, "masked": self.masked, "origin_file": self.origin_file}


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value.split(" #", 1)[0].strip() if not value.startswith(("'", '"')) else value


def parse_env_tokens(text: str, origin_file: str = "") -> tuple[TokenCandidate, ...]:
    out: list[TokenCandidate] = []
    for line in (text or "").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _ENV_LINE_RE.match(line)
        if not match or not _SECRET_NAME_RE.search(match.group(1)):
            continue
        value = _strip_quotes(match.group(2))
        if value:
            out.append(TokenCandidate(match.group(1), value, origin_file))
    return tuple(out)


def _json_secret_walk(node: Any, path: tuple[str, ...], out: list[TokenCandidate], origin: str) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str):
                _json_secret_walk(value, path + (key,), out, origin)
    elif isinstance(node, str) and node.strip() and path and _SECRET_NAME_RE.search(path[-1]):
        name = "_".join(_PREDICATE_RE.sub("_", part.lower()).strip("_") for part in path).upper()
        name = re.sub(r"_+", "_", name).strip("_")[:128]
        if name and name[0].isdigit():
            name = f"_{name}"
        out.append(TokenCandidate(name, node.strip(), origin))


def parse_json_tokens(text: str, origin_file: str = "", *, prefix: str = "") -> tuple[TokenCandidate, ...]:
    """Secret-looking string leaves of a JSON config (``openclaw.json``,
    Claude Code ``settings.json``), named by their key path (``PREFIX_A_B``)."""
    try:
        data = json.loads(text or "")
    except json.JSONDecodeError:
        return ()
    out: list[TokenCandidate] = []
    root: tuple[str, ...] = (prefix,) if prefix else ()
    if isinstance(data, dict) and isinstance(data.get("env"), dict):
        # Claude Code settings.json carries plain env names — keep them verbatim.
        for key, value in data["env"].items():
            if isinstance(key, str) and isinstance(value, str) and value.strip() and _SECRET_NAME_RE.search(key):
                out.append(TokenCandidate(key, value.strip(), origin_file))
        data = {k: v for k, v in data.items() if k != "env"}
    _json_secret_walk(data, root, out, origin_file)
    return tuple(out)


def collect_tokens(source: DetectedSource) -> tuple[TokenCandidate, ...]:
    found: list[TokenCandidate] = []
    seen: set[str] = set()
    for path in source.token_files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if path.suffix == ".json":
            items = parse_json_tokens(text, str(path), prefix=source.source.replace("-", "_"))
        else:
            items = parse_env_tokens(text, str(path))
        for item in items:
            if item.name not in seen:
                seen.add(item.name)
                found.append(item)
    return tuple(found)


# ── persona ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PersonaPreview:
    source: str
    files: tuple[str, ...]
    text: str = field(repr=False)
    injection_flags: tuple[str, ...] = ()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict:
        return {
            "source": self.source, "files": list(self.files), "chars": len(self.text),
            "sha256": self.sha256, "injection_flags": list(self.injection_flags),
            "applies_to_soul": False,
        }

    def render(self) -> str:
        head = (
            f"<!-- nerva import preview · source={self.source} · sha256={self.sha256}\n"
            f"     tainted=true · files={', '.join(self.files)}\n"
            "     This is a PREVIEW. It is not loaded into any agent; adopt lines into a\n"
            "     SOUL.local.md yourself. -->\n\n"
        )
        return head + self.text


def build_persona_preview(source: DetectedSource) -> PersonaPreview | None:
    parts: list[str] = []
    files: list[str] = []
    for path in source.persona_files:
        try:
            body = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        files.append(str(path))
        parts.append(f"## {path.name} ({source.source})\n\n{body.strip()}\n")
    if not parts:
        return None
    text = "\n".join(parts)[:_MAX_PERSONA_CHARS]
    return PersonaPreview(
        source=source.source, files=tuple(files), text=text,
        injection_flags=tuple(quarantine.detect_injection(text)),
    )


# ── pending memory store (owner approves before anything reaches the graph) ───

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
_TRANSITIONS: dict[str, frozenset[str]] = {
    PENDING: frozenset({APPROVED, REJECTED}),
    APPROVED: frozenset(),
    REJECTED: frozenset(),
}
_SCHEMA_VERSION = 1


class PendingMemoryStore:
    """SQLite (WAL) queue of imported facts awaiting owner approval.

    Strict transition table (``pending → approved | rejected``; terminals never
    exit), one ``threading.Lock`` per store, fingerprint-keyed (a fact is queued
    once). Approval here records the owner's decision; the graph write itself is
    whoever drains ``approved`` rows (HUD/route, integrator-wired).
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS pending_memory ("
                " fingerprint TEXT PRIMARY KEY, kind TEXT NOT NULL, source TEXT NOT NULL,"
                " subject TEXT NOT NULL, predicate TEXT NOT NULL, object TEXT NOT NULL,"
                " origin_file TEXT NOT NULL, taint_source TEXT NOT NULL,"
                " injection_flags TEXT NOT NULL, status TEXT NOT NULL,"
                " created_at REAL NOT NULL, decided_at REAL)"
            )
            if int(conn.execute("PRAGMA user_version").fetchone()[0]) < _SCHEMA_VERSION:
                conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def enqueue(self, fact: MemoryFact, now: float | None = None) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO pending_memory VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)",
                (fact.fingerprint, KG_WRITE_KIND, fact.source, fact.subject, fact.predicate,
                 fact.object, fact.origin_file, fact.taint_source,
                 json.dumps(list(fact.injection_flags)), PENDING,
                 time.time() if now is None else float(now)),
            )
            return cur.rowcount == 1

    def list(self, status: str | None = None) -> list[dict]:
        query = "SELECT * FROM pending_memory"
        params: tuple = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status,)
        with self._lock, self._connect() as conn:
            rows = conn.execute(query + " ORDER BY created_at, fingerprint", params).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["injection_flags"] = json.loads(item["injection_flags"])
            item["metadata"] = taint.mark({}, item["taint_source"])
            out.append(item)
        return out

    def transition(self, fingerprint: str, new_status: str, now: float | None = None) -> bool:
        if new_status not in _TRANSITIONS:
            raise ValueError(f"unknown status: {new_status!r}")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM pending_memory WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
            if row is None or new_status not in _TRANSITIONS[row["status"]]:
                return False
            conn.execute(
                "UPDATE pending_memory SET status = ?, decided_at = ? WHERE fingerprint = ?",
                (new_status, time.time() if now is None else float(now), fingerprint),
            )
            return True

    def count(self, status: str | None = None) -> int:
        return len(self.list(status))


# ── authorizer seam ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class QueueDecision:
    """Decision-shaped result of the default authorizer (mirrors ``kernel.Decision``)."""

    verdict: str = "queue"
    reason: str = "imported_memory_requires_owner_approval"


def queue_only_authorizer(action) -> QueueDecision:
    """The default hook: never GRANTs. Every imported fact goes to the owner queue."""
    return QueueDecision()


def build_kernel_action(fact: MemoryFact):
    """``kernel.Action`` for one fact — the shape a real ``make_action_kernel``
    hook expects. Lazy import keeps the CLI cheap when no kernel is wired."""
    from agents.core.kernel import Action

    return Action(
        kind=KG_WRITE_KIND, agent="import", title=f"import memory fact {fact.predicate}",
        payload=fact.kernel_payload(), scope="global", origin=IMPORT_ORIGIN,
    )


def _verdict_of(decision) -> str:
    verdict = getattr(decision, "verdict", decision)
    value = getattr(verdict, "value", verdict)
    return str(value or "").strip().lower()


# ── the runner ───────────────────────────────────────────────────────────────


class ImportRunner:
    """Plan (dry run) or apply one detected source.

    ``authorizer`` is the kernel seam: ``authorizer(Action) -> Decision``. It is
    injected — the CLI passes :func:`queue_only_authorizer`; a HUD route can pass
    the bound Action Kernel. ``kg_writer(fact)`` is only ever called after a GRANT.
    """

    def __init__(
        self,
        source: DetectedSource,
        *,
        authorizer: Callable[[Any], Any] | None = None,
        secret_store=None,
        skills_dir: Path | None = None,
        kg_writer: Callable[[MemoryFact], Any] | None = None,
        pending_store: PendingMemoryStore | None = None,
        preview_dir: Path | None = None,
        sections: tuple[str, ...] = SECTIONS,
        overwrite_tokens: bool = False,
    ) -> None:
        unknown = set(sections) - set(SECTIONS)
        if unknown:
            raise ValueError(f"unknown sections: {sorted(unknown)}")
        self.source = source
        self.authorizer = authorizer or queue_only_authorizer
        self.secret_store = secret_store
        self.skills_dir = skills_dir
        self.kg_writer = kg_writer
        self.pending_store = pending_store
        self.preview_dir = preview_dir
        self.sections = tuple(sections)
        self.overwrite_tokens = overwrite_tokens

    # -- read side (shared by plan and apply; never writes) --

    def memory_facts(self) -> tuple[MemoryFact, ...]:
        facts: list[MemoryFact] = []
        seen: set[str] = set()
        for path in self.source.memory_files:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for fact in parse_memory_facts(text, self.source.source, str(path)):
                if fact.fingerprint not in seen:
                    seen.add(fact.fingerprint)
                    facts.append(fact)
        return tuple(facts)

    def _importer(self) -> SkillImporter | None:
        return SkillImporter(str(self.skills_dir)) if self.skills_dir else None

    async def _skills(self, dry_run: bool) -> list[dict]:
        importer = self._importer()
        results = []
        for skill_dir in self.source.skill_dirs:
            if importer is None:
                results.append({"slug": skill_dir.name, "status": "skipped", "reason": "skills_dir_unset"})
                continue
            results.append(await importer.import_local_skill(skill_dir, self.source.source, dry_run=dry_run))
        return results

    def _persona(self, dry_run: bool) -> dict | None:
        preview = build_persona_preview(self.source)
        if preview is None:
            return None
        info = preview.as_dict()
        if dry_run or self.preview_dir is None:
            info["status"] = "would_preview" if dry_run else "skipped"
            info["reason"] = "" if dry_run else "preview_dir_unset"
            return info
        target = Path(self.preview_dir) / self.source.source / "persona_preview.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(preview.render(), encoding="utf-8")
        info.update(status="previewed", reason="", path=str(target))
        return info

    def _memory(self, dry_run: bool) -> list[dict]:
        out = []
        for fact in self.memory_facts():
            row = {"fingerprint": fact.fingerprint, "predicate": fact.predicate,
                   "tainted": True, "kind": KG_WRITE_KIND}
            denial = contract_denial(
                MEMORY_IMPORT_CONTRACT.evaluate({"kind": KG_WRITE_KIND, **fact.kernel_payload()})
            )
            if denial:
                row.update(status="denied", reason=denial)
            elif dry_run:
                pending = self.pending_store is not None and any(
                    r["fingerprint"] == fact.fingerprint for r in self.pending_store.list()
                )
                row.update(status="already_pending" if pending else "would_queue", reason="")
            else:
                row.update(self._mediate(fact))
            out.append(row)
        return out

    def _mediate(self, fact: MemoryFact) -> dict:
        decision = self.authorizer(build_kernel_action(fact))
        verdict = _verdict_of(decision)
        reason = str(getattr(decision, "reason", "") or "")
        if verdict == "grant":
            if self.kg_writer is None:
                return self._queue(fact, "granted_but_no_kg_writer")
            self.kg_writer(fact)
            return {"status": "written", "reason": reason}
        if verdict == "queue":
            return self._queue(fact, reason)
        return {"status": "denied", "reason": reason or verdict or "denied"}

    def _queue(self, fact: MemoryFact, reason: str) -> dict:
        if self.pending_store is None:
            return {"status": "skipped", "reason": "pending_store_unset"}
        queued = self.pending_store.enqueue(fact)
        return {"status": "queued" if queued else "already_pending", "reason": reason}

    def _tokens(self, dry_run: bool) -> list[dict]:
        out = []
        for token in collect_tokens(self.source):
            row = token.as_dict()
            if dry_run:
                row.update(status="would_store", reason="")
            elif self.secret_store is None:
                row.update(status="skipped", reason="secret_store_unavailable")
            elif token.name in self.secret_store and not self.overwrite_tokens:
                row.update(status="skipped", reason="exists")
            else:
                self.secret_store.set(token.name, token.value)
                row.update(status="stored", reason="")
            out.append(row)
        return out

    async def _run(self, dry_run: bool) -> dict:
        report: dict = {"source": self.source.as_dict(), "dry_run": dry_run, "sections": {}}
        if "skills" in self.sections:
            report["sections"]["skills"] = await self._skills(dry_run)
        if "persona" in self.sections:
            report["sections"]["persona"] = self._persona(dry_run)
        if "memory" in self.sections:
            report["sections"]["memory"] = self._memory(dry_run)
        if "tokens" in self.sections:
            report["sections"]["tokens"] = self._tokens(dry_run)
        return report

    async def plan(self) -> dict:
        """Dry run: the full report with ``would_*`` statuses and zero writes."""
        return await self._run(dry_run=True)

    async def apply(self) -> dict:
        return await self._run(dry_run=False)


# ── CLI ──────────────────────────────────────────────────────────────────────


def _default_skills_dir() -> Path:
    from agents.core.paths import app_root, user_skills_dir

    return user_skills_dir() or (app_root() / "skills")


def _summary_line(section: str, rows) -> str:
    if rows is None:
        return f"  {section:8s} —"
    if isinstance(rows, dict):
        rows = [rows]
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.get("status", "?")] = counts.get(row.get("status", "?"), 0) + 1
    body = ", ".join(f"{n} {status}" for status, n in sorted(counts.items())) or "nothing found"
    return f"  {section:8s} {body}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nerva import", description=__doc__.split("\n\n")[0])
    parser.add_argument("--from", dest="source", default="all",
                        choices=(*MIGRATION_SOURCES, "all"))
    parser.add_argument("--home", default=None, help="home directory holding the installs (default ~)")
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    parser.add_argument("--only", default=",".join(SECTIONS),
                        help="comma list of sections: skills,persona,memory,tokens")
    parser.add_argument("--skills-dir", default=None)
    parser.add_argument("--overwrite-tokens", action="store_true")
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    return parser


async def _main_async(args) -> int:
    from agents.core.paths import data_path

    sections = tuple(s.strip() for s in args.only.split(",") if s.strip())
    try:
        detected = detect_sources(Path(args.home) if args.home else None,
                                  None if args.source == "all" else args.source)
    except ValueError as exc:
        print(f"✗ {exc}")
        return 2
    if not detected:
        print("✗ no Hermes / OpenClaw / Claude Code install detected")
        return 2

    secret_store = None
    pending_store = None
    if args.apply:
        pending_store = PendingMemoryStore(data_path("imports", "imports.db"))
        if "tokens" in sections:
            from agents.core.secrets import SecretStore

            secret_store = SecretStore()
    reports = []
    for source in detected:
        runner = ImportRunner(
            source,
            authorizer=queue_only_authorizer,
            secret_store=secret_store,
            skills_dir=Path(args.skills_dir) if args.skills_dir else _default_skills_dir(),
            pending_store=pending_store,
            preview_dir=data_path("imports") if args.apply else None,
            sections=sections,
            overwrite_tokens=args.overwrite_tokens,
        )
        reports.append(await (runner.apply() if args.apply else runner.plan()))

    if args.json:
        print(json.dumps(reports, indent=2, ensure_ascii=False))
        return 0
    for report in reports:
        mode = "APPLIED" if args.apply else "DRY RUN"
        print(f"→ {report['source']['source']} at {report['source']['root']} [{mode}]")
        for section in sections:
            print(_summary_line(section, report["sections"].get(section)))
    if not args.apply:
        print("  (nothing written — re-run with --apply; memory facts still queue for your approval)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    sys.exit(main())
