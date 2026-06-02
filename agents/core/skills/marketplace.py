"""
marketplace.py — Dynamic Skill sharing registry & Agent Marketplace.
Provides SQLite DB persistence, ZIP packaging/unpacking, and dynamic loader integration.
"""

import io
import json
import logging
import sqlite3
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

from .loader import SkillLoader

logger = logging.getLogger("jarvis.skills.marketplace")

# Locate the DB under memory_logs/
DB_PATH = Path(__file__).parent.parent.parent.parent / "memory_logs" / "marketplace.db"


class SkillMarketplace:
    def __init__(self, skills_dir: str = "skills"):
        self.skills_dir = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = DB_PATH
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
                    published_at TEXT NOT NULL
                )
            """)
            conn.commit()
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

        # Build Zip archive in memory
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
                conn.execute(
                    """
                    INSERT OR REPLACE INTO marketplace_skills
                    (name, version, description, author, agents, requires, package_zip, published_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        manifest.get("name", skill_name),
                        manifest.get("version", "0.1.0"),
                        manifest.get("description", ""),
                        manifest.get("author", "unknown"),
                        ",".join(manifest.get("agents", [])),
                        ",".join(manifest.get("requires", [])),
                        zip_data,
                        datetime.now(timezone.utc).isoformat()
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
                    "SELECT name, version, description, author, agents, requires, published_at FROM marketplace_skills"
                ).fetchall()
            return [
                {
                    "name": r["name"],
                    "version": r["version"],
                    "description": r["description"],
                    "author": r["author"],
                    "agents": r["agents"].split(",") if r["agents"] else [],
                    "requires": r["requires"].split(",") if r["requires"] else [],
                    "published_at": r["published_at"]
                }
                for r in rows
            ]
        finally:
            conn.close()

    def install_skill(self, skill_name: str) -> bool:
        """
        Fetch dynamic skill package from database and extract it.
        """
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            conn.row_factory = sqlite3.Row
            with self._lock:
                row = conn.execute(
                    "SELECT package_zip FROM marketplace_skills WHERE name = ?", (skill_name,)
                ).fetchone()
            if not row:
                raise ValueError(f"Skill '{skill_name}' not found in registry database.")
            zip_data = row["package_zip"]
        finally:
            conn.close()

        return self.install_from_zip(zip_data)

    def install_from_zip(self, zip_bytes: bytes) -> bool:
        """
        Extract files from zip_bytes directly into the skills/ directory.
        Reads manifest from zip to determine exact dynamic skill name structure.
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
            
            zip_buffer.seek(0)
            zip_file.extractall(target_dir)

        logger.info(f"Successfully extracted skill package '{skill_name}' into: {target_dir}")
        return True
