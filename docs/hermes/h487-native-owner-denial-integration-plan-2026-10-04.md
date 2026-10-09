# H487 native owner-once denial integration

Generated 2026-10-04. Goal: all697 pinned Hermes capabilities; exact-card native
owner-once `/deny [reason]` dependency. Base/head before integration:
`220052441ca2befdd5a839dc98a937486e0b1cb6`. Root is sole checkout writer.

## Scope and design

Integrate the reviewed six-path prototype, patch SHA-256
`3364b2e7d8e64b2948c6de642c1e22750ea4870c90452513b4e33bb2808c103f`.
An original direct reply to the exact delivered owner-once Telegram card enters
a bounded private task outside the occupied originating chat lane. The existing
queue rejection CAS checks current owner, source, turn, generation, original task,
offer and deadline. Pure selectors choose exactly one owner or reusable-consent
registry; ambiguity and stale commands never become model turns.

Text supplies optional human-denial metadata only. A denial-specific MAC binds
the exact raw/normalized reason and human decision to the original task, denial,
offer, origin and delivered card, in the same durable transaction. Add a nullable
`task_owner_once.denial_metadata_mac` column through the existing initialization
migration pattern. Legacy exact six-key reasonless button records remain valid
with a null MAC; new reason-bearing records require the existing signer. Accepted
claims, receipt signatures, grant and physical execution paths remain unchanged.

The one-shot process-local observation reconciles its exact durable rejection,
including a timeout or withdrawal during callback publication lag. It returns a
reason only with `owner_denied`. Policy/source changes before CAS refuse; changes
after a legitimate committed denial do not erase the human outcome.

Owned production paths: `agents/core/autonomy/queue.py`,
`agents/core/autonomy/owner_once_prompts.py`,
`agents/core/autonomy/terminal_review.py`,
`agents/core/autonomy/consent_prompts.py`, `agents/core/channels/telegram.py`.
Owned test: `tests/test_h487_telegram_owner_once_denial.py`. This plan and its
progress receipt accompany the local rollback unit. Shared status and collateral
review remain separate. No new route or HUD/mobile endpoint is introduced.

## Steps and acceptance

1. Rehash all six baseline/proposed files and patch; inspect exact source/test
   delta and the independent review finding. All hashes match current root bytes.
2. Add only the new test module. Run its real occupied ToolRPC/Telegram lane test;
   expect one behavior failure and no setup error before production application.
3. Apply the five production deltas; run all new cases and the deduplicated native
   Telegram, owner-once, consent, worker, continuation, kernel and human-wait suites.
4. Check reason bounds, exact-card/currentness races, post-CAS reason tampering,
   unavailable signer, legacy schema migration and unchanged accepted execution.
   The prototype already captured meaningful RED tests for coherent forged reasons
   and post-CAS policy drift; root verifies final behavior independently.
5. Run Ruff, baseline-aware Bandit and exact selected-index secret scanning; record
   actual terminal XML counts/hashes and commit this unit locally.
6. Update shared counts/architecture and claim-specific evidence after reviewing
   new source changes. Run expensive full suites serially at a clean frozen batch
   milestone after the independent judge-recovery unit is integrated.

Review repair: the first prototype trusted a coherently modified human reason.
The final prototype adds the denial MAC and actual signed ToolRPC regressions;
root accepts this scoped integrity repair, not a change to approval authority.

Rollback: reverse only this unit's scoped source/test diff, retaining adjacent
work. The nullable additive database column may remain inert on rollback; do not
drop or rewrite existing task data. No push, merge, deployment, provider activation,
real Telegram/Docker/SSH/terminal effect or paid call. No H487 equivalence credit
or full parity claim. Next action: root test-only RED, then production GREEN.
