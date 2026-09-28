# Handover: Hermes integration, PR #1207 (2026-09-28)

Branch `claude/cto-session-recovery-qinvkg`, **draft** PR #1207, synced with `main` on 2026-09-28 (`49371022`,
#1211). Nothing is merged or deployed. The prompt to paste into the next session is in [PROMPT.md](PROMPT.md).

## Where things stand

- **Headline: 190/697 (27.3%) equivalent.**
  - 190 equivalent: 82 re-proven on code in this sprint, 108 inherited from the 7 September audit and never re-read.
  - 254 partial and 64 missing.
  - 189 needs review: 107 rows the owner reopened (no credit, never reviewed) and 82 partial/missing rows whose
    evidence drifted.
  - Live numbers: `python3 scripts/hermes_status.py summary`.
- **This session (Claude, 2026-09-27/28):**
  - **Codex's sprint** (`beb2ee5a`) reviewed and fixed in six rounds: honest capability outcomes and machinery-versus-
    governance classes.
  - **H117** reason-reply regression fixed in five rounds.
  - **65 drifted rows restored** and 76 rows content-audited: 125 → 190.
  - **H464** rounds 1–2: the shipped Company Mode runtime now builds and parks finished plans on their in-flight tasks,
    bound to the approved goal. It is still partial.
  - **Four bucket prompts** written.
  - Details are in [the Codex review note](../2026-09-28-codex-review/README.md), `BACKLOG.md` (Hermes sprint section) and
    the PR body.
- **H464 round 3** landed in `b06fbaf0`. Its latent and bounded residuals (two MINOR, NITs, test gaps) are listed at the
  top of [h464-round3-brief.md](h464-round3-brief.md).
- **CI:**
  - The heads pushed this session (`788fc05f`, `8d256171`) passed every check.
  - `github-advanced-security` did not report on them. It is a repository setting and yours (P29).
  - This handover push also lands H464 rounds 1–2 and the sync with `main`, so check CI on the new head.

## How to continue

- **Per bucket:** [docs/prompts/hermes/](../../prompts/hermes/README.md) holds four self-contained ultracode prompts:
  missing, partial, equivalent and needs-review.
  - They all push to this branch and edit the same ledger.
  - Run at most two at once, one records bucket (equivalent or needs-review) with one build bucket (missing or partial).
  - Every session must merge and regenerate before each push. Never rebase or force-push.
- **One driver session:** use [PROMPT.md](PROMPT.md). It checks the PR, lands H464 round 3 if missing, then works through
  the buckets in order.

## Owner items (not for agents)

1. **`AGENTS.md`:** Codex added "Keep this sprint local…" and a Codex-only resource plan with no end date. Once merged
   they bind every agent. Keep them, date them, or move them to a Codex-only note.
2. **H464 decisions:** P31.1–3 in `docs/OWNER_TASKS.md`.
   - Is a pid wait required?
   - May a local model judge or plan company runs unattended?
   - Should you be able to park a run by hand?
3. **H427** waits on P30.2.
4. **Security rows last, yours:** e.g. H512, `agents/core/security/**`. Known gap 4 of the Codex review:
   `credential_not_configured` also covers a secret that cannot be decrypted.
5. **`github-advanced-security`** (P29) is a repository setting.
6. **Canva:** the connector is connected but still needs OAuth in claude.ai → Settings → Connectors.

## Gotchas learned this session

- **Python versions.**
  - Run pytest with **python3.12**. Python 3.11 cannot import `agents/core/media_providers.py` (PEP 695).
  - Run bandit with python3.11 and `-b .bandit-baseline.json`.
  - `scripts/status_sync.py` counts backend tests with its own interpreter, so run it with python3.12.
- **The checker is shallow.** `hermes_status check` only checks that a cited `path:line` is a non-blank line of a pinned
  file, so verify each citation by content.
- **Restamp from the pinned version.** A row's line numbers were authored against the file version its **digest pins**,
  which can be older than the last restamp. Find that version (`git log -- <path>` plus the sha256 of each blob) and map
  from it by content. Mechanical remaps from the wrong base caused the H273 miss.
- **`tests/test_orchestrator_bindings.py`** pins exact line numbers of orchestrator binding writes. Update them after
  checking that each moved line is the same statement.
- **Known-failing and missing tools.**
  - vitest `desktop.test.tsx` "floating app renders…" failed in this container. The H277 handoff lists it as pre-existing.
  - gitleaks is not installed in the container; CI runs it.
- **Disk:** repo copies for mutation or verification fill the disk quickly: a checkout is about 100 MB, plus `.git` and
  `node_modules`. Delete your own scratch copies.
- **`BACKLOG.md`** is about 1.35 MB. Query it with `scripts/backlog.py`; never load it whole.
- **Missing records:** BACKLOG and `docs/hermes/build-queue.md` describe H464 only up to round 1. The round-3 brief's
  records step covers rounds 1–3.
