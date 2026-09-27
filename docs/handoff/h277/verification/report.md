# H277 round2 local mutation verification

Executed 2026-09-27, local only. No production source mutations, commits, pushes, service changes, or global installs.

**Final: 73 killed, 0 survived, 1 superseded/equivalent, 0 invalid.**
All 49 prepared handoff cases were executed against their current semantic anchors and killed. Of 25 additional N1–N7 cases, 24 were killed and one is observationally equivalent.

## Scope and fingerprints

- Archived Git HEAD: `bd2bb70ead1b493043a335e77713fc42c47d4013`.
- Source snapshot: Git archive plus tracked dirty-file overlay taken before the concurrent kernel/mixin extraction. Untracked handoff files supply mutation metadata only. The snapshot has no .git directory.
- Original tracked-source fingerprint: `8f150f22e951b6d872355dd8fe9bd3553a9c3655d4563146a9c8abee7c4f856f`.
- Same source with coordinator regression-test overlay: `40d4d4b7e9634bb64e06893e1d43d718b08c75f49e2f6b266e7b6ad2decb6d5c`.
- [source_manifest.json](source_manifest.json) records every tracked-file SHA256, the dirty overlay, and the disposable source path. Fingerprints hash sorted JSON of relative paths and SHA256 values.
- [test_overlay_manifest.json](test_overlay_manifest.json) records the only subsequently copied files:

  - `tests/test_h277_approval_judge.py`: `5d93ae75533e99f7b0ad7476f1ce17201fc32e9b6f0c7e4042a93585b70691c7`
  - `tests/frontend/tools.test.js`: `c2f8d6343cbd00de6e5cec1902a8195440819537a8d5fccef1d54fa60740b827`

The evidence applies to the settled round2 implementation plus these test overlays. It does not verify the subsequently edited shared kernel, new routes, Decision Inbox extension, full backend suite, or separate frontend application.

## Baselines and execution

- Initial targeted Python union: **433 passed**; [exact command/output](logs/baseline_py.log).
- Initial legacy HUD tools file: **34 passed**; [exact command/output](logs/baseline_js.log).
- Test-overlay H277 judge/roles baseline: **275 passed**; [exact command/output](logs/overlay_baseline_py.log).
- Test-overlay legacy HUD tools baseline: **35 passed**; [exact command/output](logs/overlay_baseline_js.log).
- Python uses the repository `.venv/bin/python3.12 -B -m pytest` with normal project pytest addopts, timeout and socket controls. No addopts override. JS uses the current PATH node and existing Vitest dependency tree. Snapshot dependencies are symlinked; source is copied.
- Exactly one mutation process at a time. Each source file is restored in finally before proceeding. Python mutations parse before execution; collection/tool/import/setup errors are not counted as killed. No remaining invalid/unmatched cases.
- After the test overlay and final rechecks, all **3724 tracked-file hashes** matched their expected original/overlaid values; [restoration evidence](restoration.json).

## Survivors found and closed

The initial complete pass had 69 killed and 5 survivors. Five stale anchors were remapped and executed, never counted as kills while unmatched. [Original results](initial_results.json) retain every original survivor and log.

| Initial survivor | Regression/equivalence | Final |
|---|---|---|
| queue_short_lived_loop_not_judged_on_hub | Capture asyncio.get_running_loop in the fake backend probe and assert it is the hub loop; instant fake completion had masked wrong-loop scheduling. | killed |
| hud_repoll_never_stops | Capture a poll callback and invoke it after the hard deadline; an ordinary on-time fake timer had masked removal of the final deadline guard. | killed |
| N1_memory_pending_recheck_dropped | Run waiting-policy revocation with both persisted and in-memory queues; disk checks had masked removal of the memory-status guard. | killed |
| N4_remote_depth_refusal_dropped | Call remote score directly with a deep snapshot and assert no backend call; wants refusal had masked removal of the score defense. | killed |
| N2_decide_pending_not_cleared | Public pending also checks terminal status; capacity uses _judging; status never returns to pending; task finally clears both sets. Removing eager discard changes transient private state only. The source keeps eager cleanup. | superseded/equivalent |

Superseded here means observationally equivalent under the current public API, not unexecuted: the eager-discard mutant ran, returned zero, and is retained with observed_result=survived and a precise explanation. No kill ratio excludes this case silently.

## Reproduction

```sh
.venv/bin/python3.12 docs/handoff/h277/verification/run_mutations.py
# Resume invalid anchors only in that same snapshot:
H277_MUTATION_RESUME=1 .venv/bin/python3.12 docs/handoff/h277/verification/run_mutations.py
# Only after coordinator regression-test files are ready:
.venv/bin/python3.12 docs/handoff/h277/verification/recheck_survivors.py
.venv/bin/python3.12 docs/handoff/h277/verification/build_report.py
```

The initial evidence is tied to source_manifest.json; rerunning the initial script now snapshots the newer working tree and replaces that evidence. Archive this directory first if retaining these exact runs. The recheck script validates original snapshot hashes before copying tests and intentionally rejects a repeated overlay run.

## Cases and exact logs

