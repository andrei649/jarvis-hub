# Antigravity handover inventory review

Generated 2026-11-14T09:23:37.073000+00:00. Read-only inventory; only this report written. No remote calls, source changes, staging, commits, merge or deploy. Read `/workspace/jarvis-hub/AGENTS.md`; the current owner handover/publication request supersedes its historical local-only publication restriction, while preservation and truthful evidence remain applicable.

## Finding

There are TWO complementary source lines. Publishing only the V81 combined tree is not uploading all cumulative work. Publishing the original cumulative V70 tree alone would lose later reviewed fixes. Do not overlay either tree wholesale onto the other.

- Original `/workspace/jarvis-hub`: branch `codex/hermes-continuation-20261112`, HEAD `686fcbf4f25ebfbb416b3a35dff29045163cffbd`, 439 dirty status records, zero staged, 7,294 present source files plus 8 deleted tracked paths (7,302 historical Git paths). V70 complete main delta is 463 paths, including six committed gateway prerequisites and new files. `nerva-continuation-v70-delivery/main-to-v70.patch` reconstructs this cumulative source on main `1338833d5a344d277c43828a9d9314e10af792f1`; do not apply successive cumulative V1–V70 patches.
- Combined `/workspace/scratch/nerva-v81-combined/source`: 7,068 files, tree `9deba0f24220f9f0f89fee585f2a923e549cecc1`; manifest reports 114 main-relative paths. Existing publication receipt records PR1363 head `702845ae45765583f996fdb5b2b08de9db6664bc`, that exact tree and parent `33b8d57bc2897cc8d5c33f148cb7ea47c443cf7b`. This is a dated local receipt, not a fresh remote verification.
- Fresh comparison: 186 present same-path files have different bytes; 236 present original paths are absent from combined. These are largely cumulative runtime, tests, UI, docs, and rebuilt chunks, not cache artifacts. Appendix lists both sets. The combined manifest additionally includes new browser helper/tests absent from original. `docs/foreign-session-resume.md` and `tests/test_browser_chromium_runtime.py` remain base bytes in original and have later changes in combined.

## Delivery lineage to retain

| Version | Distinct handover content |
| --- | --- |
| V70 | Full cumulative source, main-based forward/rollback proofs, full Linux 36,570 passed/108 skipped; fresh mobile420, build/types. Frontend3178 reused with byte linkage. See final receipts, not earlier red run. |
| V71 | Standalone CLI organization and parent JSON fix, not copied back to original. |
| V72–73 | Bootstrap locked/unlocked/smoke extraction, bookkeeping; pagination prerequisite on main. |
| V74 | Composed CLI history/pagination and trailing/parent JSON fixes. |
| V75–76 | Retained transcript backend/CLI, web privacy formatter and preview/download; mobile preview with intentional no native export; separate bootstrap PR1360. |
| V77 | PR1361 organization on exact candidate tree, complete successful dated CI. |
| V78 | Retained surfaces PR1362, actual generator comment correction, schema equivalence, privacy and stale-state handling. |
| V79 | Session history/pagination PR1363; metadata-only filtering and bounded scans. |
| V80 | Reconciled PR1359–1363 source, preserving parser dispatch/JSON flags/session API/schema; literal script SILENT transport, conservative Unicode estimate, deterministic skill/PDF/DNS/OCR fixtures, actual57-route docs. Full backend34,904passed108skipped; frontend3009/mobile396/typechecks/build. |
| V81 | Exact ready-browser fixture with test-only child supervisor; pinned actual combined OpenAPI generation; 693 focused passes. Production bytes unchanged from V80. Remote publication head/tree receipt exists. |

Retain delivery directories `nerva-continuation-v70-delivery`, `nerva-v71-delivery` through `nerva-v80-delivery`, V81 combined/typegen/Chrome receipts, forward/rollback patches, source manifests, input-head records and red as well as green evidence. Avoid raw recursive scratch upload: scratch contains runtime fixtures, node_modules, caches, Git objects, and quarantined proposals. Archives and each version's structured report are durable historical evidence; they are not sequential patches to apply.

## V50 and other outside-original material

