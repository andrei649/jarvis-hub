# H517 named speech Task 1 — storage, approval and configuration

Frozen local implementation, 2026-09-27. No commits/push, providers, full suites or subagents. Existing dirty state preserved. Owned existing files copied before editing beneath /tmp/h517-named-baseline (voice/command_settings.py, routers/voice.py, settings_db.py).

## Exact owned files

- agents/core/voice/provider_store.py (new)
- agents/core/voice/command_settings.py
- agents/core/routers/voice.py
- agents/core/settings_db.py
- tests/test_h517_named_provider_store.py (new)
- tests/test_h517_named_provider_approval.py (new)

No other source/test paths edited in this slice.

## Contract and implementation

Store APIs match the plan: valid_provider_id, RESERVED_IDS, load, list_records, save_approved(expected_revision=...), clear; ProviderConflict/ProviderLimit subclass ProviderStoreError. Exact lowercase finite IDs; built-in reserved IDs refused. Separate settings SQLite table voice_command_providers(side,provider_id,approved_json,revision), primary key side+ID. BEGIN IMMEDIATE and rollback cover table creation, current-row inspection, count checks, CAS and commit. Concurrent independent names commit; concurrent same-revision writes yield one winner. Revisions are positive bounded SQLite integers. Clear increments revision even for never-seen or already-empty names and retains tombstones. Caps:16 active/128 historical per side,300000 UTF-8 JSON bytes per record, no tombstone recycling. Malformed JSON, duplicate fields, nonfinite constants, invalid revisions/counts/argv, overflow and storage faults fail closed.

Lookup uses a fresh mode=ro connection only. Absent database/table returns empty without initialization. Tombstones/absent IDs return only provider_id/provider_revision metadata; no legacy fallback. Writer refusal for a never-seen nonzero expected revision does not create the database. SQL abort leaves approved value/revision unchanged.

request/clear gain keyword-only provider_id=None, preserving omission/null legacy slot. Named request snapshot uses provider_id and provider_revision (current expected revision) in signed payload, server record and preview/title. Pending lookup isolates exact side+ID from other names and legacy. Request body uses strict optional string; invalid/reserved IDs refuse. Capacity/storage errors refuse honestly. Record-save failure returns503 approval_record_unavailable; the already queued task remains non-executable because no matching record exists.

Named apply retains exact recorded payload, plain human acceptance through irreversible execution, arming/safe-mode and bound-file rechecks, then saves by revision CAS. It cannot resurrect clear/recreate history, substitute another ID or apply edited intent. Registration maintains tier3/ASK even kernelGRANT and independently signed receipts. Legacy settings writer remains unchanged. Named clear only affects the chosen side/name.

Admin GET retains sides/arm_env/kind and adds providers:{tts:[],stt:[]} with active and pending-only names, metadata readiness using verify_content=False, and selected_stt_provider (None means legacy). Catalog storage failure supplies explicit provider_store_unavailable and empty named rows rather than a legacy named fallback.

POST named responses include provider_id/provider_revision when applicable. Dry-run registration creates no table/task/record. Settings adds only voice.stt_command_provider with empty legacy default and strict nonempty ID validation. Generic settings PUT/export/reset/undo do not install/delete/rewrite named authority. Capabilities retains old fields, adds ready named TTS selectors/rows and uses selected named STT readiness; named programs do not count as proven local TTS. No named execution grants are created by choosing a selector.

## RED/GREEN evidence

- /tmp/h517-named-store-red.xml: initial missing new store import (interface unavailable, not a behavioral assertion).
- /tmp/h517-named-approval-red.xml: real strict request fails because provider_id was not accepted by existing API.
- /tmp/h517-named-corrupt-red.xml:3 genuine failing assertions for duplicate approved JSON fields, empty argv and bool argv accepted by draft; now fail closed.
- /tmp/h517-named-no-write-red.xml: genuine assertion showing a revision conflict created an absent store; corrected precheck before writer connection.
- /tmp/h517-named-storage-approval-final.xml:42 passed,0 failures/errors/skips,1.452s. Includes strict signed installs, both sides, per-name isolation, pending visibility, exact edited/forged identity refusal, clear/recreate/revision-zero invalidation, record failure, bounded/corrupt/rollback/concurrent storage, no-write dry-run, selector validation and generic settings isolation.
- /tmp/h517-named-storage-final.xml:322 passed,0 failures/errors/skips,27.202s. Command:

```
.venv/bin/python -m pytest tests/test_h517_named_provider_store.py tests/test_h517_named_provider_approval.py tests/test_h613_piper_command_voice.py tests/test_h517_voice_kernel.py tests/test_settings_db.py tests/test_settings_defaults_undo.py tests/test_settings_transfer.py tests/test_admin_settings_mutations.py tests/test_voice_stt.py tests/test_stt_config.py tests/test_route_auth_matrix.py tests/test_action_auth_matrix.py -q --maxfail=3 --junitxml=/tmp/h517-named-storage-final.xml
```

Final42-case run additionally contains last two actual both-side and clear/recreate tests added after broad collection. Ruff on all six Python files and scoped git diff --check passed. Existing Starlette/httpx deprecation and two STT AsyncMock warning cases occurred in the broad group; no failures.

## Limits and handover

Task2 owns actual speech registry/dispatch and post-slot identity binding; parent owns shared/image/HUD/joined HTTP integration/full milestone. This writer has not asserted those independent tests or full-suite completion. Approved speech programs remain unverified for network locality; existing local_only exclusion is preserved. Registration authorizes exact program/script content, not libraries/imports. The existing bounded64 server request records may evict older cards, which then safely refuse as not_requested. No new expiry/configuration/retention migration. Ordinary settings reset preserves named tombstones and revisions; explicit global data purge remains outside this slice.

Rollback only these owned hunks; disable JARVIS_VOICE_COMMANDS to stop commands while preserving named rows/history. No automatic deletion or revision reset. Source frozen for parent integration and handover; no additional modules planned.

## Review correction — selected corrupt named store

Confirmed RED /tmp/h517-named-selected-store-red.xml: selected named STT command_status loaded corrupt named JSON before the catalog error handler, raising ProviderStoreError from capabilities. Changed only owned routers/voice.py and new approval test module: selected named metadata now uses command_ready(provider_id=...,verify_content=False), which returns structured unavailable on store failure. Catalog still emits providers.named_error=provider_store_unavailable; selected named readiness false, no legacy fallback. Cheap named readiness governs capability STT availability while preserving loaded Whisper mode behavior. Legacy STT keeps its existing path even if an unrelated named catalog is corrupt.

Three focused regressions cover corrupt selected structured unavailability, unrelated corrupt catalog preserving ready legacy STT, and no named metadata content hashing. Final focus 181 passed,0 failures/errors/skips,23.297 seconds: /tmp/h517-named-selected-store-final.xml (new storage+approval,H613,voice STT/config). Ruff/scoped diff clean; existing warnings unchanged. Source refrozen; no B-owned edits or broader scope.
