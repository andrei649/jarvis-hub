#!/usr/bin/env python3
"""import_drive_ai.py — onboarding helper: pull the Drive "AI" folder locally.

PRIVATE personalization. Uses rclone to mirror the owner-configured Google Drive
folder into a gitignored local dir (default `memory_logs/drive_ai`). The repo
never sees the content or the Drive credentials — only the rclone remote *name*
and dest path (from env). Run once during onboarding, or let startup do it
automatically with JARVIS_DRIVE_AI_SYNC=1.

Setup (one-time, host):
  1. rclone config         # create a Google Drive remote, e.g. named "gdrive"
  2. export JARVIS_DRIVE_AI_REMOTE=gdrive:AI   # remote:folder
  3. python scripts/import_drive_ai.py

Ingestion into memory happens at server startup (the local-docs indexer) or via
the HUD onboarding; this script only does the fast file import.
"""

import asyncio
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "agents"))

from agents.core.ingestion.drive_sync import DriveAISync


async def _main() -> int:
    sync = DriveAISync.from_env()
    if not sync.remote:
        print("✗ JARVIS_DRIVE_AI_REMOTE is not set (e.g. 'gdrive:AI'). "
              "Run `rclone config` first, then export it.")
        return 2
    if not sync.available():
        print("✗ rclone is not on PATH. Install rclone, then re-run.")
        return 2

    print(f"→ rclone {sync.mode} {sync.remote} → {sync.dest}")
    summary = await sync.sync()
    if summary.get("ok"):
        print(f"✓ Imported to {summary['dest']} (gitignored). "
              f"Ingestion runs at server startup / via HUD onboarding.")
        return 0
    print(f"✗ Import failed: {summary.get('error')}")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
