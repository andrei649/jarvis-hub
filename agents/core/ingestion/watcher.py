"""
watcher.py — Continuous Ingestion Watcher for Howard's Digital Twin.

Monitors the data/ facebook and whatsapp export directories recursively.
If any new or modified conversation files are found, it triggers the IngestionPipeline
to automatically ingest the new chat history, update stylometry/knowledge,
and rebuild cached embeddings.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from agents.core.paths import data_path

from .pipeline import IngestionPipeline

logger = logging.getLogger("jarvis.ingestion.watcher")


class IngestionWatcher:
    """Recursively monitors data directories for exports and triggers ingestion."""

    def __init__(
        self,
        data_root: str = "data",
        state_path: str = None,
        pipeline: Optional[IngestionPipeline] = None,
    ):
        self.data_root = Path(data_root)
        self.state_path = Path(state_path) if state_path is not None else data_path("archive", "watcher_state.json")
        self.pipeline = pipeline or IngestionPipeline(data_root=data_root)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_current_files(self) -> dict[str, float]:
        """Scan data directories recursively for JSON and TXT files.

        Returns a dictionary mapping relative file paths to their modification times.
        """
        current = {}
        if not self.data_root.exists():
            return current

        # Search for Facebook messages (*.json) and WhatsApp exports (*.txt)
        for ext in ("**/*.json", "**/*.txt"):
            for path in self.data_root.glob(ext):
                if path.is_file():
                    try:
                        rel = str(path.relative_to(self.data_root))
                        current[rel] = path.stat().st_mtime
                    except Exception as e:
                        logger.warning(f"Failed to stat {path}: {e}")
        return current

    def _load_state(self) -> dict[str, float]:
        """Load the last seen file states from disk."""
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to read watcher state: {e}")
            return {}

    def _save_state(self, state: dict[str, float]) -> None:
        """Save the current file states to disk."""
        try:
            self.state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to write watcher state: {e}")

    def check_and_run(self) -> bool:
        """Check for folder updates; run ingestion pipeline if changes are found.

        Returns True if pipeline ran successfully, False otherwise.
        """
        if not self.data_root.exists():
            # Dynamically create the folder structures if they do not exist
            self.data_root.mkdir(parents=True, exist_ok=True)
            (self.data_root / "facebook" / "messages" / "inbox").mkdir(parents=True, exist_ok=True)
            (self.data_root / "whatsapp").mkdir(parents=True, exist_ok=True)
            logger.info("Ingestion folder structures created dynamically")

        current = self._get_current_files()
        previous = self._load_state()

        # Check for additions or modification changes
        changes = []
        for file, mtime in current.items():
            if file not in previous:
                changes.append(f"new: {file}")
            elif previous[file] != mtime:
                changes.append(f"modified: {file}")

        # Check for deletions
        for file in previous:
            if file not in current:
                changes.append(f"deleted: {file}")

        if not changes:
            logger.debug("Ingestion Watcher: no changes detected.")
            return False

        logger.info(f"Ingestion Watcher: changes detected! ({len(changes)} files). Running pipeline...")
        logger.info(f"Changes: {', '.join(changes[:5])}" + ("..." if len(changes) > 5 else ""))

        try:
            # Re-run pipeline to fully consolidate SQLite / Embeddings cache
            self.pipeline.run()
            # Update disk state to avoid double-runs
            self._save_state(current)
            logger.info("Ingestion Watcher: pipeline ran and state updated successfully.")
            return True
        except Exception as e:
            logger.error(f"Ingestion Watcher: pipeline run failed: {e}")
            return False