`nerva-v50-isolated-delivery` (plus immutable ZIP and candidate manifest) must remain as historical provenance, but its older runtime files must not overwrite V70. Compared its intended candidate paths to current original: activation_hints.py, command_bindings.py and test_extension_manifest_catalog.py are byte-identical; restored_commands.py/runtime.py and five restoration tests differ. None of the ten intended paths is missing. Original now has later startup/acquisition/persistence integration and H079 test families; V50's “not integrated” statement is historical, not proof of current missing functionality. Exclude candidate __pycache__.

The full external Mac handover export remains unavailable: `mac-handover-audit/RECONCILIATION_BLOCKED.md` records absent shared export/report paths and HTTP403 downloads. Parent-reported path/block counts are not independently verified source. Carry this limitation and any available sanitized reports; do not invent Mac reconciliation completion or apply absent deltas. Actual Windows checkout remains unobserved; do not overwrite its work or claim conflict clearance. No review of other repository directories was authorized or undertaken.

## Known blocked/quarantined boundaries

- Update/restart adversarial review was platform-blocked and incomplete. Do not retry/bypass blocked reproduction or upload blocked reproduction materials. Existing cumulative kernel/security/host lifecycle source is legitimate preserved work, but must be described as unreviewed at that boundary rather than security-neutral.
- V80 unsafe Chrome diagnostic proposal was quarantined and excluded. Carry its exclusion/reason, not proposal code. V81 is a separately reviewed fixture correction; exact historical Google Chrome failure cause was not proven locally.
- Legacy complete-history replay lacks provenance and remains excluded. Bounded retained text/history is the implemented feature; do not conflate it with legacy recovery.
- Native device/provider/real channel acceptance, unknown Windows checkout, and unavailable Mac source stay explicit limitations. No paused schedule/service activation or network changes are implied by upload.

## Safe assembly and publication strategy

1. Freeze/hash original dirty source and V81 manifest immediately before assembly. Work in a new isolated tree; preserve original index/source, immutable packages and existing remote branches. Check actual main and PR heads before any mutation; never overwrite a moved head or force-push.
2. Reconstruct complete V70 once from its pinned main-based package (or exact original files plus deletion manifest). This captures the 236 source paths absent from combined. Preserve full source as an archive/manifest even if later integrated source requires review.
3. Reconcile V81 delta against the common pinned main using three-way/hunk review. Many overlapping files are modified on BOTH sides: CLI, channels, commands, orchestrator/web, bootstrap/serve, frontend sessions, mobile clients, BACKLOG and generated status. A whole-file copy of V81 would erase V70 extensions/restart/channel wiring; a whole-file copy of V70 would erase reviewed later corrections. Keep source conflicts visible until resolved. Treat generated assets as a coherent build output set, not independent chunks.
4. Preserve V71/V74 JSON parser fixes, V76/V78 privacy/generator corrections, V80 transport/Unicode/PDF/DNS/OCR fixes and V81 browser helpers explicitly. Recollect counts, regenerate schema/status/build artifacts on the resulting cumulative candidate; standalone 57-route/collection totals cannot simply replace V70 totals.
5. Test actual assembled source. V70 and V81 receipts certify different trees; neither certifies the union. Run focused boundary regressions, types/build, policy/route/parity/metadata checks and appropriate full backend on the final union before claiming integrated acceptance. Keep blocked adversarial review visibly incomplete.
6. Publish only from the verified isolated branch and package sanitized source/evidence in a complete handover. Existing V81 publication can remain a separate exact artifact; do not duplicate its blobs/PR blindly. Check exact resulting head/tree and triggered CI after publication. Keep draft/no-merge/no-deploy safeguards requested by owner.

A complete archival handover can safely include BOTH exact snapshots plus lineage/evidence without pretending that their union is tested. A single runnable “all work” tree requires explicit reconciliation/testing above; V81 combined is only the selected five-PR composition, not cumulative V70.

## Appendix: fresh source comparison

Original present files absent from V81 combined (236):

