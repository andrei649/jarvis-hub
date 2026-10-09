# H18.24 native orb renderer

Generated: 2026-10-09 UTC. Base/head at design: `da7c8a222c2cd0cb658b192c967194bc9c88efa3`. Branch: `codex/mobile-voice-orb-20261009`.

Goal: render the existing native `orbVisual` state contract as an accessible, bounded SVG particle orb. Its color, state label, energy, and spin remain driven by the shared 80-vector contract. A measured listening level affects energy only when explicitly supplied; the component does not create a microphone signal.

Non-goals: changing `orbVisual` or browser vectors; a mobile mic/STT pipeline; a numeric audio meter; browser canvas or Skia; backend changes or a claim of on-device acceptance.

Paths: add `mobile/src/voice/orbGeometry.ts` and pure Jest tests, `mobile/src/components/VoiceOrb.tsx`, native host tests and SVG/AccessibilityInfo test stubs under `frontend/native-tests`, an SVG alias in `frontend/vitest.native.config.ts`, and only `react-native-svg@15.15.5` to `mobile/package.json`/lock. The `orbVisual.ts` implementation is unchanged; its introductory renderer comment is updated. Root integrates ChatScreen and its mounted regressions; the TTS helper and new lifecycle tests provide the actual playback state.

Design: cache a small Fibonacci sphere (at most 72 points) and stable filament pairs (at most 24), project it into SVG circles/lines plus two reactor ellipses and core. Clamp size to 80–360 logical pixels and reject nonfinite geometry inputs. Use one JS interval no faster than 50 ms while active and motion allowed; pause in background, stop on unmount, and freeze when reduced-motion preference is true or unavailable. Re-query reduced motion on accessibility change. Accessibility exposes the state label and source (`measured mic level`, `state animation`, or `no measured mic level`), never a numeric reading. Props: `{status?: OrbStatus; level?: number; size?: number; motion?: string}`.

Tests: red-first pure count/bounds/projection/invalid-input and native state label/source, SVG caps, reduced-motion toggles, background/foreground, timer cleanup. The coordinator also verifies Chat preparation/playback/error transitions and scope/unmount cleanup with mounted native host tests.

Rollback: revert this renderer/TTS lifecycle/integration unit. No backend or persisted conversation schema changes. Temporary speech files use unique names and are cleaned best effort; reverting does not remove user data.

Dependencies: Expo SDK 58, React Native 0.87.1, pinned `react-native-svg@15.15.5` from Expo's bundled native module list. No provider or external credentials.


Native playback integration: Chat subscribes to the helper's stable `off | preparing | speaking | error` snapshot. Preparing is shown separately and never passed as measured activity. Only a real Expo `playing` event without buffering produces speaking; pause is off and buffering is preparing. The existing Speak/Stop controls remain explicit. No live native producer sets listening/transcribing or supplies a microphone level.

Lifecycle: every speak/stop has a generation fence. Late synthesis, file writes, audio-mode setup and old native callbacks cannot create a player or replace the current utterance after stop, tab unmount or hub change. A 35-second preparation deadline and a 15-second playback-start watch retire stalled work. Native completion/error releases the subscription/player and calls only the current completion callback. Unique cache MP3s are removed on stop/finish/error, including late or failed writes. The existing fetch API does not abort a synthesis request already sent to the hub; cancellation prevents its late result from playing. Deletion remains best effort if native storage fails.

Verification on 2026-10-09 UTC:

- Full mobile Jest: **186/186**, 41 suites (`/workspace/scratch/h1824-mobile-final.json`).
- Full native React host suite: **55/55**, 6 files (`/workspace/scratch/h1824-native-final.json`); separate from the unchanged browser test count.
- Mobile TypeScript: `npx tsc --noEmit` passed.
- Offline Metro/Hermes exports for **Android and iOS** passed (`/workspace/scratch/h1824-export-android`, `/workspace/scratch/h1824-export-ios`). These compile bundles; they do not test device graphics, audio or performance.
- H526 speech normalization Python tests: **114/114**. The initial combined run had one expected generated-evidence failure because `tts.ts` changed. Named review verified unchanged hub normalization and empty/204 silence before refreshing exactly its H526 evidence hash. Status/Hermes Python tests then passed **86/86**, and generated-status/count/freshness checks passed after synchronization; H135 was already effectively `needs_review` on the base and is not re-pinned.
- Fresh npm audit reports the same **45 findings (1 critical, 17 high, 27 moderate)** on base and candidate; no new advisory package is introduced by SVG. The critical `shell-quote` and compatible transitive refreshes are tracked separately, not claimed fixed by this renderer.
- Implementation and independent renderer/integration review used `gpt-6-sol` with high reasoning. Coordinator reviewed the TTS lifecycle and H526 preservation. No remaining Important/Critical issue was identified within the reviewed slice.

The H18.24 ledger remains partial for native mic/STT capture and physical Android/iOS acceptance. This candidate is local and unpushed.
