# Maintenance Runbook — "if the owner disappears for a month"

> The bus-factor-1 mitigation from [REVIEW_YEAR_ONE](REVIEW_YEAR_ONE.md) §9.7, drafted by
> Fable 5 (2026-07-07, see [handoff](handoff-fable-2026-07-07.md) §4.6). Everything here is
> derived from the repo and its docs; items the drafter could not verify on the real
> Windows/RTX box are marked **[owner: verify]**. Correct those, then delete this note.

**Audience:** future-you after a long gap, a family member keeping the box alive, or a new
maintainer. **Goal:** keep the system *running and safe* with zero feature work.

---

## 1. What this is, in three lines

A local-first multi-agent AI assistant ("Jarvis Hub"): Python 3.12 + FastAPI on port
**8080**, talking to a local LLM via **LM Studio** (port 1234) or Ollama, with 18 agents,
a web HUD at `http://127.0.0.1:8080/`, and all personal state in local files. Cloud calls
are opt-in per agent; `frigga`/`ultron`/`howard` never leave the machine. A separate Node
stack (WorldView, ports 3000/4000) is optional and independent.

## 2. Start / stop / health

```bash
pip install -r requirements-beta.txt   # or: pip install --require-hashes -r requirements-beta.lock
python serve.py                        # canonical entry; HUD on http://127.0.0.1:8080/
python scripts/install_smoke.py --json # ~30s self-test: boot + /readyz + one fake turn
```

- Health probes: `GET /healthz` (liveness) · `GET /readyz` (readiness).
- Run as a service: `deploy/systemd/` (Linux) or `deploy/windows/install-service.ps1`
  (NSSM) — both documented in [`deploy/README.md`](../deploy/README.md).
- The production box is Windows + RTX 5090, LM Studio serving the local model
  **[owner: verify current model + LM Studio autostart setup]**.
- Stop: Ctrl+C / service stop — shutdown is bounded and drains in-flight requests
  (`JARVIS_SHUTDOWN_TIMEOUT`).

## 3. Where the state lives (the only things that can't be re-downloaded)

