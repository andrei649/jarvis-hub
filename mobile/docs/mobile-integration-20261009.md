# Combined native mobile candidate

Generated2026-10-09 UTC. Local worktree `/workspace/jarvis-hub-mobile-integration`, branch `codex/mobile-integration-20261009`; integration base6749d76 (briefing sources atop wall, dictation and orb). The source candidates and published PR1247 remain intact. No push, merge, deployment or live provider invocation was performed for this integration. This document supersedes standalone candidate notes only where they describe whether another local feature is included or how permissions must be combined; their original test reports remain historical evidence.

## Included units

| Capability | Original local source | Integrated commit |
| --- | --- | --- |
| Session continuity | da7c8a2 / PR1247 | Inherited by base |
| Orb, dictation and briefing including ten sources | 7b1737a,d720681,8c47e4d,6749d76 | Inherited by base |
| Command discovery | 7beeb92 | 10d7dba |
| Memory neighbors | 25359eb | 9931150 |
| Advisory approval opinions/model roles | c29d244 | 467dd6f |
| Generated images | 225d1ce | 8d2731f |
| Selected images and active history | a656cfa | 8dcb343 |
| Compatible lock security updates | d4a9639 | b70181d |

The independent backend authentication-audit and browser text-contrast candidates are not included. PR1233 remains a historical source-recovery reference; this app targets the current merged owner-only selected-Ollama API. No broad runtime merge was performed.

## Integration behavior

Commands fill the draft and require explicit Send. Accepted dictation advances the same draft version as typing, so an old command choice cannot replace newly dictated content. Commands and Images disable and cancel dictation. A monotonic interaction epoch and synchronous callback revocation prevent an old transcript from reappearing after a modal or briefing transition closes. Agent, concrete session and connection changes retain their existing fences.

Selected image submission keeps its durable outcome-unknown marker and uses the Conversation turn lock shared with text. Moving to Commands/Briefing closes the image surface and invalidates its review. Stop does not authorize an automatic retry. Generated images still require the separate exact-prompt approval handoff; advisory opinions do not change decision authority. Memory and briefing retain their bounded read contracts.

Both Expo audio and image-picker plugins are retained. The image-picker microphone setting now uses the same explicit dictation purpose string, because setting it to false removes Android RECORD_AUDIO even if audio requests it. Introspection confirms RECORD_AUDIO is present and CAMERA is removed on Android; iOS contains photo-library and microphone purposes with no camera purpose. Background recording/playback remain disabled. Runtime microphone capture still requires the explicit dictation interaction, OS permission, current Hub trust and lease.

Native test mocks combine prior file cleanup/write/copy behavior, multiline text and press-in/out events, SVG/audio, picker/Crypto, and image-error behavior. No production file API was replaced with a test implementation.

## Verification

- Clean `npm ci` completed for mobile and frontend. Full mobile Jest **284/284**,52 suites; full mounted native Vitest **137/137**,17 files. The four new integration tests cover late dictation after Commands/Images transitions, image-review invalidation when moving to Commands/Briefing, and image/text turn mutual exclusion with Stop retaining uncertainty.
- Mobile TypeScript passed. Android and iOS Metro/Hermes exports passed. Expo config introspection assertions verified the combined permissions.
- Independent gpt-6-sol/high integration review found no remaining concrete Critical/Important issue in the resolved production source, permission config, aliases/mocks or new tests. The reviewer inspected source/tests and did not repeat the full suites.
- Status/Hermes regressions **86/86**; generated status, mobile executed-count check, Hermes freshness and whitespace checks pass. No evidence hashes were restamped during integration; inherited H135 review status remains unchanged.
- Current dependency audit: **42 findings (0 critical,15 high,27 moderate)**, matching the earlier isolated lock refresh. The three compatible transitive updates are included; there is no forced SDK/RN downgrade or clean-audit claim.

Backend and browser source did not change during this composition. Their tracked20985/1865 test counts are reused, with no new full-suite pass claim. Standalone source-unit backend contract runs remain linked in their respective documents. Local report artifacts use `/workspace/scratch/mobile-integration-*`: mobile/native finalJSON, tsc, Android/iOS exports, config introspection, audit, statusJUnit and final review.

Physical Android/iOS picker/graphics/accessibility/microphone behavior and live owner-authenticated Hub/Ollama/STT operation remain unverified here. H18 partial rows stay partial. Local image history is process-local, recording stop can remain unconfirmed, and already-dispatched uploads cannot be retracted. The native image transport still uses buffered response text; its checks are not streaming memory bounds.

Rollback this integration branch or revert its individually preserved source units; the standalone candidates are retained. Next work remains local software and backlog integration; this is not whole-project completion.
