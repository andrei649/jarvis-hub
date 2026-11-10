# Hermes integration by feature, not by row (owner decisions, 2026-11-10)

**Status:** accepted by the owner on 2026-11-10 ("ok to all 4"), on the recommendations below.
**Context:** `docs/hermes/feature-integration-plan-2026-11-10.md` (the three lanes: Own, Adopt, Run) and
`docs/hermes/missing-rows-plan-2026-11-10.md` (the 112 missing rows).

## 1. Adopted and sidecar capabilities count as delivered, on one condition

- **Adopted** Hermes code (vendored under `agents/vendor/hermes/`, behind the compat layer, every effect
  through Nerva's egress, kernel and credential paths) counts like native code. The owner uses it through
  Nerva's own settings, HUD, CLI and chat, so the experience is the same.
- **Sidecar** capabilities (the governed Hermes runtime, `docs/hermes/RUNTIME_INTEGRATION.md`) count
  **only when the owner can reach them from a normal Nerva surface** (chat, a HUD panel or a `nerva`
  verb) and their approvals arrive as ordinary approval cards. The admin RPC console alone does not count.
- A row is still judged against its full Hermes contract; the lane changes where the code comes from,
  not how strictly the row is assessed.

This reverses the earlier rule in `RUNTIME_INTEGRATION.md` that runtime-backed availability earns no credit.

## 2. Hermes's own CLI, TUI and desktop surfaces are judged by job, not by screen

Nerva does not rebuild Hermes's terminal UI, desktop app or CLI screens. Each of those rows (cli 56,
tui 25, desktop 54) is re-read as "can the owner do this job in Nerva's HUD or `nerva` CLI?". Covered
jobs count; uncovered ones are real gaps in Nerva's own surfaces and are built there.

## 3. Behaviour tests per feature area replace per-row hash pinning

Each feature area gets one acceptance suite written from the owner's side (what the owner can do, and
what an attacker cannot). Evidence is that suite passing, not file hashes, so a merge that moves code
no longer re-opens hundreds of rows. Adversarial review stays mandatory for approvals, memory writes,
execution, delegation and credentials. Until the tooling change lands, the existing restamp process
continues.

## 4. Thirty-two rows return to `excluded`

The owner directive of 2026-09-27 reopened all 107 former exclusions. This decision returns the 32 rows
whose exclusion is honest by design (they conflict with the approval model, lend credentials, run
effects outside the kernel, or serve a hosted storefront) to the original audit's exclusion:

H050 H054 H077 H087 H102 H110 H125 H128 H149 H166 H213 H215 H233 H239 H292 H324 H341 H371 H376 H384
H489 H546 H565 H568 H572 H584 H587 H609 H627 H628 H638 H662

Their reviews and reopenings are archived in `docs/hermes/evidence/2026-11-10-scope-exclusions.json`.
The reasons per row are in `docs/hermes/missing-rows-plan-2026-11-10.md` §3.

**Still reopened, awaiting a separate owner call:**
- Contradictions with copy rows: H055, H056, H163, H564.
- Premises the Workspace pilot broke: H365, H496.
- Candidates for "deferred": H123, H124, H127, H348.
- A cheap Adopt candidate: H582 (`x_search`).
- Excluded natively but exposed by the sidecar: H032, H214, H238, H590, H657.