```text
agents/core/autonomy/restart_records.py
agents/core/channels/connect_deadline.py
agents/core/channels/credentials.py
agents/core/channels/discord_commands.py
agents/core/channels/discord_media.py
agents/core/channels/escalation.py
agents/core/channels/inbound_document.py
agents/core/channels/media_limits.py
agents/core/channels/native_metadata.py
agents/core/channels/outbound_stream.py
agents/core/channels/polling_claims.py
agents/core/channels/skill_menu.py
agents/core/channels/sticker_reader.py
agents/core/checkpoint_session_diff.py
agents/core/command_discovery.py
agents/core/command_shortcuts.py
agents/core/command_source.py
agents/core/diagnostic_commands.py
agents/core/diff_commands.py
agents/core/diff_paths.py
agents/core/egress_commands.py
agents/core/extensions/activation_hints.py
agents/core/extensions/command_bindings.py
agents/core/extensions/restored_commands.py
agents/core/extensions/store_lock.py
agents/core/hub_restart_apply.py
agents/core/identity_commands.py
agents/core/maintenance_commands.py
agents/core/mcp/saved_reload.py
agents/core/mcp_reload_confirmation.py
agents/core/platform_commands.py
agents/core/restart_command.py
agents/core/restart_notice.py
agents/core/restart_runtime.py
agents/core/session_transition.py
agents/core/skills/slash_load.py
agents/core/update_commands.py
agents/core/update_progress.py
agents/web/v2/assets/gap-BFo5hWDr.js
agents/web/v2/assets/index-40MgBx64.js
agents/web/v2/assets/jobs-cMUJEowo.js
agents/web/v2/assets/modes-DOv6-vXA.js
agents/web/v2/assets/modes2-C17hSjEo.js
agents/web/v2/assets/modes3-CChH2t0x.js
agents/web/v2/assets/modes4-CcJUbZiJ.js
agents/web/v2/assets/modes_world-DjJLPhfW.js
docs/DISCORD_SETUP.md
docs/INBOUND_MEDIA.md
docs/SKILL_COMMANDS.md
docs/hermes/evidence/2026-11-12-local-continuation.md
frontend/native-tests/deliveries.test.tsx
frontend/native-tests/extension-inspection.test.tsx
frontend/native-tests/session-filters.test.tsx
frontend/native-tests/session-pagination.test.tsx
frontend/native-tests/session-recovery.test.tsx
frontend/native-tests/session-search.test.tsx
frontend/src/panels/channel-deliveries.test.tsx
frontend/src/panels/channel-deliveries.tsx
frontend/src/panels/extension-inspection.test.tsx
frontend/src/panels/extension-inspection.tsx
frontend/src/session-recovery.ts
frontend/src/test/app-session-recovery.test.tsx
frontend/src/test/desktop-session-recovery.test.tsx
frontend/src/test/session-recovery.test.ts
frontend/src/test/sessions-filters.test.tsx
frontend/src/test/sessions-pagination.test.tsx
frontend/src/test/sessions-search.test.tsx
mobile/src/api/__tests__/extensions.test.ts
mobile/src/api/deliveries.ts
mobile/src/api/extensions.ts
mobile/src/components/DeliveryReceipts.tsx
mobile/src/components/ExtensionInspection.tsx
mobile/src/components/__tests__/extensionInspectionContract.test.ts
scripts/venv_ownership.py
tests/support/h079_plugin_import_probe.py
tests/test_archive_snapshot_identity.py
tests/test_backup_identity_failure_review.py
tests/test_backup_restore_receipt_digest.py
tests/test_bootstrap_lock_review.py
tests/test_bootstrap_venv_guard.py
tests/test_bootstrap_venv_real_guard.py
tests/test_h010_restore_archive_identity.py
tests/test_h057_bundle_precedence.py
tests/test_h057_command_completion.py
tests/test_h057_discord_commands.py
tests/test_h057_help_mentions_composed.py
tests/test_h057_telegram_help_mentions.py
tests/test_h069_anthropic_failure_safety.py
tests/test_h069_native_metadata.py
tests/test_h069_protocol_outbound.py
tests/test_h069_provider_error_envelopes.py
tests/test_h069_provider_error_transports.py
tests/test_h069_web_outbound.py
tests/test_h070_discord_media.py
tests/test_h070_media_limits.py
tests/test_h070_media_transport_limits.py
tests/test_h070_telegram_documents.py
tests/test_h070_telegram_stickers.py
tests/test_h079_acquisition_restore.py
tests/test_h079_activation_hint_persistence.py
tests/test_h079_activation_hints.py
tests/test_h079_collision_diagnostics.py
tests/test_h079_command_bindings.py
tests/test_h079_command_discovery.py
tests/test_h079_consent_revision.py
tests/test_h079_discord_skill_menu.py
tests/test_h079_extension_cli_inspection.py
tests/test_h079_extension_command_inspection.py
tests/test_h079_extension_regrant_fences.py
tests/test_h079_extension_restart_cli.py
tests/test_h079_extension_restart_composed.py
tests/test_h079_extension_restart_routes.py
tests/test_h079_extension_rpc_retirement.py
tests/test_h079_extension_store_lock.py
tests/test_h079_native_skill_menu.py
tests/test_h079_plugin_loadset_preflight.py
tests/test_h079_reload_during_start.py
tests/test_h079_reload_menu_composed.py
tests/test_h079_reload_menu_queue.py
tests/test_h079_required_args_composed.py
tests/test_h079_required_args_manifest.py
tests/test_h079_required_args_menu.py
tests/test_h079_restored_commands.py
tests/test_h079_restored_composed.py
tests/test_h079_shortcut_catalog.py
tests/test_h079_shortcut_composed.py
tests/test_h079_skill_dispatch.py
tests/test_h079_skill_slash.py
tests/test_h079_telegram_menu_refresh.py
tests/test_h080_command_observer_queue.py
tests/test_h080_command_started.py
tests/test_h080_observer_admission.py
tests/test_h080_observer_threads.py
tests/test_h080_started_composed.py
tests/test_h080_started_subscription.py
tests/test_h081_card_fallback.py
tests/test_h081_card_fallback_composed.py
tests/test_h081_delivery_claims.py
tests/test_h081_discord_prompt_outcomes.py
tests/test_h081_keyed_delivery_failure.py
tests/test_h081_ledger_startup.py
tests/test_h081_media_delivery_claims.py
tests/test_h081_prompt_receipts.py
tests/test_h081_prompt_receipts_composed.py
tests/test_h081_receipt_snapshot.py
tests/test_h081_slack_prompt_outcomes.py
tests/test_h081_telegram_ack.py
tests/test_h081_telegram_ack_composed.py
tests/test_h081_unconfirmed_ack.py
tests/test_h083_claim_backup_boundary.py
tests/test_h083_claim_file_preflight.py
tests/test_h083_connect_deadline.py
tests/test_h083_credentials.py
tests/test_h083_discord_claim_kernel.py
tests/test_h083_discord_claims.py
tests/test_h083_discord_credentials.py
tests/test_h083_discord_deadline.py
tests/test_h083_email_circuit.py
tests/test_h083_email_deadline.py
tests/test_h083_email_worker_boundary.py
tests/test_h083_escalation_fences.py
tests/test_h083_escalation_tracker.py
tests/test_h083_ntfy_circuit.py
tests/test_h083_ntfy_claim_kernel.py
tests/test_h083_ntfy_claim_retirement.py
tests/test_h083_ntfy_claims.py
tests/test_h083_ntfy_close_boundary.py
tests/test_h083_ntfy_deadline.py
tests/test_h083_platform_audit.py
tests/test_h083_platform_audit_dispatch.py
tests/test_h083_platform_command.py
tests/test_h083_polling_circuit.py
tests/test_h083_polling_claims.py
tests/test_h083_sdk_failures.py
tests/test_h083_slack_claim_kernel.py
tests/test_h083_slack_claims.py
tests/test_h083_slack_claims_native.py
tests/test_h083_slack_credentials.py
tests/test_h083_slack_deadline.py
tests/test_h083_sustained_escalation.py
tests/test_h083_telegram_circuit.py
tests/test_h083_telegram_claims.py
tests/test_h083_telegram_credentials.py
tests/test_h083_telegram_deadline.py
tests/test_h084_checkpoint_session_diff.py
tests/test_h084_command_source.py
tests/test_h084_debug_command.py
tests/test_h084_diff_command.py
tests/test_h084_diff_path_command.py
tests/test_h084_diff_path_selection.py
tests/test_h084_diff_paths_composed.py
tests/test_h084_diff_session_command.py
tests/test_h084_egress_command.py
tests/test_h084_identity_commands.py
tests/test_h084_mcp_saved_command.py
tests/test_h084_mcp_saved_reconcile.py
tests/test_h084_pause_off.py
tests/test_h084_reload_mcp.py
tests/test_h084_reload_skills.py
tests/test_h084_restart_authority.py
tests/test_h084_restart_command_notice.py
tests/test_h084_restart_composed.py
tests/test_h084_restart_ingress.py
tests/test_h084_restart_jobs.py
tests/test_h084_restart_phrase_authority.py
tests/test_h084_restart_phrase_ingress.py
tests/test_h084_restart_phrase_transport.py
tests/test_h084_restart_physical.py
tests/test_h084_restart_runtime.py
tests/test_h084_restart_subagent_admission.py
tests/test_h084_restart_update_exclusion.py
tests/test_h084_restart_wiring.py
tests/test_h084_restart_worker_admission.py
tests/test_h084_update_command.py
tests/test_h084_update_kernel.py
tests/test_h084_update_progress_reader.py
tests/test_h084_update_singleton.py
tests/test_h084_update_singleton_command.py
tests/test_h084_update_status.py
tests/test_h084_update_status_composed.py
tests/test_h096_cancellation_checkpoint.py
tests/test_h096_fetch_checkpoint.py
tests/test_h624_stash_baseline.py
tests/test_h624_stash_review.py
tests/test_h624_update_trust_boundary.py
tests/test_h695_import_review.py
tests/test_h695_restore_completion.py
tests/test_h695_startup_import_diagnostic.py
tests/test_h697_mobile_missing_contract.py
tests/test_h697_resume_refusal_contract.py
tests/test_orchestrator_process_scope_audit.py
tests/test_sec_b5_recall_scope_audit.py
tests/test_session_transition.py
tests/test_v50_runtime_pins.py
tests/test_venv_mutation_guard.py
tests/test_venv_ownership.py
```

