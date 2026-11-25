# Hermes progress checkpoint and pause

Generated 2026-10-10 UTC. Owner requested a new PR to save current progress,
followed by a pause until new resources arrive. **Do not resume automatically.**
Publication is authorized for this draft PR; no merge or deployment is requested.

Base: `main@332b16ca857a3fd126a89be411e2e6ca17de4e91`.
Last accepted whole-contract checkpoint: `17f09315ee767b71fe0c3eabcf97c650d4dd0d40`.
Combined implementation and fixture head: `17f8019e80c5975264b9054b17f8adb8cdefb5a9`.
Branch: `codex/hermes-progress-20261010`.
The final documentation commit follows this source head. Source paths are recorded
in the committed checkpoint evidence; plans for batches 01–11 describe the units.

## Saved state

The fixed 697-row inventory has 152 equivalent, 228 partial, 56 missing and 261
requiring review: 545 unfinished. This checkpoint adds no whole-contract credit.
Twenty previously current collateral evidence pins were reviewed against the
small context changes; previously stale pins remain stale. H526's changed pins
are deliberately left for its full acceptance review. No inventory rows changed.

Batches 01–09 preserve the accumulated CLI, runtime, skills, foreign-session,
usage-receipt, scheduling/job-output and pending-input work. The last whole
acceptance is H067: real startup clarification registration, corrected Other
choice parsing, owner-bound answer/resume, confirmation and safe deletion.

Batch10's bounded H673 repairs are saved: eager synchronized 256-entry managed
anchor storage, removal of the invalid unmanaged callback without losing usage
totals, and no guessed image-token subtraction from provider measurements.
**H673 remains incomplete.** Actual rendered system/schema/prompt binding and
single full-request pressure accounting are not implemented.

Batch11's H526 repair is saved: both normalizers remove the exact structured
file-mutation verifier advisory only from speech. The HUD handles split token
markers and CRLF, preserves ordinary warnings/later prose, and resets correctly
when a stream filter is reused. Footer-only hub replies return 204. The visible
chat advisory remains intact. The shipped HUD bundle is regenerated; mobile
uses the shared hub normalizer. **H526 whole acceptance is deferred.**

## Verification and limits

The combined implementation passes 352 focused backend tests covering voice,
context lifecycle, usage, route planning and compression. H526 independently
passed 170 backend and 91 HUD focused cases, TypeScript and Ruff. Its missing
footer and flush-reuse regressions were demonstrated failing before repairs.
Independent code review found no remaining blocker in the frozen H526 changes.

The built HUD was exercised in Chromium with fixture STT/chat and a synthetic
speech sink. Both initial load and hard reload spoke only the ordinary reply,
while the exact advisory remained visible in the chat. No browser errors or
failed built assets were observed. The first smoke selected the wrong icon;
the corrected run used the actual voice button. No physical audio is claimed.

The latest completed full backend milestone belongs to batch09, not this combined
head: 25,951 cases, 25,906 passed, five failed, 40 skipped/xfail. All frozen inputs
were verified unchanged before repairs. Three fixture repairs passed all 245
module cases; optional TLS provenance repairs passed all 130 module cases and
both original guards without the SDK. Do not call that original full run green.
The combined head receives fresh collection and focused verification, not a new
full-backend execution. Final frontend/count/metadata results are recorded in
`docs/hermes/evidence/hermes-progress-checkpoint-2026-10-10.json`.

## Resume only after the owner's signal

1. Inspect the draft PR head and CI. Keep any new unrelated owner work intact.
2. Finish H526 acceptance: verify the full frozen clause against the current
   head, run a new frozen backend milestone, resolve genuine failures, then use
   the guarded assessment update. Do not award partial credit meanwhile.
3. Continue H673 from `2026-10-10-h673-phase2-interfaces.json`. It is a read-only
   proposal, not an approved or implemented interface contract. Settle it before
   assigning writers. Managed prompts need a recomputed fixed prologue and an
   append-stable transcript; actual physical dispatch must bind system, schema,
   model/backend/session generation and prefix. Only appended material may be
   estimated on top of a valid provider measurement, charged against the full
   request allowance once. Changed scaffolding, summary, sliding history and
   transient tool-loop messages must invalidate cross-turn reuse.
4. Prove actual backend inputs over two nonstream and two SSE outer turns,
   including lower measured counts, 85% pressure, invalidation and late usage.
   Clock CAS changes metadata, not raw memory rows; do not revive that rejected
   diagnosis. Do not broaden the frozen row into donor persistence/billing work.

Rollback remains separable by the existing commits and batch plans. Keep this
as a draft progress snapshot until the deferred acceptance work is complete.

The final frontend run completed 2,192 cases: 2,191 passed and the cold lazy desktop render exceeded its one-second assertion wait. The same case failed in isolation, then the unchanged outcome assertions passed with an explicit five-second wait (10/10 module cases; the real render took about two seconds). Only the fixture deadline changed. The complete frontend suite was not rerun after that repair. Fresh backend collection is 25,971; mobile count 359 is reused.

Final metadata regressions pass 86/86; generated Hermes/status checks and whitespace validation pass.
