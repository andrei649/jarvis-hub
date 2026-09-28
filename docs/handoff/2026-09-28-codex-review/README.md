# Review of the Codex sprint and H117 reason replies (PR #1207, 2026-09-28)

Continues [the local sprint handover](../2026-09-27-local-sprint/README.md) (Codex, `beb2ee5a`).
Claude reviewed that commit, fixed what the review confirmed, repaired an H117 regression, and
restored the ledger rows whose evidence had drifted. Nothing here was merged or deployed.

## Headline

**190/697 (27.3%) documented code-equivalent** (`HERMES_STATUS.md`), up from the 125 published
at `beb2ee5a`. No capability was added to reach it. The 65 recovered rows were never broken:
their pinned evidence had changed, so the checker withheld credit until each row was re-read.
Every one of the 76 changed rows (the 65 plus rows the fix rounds touched) had each
`path:line` citation and each claim on changed code verified against the final code by an
auditor and an independent skeptic. That produced 31 text/citation corrections and no
downgrades. H117 counts again only because its regression is fixed (below).

## What changed in code

**Codex-sprint review: six fix rounds, each red-first, then a closure check and an adversarial hunt.**
It started with no MAJOR findings, only MINOR ones, and converged at round 6 with no
regression found. The subject throughout is honest capability outcomes in
`agents/core/autonomy/worker.py`, the record behind `/api/capabilities` and earned autonomy:

- **Failure:** an attempt that could have touched the world, or machinery that broke.
- **Nothing recorded:**
  - a governance refusal before any attempt, with a per-kind vocabulary;
  - a governance withhold of a generated result (`withheld_after_generation`,
    `withheld_after_fetch`);
  - a deferral for missing configuration.
- **Success:** only an explicit success status from the kind's real handler. The `_llm`
  fallback records nothing.

Along the way:
- **Mediation store:** errors raise `MediationStateUnavailable` (a failure) instead of
  reading as "not approved".
- **House actuation:**
  - A kernel that raised or is missing is a failure. A real DENY stays a refusal.
  - A driver failure on a device that was already in the target state is `driver_failed`.
  - A stranded row carries `manual_recovery_required`.
- **Promotion:** an install that began and then broke is `install_failed`. A store that cannot
  be read is a store failure.
- **Cloud image:** a catalog-only failure after the image is durably saved is a success with a
  warning.
- **Brokers:** the call/social/writeback/node brokers lift their degraded marker.
- **Other fixes:**
  - ToolRPC scrubs the lifted `detail`.
  - Named-provider audit rows name the revision.
  - OSINT signal-layer text is tainted for the task judge.
  - Legacy blocked runs resume once every ask is answered, and stay held after an expiry.

**H117, five rounds.** A Telegram reply that answers a decision-reason prompt had become an
ordinary batched turn. Now:
- The poll loop decides, with no side effects, which replies to claim. A claimed reply is
  handled in the chat's lane, behind what the chat said before it.
- The reason window is judged by a per-`getUpdates`-page stamp. Telegram's `date` credits it
  within bounds: never after its page, never before the previous page.
- A page cut short keeps a true lower bound, and hostile dates never raise.
- Service lines (acknowledgements, attachment notices, pairing replies) are never spoken, and
  only the running turn's reply takes a chat's voice mark.

**Tests and inventory.** Line-keyed orchestrator binding inventory updated after review, and
the URL monitor deadline test made robust on a loaded runner.

## Verification (python3.12)

- **Full backend suite at `7a7f976a`:** 19,824 tests.
  - 4 failures, all fixed since: two binding-inventory tests (line numbers), the Hermes report
    check (records not yet written) and a 10 ms timing test.
  - The final head adds 2 tests.
- **Each round's related selection:** up to 5,975 tests, 0 failures.
- **Mutants:** 20 to 36 per round, all killed or proven equivalent.
- **Lint and SAST:** ruff and the bandit baseline gate pass.
- **Frontend:** unchanged since `beb2ee5a`.

## Known gaps (documented, not fixed)

1. **goal.approve:** ~~a retry after `open_run`'s commit raises opens a second run with a new
   goal_id.~~ **Closed by H464c (2026-09-28):** `open_run` checks and inserts in one write
   transaction that rolls back on any failure, and a `task:<id>:…` approval opens one run,
   ever — the retry gets the first attempt's run (and its goal id) or `approval_already_used`
   (`tests/test_h464c_company_run_binding.py`).
2. **permission.grant:** `_audit` or `commit` raising after `_insert` lets a retry insert a
   second grant.
3. **channel.reply:** `record_outbound` raising after the send lets a retry send again.
4. **Credential:** `credential_not_configured` also covers a secret that cannot be decrypted.
   The fix belongs in the protected `agents/core/security/secret_broker.py`, so it is **owner,
   security last**.
5. **ComfyUI:** the provider drops the post-request guard (`media_backends/registry.py`), so a
   kernel change mid-generation still publishes.
6. **skill.install:** a reconciled install reads as `promotion_refused`.
7. **DONE transition:** when it fails, the handler runs again. Only the record is correct.
8. **Model removed:** removing the approved image model mid-request records a failure
   (`model_not_configured`).
9. **Offline call rail:** it still spends an attention-budget slot for a deferred call.
10. **Mediation-store failure:** at the worker's pre-dispatch check it records nothing. At the
    guard it records a failure.
11. **Lost cloud-image configuration record:** it reads as the governance decline
    `configuration_changed`.
12. **H117, documented behaviour:**
    - stop/start keeps the previous page as a bound;
    - a job fired *inside* a running voice turn's context (APScheduler re-armed by that turn)
      can take that turn's mark.

## For the owner

- **`AGENTS.md` (not edited here).** Codex's commit added two sections:
  - `Safe task start` has "Keep this sprint local: no push, merge, or deployment until the
    owner requests publication".
  - `Coordination and leases` has a Codex-specific resource plan: at most four agents, no
    subagent delegation, `gpt-6-sol`/`gpt-6-luna`/Astra models, "Work remains local".

  `AGENTS.md` is the shared instruction source for Claude, Codex, opencode and Gemini, and
  neither section has an end date. Once #1207 merges, both would bind every agent. Please
  decide whether to keep them, date them, or move them to a Codex-only note.
- **CI and security.**
  - `github-advanced-security` is a repository setting (P29 in `docs/OWNER_TASKS.md`).
  - Security-path rows (e.g. H512, `agents/core/security/**`) stay last, for you.
