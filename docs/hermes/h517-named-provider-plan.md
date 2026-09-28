# H517 named speech providers and shared production registry

Generated 2026-09-27. Base/head bd2bb70ead1b493043a335e77713fc42c47d4013
plus existing local work. Prior voice authority milestone verified 19,412 passed,
35 skipped. This plan supersedes the candidate choices in h517-named-provider-next.md.
Goal: independently register/approve/select/revoke named speech programs through
real speech paths, using a common provider identity/registry also consumed by images.
This is additional H517/H613 progress, not full media/vendor/plugin parity.

## Global constraints

Local only; no commit/push/merge/deploy/live or paid providers. Preserve all dirty
work. Two Sol High writers maximum, no subdelegation, disjoint owned files below.
Parent owns common interfaces, image integration, HUD, final review and records.
Focused TDD after each behavior change. Broad impacted voice/settings/routes and
capability/registry gates before one serial full backend run; frontend tests,
typecheck/build for changed HUD. Preserve timeout/socket guards and existing
approval, arming, safe-mode, consent, local-only and process/output limits.

## Settled interface

The existing admin command POST gains optional `provider_id`. Omission/null keeps
the legacy tts_command/stt_command slot. A named ID is strictly
`[a-z][a-z0-9_-]{0,31}` and must not be a reserved built-in name. No trimming or
case folding creates another identity. Reserve auto, command, whisper,
faster-whisper, piper, edge, edge-tts, kokoro, xtts, elevenlabs, fish, fish-audio,
openai, minimax, mistral, gemini, xai, neutts, kittentts, local and provider.
At most 16 active names per side and 128 historical names per side (tombstones
remain bounded and keep stale-approval detection). Same name on opposite sides is
independent. No importable Python name or executable module path in configuration.

Use a dedicated `voice_command_providers` table in the existing settings SQLite
database, keyed by (side, provider_id), storing approved JSON plus positive revision.
Empty JSON is a tombstone. Read/catalog uses a read-only connection: absent DB/table
means empty, other storage failures fail closed. Reads do not initialize a DB/table.
Writers use BEGIN IMMEDIATE, durable normal SQLite commits and per-row compare-and-
swap. Clear increments revision even when empty so a pending revision-zero request
cannot later recreate it. Never drop/recycle tombstones automatically. Bounded JSON
(300000 UTF-8 bytes per approved record), IDs, counts and revision overflow checked.
Generic settings PUT/import/reset/undo cannot touch this separate table; preserve
their existing legacy protections.

New `agents/core/voice/provider_store.py` API (Task 1):
- `valid_provider_id(value) -> bool` and `RESERVED_IDS`.
- `load(side, provider_id) -> dict`: approved fields plus `provider_id` and
  `provider_revision`; absent/tombstone returns metadata with no argv, revision 0
  for never-seen names. Never falls back to legacy.
- `list_records(side) -> list[dict]`: active named records with the same metadata.
- `save_approved(side, provider_id, value, *, expected_revision) -> int`: new
  revision; conflicts raise `ProviderConflict`, limits `ProviderLimit`, storage/
  malformed data `ProviderStoreError` (both subclasses). No writes on refusal.
- `clear(side, provider_id) -> int`: incremented revision; other names unaffected.

Task 2 extends existing lp helpers with keyword-only `provider_id=None`:
`stored_command`, `command_ready`, `command_status`, `speak_command`,
`transcribe_command`. None preserves existing behavior and monkeypatch seams.
The initial Ready binding includes provider_id/provider_revision; post-slot recheck
pins the original ID. A selector change must never retarget an in-flight invocation.

Parent supplies `agents/core/media_providers.py`:
`ProviderBase` ABC with abstract read-only `name` and `kind` properties; default
`display_name` = name, `get_setup_schema() -> dict | None`, `is_available() -> bool`.
These metadata methods must never network/spawn/load a model; registry construction
does not call availability or setup hooks. `ProviderRegistry(providers)` freezes
identity mapping, validates lowercase IDs and supported kinds (image, video, tts,
stt, browser, web, terminal), rejects duplicates, and provides
`get(kind, name) -> ProviderBase | None`, `list(kind=None) -> tuple[ProviderBase,...]`.
Registration itself grants no execution authority. No global mutable plugin loader.

## Task 1 — storage, approval and public configuration

Own provider_store.py, voice/command_settings.py, routers/voice.py, settings_db.py,
new tests/test_h517_named_provider_store.py and
tests/test_h517_named_provider_approval.py. No other shared files without handoff.

Add store with the contract above. Existing request/apply/clear signatures gain
optional keyword provider_id=None. Include named ID and expected revision in the
server-recorded payload and card preview. Existing pending lookup is per side+ID;
legacy pending cards do not block named cards or vice versa. Named apply validates
the same exact record/human decision/arming/safe mode/files as legacy, then CAS;
stale revision refuses. Clearing/recreating a name cannot restore old authority.
No generic settings route becomes an installer. Do not weaken kernel/human floor.
Record failure must return honest refusal (never report usable registration when
no approval record exists); the queued task remains non-executable without a record.

