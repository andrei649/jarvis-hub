# H517 named speech and shared provider registry review

Generated 2026-09-27. Base/head: bd2bb70ead1b493043a335e77713fc42c47d4013
plus existing local changes. Goal: independently register, approve, select and revoke
named speech programs and use the shared provider identity registry in real image
and speech dispatch. Scope and acceptance: h517-named-provider-plan.md.

## Delivered behavior

- Shared immutable ProviderBase/ProviderRegistry identity lookup accepts only
  explicitly constructed trusted adapters. Image and speech production dispatch
  use it. Registry construction performs no setup hook, model load, subprocess or
  network probe. The image approval fingerprint includes shared implementation
  bytes; source drift requires a fresh process and new approval.
- Named speech approvals use a separate SQLite table with per-side/name revisions,
  transactional CAS, bounded active/history counts and retained cleared-name
  tombstones. Catalog reads are read-only and do not initialize absent storage.
  Generic settings operations cannot install or reset this authority.
- Existing command intake retains recorded exact payloads, signed mediation,
  irreversible risk, explicit human acceptance, arming, safe-mode and file checks.
  The request binds the name and its current revision. A clear or another approval
  invalidates old pending requests and command invocations waiting for a slot.
- Explicit TTS provider selectors resolve before vendor substrings. Absent/invalid
  selections refuse without a legacy or vendor fallback. Runtime failures retain
  existing safe fallback policy. local_only never treats arbitrary programs as
  verified local. Persona consent and existing native providers are preserved.
- STT keeps native mode preference and captures the selected command identity
  through async choice, executor handoff and the command slot. A selector change
  cannot retarget an in-flight command to another named program.
- HUD lists independent named rows, requests exact named registration/update,
  clears configured or pending-only names, displays original revision in the
  Decision Inbox and saves the STT selector explicitly. A missing selected name
  remains visible as unavailable. Legacy controls remain compatible.
- Joined tests traverse real HTTP admin intake, signed decisions, guarded worker,
  actual bounded synthetic speech subprocesses, audio/transcript readback and
  revocation. Image integration verifies approved execution calls the registered
  concrete adapter and performs one transport request.

## Review corrections

Initial missing named TTS pins reached vendor fallback: deterministic regressions
now refuse them. Store corrupt JSON/argv and absent nonzero-revision writes were
reproduced and fixed. A loaded-Whisper async handoff could reread a new named selector;
a thread-scoped original selector now covers that private override seam.
Independent Luna review found selected named STT capability reporting could raise
on provider-store failure before its handler; the final evidence records its fix
and regression. No external model/service credentials are used in these tests.

## Changed paths and responsibility

Coordinator: agents/core/media_providers.py, agents/core/media_backends/registry.py,
agents/core/image_generation_runtime.py, frontend/src/panels/voice-commands.tsx,
frontend/src/test/named-voice-providers.test.tsx,
tests/test_h517_shared_provider_registry.py,
tests/test_h517_named_provider_integration.py, generated HUD assets and delivery
records. Sol High Task 1: agents/core/voice/provider_store.py,
agents/core/voice/command_settings.py, agents/core/routers/voice.py,
agents/core/settings_db.py, tests/test_h517_named_provider_store.py,
tests/test_h517_named_provider_approval.py. Sol High Task 2:
agents/core/voice/local_providers.py, agents/core/voice/provider_registry.py,
agents/core/voice/tts.py, agents/core/voice/stt.py,
tests/test_h517_named_provider_dispatch.py. Luna Medium performed a bounded
read-only review. No agent delegated further; maximum two implementation agents.

## Limits and rollback

H517 and H613 remain partial. Video/browser/web/terminal registry integration,
additional vendor/local adapters, Python plugins and full interactive setup hooks,
remaining cloning/persona/audio-tag/voice-bubble semantics and live model/device
acceptance are not delivered here. Native mobile provider configuration is open.
Commands run as the hub user; approved executable/script bytes do not pin imported
libraries or make a sandbox. Named history intentionally cannot be automatically
recycled. The existing 64-request approval record bound may invalidate old pending
cards safely. Clear revokes future dispatch, not an already running process.
Identical legacy records without approval metadata retain their documented limitation.

Rollback only the localized slice hunks, preserving all pre-existing dirty work.
Disable JARVIS_VOICE_COMMANDS to stop new command execution. Keep named table/history
rather than deleting or recreating the settings DB. No commit, push, merge,
deployment, new dependency or live/paid provider call is part of this delivery.

Final test/scan counts and source hashes are recorded in the companion evidence
JSON and the local sprint handover. Next action: finish final gates and handover;
the owner requested stopping by 2026-09-27 18:05 UTC (21:05 Europe/Bucharest).
