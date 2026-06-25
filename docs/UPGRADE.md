# Jarvis Hub — Upgrade Guide

> How to move to a newer version safely, and what to watch per release. See
> [`COMPATIBILITY.md`](COMPATIBILITY.md) for the SemVer contract + supported-version window
> and [`RELEASE.md`](RELEASE.md) for how releases are built/verified.

## Pre-1.0 caveat

Jarvis is **`0.x`**: under SemVer, **breaking changes can land between minor versions**
(`0.MINOR`). Only the **latest minor line** gets fixes — upgrade forward rather than
back-patching. Read the version notes below before a minor bump.

## How to upgrade

**Windows (no terminal):** double-click **`UPDATE.bat`** — pulls the latest, installs deps,
runs the tests.

**Any OS (manual):**
```bash
# 1. (recommended) back up first — see below
git pull                                   # or download the release bundle (RELEASE.md)
source .venv/bin/activate                  # Windows: .venv\Scripts\activate
pip install -r requirements-beta.txt       # refresh dependencies
python -m pytest                           # optional: confirm green before relying on it
# 2. restart the server (see "Restart" below)
```

From a **release bundle** instead of git: download `jarvis-<ver>.tar.gz`, verify it
(`sha256sum -c SHA256SUMS`, and `gpg --verify` if signed — see [RELEASE.md](RELEASE.md)),
unpack, and re-run the install step.

## Database migrations — automatic

Schema migrations apply **automatically** on first run after an upgrade: each local store
runs its own versioned migrations (the H23.7 framework) when it opens its database. There
is **no manual migration step**. Migrations are forward-only.

## Back up before upgrading (recommended)

Take a snapshot first so you can roll back: `POST /api/admin/backup` (optionally encrypted
to `.tar.gz.enc`). Because migrations are forward-only, a backup is your rollback path if a
new minor doesn't suit you.

## Restart

Stop the running server and start the new one. Shutdown is **graceful** (H23.11): `SIGTERM`
/ `systemctl stop` / closing the `START.bat` window drains in-flight requests and flushes
checkpoints before exiting, bounded by `JARVIS_SHUTDOWN_TIMEOUT`.

## Rollback

1. Restore the pre-upgrade **backup** (covers data + settings at rest).
2. Check out the previous **git tag** / unpack the previous **release bundle**.
3. Reinstall deps for that version and restart.

## Version notes

Per-release notes for notable or breaking changes. The authoritative roadmap is the
**Version Roadmap** in [`BACKLOG.md`](../BACKLOG.md#version-roadmap); GitHub Releases carry
auto-generated changelogs.

| Version line | Notes |
| --- | --- |
| `0.x` (current) | Active pre-1.0 development. Minor bumps may change internal surfaces; data migrations are automatic and forward-only. No action needed beyond the steps above. |

*(As 1.0 nears, breaking changes between minors will be called out here explicitly.)*