GET admin status preserves sides/arm_env/kind and adds
`providers: {tts: [...], stt: [...]}`. Rows have provider_id, provider_revision and
the existing side status fields (configured/ready/reason/argv/files/approved_task/
pending_task etc). Include pending-only names so new requests remain visible before
approval. Named readiness uses verify_content=False for metadata; runtime still
verifies full content. On store failure report refusal rather than a legacy fallback.
POST validation/errors distinguish provider name, full capacity, revision conflict.
Return provider_id/provider_revision where applicable. Dry run does not write.

Settings adds only `voice.stt_command_provider`, text, default empty string for
legacy selection; reject malformed/reserved nonempty values. TTS uses existing
voice.tts_voice with `provider:<id>`. Selecting a name never registers/approves it.
Voice capabilities preserves existing fields and exposes active ready named TTS
selectors in voices; selected named STT readiness governs stt availability. Read
Task 2 helpers/registry; do not advertise arbitrary named programs as proven local.

Tests: readonly absent store, bounded/corrupt state, atomic independent concurrent
names, CAS same-name conflict, clear/recreate and pending-zero revision, exact
approval under strict signed worker, no-write dry run, generic settings refusal,
invalid/forged/edited identity, two sides/names independent, clear-one-keeps-other.
Report /tmp/h517-named-storage-report.md with RED/GREEN and limitations.

## Task 2 — shared-registry-backed speech selection

Own voice/local_providers.py, voice/tts.py, voice/stt.py, new
voice/provider_registry.py and tests/test_h517_named_provider_dispatch.py.
Use Task 1 store and parent common ProviderBase/ProviderRegistry interfaces.

Build a fresh typed speech registry from named records. Concrete command provider
objects expose real async synthesize/transcribe methods through the existing guarded
lp runners, not just catalog descriptors. IDs cannot replace native providers.
Catalog/setup schema describes approved-command configuration without loading code,
probing endpoints or spawning processes. Registry lookup is used by actual named
TTS/STT dispatch, including calls from the existing HTTP engines and channels.
Keep legacy providers, private override methods and language/default behavior intact.

TTS `provider:<id>` selects exactly that named TTS program. This prefix is handled
before vendor substring dispatch; persona-marker consent still applies conservatively.
Missing/invalid explicit named selection refuses synthesis (None), never executes
legacy command or leaks it to another vendor. Named runtime failures use the existing
safe fallback policy, but never the legacy command. local_only blocks named commands
just as it blocks legacy commands. Preserve legacy command:anything ignoring suffix.

STT: selected provider comes from voice.stt_command_provider (empty = legacy).
Preserve whisper-only, command-only and auto preference for loaded Whisper. In
command mode an absent/invalid selected provider is unavailable; no legacy or Whisper
fallback. Pin selected ID through async choice and post-slot invocation; no retarget
if settings changes. Preserve sentinels and hallucination handling exactly.
Add `selected_stt_provider() -> str | None` (invalid nonempty remains a nonmatching
string rather than None), and `named_command_status(side) -> list[dict]` with
provider_id/provider_revision/selector/configured/ready/reason for the router.
`stt_available` and `tts_available` consider selected/registered named providers
without granting local provenance. No named command must run while unarmed/safe-mode.

Tests: two real providers per side emit distinguishable synthetic outputs; registry
selection, missing pin, legacy compatibility, consent/local-only, prefix safety,
selector drift, per-name revocation and same-argv revision replacement after slot.
Use real stored approvals/helpers; mock only external engines/transports as needed.
Report /tmp/h517-named-dispatch-report.md with RED/GREEN and limitations.

## Parent integration and delivery

Parent owns common media_providers.py and its tests, adapts actual local image
provider selection/dispatch to the shared identity registry while preserving native
backend factory test seams, and binds the common implementation source into image
approval fingerprints. No image protocol/egress/approval option changes.
Own frontend/src/panels/voice-commands.tsx, focused HUD tests, generated route schema
if needed and built HUD assets. Existing tts_voice selector accepts named choices;
the named provider panel exposes add/update/clear and chosen STT provider without
turning approval into a generic settings write. The Inbox names exact provider ID.
Parent adds joined HTTP/signed-approval/actual speech tests after both tasks freeze.

Before full suites run voice/settings/router/route-schema/capability/readiness and
shared image regressions together. Review independent diffs. Update only reviewed
evidence; native UI gaps and provider breadth stay explicit. Rollback localized
hunks and stop command execution with JARVIS_VOICE_COMMANDS off; preserve named
table/revision history and existing owner data. Never reset/recreate the settings DB.

Next action: implement common contract and independent Tasks 1/2, integrate HUD,
verify real registry selection/approval, then full milestone tests.
