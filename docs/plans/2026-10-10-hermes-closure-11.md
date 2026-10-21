# Hermes speech normalization — batch 11 implementation plan

Generated 2026-10-10 UTC. Goal: close the complete frozen H526 contract by
removing the missing file-mutation verifier advisory from speech on every entry
point. Base/head: `17f09315ee767b71fe0c3eabcf97c650d4dd0d40`.
Branch: `codex/hermes-closure-11-20261010`. Next action: red/green regression and
implementation. Local only; no push, remote merge, deployment or paid providers.

Architecture: normalize the exact producer-shaped advisory before Markdown,
emoji and whitespace processing in the paired Python/TypeScript normalizers.
The HUD stream filter must withhold a potential advisory until it can decide,
so sentence synthesis cannot leak it before whole-reply normalization.
Tech stack: Python, TypeScript, pytest, Vitest, existing shared JSON corpus.
Spec: frozen H526 in the immutable Hermes ledger and pinned donor
`NousResearch/hermes-agent@59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.
Exact donor sources and clause review are in scratch batch09/h526-next-design.json
and h526-whole-review.json. Existing behavior is covered by 157 backend, 80 HUD
and 12 mobile focused tests; those prior results are a baseline, not new proof.

## Constraints and decisions

Preserve all visible reply text and current TTS route/engine/mobile APIs. No new
mutation verifier producer. No broad suppression of ordinary warnings or prose
about verification. No new dependency. Python and TypeScript use the same corpus.
No partial slice earns complete-contract credit. Keep the 697-row inventory fixed.

Publication steering: the owner requested a new PR for all current progress, then
a pause until new resources arrive. Finish the existing focused regressions,
review, build/browser check and metadata synchronization only. Save the latest
H526 implementation and bounded H673 repairs as a draft checkpoint. The planned
new full-backend milestone and H526 whole-contract promotion are deferred; do not
describe the older batch09 full run as validation of this newer combined head.

Ruling: match the pinned producer's complete unique warning/header sentence and
its contiguous indented bullet block, requiring at least one bullet. The donor
normalizer's broader arbitrary header suffix is unnecessary and risks suppressing
ordinary prose. Accept warning icon with/without variation selector, positive
count, LF/CRLF, producer bullet paths/errors and overflow. Preserve all preceding
and following prose, including a later abnormal-exit explainer. Do not require
absolute EOF. Never classify merely by a word such as `verifier` or `failed`.

Header: `⚠️ File-mutation verifier: <positive integer> file edit(s) FAILED this turn despite any wording above that may suggest otherwise. Run \`git status\` or \`read_file\` to confirm what actually landed.`
Body: contiguous lines beginning two spaces and `• `; producer emits 1–10 path
bullets and optionally `  • … and <positive integer> more`.

Review focus: split token/CRLF boundaries; marker-like ordinary warnings; header
without a bullet; later explanatory text; very long malformed candidate input.
Use bounded streaming lookahead, not buffering the complete reply. Preserve
fenced-code/reasoning handling and immediate output for unrelated ordinary prose.

## Task 1: paired normalization and live stream

Single writer review_1233 (gpt-6-sol/high), no delegation. Owned files:
`agents/core/voice/speech_text.py`, `frontend/src/speech-text.ts`,
`frontend/src/test/speech-text-cases.json`, `tests/test_h526_speech_text.py`,
`frontend/src/test/speech-text.test.ts`,
`frontend/src/test/voice-speech-text.test.tsx`.
Existing public interfaces stay `for_speech`, `speechText`, and
`SpeechStreamFilter.push/flush`. Root owns plan, parity notes, evidence and integration.

- [x] Add shared cases: exact one-path advisory after Done -> Done; advisory-only
  -> empty; ten paths plus overflow; Unicode paths; warning variation selector;
  preceding/following prose preserved; incomplete/near-miss header remains spoken.
- [x] Add real route footer-only 204 and HUD voice stream test with the marker
  split across deltas. Assert emitted speech excludes the advisory and visible
  source reply remains available; test ordinary warning prose still plays.
- [x] Run new regressions before production edits; retain expected failures.
- [x] Implement speech-only stripping and bounded stream handling, sharing the
  marker logic within TypeScript to avoid divergent whole/stream classification.
- [x] Run focused Python H526/tts/emotion/spoken_reply suites; HUD speech-text,
  voice-speech-text and ttsStream suites; Ruff/diff checks. Retain commands,
  results, source hashes and remaining limitations in scratch batch11/report.json.
- [x] Root reviews changed code, clause coverage and exact test outputs.

## Task 2: complete acceptance checkpoint

Root is the only writer for metadata. Check mobile uses the corrected shared hub
normalizer without a separate implementation and record parity in mobile/PARITY.md.
Review other accepted evidence pins affected by the narrowly changed source.
Run full frontend/typecheck/build and a refreshed browser voice-path smoke with
synthetic speech output; do not claim physically heard audio. Fresh actual server
checks use mocked synthesis, no provider accounts. Run backend integration serially
after freezing inputs; diagnose failures before any acceptance claim. Update
generated counts/status and guarded assessment only after whole-contract review.
No change to the assessment guard or frozen inventory. Rollback is this coherent
speech-only behavior unit; dependencies are batch09's completed local checkpoint.

Checkpoint results: 170 focused backend and 91 focused HUD cases passed; final combined H526/H673 selection passed 352/352. TypeScript, Ruff, regenerated HUD build and actual built-browser speech/display checks passed. H526 full-backend acceptance remains deferred. Source is saved in the combined progress branch; the owner requested a pause after publishing its draft PR.
