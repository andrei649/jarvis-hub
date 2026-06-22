"""
marketplace.py — Dynamic Skill sharing registry & Agent Marketplace.
Provides SQLite DB persistence, ZIP packaging/unpacking, and dynamic loader integration.
"""

import io
import logging
import os
import sqlite3
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from agents.core.paths import data_path
from agents.core.persistence.migrations import apply_migrations

from . import signing
from .loader import SkillLoader

logger = logging.getLogger("jarvis.skills.marketplace")


def _v1_moderation_columns(conn: sqlite3.Connection) -> None:
    """v1 — moderation/signature columns. Guarded for older DBs that predate them
    (no-op on fresh DBs whose CREATE TABLE already declares them)."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(marketplace_skills)").fetchall()}
    if "review_status" not in cols:
        conn.execute("ALTER TABLE marketplace_skills ADD COLUMN review_status TEXT NOT NULL DEFAULT 'pending'")
    if "signature" not in cols:
        conn.execute("ALTER TABLE marketplace_skills ADD COLUMN signature TEXT DEFAULT ''")


# Forward-only, append-only. Never edit/reorder a shipped entry — only append.
_MIGRATIONS = [_v1_moderation_columns]

# Locate the DB under memory_logs/
DB_PATH = data_path("marketplace.db")

# Review states for the moderation gate (H12.12, anti-ClawHub supply chain).
REVIEW_PENDING = "pending"
REVIEW_APPROVED = "approved"
REVIEW_REJECTED = "rejected"


def _require_reviewed() -> bool:
    """When set, only skills moderated to 'approved' may be installed."""
    return os.environ.get("JARVIS_REQUIRE_REVIEWED_SKILLS", "").lower() in ("1", "true", "yes")


class SkillMarketplace:
    def __init__(self, skills_dir: str = "skills", db_path: Optional[str] = None):
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Guard concurrent publish/install from async task runners (H7.4).
        self._lock = threading.Lock()
        self._init_db()

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
            return [
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
                }
                for r in rows
            ]
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
                row = conn.execute(
                    "SELECT package_zip, review_status FROM marketplace_skills WHERE name = ?", (skill_name,)
                ).fetchone()
            if not row:
                raise ValueError(f"Skill '{skill_name}' not found in registry database.")
            zip_data = row["package_zip"]
            status = row["review_status"] or REVIEW_PENDING
        finally:
            conn.close()

        if _require_reviewed() and status != REVIEW_APPROVED:
            raise PermissionError(
                f"Skill '{skill_name}' is not approved (review status: {status}). "
                "Moderate it to 'approved' before installing (JARVIS_REQUIRE_REVIEWED_SKILLS)."
            )

        return self.install_from_zip(zip_data)

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

            skill_folder_name = skill_name.lower().replace(" ", "_")
            target_dir = self.skills_dir / skill_folder_name
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

        # Avoid logging the package-derived name/path (log-injection); signature
        # reason is a fixed label.
        logger.info("Installed a marketplace skill package (signature: %s)", reason)
        return True