Different present same-path files (186):

```text
.gitignore
BACKLOG.md
GO_LIVE_PLAN.md
HERMES_STATUS.md
NERVA.md
README.md
STATUS.md
agents/cli/nerva.py
agents/cli/session_history.py
agents/cli/session_transcript.py
agents/core/acquisition/runtime.py
agents/core/archive_safe.py
agents/core/autonomy/executor.py
agents/core/autonomy/irreversible.py
agents/core/autonomy/jobs.py
agents/core/autonomy/jobs_dispatch.py
agents/core/autonomy/queue.py
agents/core/autonomy/worker.py
agents/core/autonomy_coordinator.py
agents/core/backup.py
agents/core/capability_manifests.py
agents/core/capability_verification.py
agents/core/channel_reply.py
agents/core/channels/base.py
agents/core/channels/delivery_ledger.py
agents/core/channels/discord.py
agents/core/channels/email.py
agents/core/channels/gateway.py
agents/core/channels/inbound_media.py
agents/core/channels/inbound_voice.py
agents/core/channels/manager.py
agents/core/channels/media_reader.py
agents/core/channels/ntfy.py
agents/core/channels/outbound_safety.py
agents/core/channels/pending_input_runtime.py
agents/core/channels/reconnect.py
agents/core/channels/slack.py
agents/core/channels/telegram.py
agents/core/commands.py
agents/core/env_config.py
agents/core/env_provenance.py
agents/core/extensions/consent.py
agents/core/extensions/doctor.py
agents/core/extensions/events.py
agents/core/extensions/manifest.py
agents/core/extensions/runtime.py
agents/core/file_checkpoint_history.py
agents/core/hub_update_apply.py
agents/core/kernel/__init__.py
agents/core/kernel/registry.py
agents/core/lifecycle_budget.py
agents/core/llm/anthropic.py
agents/core/llm/tokenizer.py
agents/core/mcp/client.py
agents/core/observability/reality_harness.py
agents/core/openai_api/turn.py
agents/core/orchestrator.py
agents/core/orchestrator_bindings.py
agents/core/plugin_manager.py
agents/core/quick_commands.py
agents/core/routers/chat_pending.py
agents/core/routers/commands.py
agents/core/routers/integrations.py
agents/core/routers/openai_compat.py
agents/core/routers/plugins.py
agents/core/routers/workspace_chat.py
agents/core/safe_mode.py
agents/core/security/recall_taint.py
agents/core/settings_db.py
agents/core/skills/bundles.py
agents/core/skills/loader.py
agents/core/subagents.py
agents/web.py
agents/web/v2/index.html
desktop/src-tauri/hud-routes.json
docs/DEVELOPMENT_ROADMAP.md
docs/EXTENSIONS.md
docs/HERMES_CAPABILITIES.md
docs/INSTALL.md
docs/SLACK_SETUP.md
docs/design/HUD_V2_REMAINING.md
docs/foreign-session-resume.md
docs/hermes/CAMPAIGN_HANDOFF.md
docs/hermes/areas.json
docs/hermes/assessment.json
frontend/native-tests/commands.test.tsx
frontend/native-tests/conversation.test.tsx
frontend/native-tests/session-transcript.test.tsx
frontend/native-tests/turn-duration.test.tsx
frontend/src/api/schema.gen.ts
frontend/src/app.tsx
frontend/src/console-routes.ts
frontend/src/desktop.tsx
frontend/src/gap.tsx
frontend/src/panels/channels-config.tsx
frontend/src/panels/quickbar.test.tsx
frontend/src/panels/quickbar.tsx
frontend/src/panels/sessions.tsx
frontend/src/test/h595-chat-followup.test.tsx
frontend/src/test/sessions-transcript.test.tsx
mobile/PARITY.md
mobile/src/api/__tests__/streamChat.test.ts
mobile/src/api/client.ts
mobile/src/api/commands.ts
mobile/src/api/sse.ts
mobile/src/chat/__tests__/conversation.test.ts
mobile/src/chat/conversation.ts
mobile/src/components/CommandsModal.tsx
mobile/src/components/SessionsModal.tsx
mobile/src/screens/ChatScreen.tsx
mobile/src/screens/StatusScreen.tsx
mobile/src/storage/__tests__/chat.test.ts
mobile/src/storage/chat.ts
project-status.json
scripts/bootstrap.py
serve.py
tests/_snapshots/action_auth.json
tests/_snapshots/capability_readiness.json
tests/test_action_auth_matrix.py
tests/test_aud7_sse_hotpath.py
tests/test_backup_h010_review.py
tests/test_backup_h010_review5.py
tests/test_backup_h010_review6.py
tests/test_bootstrap_script.py
tests/test_browser_chromium_runtime.py
tests/test_browser_kernel_gate.py
tests/test_channel_render.py
tests/test_chat_http.py
tests/test_cli_session_history.py
tests/test_cli_session_organization.py
tests/test_cli_session_transcript.py
tests/test_cloud_image.py
tests/test_commands_catalog.py
tests/test_default_deny_front_door.py
tests/test_extension_consent.py
tests/test_extension_event_emission.py
tests/test_extension_events.py
tests/test_extension_manifest_catalog.py
tests/test_extension_runtime.py
tests/test_g15_channel_reliability.py
tests/test_h026_skill_bundles.py
tests/test_h069_outbound_safety.py
tests/test_h096_email_channel.py
tests/test_h117_message_batching.py
tests/test_h15_1_browser_agent.py
tests/test_h223_terminal_client.py
tests/test_h275_safe_mode.py
tests/test_h27_capability_verification.py
tests/test_h27_earned_autonomy.py
tests/test_h285_load_set.py
tests/test_h297_production_images.py
tests/test_h310_web_parity.py
tests/test_h331_pending_skill_review.py
tests/test_h381_egress_ledger_persistence.py
tests/test_h381_no_bare_model_client.py
tests/test_h391_turn_compaction.py
tests/test_h396_turn_outcome.py
tests/test_h430_recall_indicator.py
tests/test_h450_app_timezone.py
tests/test_h450_schedule_words.py
tests/test_h490_safe_mode_posture.py
tests/test_h624_update_apply.py
tests/test_h677_boot_and_shutdown.py
tests/test_hud_v2_parity.py
tests/test_inbound_media_read.py
tests/test_inbound_voice_read.py
tests/test_job_gates.py
tests/test_ntfy_inbound.py
tests/test_o26_golden_loop_chat.py
tests/test_orchestrator_bindings.py
tests/test_pending_input_native_transport.py
tests/test_pending_input_workspace_runtime.py
tests/test_require_component_sweep.py
tests/test_session_pagination.py
tests/test_session_transcript.py
tests/test_slack_socket_mode.py
tests/test_slash_commands.py
tests/test_telegram_inbound_media.py
tests/test_telegram_streaming.py
tests/test_telegram_voice_reply.py
tests/test_turn_status_readout.py
tests/test_workspace_assistant_sse.py
tests/test_workspace_file_modes.py
tests/test_workspace_integration.py
tests/test_workspace_ocr.py
tests/test_workspace_windows_ocr_job.py
```


