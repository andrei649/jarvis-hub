"""drive_sync.py — fast personal import of a Google Drive folder via rclone.

PERSONALIZATION — **PRIVATE**. Pulls an owner-configured Drive folder (e.g. the
root "AI" folder) into a local, **gitignored** runtime-data dir (under the
`data_path` root, default `memory_logs/`, honoring `$JARVIS_HOME`) so the existing
local-docs indexer (H12.2) can ingest it into memory.

Nothing personal is committed:
  * the rclone **remote** (which holds the Google Drive OAuth) lives in the user's
    own `rclone.conf` (managed by `rclone config`), never in this repo;
  * the **synced content** lands in a gitignored path;
  * only the *remote name* and *dest path* are read from env — no secrets here.

rclone is the host seam; the subprocess runner is injectable for offline tests.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Awaitable, Callable, Optional

from agents.core.paths import data_path

logger = logging.getLogger("jarvis.ingestion.drive")

# runner(argv) -> (returncode, stdout, stderr)
Runner = Callable[[list[str]], Awaitable[tuple[int, str, str]]]

_DEFAULT_FLAGS = ["--fast-list", "--drive-acknowledge-abuse"]


async def _default_runner(argv: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


class DriveAISync:
    """One-way Drive→local mirror of a configured folder via rclone."""

    def __init__(
        self,
        remote: str,
        dest,
        *,
        mode: str = "copy",
        flags: Optional[list[str]] = None,
        runner: Optional[Runner] = None,
    ) -> None:
        self.remote = (remote or "").strip()
        self.dest = Path(dest)
        # copy = non-destructive (default); sync = mirror (deletes local extras).
        self.mode = mode if mode in ("copy", "sync") else "copy"
        self.flags = list(flags) if flags is not None else list(_DEFAULT_FLAGS)
        self._runner = runner or _default_runner

    @classmethod
    def from_env(cls, runner: Optional[Runner] = None) -> "DriveAISync":
        """Build from env. `JARVIS_DRIVE_AI_REMOTE` is e.g. `gdrive:AI` (an rclone
        remote + path). Dest defaults to the gitignored `data_path("drive_ai")`."""
        remote = os.environ.get("JARVIS_DRIVE_AI_REMOTE", "").strip()
        dest = os.environ.get("JARVIS_DRIVE_AI_DEST", "").strip() or str(data_path("drive_ai"))
        mode = os.environ.get("JARVIS_DRIVE_AI_MODE", "copy").strip().lower()
        raw_flags = os.environ.get("JARVIS_DRIVE_AI_FLAGS", "").strip()
        flags = raw_flags.split() if raw_flags else None
        return cls(remote=remote, dest=dest, mode=mode, flags=flags, runner=runner)

    def available(self) -> bool:
        """A remote is configured AND rclone is on PATH (host seam)."""
        return bool(self.remote) and shutil.which("rclone") is not None

    def argv(self) -> list[str]:
        return ["rclone", self.mode, self.remote, str(self.dest), *self.flags]

    async def sync(self) -> dict:
        """Run the rclone transfer. Best-effort: returns a summary dict, never
        raises — a sync failure must not break startup."""
        if not self.remote:
            return {"ok": False, "error": "JARVIS_DRIVE_AI_REMOTE not set", "dest": str(self.dest)}
        try:
            self.dest.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {"ok": False, "error": f"cannot create dest: {e}", "dest": str(self.dest)}

        try:
            code, out, err = await self._runner(self.argv())
        except FileNotFoundError:
            return {"ok": False, "error": "rclone not installed (host)", "dest": str(self.dest)}
        except Exception as e:  # pragma: no cover - defensive
            return {"ok": False, "error": repr(e), "dest": str(self.dest)}

        ok = code == 0
        if not ok:
            logger.warning("rclone %s failed (code=%s): %s", self.mode, code, (err or "")[-400:])
        summary = {
            "ok": ok,
            "remote": self.remote,
            "dest": str(self.dest),
            "mode": self.mode,
            "returncode": code,
        }
        if not ok:
            summary["error"] = (err or out or "")[-400:]
        return summary
