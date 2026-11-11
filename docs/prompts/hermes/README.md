# Hermes bucket prompts (ultracode)

> **Inactive archive, 2026-11-04.** These four prompts document the 2026-09-28
> bucket campaign on draft #1207. Do not launch them, push their shared branch,
> or use their protected-path and stale-evidence rules as current authority.
> The active local 697-contract workflow is
> [autonomous-development-objective.md](../../hermes/autonomous-development-objective.md),
> starting from [CAMPAIGN_HANDOFF.md](../../hermes/CAMPAIGN_HANDOFF.md) and the
> current checkout/SHA. Integrate the current batch first. Select and review
> relevant rows with the bounded query tools; do not treat all stale citations as
> automatic loss of acceptance or change recorded statuses without evidence.
> No stage, commit, push, merge, deploy, PR update, paid activation, or schedule
> reactivation in the current campaign. Owner-only actions remain owner-only.

<details>
<summary>2026-09-28 bucket launch notes — inactive archive</summary>

Four self-contained prompts, one per ledger bucket, for a fresh Claude Code session with ultracode on
(`/effort ultracode`). Each computes its rows live from `scripts/hermes_status.py`, so the counts in it
are a snapshot, not a contract. Written 2026-09-28 at `abf0aebd` and checked against the repo.

Since 2026-11-10 evidence is no longer hash-pinned: rows sit in feature areas (`docs/hermes/areas.json`)
whose acceptance suites keep equivalent rows honest, and restamping is retired. Each prompt opens with
a note that overrides its older pin/restamp instructions.

| Bucket | Prompt | What the session does |
|---|---|---|
| missing | [missing.md](missing.md) | builds missing rows to equivalent, or an honest partial |
| partial | [partial.md](partial.md) | closes `remaining` items, nearest-to-equivalent first |
| equivalent | [equivalent.md](equivalent.md) | audits the 190, the 108 inherited 7 September rows first; downgrades honestly |
| needs_review | [needs-review.md](needs-review.md) | records work: re-reads rows a failing area suite demoted, assesses reopened ones |

Historical launch text (inactive): `Read docs/prompts/hermes/<bucket>.md from branch claude/cto-session-recovery-qinvkg and execute it.`

Historically, all four pushed to the same branch and edited the same ledger (`docs/hermes/assessment.json`) and generated
reports. Each prompt merges and regenerates before every push, but running them in parallel still
costs merge work. Run at most two at a time, and prefer pairing a records bucket (equivalent or
needs_review) with a build bucket (missing or partial).

Historical 2026-09-28 owner-only classification for those prompts (not the
current local-development authorization):
- every path in `selfdev-policy.json` → `protected_paths`, including `agents/core/kernel/**`,
  `agents/core/security/**`, `agents/core/secrets/**`, `AGENTS.md` and `.github/workflows/**`;
- rows that need network or hardware;
- the decisions in `docs/OWNER_TASKS.md`.

A single driver session can run all four in order: see `docs/handoff/2026-09-28-handover/PROMPT.md`.

</details>
