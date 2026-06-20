# Importing your Google Drive "AI" folder (private)

> Fast personal import of a Drive folder into Jarvis at onboarding / startup,
> via **rclone**. This is **personalization** — the content and credentials stay
> on your machine and are **never committed**. (Contrast: the vendored
> superpowers plugin under `.claude/` is public.)

## Privacy model
- The Google Drive OAuth lives in **your own `rclone.conf`** (created by
  `rclone config`), not in this repo.
- The synced content lands under **`memory_logs/drive_ai/`** (or `$JARVIS_HOME`),
  which is **gitignored** — it can never be accidentally committed.
- Only the rclone **remote name** and **dest path** are read from env
  (`.env`, also gitignored). No secrets in the repo.

## One-time setup (host)
```bash
rclone config            # create a Google Drive remote, e.g. named "gdrive"
# then in .env:
JARVIS_DRIVE_AI_REMOTE=gdrive:AI     # remote:folder (the root "AI" folder)
```

## Run it
**During onboarding (manual):**
```bash
python scripts/import_drive_ai.py
```

**Automatically at startup:** set `JARVIS_DRIVE_AI_SYNC=1`. The orchestrator then
imports the folder fire-and-forget on boot and (unless `JARVIS_DRIVE_AI_INDEX=0`)
ingests it into memory via the existing local-docs indexer (H12.2).

## Knobs (`.env`)
| Var | Default | Meaning |
|-----|---------|---------|
| `JARVIS_DRIVE_AI_REMOTE` | — | `remote:folder`, e.g. `gdrive:AI`. Empty = off. |
| `JARVIS_DRIVE_AI_SYNC` | `0` | `1` = import at startup. |
| `JARVIS_DRIVE_AI_INDEX` | `1` | `1` = also ingest into memory; `0` = files only. |
| `JARVIS_DRIVE_AI_MODE` | `copy` | `copy` (non-destructive) or `sync` (mirror — deletes local extras). |
| `JARVIS_DRIVE_AI_DEST` | `memory_logs/drive_ai` | local dest (keep it gitignored). |
| `JARVIS_DRIVE_AI_FLAGS` | — | extra rclone flags, space-separated. |

## How it composes
`DriveAISync` (`agents/core/ingestion/drive_sync.py`) only does the
Drive→local-dir transfer (rclone is the host seam; the runner is injectable for
tests). Ingestion reuses `LocalDocsIndexer` (H12.2) → `memory.remember`, so the
imported docs become searchable like any other local docs.