| Path | Contents |
|------|----------|
| `memory_logs/` | ALL runtime state: settings.db, checkpoints, audit log (Merkle), autonomy queue, embeddings cache, cognition stores |
| `agents/data/` | personal memory + ingested corpus |
| `agents/<id>/SOUL.local.md`, `HEARTBEAT.local.md` | personalized agent souls (gitignored; templates in git are generic) |
| `.env` | API keys/tokens (never in git) **[owner: verify where the box's copy is backed up]** |

Everything else is reproducible from git + `pip install`.

## 4. Backup & restore (do this before ANY upgrade or experiment)

```bash
scripts/backup-data.sh                # or backup-data.ps1 on Windows → ./backups/
scripts/backup-data.sh restore <file> # restore (overwrites)
python -m agents.core.data_export     # portable data export CLI (H23.9; also POST /api/admin/export)
```

Backups are encrypted once a key is set (AUD-1). The restore drill is part of
[MANUAL_TESTING.md](MANUAL_TESTING.md). Forget/erase: `POST /api/admin/forget` or the CLI
(AUD-2) — clears memory at rest *and* live.

## 5. Upgrading

1. Backup first (§4). 2. `git pull` on `main` (CI is green-gated; every merge passed the
full offline suite). 3. Reinstall deps (`pip install -r requirements-beta.txt`).
4. Restart; DB schemas migrate automatically (`PRAGMA user_version`, H23.7 — never edit
shipped migrations). 5. `python scripts/install_smoke.py --json` must pass.
Contract & supported versions: [COMPATIBILITY.md](COMPATIBILITY.md) · [UPGRADE.md](UPGRADE.md).

## 6. When something is wrong (triage order)

1. **HUD dead / 503** → is the server up? `GET /readyz`. Restart via §2. Logs rotate under
   `memory_logs/` (`JARVIS_LOG_MAX_MB`/`JARVIS_LOG_BACKUPS`).
2. **Replies degraded / "LLM unavailable"** → LM Studio isn't serving. Open LM Studio, start
   the server, load the model (or chat "start LM Studio" — governed, H23.12 degrades
   gracefully meanwhile). Troubleshooting table: [ARCHITECTURE.md](ARCHITECTURE.md) §5.
3. **Autonomy doing something you don't like** → kill-switch: HUD Trust panel or
   `POST /api/security/kill-switch` — tasks hold, nothing is lost; disengage releases them.
4. **Weird behavior after an upgrade** → restore the pre-upgrade backup (§4), pin the
   previous tag, file the diff.
5. **Security worry** → `GET /api/security/posture` + audit log verify; docs:
   [THREAT_MODEL.md](THREAT_MODEL.md), [SECURITY.md](../SECURITY.md), [PRIVACY.md](PRIVACY.md).

## 7. Monthly minimum (≈30 min, keeps it alive indefinitely)

- [ ] `git pull` + restart + smoke (§5) — or consciously decide to stay pinned.
- [ ] Run a backup (§4); spot-check one restore per quarter.
- [ ] Glance at GitHub Dependabot/CodeQL alerts; merge the green dependency PRs. (If a merge is refused with
      *"a lock file already exists in the repository"*, it's transient — see §9.)
- [ ] `GET /api/metrics/north-star` still responds; interrupt budget ≤4/day holds.
- [ ] Nothing new listening on the network that you didn't configure (`GET /api/admin/network/calls`).

## 8. If handing to a NEW maintainer

Read in this order: [MOONSHOT.md](../MOONSHOT.md) (why) → [STATUS.md](../STATUS.md) (where)
→ [BACKLOG.md](../BACKLOG.md) (what's next) → [ARCHITECTURE.md](ARCHITECTURE.md) (how) →
[AGENTS.md](../AGENTS.md) (rules). AI assistants: start with `.claude/skills/jarvis-load-context`.
The non-negotiables are MOONSHOT §5 — local-first, opt-in cloud, strict-local agents stay
strict-local. CI enforces the rest (route parity, auth matrix, lockfiles, eval gate).

## 9. Git / GitHub: "a lock file already exists" & other merge/push errors

Hitting **`A lock file already exists in the repository, which blocks this operation from completing.`** when
merging a PR, pushing, or committing a file via the GitHub API/UI? It is a **transient HTTP 409**, not corruption
and not a file in the repo. GitHub serializes writes to a repo's git backend; when a previous write (a merge, a
push, a branch update, or a draft→ready flip fired in the same instant) is still in flight — or left a stale
`.lock` on a ref such as `refs/heads/main.lock` — the next write is rejected until the lock is released. GitHub
reaps stale ref locks automatically within seconds. (The tracked lock files in the tree — `*.lock`,
`package-lock.json`, `requirements*.lock` — are unrelated *dependency* locks; deleting them fixes nothing here.)

**Resolution ladder:**

1. **Retry after ~10–30s.** This clears it almost every time (it did for the H34.2/#726 merge — refused once,
   then clean on the second try).
2. **Don't fire two writes at the same ref at once:** e.g. converting a PR draft→ready and merging it in the same
   second, an auto-merge racing a manual merge, or two sessions/agents pushing the same branch. Serialize them.
3. **If it persists over several minutes:** re-fetch the PR *fresh* (not a cached view) and confirm it is not still
   a draft and `mergeable_state` is `clean`; check no branch-protection / merge-queue job is holding the ref. Then
   try a different merge method (`squash` / `merge` / `rebase` touch the ref slightly differently), or merge locally
   and push: `git fetch origin main && git checkout main && git merge --no-ff <branch> && git push`.

**Local look-alike (different cause, same words):** if a *local* git command says
`Unable to create '.git/…/index.lock': File exists`, a previous git process crashed or is still running. Confirm
none is running, then remove that one stale lock: `rm -f .git/index.lock`. This is a local filesystem lock, distinct
from the server-side ref lock above — the tree in this repo carries no stale `.git/*.lock` files by default.

## 10. Merge deadlock: a required check that will never report ("Expected — Waiting for status to be reported")

Distinct from §9. §9 is a *transient* 409 that clears on retry; this one is a **configuration
deadlock** that never clears on its own.

**Symptom.** A PR sits at `mergeStateStatus: BLOCKED` with one or more checks shown as
**"Expected — Waiting for status to be reported"**. Nothing is queued, nothing is running, and the
hourly `pr-auto-merge.yml` sweep never picks the PR up — that sweep merges only PRs GitHub reports
as CLEAN, so a permanently-BLOCKED PR is simply skipped forever.

**Cause.** Branch protection (or a ruleset) on `main` still lists **check names whose workflows no
longer produce them**. The 2026-08-29 de-gate (#981) removed the `pull_request:` trigger from — or
deleted outright — every PR-blocking workflow. A required name with no workflow behind it can never
post a status, so the PR can never go CLEAN. The repo half of the de-gate is done and verifiable in
the tree (`.github/workflows/` no longer contains `security.yml`; `codeql.yml`, `e2e.yml` and the
rest have no `pull_request` trigger). The **settings** half is owner-side and cannot be observed
from the repo — `docs/OWNER_TASKS.md` itself notes that if #981 was merged via admin bypass rather
than by clearing the settings, the stale names are still there. This deadlock is what that looks
like.

**Resolution ladder:**

1. **Clear the stale names (the real fix, owner-only).** Settings → Rules / Branch protection for
   `main` → *Require status checks to pass* → remove the required status checks that no workflow
   emits. The exact
   list to drop is in [`OWNER_TASKS.md`](OWNER_TASKS.md) → "De-gate merges"; the per-group mapping
   of check name → workflow is the table in [`docs/restore/README.md`](restore/README.md). Also
   check *Require review from Code Owners* (CODEOWNERS was deleted — restore group I) and the
   CodeQL merge-protection ruleset (group K).
2. **Interim: admin-bypass merge.** Unblocks the one PR in front of you and leaves the deadlock in
   place for the next one. Use it to land the fix, not as the fix.
3. **If the gate is actually wanted back, restore BOTH halves.** Apply the workflow patch from
   `docs/restore/groups/<group>.patch` **and** re-add that group's check names in branch
   protection. Restoring one half reproduces the deadlock from the other direction: a required name
   with no workflow blocks everything, and a workflow with no required name blocks nothing while
   looking like a gate.

**Telling the two apart:** *"A lock file already exists"* → §9, transient, retry.
*"Expected — Waiting for status to be reported"* → this section, configuration, retrying forever
will not help.
