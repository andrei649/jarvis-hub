#!/usr/bin/env python3
"""nerva_import.py — one-command migration from Hermes Agent / OpenClaw / Claude Code.

    python scripts/nerva_import.py --from hermes            # dry run: plan only
    python scripts/nerva_import.py --from all --apply       # write, still gated
    python scripts/nerva_import.py --from all --apply --update   # re-import changed skills

What each foreign artefact becomes (and what it never becomes):

* **skills**   → copied into the skills tree **quarantined** (``PENDING_REVIEW``):
  registered for owner review, never exec'd in-process until approved (CDX-8).
  Every write crosses the ``skill.install`` kernel kind through the same injected
  authorizer as memory; a DENY writes nothing, and even a GRANT lands quarantined.
  A re-run re-detects each imported skill against its recorded source file and
  digest: ``unchanged`` / ``changed`` (both digests + a bounded diff) /
  ``source_removed``. ``--apply --update`` re-imports only the changed ones: the
  current copy is backed up under ``data/imports/skill_backups``, the skill goes
  back to ``PENDING_REVIEW`` and the owner's approval of the old bytes is revoked.
  Import-once, never a live scan of a foreign directory (H344).
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
    install_root,
    rescan_imported,
)

KG_WRITE_KIND = "kg.write"
SKILL_INSTALL_KIND = "skill.install"
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


# ── skill.install contract for imported (quarantined) skills ─────────────────

SKILL_IMPORT_OPS: frozenset[str] = frozenset({"import", "reimport"})
# The importer's slug alphabet (agents/core/skills/importer.py ``_SLUG_RE``).
_SKILL_SLUG_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_SHA256_HEX_RE = re.compile(r"[0-9a-f]{64}")


def _is_sha256(value) -> bool:
    return isinstance(value, str) and _SHA256_HEX_RE.fullmatch(value) is not None


def _skill_import_contract() -> ContractTemplate:
    """Admissibility for writing an imported skill into the skills tree (``skill.install``).

    In front of the injected authorizer, like the memory contract: the write must be
    an ``import`` or ``reimport``, name a safe slug, land **quarantined**, carry the
    taint flag with an ``import:<source>`` origin, and name the exact bytes by digest
    (a re-import also names the digest it replaces). Injection hits are reported to
    the owner but do not deny: the skill is quarantined either way.
    ``requires_approval=True`` — an admissible write is still owner-reviewed.
    """

    def skill_install_kind(view, now):
        return view.get("kind") == SKILL_INSTALL_KIND

    def import_operation(view, now):
        return view.get("op") in SKILL_IMPORT_OPS and view.get("action") == "install"

    def safe_name(view, now):
        name = view.get("name")
        return isinstance(name, str) and _SKILL_SLUG_RE.fullmatch(name) is not None

    def quarantined(view, now):
        return view.get("quarantined") is True

    def tainted(view, now):
        return view.get(taint.TAINT_KEY) is True

    def import_origin(view, now):
        source = view.get("source")
        return source in MIGRATION_SOURCES and view.get("taint_source") == f"import:{source}"

    def digests(view, now):
        if not _is_sha256(view.get("content_sha256")):
            return False
        return view.get("op") != "reimport" or _is_sha256(view.get("previous_sha256"))

    return ContractTemplate(
        kind=SKILL_INSTALL_KIND,
        constraints=(
            predicate("skill_install_kind", skill_install_kind, reason="invalid_kind"),
            predicate("import_operation", import_operation, reason="unknown_operation"),
            predicate("skill_name_safe", safe_name, reason="invalid_skill_name"),
            predicate("quarantined", quarantined, reason="not_quarantined"),
            predicate("tainted_import", tainted, reason="untainted_import"),
            predicate("import_origin", import_origin, reason="unknown_import_origin"),
            predicate("content_digests", digests, reason="invalid_digest"),
        ),
        requires_approval=True,
        description="Imported skills (quarantined, tainted) written into the skills tree.",
    )


SKILL_IMPORT_CONTRACT = _skill_import_contract()


def skill_import_payload(probe: dict, source: str, op: str) -> dict:
    """The ``skill.install`` payload for one probed skill: ids and digests only,
    never the SKILL.md body (audit hygiene, as the memory payload)."""
    payload = {
        "op": op,
        "action": "install",
        "name": probe.get("slug"),
        "source": source,
        "content_sha256": probe.get("sha256"),
        "quarantined": True,
        taint.TAINT_KEY: True,
        "taint_source": f"import:{source}",
        "injection_flags": list(probe.get("injection_flags") or []),
    }
    if op == "reimport":
        payload["previous_sha256"] = probe.get("old_sha256")
    return payload


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
    """The default hook: never GRANTs. Every imported fact goes to the owner queue;
    every imported skill lands quarantined for owner review."""
    if getattr(action, "kind", None) == SKILL_INSTALL_KIND:
        return QueueDecision(reason="imported_skill_requires_owner_review")
    return QueueDecision()


def build_kernel_action(fact: MemoryFact):
    """``kernel.Action`` for one fact — the shape a real ``make_action_kernel``
    hook expects. Lazy import keeps the CLI cheap when no kernel is wired."""
    from agents.core.kernel import Action

    return Action(
        kind=KG_WRITE_KIND, agent="import", title=f"import memory fact {fact.predicate}",
        payload=fact.kernel_payload(), scope="global", origin=IMPORT_ORIGIN,
    )


def build_skill_action(payload: dict):
    """``kernel.Action`` for one skill write into the skills tree (``skill.install``).
    Origin ``external``: the kernel escalates a GRANT on it back to QUEUE."""
    from agents.core.kernel import Action

    verb = "re-import" if payload.get("op") == "reimport" else "import"
    return Action(
        kind=SKILL_INSTALL_KIND, agent="import", title=f"{verb} skill {payload.get('name')}",
        payload=dict(payload), scope="global", origin=IMPORT_ORIGIN,
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
    Skill writes cross the same seam as ``skill.install``: GRANT or QUEUE both land
    the skill quarantined (``PENDING_REVIEW`` is the owner-review queue for skills),
    anything else writes nothing. ``update_skills`` re-imports skills whose source
    changed since import; it needs ``skill_backup_dir`` and ``approval_revoker``
    (``SkillLoader.revoke_approval``) or the importer refuses the re-import.
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
        update_skills: bool = False,
        skill_backup_dir: Path | None = None,
        approval_revoker: Callable[[Path], bool] | None = None,
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
        self.update_skills = update_skills
        self.skill_backup_dir = skill_backup_dir
        self.approval_revoker = approval_revoker

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
            # Re-detect first, always read-only: would_import / unchanged / changed /
            # skipped / rejected. Only a write that is actually wanted is mediated.
            probe = await importer.import_local_skill(skill_dir, self.source.source, dry_run=True)
            wanted = probe["status"] == "would_import" or (
                probe["status"] == "changed" and self.update_skills
            )
            if dry_run or not wanted:
                results.append(probe)
                continue
            results.append(await self._install_skill(importer, skill_dir, probe))
        if importer is not None:
            results.extend(rescan_imported(importer.skills_dir, self.source.source))
        return results

    async def _install_skill(self, importer: SkillImporter, skill_dir: Path, probe: dict) -> dict:
        """One skill write, after crossing ``skill.install`` (contract, then authorizer)."""
        op = "reimport" if probe["status"] == "changed" else "import"
        if op == "reimport" and (self.skill_backup_dir is None or self.approval_revoker is None):
            # Refused before the kernel is asked: a re-import that could not keep the
            # old copy or revoke the old approval is never proposed at all.
            missing = "backup_dir_unset" if self.skill_backup_dir is None else "approval_revoker_unset"
            return {**probe, "status": "rejected", "reason": missing}
        payload = skill_import_payload(probe, self.source.source, op)
        denial = contract_denial(
            SKILL_IMPORT_CONTRACT.evaluate({"kind": SKILL_INSTALL_KIND, **payload})
        )
        if denial:
            return {**probe, "status": "denied", "reason": denial}
        try:
            decision = self.authorizer(build_skill_action(payload))
        except Exception:
            return {**probe, "status": "denied", "reason": "authorizer_error"}
        verdict = _verdict_of(decision)
        reason = str(getattr(decision, "reason", "") or "")
        if verdict not in ("grant", "queue"):
            return {**probe, "status": "denied", "reason": reason or verdict or "denied"}
        # GRANT or QUEUE: the skill lands quarantined either way; the grant is bound
        # to the probed bytes (a source edited since is refused, not written).
        result = await importer.import_local_skill(
            skill_dir,
            self.source.source,
            overwrite=op == "reimport",
            expected_sha256=probe["sha256"],
            backup_dir=self.skill_backup_dir,
            revoke_approval=self.approval_revoker,
        )
        result.update(kernel=verdict, kernel_reason=reason)
        return result

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
    parser.add_argument(
        "--update", action="store_true",
        help="re-import skills whose source changed since import (needs --apply: the "
             "current copy is backed up, the skill is re-quarantined and its approval revoked)",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    return parser


def _approval_revoker() -> Callable[[Path], bool]:
    """``SkillLoader.revoke_approval`` over the default approval registry: the seam
    the marketplace uninstall route uses. Constructing the loader runs no discovery."""
    from agents.core.skills.loader import SkillLoader

    return SkillLoader().revoke_approval


def _count(rows, status: str) -> int:
    return sum(1 for row in (rows or []) if row.get("status") == status)


async def _main_async(args) -> int:
    from agents.core.paths import data_path

    sections = tuple(s.strip() for s in args.only.split(",") if s.strip())
    home = Path(args.home) if args.home else None
    try:
        detected = detect_sources(home, None if args.source == "all" else args.source)
    except ValueError as exc:
        print(f"✗ {exc}")
        return 2
    skills_dir = Path(args.skills_dir) if args.skills_dir else _default_skills_dir()
    if "skills" in sections:
        # An install removed wholesale is a source change too: its imported skills
        # are reported source_removed instead of the run claiming nothing is there.
        in_scope = MIGRATION_SOURCES if args.source == "all" else (args.source,)
        present = {item.source for item in detected}
        for name in in_scope:
            if name not in present and rescan_imported(skills_dir, name):
                detected.append(DetectedSource(source=name, root=install_root(name, home)))
    if not detected:
        print("✗ no Hermes / OpenClaw / Claude Code install detected")
        return 2

    secret_store = None
    pending_store = None
    revoker = None
    if args.apply:
        pending_store = PendingMemoryStore(data_path("imports", "imports.db"))
        if "tokens" in sections:
            from agents.core.secrets import SecretStore

            secret_store = SecretStore()
        if args.update and "skills" in sections:
            revoker = _approval_revoker()
    reports = []
    for source in detected:
        runner = ImportRunner(
            source,
            authorizer=queue_only_authorizer,
            secret_store=secret_store,
            skills_dir=skills_dir,
            pending_store=pending_store,
            preview_dir=data_path("imports") if args.apply else None,
            sections=sections,
            overwrite_tokens=args.overwrite_tokens,
            update_skills=args.update,
            skill_backup_dir=data_path("imports", "skill_backups") if args.apply else None,
            approval_revoker=revoker,
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
        skills = report["sections"].get("skills")
        changed = _count(skills, "changed")
        if changed and not (args.apply and args.update):
            print(f"  ({changed} skill(s) changed at the source: see the diff with --json; "
                  "re-run with --apply --update to re-import them into quarantine)")
        removed = _count(skills, "source_removed")
        if removed:
            print(f"  ({removed} imported skill(s) lost their source: the imported copies "
                  "stay until you remove them)")
    if not args.apply:
        print("  (nothing written — re-run with --apply; memory facts still queue for your approval)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    sys.exit(main())