## Follow-up: exact outside-original candidates and public-source hygiene

The coordinator intends a separate exact cumulative V70 draft, keeping PR1363 untouched. That safely preserves the two source lines without claiming their union is integrated. Keep a machine path comparison and integration instructions with that draft.

Exactly ten present V81 files are absent from original: `tests/browser_orphan_fixture.py`, `tests/test_browser_orphan_fixture.py`, and eight compiled chunks `agents/web/v2/assets/{gap-DaUsI-au,index-CZDMKepl,jobs-DggYcr9N,modes-BNhbWsWm,modes2-DXD0WAzx,modes3-C9_cmo-e,modes4-C0snaE_q,modes_world-BL1vQ8CL}.js`. The two test helpers are distinct later source that must be represented in the handover; assets belong with their exact V81 index/build and must not be mixed into V70's build. The V81 fixture change also requires its existing target file delta. V50 adds no uniquely missing intended path to cumulative V70; preserve its immutable historical candidate package without replacing evolved code.

Correction/clarification to the external-Mac gap: an isolated recovered V51 proposal DOES exist locally under `nerva-continuation-v70-delivery/mac-review-not-integrated/`. It is distinct from the unavailable full external Mac export. It contains `bounded-inspection-combined.patch` (recovered archive inspection helper plus PAX metadata-cache fix), `pax-cache-fix.patch`, `tests/test_archive_inspection_recovery.py`, `tests/test_archive_inspection_adversarial.py`, `tests/test_archive_inspection_pax_cache.py`, `pax_memory_probe.py`, two memory JSON receipts, `final-receipt.json`, `REPORT.md` and `V52-NOTE.md`. The combined patch is based on pre-V52 archive_safe.py, has no caller adoption and remains unapplied. Represent it as an explicitly unapplied `.patch.txt` proposal with its tests/reviewed receipts; do not call it missing integrated functionality or apply over evolved archive safety source. Reported final evidence is119 ordinary cases plus12 successful subtests (131 aggregate reports), not131 distinct test nodes. The full external export/actual Windows limits still stand.

Public-source scan: inspected all430 readable changed/new original text files, including JSON and generated JS, for common private-key, GitHub/AWS/OpenAI/Slack/Telegram credential patterns. Only two matches occurred: deterministic synthetic `sk-DIAGNOSTIC-*` test sentinels in `tests/test_h084_debug_command.py` at lines76/92. The sentinels are intentionally supplied to redaction assertions and are not live credentials. No email-address patterns occurred in changed Markdown/JSON. The1591-line continuation evidence document contains authored engineering checkpoints and test/limitation notes; no raw user/assistant conversation or obvious personal data was found in the inspected evidence text. This is a bounded pattern/manual source scan, not an unrun Gitleaks result or certification of every external artifact. Exclude logs, runtime databases, real conversation archives, personal overrides, caches, dependencies and Git internals. Check any chosen receipt/proposal files separately before public inclusion.

Quarantine representation: preserve the V80 Chrome proposal's exclusion and review reason explicitly. If coordinator chooses to carry its source as `.patch.txt`, keep it unmistakably inert/unapplied and separate from V81 implementation. Do not include platform-blocked update/restart reproduction materials; a filename suffix does not authorize bypass of that prior block.
