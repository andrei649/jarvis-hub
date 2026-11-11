# Nerva — Upgrade Guide

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

**From Nerva itself (git checkouts, H624):** pin trust once, then plan, apply, and roll back.

```bash
nerva update trust --ssh-key ~/.ssh/release_signing.pub   # or --gpg-key key.asc --fingerprint <FPR>, or --pin <commit>
nerva update plan                                         # commits, files, lock, migrations, version from → to
nerva update apply                                        # queues an approval card; accept it in the approval queue
nerva update status                                       # trust, the update in flight, the receipts
nerva update rollback                                     # queues a card that returns to the commit before the last update
```

- **Trust.** Nerva applies only a commit (or a tag pointing at it) whose signature verifies against
  the keys you pinned, or the one commit you pinned. SSH keys go into Nerva's own allowed-signers
  file and OpenPGP keys into a dedicated keyring, both under `<data root>/update/`; your global
  git and gpg configuration is not used, and the repository's own git config cannot choose the
  program that verifies. With no trust pinned every apply is refused. Changing trust is itself an
  approval card at the irreversible tier. A signed tag must carry its own name: a tag object
  re-pointed under another tag name is refused. The trust and the receipts under
  `<data root>/update/` are live state a backup restore never replaces (an older archive's copy is
  ignored); re-pin trust through its own card.
- **Apply.** After you accept the card: HEAD, the target and its signature are re-checked, a full
  backup is created and verified, a receipt is written (`<data root>/update/receipts.jsonl`), the
  checkout is fast-forwarded to the verified sha (never a merge), `requirements-beta.lock` is
  installed with `--require-hashes --only-binary :all: --no-deps` if it changed (wheels only, so
  no package build script runs; a lock line with any pip option other than `--hash`, such as
  `--no-binary`, `--no-build-isolation`, `--index-url`, `-e`, or a direct URL, refuses the update —
  what still runs is the installed code itself, including any `.pth` file a wheel ships), and
  Nerva restarts. HEAD and the tree are re-read right before the fast-forward: a checkout that
  moved while the backup ran is not updated. Schema migrations run as each store opens.
  The log is shown in Console → Restart / Update and kept in the receipt.
- **Check after restart.** The restarted hub polls its own `/readyz` and checks it booted from the
  target commit and reports the target's version (`JARVIS_UPDATE_VERIFY_SECONDS`, default 180).
  The probe goes straight to loopback, never through `HTTP_PROXY`.
  If not, it returns to the previous commit, reinstalls the previous lock if it had changed and
  removes the packages the new lock added, stages the pre-update backup for restore when a
  migration may have run, and restarts. If the
  new code cannot start at all, `serve.py` does the same after `JARVIS_UPDATE_MAX_BOOTS`
  (default 3) failed starts. A rollback whose dependency reinstall fails (or whose backup could
  not be staged) ends **`rollback_incomplete`**, never `rolled_back`, and the receipt's
  `action_needed` names the exact command to run.
- **Possible migrations.** The plan and the card list every changed file that may migrate data:
  a migration-shaped name, a changed `.sql`, or a changed Python file under `agents/` whose
  contents (read from the target commit) hold `ALTER TABLE`/`CREATE TABLE`/`CREATE INDEX`,
  `user_version`, a schema-version constant, a migrations list or an SQLite connect — the stores
  declare their migrations inline. When the scan cannot run, a migration is assumed. The card
  says "none expected" only when no store code changed.
- **What the automatic rollback cannot do.** It runs in the release it rolls back from. A release
  whose `serve.py`, or whose `agents/core/hub_update_apply.py` and its imports, break before the
  boot guard runs cannot roll itself back through that module: `serve.py` then counts the boots
  with the standard library and, past `JARVIS_UPDATE_MAX_BOOTS`, runs `git reset --keep <from>`
  (no data restore, no dependency reinstall; the receipt ends `rollback_incomplete` when either was
  needed). When even `serve.py` does not run: stop Nerva and run
  `nerva update rollback --offline --yes`; if that does not import either, run
  `git reset --keep <from>` in the checkout (the receipt's `from`), reinstall
  `requirements-beta.lock`, and restore the pre-update backup if a migration ran.
  `nerva update status` shows this as `auto_rollback_limits`.
- **Dirty tree.** Uncommitted changes refuse the update; `nerva update apply --stash` stashes them
  first (never discards them) and the receipt names the stash.
- **Requirements.** The hub must be able to restart itself (started by `serve.py`, a service with
  the restart marker) so the new code can be checked; containers update by image.
- **Not done by the updater:** rebuilding the HUD when `frontend/` changed (the plan says so),
  channel `/update` commands, release bundles (below), and binding targets to a branch or tag
  pattern the owner pins (any trusted commit that fast-forwards HEAD is accepted).

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

After an update made by Nerva: `nerva update rollback` (an approval card; `--restore-data yes|no`
chooses whether the pre-update backup is restored — by default only when a migration may have
run), or with the hub stopped `nerva update rollback --offline --yes`.

By hand:

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

### Company mode: runs in flight when you upgrade (H464c/H464d)

Only relevant if you turned company mode on (`JARVIS_COMPANY_MODE`). From this
version a work run is tied to the exact plan you approved: it records that plan's
fingerprint when it opens, and every sweep checks the plan against it. A run that
was already open before the upgrade has no such record, so it cannot prove its plan
is still the one you approved. **On its first sweep after the upgrade it stops, once,
and does nothing else** — no step is taken and nothing is queued. The company brief
and the HUD show it as *"stopped — it was opened before this version tied a run to
the plan you approved; approve the goal again to run it"* (the stored reason is
`plan not bound to its approval: no_approved_fingerprint`). To carry on, approve the
goal again from the inbox; the new run starts its checklist from the top. Finished
runs are not touched, and the ledger's schema upgrades itself (work_runs migration
v5).

**Rolling back** the code over an upgraded database is not supported this way:
older code reads every run opened by this version as tampered (its record carries a
field the older fingerprint does not cover), which is the safe direction but makes
those runs unusable. Restore the pre-upgrade backup instead, as described under
[Rollback](#rollback).