Semantic anchor mappings are recorded in [effective_mutants.json](effective_mutants.json) and results.json. The obsolete test file tests/test_llm_model_config.py maps to existing tests/test_model_config.py. URL-default behavior moved to vlm.resolve_vlm_config; shallow taint and JSON-copy behavior moved to deep scanning and normalization; HUD poll-count caps moved to wall-clock deadlines.

| Case | Generation | Result | Evidence |
|---|---|---|---|
| roles_pick_legacy_fallback_dropped | prepared | killed | [log](logs/roles_pick_legacy_fallback_dropped.log) |
| roles_vision_view_provider_not_validated | prepared | killed | [log](logs/roles_vision_view_provider_not_validated.log) |
| roles_validate_supported_set_check_dropped | prepared | killed | [log](logs/roles_validate_supported_set_check_dropped.log) |
| roles_main_becomes_env_selectable | prepared | killed | [log](logs/roles_main_becomes_env_selectable.log) |
| roles_env_role_default_provider_ollama | prepared | killed | [log](logs/roles_env_role_default_provider_ollama.log) |
| roles_env_role_unset_model_guard_dropped | prepared | killed | [log](logs/roles_env_role_unset_model_guard_dropped.log) |
| roles_locality_or_instead_of_and | prepared | killed | [log](logs/roles_locality_or_instead_of_and.log) |
| roles_describe_catches_wrong_error | prepared | killed | [log](logs/roles_describe_catches_wrong_error.log) |
| vlm_role_error_reason_masked | prepared | killed | [log](logs/vlm_role_error_reason_masked.log) |
| model_config_override_flag_inverted | prepared | killed | [log](logs/model_config_override_flag_inverted.log) |
| judge_safe_mode_check_dropped | prepared | killed | [log](logs/judge_safe_mode_check_dropped.log) |
| judge_protocol_refusal_dropped | prepared | killed | [log](logs/judge_protocol_refusal_dropped.log) |
| judge_h378_findings_ignored | prepared | killed | [log](logs/judge_h378_findings_ignored.log) |
| judge_remote_gate_applies_to_local | prepared | killed | [log](logs/judge_remote_gate_applies_to_local.log) |
| judge_allow_remote_inverted | prepared | killed | [log](logs/judge_allow_remote_inverted.log) |
| judge_strict_local_ignored | prepared | killed | [log](logs/judge_strict_local_ignored.log) |
| judge_cloud_fallback_never_ignored | prepared | killed | [log](logs/judge_cloud_fallback_never_ignored.log) |
| judge_timeout_floor_dropped | prepared | killed | [log](logs/judge_timeout_floor_dropped.log) |
| judge_public_leaks_remote_base_url | prepared | killed | [log](logs/judge_public_leaks_remote_base_url.log) |
| judge_prompt_not_fenced | prepared | killed | [log](logs/judge_prompt_not_fenced.log) |
| judge_parse_extra_keys_allowed | prepared | killed | [log](logs/judge_parse_extra_keys_allowed.log) |
| judge_parse_fractional_risk_allowed | prepared | killed | [log](logs/judge_parse_fractional_risk_allowed.log) |
| judge_parse_empty_why_allowed | prepared | killed | [log](logs/judge_parse_empty_why_allowed.log) |
| judge_parse_code_fence_unanchored | prepared | killed | [log](logs/judge_parse_code_fence_unanchored.log) |
| judge_clamp_upper_bound_raised | prepared | killed | [log](logs/judge_clamp_upper_bound_raised.log) |
| judge_rationale_fence_markers_kept | prepared | killed | [log](logs/judge_rationale_fence_markers_kept.log) |
| judge_wants_unconfigured_guard_dropped | prepared | killed | [log](logs/judge_wants_unconfigured_guard_dropped.log) |
| judge_wants_skill_card_judged | prepared | killed | [log](logs/judge_wants_skill_card_judged.log) |
| judge_wants_local_agent_sent_remote | prepared | killed | [log](logs/judge_wants_local_agent_sent_remote.log) |
| judge_wants_tainted_sent_remote | prepared | killed | [log](logs/judge_wants_tainted_sent_remote.log) |
| judge_selection_pin_check_inverted | prepared | killed | [log](logs/judge_selection_pin_check_inverted.log) |
| queue_annotate_after_decision | prepared | killed | [log](logs/queue_annotate_after_decision.log) |
| queue_annotate_second_answer_overwrites | prepared | killed | [log](logs/queue_annotate_second_answer_overwrites.log) |
| queue_annotate_low_score_auto_approves | prepared | killed | [log](logs/queue_annotate_low_score_auto_approves.log) |
| queue_snapshot_is_stored_item | prepared | killed | [log](logs/queue_snapshot_is_stored_item.log) |
| queue_judge_inherits_caller_context | prepared | killed | [log](logs/queue_judge_inherits_caller_context.log) |
| queue_short_lived_loop_not_judged_on_hub | prepared | killed | [log](logs/recheck_queue_short_lived_loop_not_judged_on_hub.log) |
| queue_decided_audit_drops_judge_identity | prepared | killed | [log](logs/queue_decided_audit_drops_judge_identity.log) |
| queue_judged_audit_drops_judge_identity | prepared | killed | [log](logs/queue_judged_audit_drops_judge_identity.log) |
| route_pending_drops_judge_key | prepared | killed | [log](logs/route_pending_drops_judge_key.log) |
| doctor_model_roles_attention_ignored | prepared | killed | [log](logs/doctor_model_roles_attention_ignored.log) |
| doctor_model_roles_ignored_not_flagged | prepared | killed | [log](logs/doctor_model_roles_ignored_not_flagged.log) |
| hud_opinion_shown_on_skill_card | prepared | killed | [log](logs/hud_opinion_shown_on_skill_card.log) |
| hud_repoll_never_stops | prepared | killed | [log](logs/recheck_hud_repoll_never_stops.log) |
| N1_post_slot_status_stale | N1 | killed | [log](logs/N1_post_slot_status_stale.log) |
| N1_post_slot_wants_dropped | N1 | killed | [log](logs/N1_post_slot_wants_dropped.log) |
| N1_disk_pending_recheck_dropped | N1 | killed | [log](logs/N1_disk_pending_recheck_dropped.log) |
| N1_memory_pending_recheck_dropped | N1 | killed | [log](logs/recheck_N1_memory_pending_recheck_dropped.log) |
| N1_skip_revoked_counter_dropped | N1 | killed | [log](logs/N1_skip_revoked_counter_dropped.log) |
| N2_public_pending_hidden | N2 | killed | [log](logs/N2_public_pending_hidden.log) |
| N2_finish_pending_not_cleared | N2 | killed | [log](logs/N2_finish_pending_not_cleared.log) |
| N2_decide_pending_not_cleared | N2 | superseded | [log](logs/N2_decide_pending_not_cleared.log) |
| N2_hud_early_timeout | N2 | killed | [log](logs/N2_hud_early_timeout.log) |
| N2_hud_deadline_refreshes | N2 | killed | [log](logs/N2_hud_deadline_refreshes.log) |
| N2_capacity_released_on_decide | N2 | killed | [log](logs/N2_capacity_released_on_decide.log) |
| N3_within_budget_values_cut | N3 | killed | [log](logs/N3_within_budget_values_cut.log) |
| N3_small_values_inflated | N3 | killed | [log](logs/N3_small_values_inflated.log) |
| N3_args_cap_raised | N3 | killed | [log](logs/N3_args_cap_raised.log) |
| N4_deep_truncated_flag_dropped | N4 | killed | [log](logs/N4_deep_truncated_flag_dropped.log) |
| N4_deep_flag_dropped | N4 | killed | [log](logs/N4_deep_flag_dropped.log) |
| N4_remote_depth_refusal_dropped | N4 | killed | [log](logs/recheck_N4_remote_depth_refusal_dropped.log) |
| N4_normalised_marker_not_tainted | N4 | killed | [log](logs/N4_normalised_marker_not_tainted.log) |
| N5_nfkc_dropped | N5 | killed | [log](logs/N5_nfkc_dropped.log) |
| N5_unicode_quote_categories_dropped | N5 | killed | [log](logs/N5_unicode_quote_categories_dropped.log) |
| N5_dot_separator_kept | N5 | killed | [log](logs/N5_dot_separator_kept.log) |
| N6_bytes_repr_instead_of_decode | N6 | killed | [log](logs/N6_bytes_repr_instead_of_decode.log) |
| N6_set_repr_instead_of_list | N6 | killed | [log](logs/N6_set_repr_instead_of_list.log) |
| N7_import_guard_wrong_exception | N7 | killed | [log](logs/N7_import_guard_wrong_exception.log) |
| N7_unconfigured_judge_taints_item | N7 | killed | [log](logs/N7_unconfigured_judge_taints_item.log) |
| roles_pick_legacy_wins_over_role_name | prepared | killed | [log](logs/roles_pick_legacy_wins_over_role_name.log) |
| roles_pick_shadowed_legacy_not_reported | prepared | killed | [log](logs/roles_pick_shadowed_legacy_not_reported.log) |
| roles_vision_view_legacy_url_wins | prepared | killed | [log](logs/roles_vision_view_legacy_url_wins.log) |
| roles_vision_lmstudio_default_url_dropped | prepared | killed | [log](logs/roles_vision_lmstudio_default_url_dropped.log) |
| hud_opinion_advisory_label_dropped | prepared | killed | [log](logs/hud_opinion_advisory_label_dropped.log) |

## Limits

- This is targeted mutation verification, not exhaustive correctness, kernel verification, or completion of the broader H277 ledger. Mutants model specific behavioral regressions; unrelated bugs can remain.
- Five initial test survivors led to four coordinator-owned regression improvements and one equivalence analysis. Live source/tests were never edited by this verification agent.
- An already dispatched remote call cannot be retracted. Snapshot tests do not establish multi-process transactional persistence or real-provider network behavior.
- Disposable source and existing dependency environments are reused; no paid provider or real remote model was invoked. Test execution remains governed by the project socket controls.
