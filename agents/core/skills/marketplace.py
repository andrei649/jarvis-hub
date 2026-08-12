"""
marketplace.py — Dynamic Skill sharing registry & Agent Marketplace.
Provides SQLite DB persistence, ZIP packaging/unpacking, and dynamic loader integration.
"""

import io
import json
import logging
import sqlite3
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from agents.core.automation_contracts import (
    ContractTemplate,
    contract_denial,
    field_present,
    one_of,
    predicate,
)
from agents.core.paths import data_path
from agents.core.persistence.migrations import apply_migrations

from . import signing
from .loader import EXTERNAL_SOURCE_MARKER, OWNER_APPROVED_MARKER, SkillLoader
from .skill_history import SkillHistory

logger = logging.getLogger("jarvis.skills.marketplace")


def _v1_moderation_columns(conn: sqlite3.Connection) -> None:
    """v1 — moderation/signature columns. Guarded for older DBs that predate them
    (no-op on fresh DBs whose CREATE TABLE already declares them)."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(marketplace_skills)").fetchall()}
    if "review_status" not in cols:
        conn.execute("ALTER TABLE marketplace_skills ADD COLUMN review_status TEXT NOT NULL DEFAULT 'pending'")
    if "signature" not in cols:
        conn.execute("ALTER TABLE marketplace_skills ADD COLUMN signature TEXT DEFAULT ''")


def _v2_version_archive(conn: sqlite3.Connection) -> None:
    """v2 — retain prior package snapshots so a publish can be rolled back. Purely
    additive: a new table only (``marketplace_skills`` is untouched), so existing
    rows and the publish/install flow are unchanged until a rollback is requested."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS marketplace_skill_versions (
            name TEXT NOT NULL,
            version TEXT NOT NULL,
            description TEXT,
            author TEXT,
            agents TEXT,
            requires TEXT,
            package_zip BLOB NOT NULL,
            published_at TEXT NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'pending',
            signature TEXT DEFAULT '',
            archived_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_skill_versions_name ON marketplace_skill_versions(name)")


def _v3_acquired_metadata(conn: sqlite3.Connection) -> None:
    """H32.5 — metadata-only index for sandbox-only acquired packages."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS marketplace_acquired_skills (
            name TEXT PRIMARY KEY,
            version TEXT NOT NULL,
            description TEXT NOT NULL,
            author TEXT NOT NULL,
            execution_mode TEXT NOT NULL,
            package_hash TEXT NOT NULL,
            receipt_hash TEXT NOT NULL,
            runtime_image TEXT NOT NULL,
            signature_json TEXT NOT NULL,
            indexed_at TEXT NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'approved'
        )
    """)


# Forward-only, append-only. Never edit/reorder a shipped entry — only append.
_MIGRATIONS = [_v1_moderation_columns, _v2_version_archive, _v3_acquired_metadata]

# Prior package snapshots retained per skill (oldest pruned on archive).
_VERSION_KEEP = 20

# Locate the DB under memory_logs/
DB_PATH = data_path("marketplace.db")

# Review states for the moderation gate (H12.12, anti-ClawHub supply chain).
REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_REJECTED = "rejected"


def _skill_name_safe(view, now) -> bool:
    name = str(view.get("name") or "").strip()
    return bool(name and name not in (".", "..")
                and "/" not in name and "\\" not in name and "\x00" not in name)


def _skill_install_contract_template() -> ContractTemplate:
    return ContractTemplate(
        kind="skill.install",
        description="Skill marketplace publish/install/uninstall supply-chain gate.",
        constraints=(
            field_present("action", "name"),
            one_of("action", {"publish", "install", "uninstall"}),
            predicate("skill_name_safe", _skill_name_safe, reason="invalid_skill_name"),
        ),
    )


SKILL_INSTALL_CONTRACT_KIND = "skill.install"
SKILL_INSTALL_CONTRACT = _skill_install_contract_template()


def _require_reviewed() -> bool:
    """When set, only skills moderated to 'approved' may be installed."""
    from agents.core.env_config import env_flag
    return env_flag("JARVIS_REQUIRE_REVIEWED_SKILLS")


