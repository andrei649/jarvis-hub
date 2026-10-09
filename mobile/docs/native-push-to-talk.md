# Native hold-to-dictate

Generated: 2026-10-09 UTC. Goal: provide explicit, bounded microphone capture in
native Chat and append its local STT result to the current draft. Design base/head:
`7b1737abb752c4fa7c4a76d25b767a4734da6595`; branch
`codex/mobile-push-to-talk-20261009`. Depends on the separate native orb candidate.

Hold the dictation button (or use the accessible Start/Finish alternative) to request OS permission, require fresh hub microphone
trust (`mic === 'on'`) and acquire a mobile lease without takeover. Record at most
15 seconds using Expo Audio's M4A/AAC preset. Release stops capture and checks
permission/trust again before sending raw audio to the existing local STT route.
The transcript appends to the draft; only the existing Send action sends a turn.
Listening and its optional measured level come from native recorder status.
Both input methods stop after 15 seconds. Background recording is disabled.

Cancellation on scope/session/agent changes, background, unmount, history, text
send or speech playback discards the recording and ignores late transcriptions.
Setup, guard requests and transcription have deadlines. A module-wide recorder
gate serializes native preparation/cleanup across component replacements; a new
attempt cannot record behind an unfinished old native operation. Per-attempt
lease IDs prevent a delayed release from revoking a later attempt. They do not
claim hub-side arbitration across every app instance on a physical device.

Non-goals: ambient capture, hands-free loops, automatic send, browser wall port,
new backend routes, cloud STT fallback or changes to SDK versions. Audio is a
temporary app-cache file, deleted best effort on completion/cancellation/error.
Native cancellation cannot guarantee retraction of bytes already uploaded.

The recorder is created lazily through Expo's public `AudioModule.AudioRecorder`
export. Its native lifetime belongs to the capture attempt, so leaving Chat cannot
auto-release the object before asynchronous stop and audio-mode cleanup finish.
Only confirmed stop releases the shared hardware gate. Rejected stops have at
most two recovery retries and 16 seconds of status polling; an unresolved native
operation keeps the gate held. A finite watchdog displays an explicit unconfirmed
stop message instead of claiming the microphone is off. Normal file deletion
runs after native release and cannot block a subsequent recording.

Guard checks run every two seconds while recording without overlapping each
other, with three-second request bounds. A dispatched arm request whose response
is lost can still commit after a best-effort release; the old per-attempt lease
then expires after the backend's 45-second TTL. It cannot release a newer attempt's
lease. STT uploads use foreground binary M4A, a two-MiB file bound, a 60-second
deadline, bounded response validation and explicit silence/error handling. Native
fetch/upload responses can be buffered before client validation; this is not a
streaming transport memory guarantee.

Paths: `mobile/src/api/pushToTalk.ts`, `mobile/src/voice/pushToTalk.ts`,
`mobile/src/components/PushToTalk.tsx`, ChatScreen integration, Expo audio permission
configuration, focused mobile/native host tests and parity/status evidence.

Verification plan: red-first controller/transport/Chat regressions for denied or
stale permission, release during preparation, late callbacks, context replacement,
silence/errors, measured status and draft-only behavior; full mobile/native host
suites, TypeScript, existing STT/mic-lease backend contracts and offline Android/iOS
exports. Physical capture, permission prompts, interruptions and live local STT
acceptance remain separate device checks.

Rollback: revert this dictation unit, retaining the orb/TTS base. No database,
conversation storage schema or backend contract changes.

Verification on 2026-10-09 UTC:

- Full mobile Jest: **211/211**, 43 suites; report
  `/workspace/scratch/ptt-mobile-final.json`.
- Full native React host suite: **70/70**, 8 files; report
  `/workspace/scratch/ptt-native-final.json`. Includes actual mounted Chat draft,
  explicit-send, agent/session/hub/config-save fencing, measured orb, accessible
  tap capture and keyed native-recorder cleanup regressions.
- Mobile `npx tsc --noEmit` passed.
- Final offline Android and iOS Metro/Hermes exports passed, at
  `/workspace/scratch/ptt-export-android-final` and
  `/workspace/scratch/ptt-export-ios-final`. These compile bundles, not device
  recording or codec acceptance. The earlier Android export was superseded
  after the cleanup watchdog correction.
- Existing backend STT/microphone-lease contracts: **33/33**; status/Hermes tests:
  **86/86**. Reports: `/workspace/scratch/ptt-backend-contract.xml` and
  `/workspace/scratch/ptt-status-final.xml`. Full backend/browser suites were not
  rerun; their tracked counts are reused without a new pass claim.
- Expo configuration introspection confirms the explicit microphone purpose on
  iOS, `RECORD_AUDIO` on Android, and no iOS background audio mode. No SDK or
  package/lock dependency changes are introduced by this unit.
- Generated status/count verification, Hermes freshness and `git diff --check`
  passed. No inherited Hermes evidence hash was refreshed for unrelated code.
- Independent `gpt-6-sol` / high review reproduced and closed rejected/hung native
  stop, delayed preparation, the capture deadline and queued speech/agent-change
  issues. Additional coordinator regressions cover old file cleanup versus a new
  recorder and same-connection saves. No remaining Critical/Important issue was
  found within this bounded review. Implementation used two `gpt-6-sol` / high
  agents with coordinator-owned integration; no nested delegation.

H18.24/H18.25 remain partial. No physical Android/iOS microphone, OS prompt,
interruption, acoustic, local Whisper/command codec or live Hub acceptance was
performed. The native wall renderer/chrome remains unimplemented. The independent
mobile lock security candidate is not included in this branch. Next action:
device/live acceptance and later integration of the separately reviewed units.
This candidate is local; publication of PR1247 does not publish these files.