class SkillMarketplace:
    def __init__(self, skills_dir: Optional[str] = None, db_path: Optional[str] = None,
                 *, history: Optional[SkillHistory] = None, clock=None):
        if skills_dir is None:
            # Default resolution (was CWD-relative "skills"): installed skills are
            # personal content, so they go to the user data home when one is
            # active; otherwise the app-root skills tree (repo-root anchored —
            # identical to before when running from the checkout).
            from agents.core.paths import app_root, user_skills_dir
            skills_dir = user_skills_dir() or (app_root() / "skills")
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Guard concurrent publish/install from async task runners (H7.4).
        self._lock = threading.Lock()
        # 0.58 wiring: when a version-history ledger is attached, publish/install/
        # uninstall are recorded so a rollback target can be derived. Opt-in;
        # None → behaviour is byte-identical to before.
        self._history = history
        self._clock = clock or time.time
        self._init_db()

    def _record_history(self, name: str, version: str, action: str) -> None:
        """Best-effort version-history record (no-op without a ledger; a ledger
        hiccup never breaks the publish/install/uninstall it accompanies)."""
        if self._history is None or not name or not version:
            return
        try:
            self._history.record(str(name), str(version), action, now=self._clock())
        except Exception:
            logger.debug("skill history record failed", exc_info=True)

    def _enforce_skill_contract(self, action: str, name: str, **payload) -> None:
        contract_payload = {
            "kind": SKILL_INSTALL_CONTRACT_KIND,
            "action": action,
            "name": name,
            **payload,
        }
        try:
            decision = SKILL_INSTALL_CONTRACT.evaluate(contract_payload, now=self._clock())
        except Exception as exc:
            logger.warning("skill marketplace contract evaluation failed", exc_info=True)
            raise PermissionError("contract_error") from exc
        reason = contract_denial(decision)
        if reason:
            raise PermissionError(reason)

    def history_view(self, name: Optional[str] = None) -> dict:
        """Read the 0.58 version-history ledger: events + stats (and, for one skill,
        its current/rollback-target version). When no ledger is attached
        (``JARVIS_SKILL_HISTORY`` unset) this reports ``enabled: False`` with empty
        data — the read surface degrades cleanly rather than erroring."""
        if self._history is None:
            return {"enabled": False, "events": [],
                    "stats": {"total": 0, "skills": 0, "by_action": {}}}
        out = {
            "enabled": True,
            "events": self._history.history(name),
            "stats": self._history.stats(),
        }
        if name:
            out["name"] = name
            out["current_version"] = self._history.current_version(name)
            out["rollback_target"] = self._history.rollback_target(name)
        return out

    def _registry_version(self, name: str) -> Optional[str]:
        """The version a skill is registered at, or None if not registered."""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            conn.row_factory = sqlite3.Row
            with self._lock:
                row = conn.execute(
                    "SELECT version FROM marketplace_skills WHERE name = ?", (name,)
                ).fetchone()
            return row["version"] if row else None
        finally:
            conn.close()

    def _archive_current(self, conn: sqlite3.Connection, name: str) -> None:
        """Snapshot the current ``marketplace_skills`` row for *name* into the version
        archive so a later publish/rollback can restore it. A no-op when the skill has
        no current row (e.g. a first publish). Bounded: only the most recent
        ``_VERSION_KEEP`` snapshots per skill survive (oldest pruned).

        Operates on the caller's already-open *conn*, inside the caller's lock and
        transaction, so the archive + replace commit atomically."""
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT name, version, description, author, agents, requires, package_zip, "
            "published_at, review_status, signature FROM marketplace_skills WHERE name = ?",
            (name,),
        ).fetchone()
        if cur is None:
            return
        conn.execute(
            "INSERT INTO marketplace_skill_versions "
            "(name, version, description, author, agents, requires, package_zip, "
            "published_at, review_status, signature, archived_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cur["name"], cur["version"], cur["description"], cur["author"], cur["agents"],
             cur["requires"], cur["package_zip"], cur["published_at"], cur["review_status"],
             cur["signature"], datetime.now(timezone.utc).isoformat()),
        )
        # Bound the archive: keep the most recent _VERSION_KEEP for this skill. rowid
        # breaks ties when two snapshots share an archived_at (sub-second republish).
        conn.execute(
            "DELETE FROM marketplace_skill_versions WHERE name = ? AND rowid NOT IN ("
            "SELECT rowid FROM marketplace_skill_versions WHERE name = ? "
            "ORDER BY archived_at DESC, rowid DESC LIMIT ?)",
            (name, name, _VERSION_KEEP),
        )

    def restore_prior_package(self, skill_name: str) -> dict:
        """Roll a skill's marketplace package back to its most recently archived prior
        version (0.58 Pack Manager). The *current* package is archived first, so a
        rollback is **reversible** — calling again rolls forward. The restored package
        replaces the registry row but is **not** installed; ``install_skill`` re-deploys
        it, so the moderation/signature gate still applies on the way back.

        Returns ``{ok: True, name, restored_version, previous_version}``; ``ok: False``
        with a ``reason`` when the skill isn't registered or has no archived prior."""
        name = (skill_name or "").strip()
        if not name:
            return {"ok": False, "error": "skill name required"}
        restored_version = previous_version = None
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            conn.row_factory = sqlite3.Row
            with self._lock:
                current = conn.execute(
                    "SELECT version FROM marketplace_skills WHERE name = ?", (name,)
                ).fetchone()
                if current is None:
                    return {"ok": False, "error": f"skill '{name}' not in registry"}
                prior = conn.execute(
                    "SELECT rowid, * FROM marketplace_skill_versions WHERE name = ? "
                    "ORDER BY archived_at DESC, rowid DESC LIMIT 1",
                    (name,),
                ).fetchone()
                if prior is None:
                    return {"ok": False, "error": f"no prior version archived for '{name}'"}
                # Archive the current row (so this rollback is itself reversible), drop
                # the snapshot we're restoring from the archive, then make it current.
                self._archive_current(conn, name)
                conn.execute("DELETE FROM marketplace_skill_versions WHERE rowid = ?", (prior["rowid"],))
                conn.execute(
                    "INSERT OR REPLACE INTO marketplace_skills "
                    "(name, version, description, author, agents, requires, package_zip, "
                    "published_at, review_status, signature) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (prior["name"], prior["version"], prior["description"], prior["author"],
                     prior["agents"], prior["requires"], prior["package_zip"],
                     prior["published_at"], prior["review_status"], prior["signature"]),
                )
                conn.commit()
                restored_version = prior["version"]
                previous_version = current["version"]
        finally:
            conn.close()
        self._record_history(name, restored_version, "rollback")
        return {"ok": True, "name": name, "restored_version": restored_version,
                "previous_version": previous_version}

    def _init_db(self):
        # check_same_thread=False: marketplace methods may be called from
        # asyncio.to_thread; the threading.Lock serialises all access (H7.4).
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS marketplace_skills (
                    name TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    description TEXT,
                    author TEXT,
                    agents TEXT,
                    requires TEXT,
                    package_zip BLOB NOT NULL,
                    published_at TEXT NOT NULL,
                    review_status TEXT NOT NULL DEFAULT 'pending',
                    signature TEXT DEFAULT ''
                )
            """)
            conn.commit()
            # Versioned, forward-only schema migrations (H23.7), replacing the
            # former inline table_info/ALTER guards.
            apply_migrations(conn, _MIGRATIONS, name="marketplace")
        finally:
            conn.close()

    def publish_skill(self, skill_name: str) -> dict:
        """
        Pack a skill directory into a zip blob and save it in the marketplace DB.
        """
        self._enforce_skill_contract("publish", skill_name, source="local")
        skill_path = self.skills_dir / skill_name
        if not skill_path.exists() or not skill_path.is_dir():
            raise FileNotFoundError(f"Skill directory not found: {skill_path}")

        skill_file = skill_path / "SKILL.md"
        if not skill_file.exists():
            raise FileNotFoundError(f"SKILL.md manifest missing in: {skill_path}")

        # Parse manifest using SkillLoader's internal helper
        loader = SkillLoader()
        manifest = loader._parse_manifest(skill_file)

        # Sign the skill so the published package ships a SKILL.sig the installer
        # can verify (HMAC-keyed when JARVIS_SKILL_SIGNING_KEY is set). (H12.12)
        signature = signing.sign_skill(skill_path)

        # Build Zip archive in memory (includes the freshly written SKILL.sig).
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for file_path in skill_path.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(skill_path)
                    zip_file.write(file_path, arcname)

        zip_data = zip_buffer.getvalue()

        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            with self._lock:
                # 0.58 rollback: snapshot the version about to be replaced so
                # restore_prior_package can bring it back. No-op on a first publish.
                self._archive_current(conn, manifest.get("name", skill_name))
                # Re-publishing resets the skill to 'pending' so a changed package
                # must be re-reviewed before it can be installed.
                conn.execute(
                    """
                    INSERT OR REPLACE INTO marketplace_skills
                    (name, version, description, author, agents, requires, package_zip, published_at, review_status, signature)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        manifest.get("name", skill_name),
                        manifest.get("version", "0.1.0"),
                        manifest.get("description", ""),
                        manifest.get("author", "unknown"),
                        ",".join(manifest.get("agents", [])),
                        ",".join(manifest.get("requires", [])),
                        zip_data,
                        datetime.now(timezone.utc).isoformat(),
                        REVIEW_PENDING,
                        signature,
                    )
                )
                conn.commit()
        finally:
            conn.close()

        logger.info(f"Published skill '{skill_name}' to marketplace registry.")
        self._record_history(manifest.get("name", skill_name),
                             manifest.get("version", "0.1.0"), "publish")
        return {
            "name": manifest.get("name", skill_name),
            "version": manifest.get("version", "0.1.0"),
            "author": manifest.get("author", "unknown"),
            "description": manifest.get("description", "")
        }

    def list_skills(self) -> List[dict]:
        """
        List all skills available in the marketplace registry.
        """
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            conn.row_factory = sqlite3.Row
            with self._lock:
                rows = conn.execute(
                    "SELECT name, version, description, author, agents, requires, published_at, review_status, signature FROM marketplace_skills"
                ).fetchall()
                acquired = conn.execute(
                    "SELECT name, version, description, author, execution_mode, "
                    "package_hash, receipt_hash, runtime_image, signature_json, "
                    "indexed_at, review_status FROM marketplace_acquired_skills"
                ).fetchall()
            regular = [
                {
                    "name": r["name"],
                    "version": r["version"],
                    "description": r["description"],
                    "author": r["author"],
                    "agents": r["agents"].split(",") if r["agents"] else [],
                    "requires": r["requires"].split(",") if r["requires"] else [],
                    "published_at": r["published_at"],
                    "review_status": r["review_status"] or REVIEW_PENDING,
                    "signed": bool(r["signature"]),
                    "execution_mode": "in_process",
                }
                for r in rows
            ]
            indexed = [
                {
                    "name": row["name"],
                    "version": row["version"],
                    "description": row["description"],
                    "author": row["author"],
                    "agents": [],
                    "requires": ["acquired-sandbox"],
                    "published_at": row["indexed_at"],
                    "review_status": row["review_status"],
                    "signed": bool(row["signature_json"]),
                    "execution_mode": row["execution_mode"],
                    "package_hash": row["package_hash"],
                    "receipt_hash": row["receipt_hash"],
                    "runtime_image": row["runtime_image"],
                }
                for row in acquired
            ]
            acquired_names = {row["name"] for row in indexed}
            return [row for row in regular if row["name"] not in acquired_names] + indexed
        finally:
            conn.close()

    def index_acquired_package(self, metadata: dict) -> bool:
        """Index owner-approved metadata without copying code into ``skills/``."""
        required = {
            "name",
            "version",
            "description",
            "author",
            "execution_mode",
            "package_hash",
            "receipt_hash",
            "runtime_image",
            "signature",
        }
        if not isinstance(metadata, dict) or not required.issubset(metadata):
            raise ValueError("complete acquired package metadata required")
        name = str(metadata["name"])
        if metadata.get("execution_mode") != "acquired_sandbox":
            raise ValueError("acquired package must remain sandbox-only")
        self._enforce_skill_contract(
            "publish",
            name,
            source="acquisition",
            review_status=REVIEW_APPROVED,
        )
        signature = json.dumps(
            metadata["signature"],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            with self._lock:
                conn.execute(
                    "INSERT OR REPLACE INTO marketplace_acquired_skills "
                    "(name, version, description, author, execution_mode, package_hash, "
                    "receipt_hash, runtime_image, signature_json, indexed_at, review_status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        name,
                        str(metadata["version"]),
                        str(metadata["description"])[:1024],
                        str(metadata["author"])[:128],
                        "acquired_sandbox",
                        str(metadata["package_hash"]),
                        str(metadata["receipt_hash"]),
                        str(metadata["runtime_image"]),
                        signature,
                        datetime.now(timezone.utc).isoformat(),
                        REVIEW_APPROVED,
                    ),
                )
                conn.commit()
        finally:
            conn.close()
        return True

    def remove_acquired_package(self, name: str) -> bool:
        """Remove only the metadata index; package bytes live in the acquired store."""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            with self._lock:
                cursor = conn.execute(
                    "DELETE FROM marketplace_acquired_skills WHERE name = ?",
                    (str(name or ""),),
                )
                conn.commit()
                return cursor.rowcount > 0
        finally:
            conn.close()

    def set_review_status(self, skill_name: str, status: str) -> bool:
        """Moderate a marketplace skill (H12.12). status ∈ {pending, approved, rejected}."""
        if status not in (REVIEW_PENDING, REVIEW_APPROVED, REVIEW_REJECTED):
            raise ValueError(f"invalid review status: {status}")
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            with self._lock:
                cur = conn.execute(
                    "UPDATE marketplace_skills SET review_status = ? WHERE name = ?",
                    (status, skill_name),
                )
                conn.commit()
            if cur.rowcount == 0:
                raise ValueError(f"Skill '{skill_name}' not found in registry database.")
        finally:
            conn.close()
        # Don't log the caller-supplied name (log-injection); status is a fixed enum.
        logger.info("Marketplace skill review status set to '%s'", status)
        return True

    def approve_skill(self, skill_name: str) -> bool:
        return self.set_review_status(skill_name, REVIEW_APPROVED)

    def reject_skill(self, skill_name: str) -> bool:
        return self.set_review_status(skill_name, REVIEW_REJECTED)

    def install_skill(self, skill_name: str) -> bool:
        """
        Fetch a dynamic skill package from the database and extract it.

        Moderation gate (H12.12): when JARVIS_REQUIRE_REVIEWED_SKILLS is set, only
        a skill moderated to 'approved' may be installed — an un-reviewed or
        rejected package is refused.
        """
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            conn.row_factory = sqlite3.Row
            with self._lock:
                acquired = conn.execute(
                    "SELECT 1 FROM marketplace_acquired_skills WHERE name = ?",
                    (skill_name,),
                ).fetchone()
                if acquired is not None:
                    raise PermissionError(
                        "sandbox broker is the only install path for acquired packages"
                    )
                row = conn.execute(
                    "SELECT package_zip, review_status, version FROM marketplace_skills WHERE name = ?",
                    (skill_name,),
                ).fetchone()
            if not row:
                raise ValueError(f"Skill '{skill_name}' not found in registry database.")
            zip_data = row["package_zip"]
            status = row["review_status"] or REVIEW_PENDING
            version = row["version"]
        finally:
            conn.close()

        self._enforce_skill_contract("install", skill_name, review_status=status, version=version)

        if _require_reviewed() and status != REVIEW_APPROVED:
            raise PermissionError(
                f"Skill '{skill_name}' is not approved (review status: {status}). "
                "Moderate it to 'approved' before installing (JARVIS_REQUIRE_REVIEWED_SKILLS)."
            )

        installed = self.install_from_zip(zip_data)
        if installed:
            self._record_history(skill_name, version, "install")
        return installed

    def _safe_skill_dir(self, raw_name: str, *, action: str = "install") -> Path:
        """Resolve a skill name to a directory strictly inside ``skills_dir``.

        Used for both install (name derived from an untrusted SKILL.md heading)
        and uninstall so a name with a separator, ``.``/``..``, or a NUL can never
        escape the skills tree. Returns the resolved, in-tree target directory.
        """
        folder = (raw_name or "").lower().replace(" ", "_").strip()
        if not folder or folder in (".", "..") or "/" in folder or "\\" in folder or "\x00" in folder:
            raise ValueError(f"invalid skill name: {raw_name!r}")
        base = self.skills_dir.resolve()
        target = (self.skills_dir / folder).resolve()
        if target == base or base not in target.parents:
            raise ValueError(f"refusing to {action} outside the skills directory: {raw_name!r}")
        return target

    def uninstall_skill(self, skill_name: str, *, purge: bool = False) -> bool:
        """Remove an INSTALLED skill from disk (0.58 Pack Manager).

        Safe by construction: *skill_name* is the on-disk directory name and must
        resolve **strictly inside** ``skills_dir`` — a name with a path separator,
        ``..`` traversal, or a NUL is refused (mirrors the install-time zip-slip
        guard). Returns True when a directory was removed, False when nothing was
        installed under that name.

        The published package is **retained** by default, so ``install_skill`` can
        restore it (the recovery path, since the registry keeps one version). Pass
        ``purge=True`` to also delete the marketplace registry row (full unpublish).
        """
        name = (skill_name or "").strip()
        if not name or name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
            raise ValueError(f"invalid skill name: {skill_name!r}")
        base = self.skills_dir.resolve()
        target = (self.skills_dir / name).resolve()
        if target == base or base not in target.parents:
            raise ValueError(f"refusing to remove outside the skills directory: {skill_name!r}")
        self._enforce_skill_contract("uninstall", name, purge=bool(purge), installed=target.exists())

        # capture the version before a purge drops the registry row
        version = self._registry_version(name) if self._history is not None else None

        removed = False
        if target.exists() and target.is_dir():
            import shutil
            shutil.rmtree(target)
            removed = True
        if purge:
            self.remove_from_registry(name)
        if removed and version:
            self._record_history(name, version, "uninstall")
        logger.info("Uninstalled a marketplace skill (removed=%s, purged=%s)", removed, purge)
        return removed

    def remove_from_registry(self, skill_name: str) -> bool:
        """Delete a skill's marketplace registry row (full unpublish). Returns True
        when a row was deleted, False when no such skill was registered."""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            with self._lock:
                cur = conn.execute("DELETE FROM marketplace_skills WHERE name = ?", (skill_name,))
                conn.commit()
                return cur.rowcount > 0
        finally:
            conn.close()

    @staticmethod
    def _safe_targets(zip_file: "zipfile.ZipFile", target_dir: Path) -> None:
        """Reject zip-slip / path-traversal entries before extraction (H12.12).

        ``ZipFile.extractall`` does not reliably stop ``../`` escapes, so a
        malicious skill package could write outside the skills directory. Verify
        every member resolves inside *target_dir* first, and fail closed if not.
        """
        base = target_dir.resolve()
        for member in zip_file.namelist():
            dest = (base / member).resolve()
            if dest != base and base not in dest.parents:
                raise ValueError(f"Unsafe path in skill package (zip-slip blocked): {member}")

    def install_from_zip(self, zip_bytes: bytes) -> bool:
        """
        Extract files from zip_bytes into the skills/ directory.

        Hardened (H12.12): path-traversal entries are rejected before extraction,
        and when JARVIS_REQUIRE_SIGNED_SKILLS is set the extracted package must
        carry a valid SKILL.sig (else it's removed and the install is refused).
        """
        zip_buffer = io.BytesIO(zip_bytes)

        skill_name = None
        manifest_filename = None

        with zipfile.ZipFile(zip_buffer, "r") as zip_file:
            for name in zip_file.namelist():
                if Path(name).name == "SKILL.md":
                    manifest_filename = name
                    break

            if not manifest_filename:
                raise ValueError("SKILL.md manifest file missing in ZIP package.")

            skill_md_content = zip_file.read(manifest_filename).decode("utf-8")

            for line in skill_md_content.split("\n"):
                stripped = line.strip()
                if stripped.startswith("# "):
                    skill_name = stripped[2:].strip()
                    break

            if not skill_name:
                skill_name = Path(manifest_filename).parent.name or "imported_skill"

            # skill_name is the untrusted '# ' heading of SKILL.md inside the zip.
            # Validate the derived folder BEFORE mkdir/extract, or a heading like
            # '# ..' / '# /etc/cron.d' relocates target_dir outside skills_dir and
            # the zip-slip guard (which checks members against target_dir) passes.
            target_dir = self._safe_skill_dir(skill_name)
            target_dir.mkdir(parents=True, exist_ok=True)

            self._safe_targets(zip_file, target_dir)  # zip-slip guard
            zip_buffer.seek(0)
            zip_file.extractall(target_dir)

        # Signature gate: SKILL.sig lives at the package root (manifest dir).
        sig_dir = target_dir / Path(manifest_filename).parent
        trusted, reason = signing.verify_skill(sig_dir)
        if signing.require_signed() and not trusted:
            import shutil
            shutil.rmtree(target_dir, ignore_errors=True)
            raise PermissionError(
                f"Skill '{skill_name}' rejected: {reason} (JARVIS_REQUIRE_SIGNED_SKILLS)."
            )

        # Marketplace content remains external after extraction. A package cannot
        # self-grant the separate owner approval used for in-process execution.
        provenance_dirs = {target_dir, sig_dir}
        for provenance_dir in provenance_dirs:
            (provenance_dir / OWNER_APPROVED_MARKER).unlink(missing_ok=True)
            (provenance_dir / EXTERNAL_SOURCE_MARKER).write_text(
                "source=marketplace\n", encoding="utf-8"
            )

        # Avoid logging the package-derived name/path (log-injection); signature
        # reason is a fixed label.
        logger.info("Installed a marketplace skill package (signature: %s)", reason)
        return True
