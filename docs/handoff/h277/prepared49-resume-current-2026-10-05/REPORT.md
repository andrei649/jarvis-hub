# H277 original49 after Kanban resume integration

Source HEAD `a7ffad6676cfb28e7ac374d495b4a5889e5f4646` with existing dirty local integration. All 49 original prepared semantic faults were run in a disposable copy of 997 regular inputs; root source was never mutated by this campaign.

Outcome: **43 assertion kills and six behavior-exception kills; zero survivors, invalid anchors/syntax, setup errors or timeouts**. Python baseline/restored360/360 and HUD40/40 pass. Every input hash is restored after every fault; source/snapshot drift are empty.

Mapping preserves the previously reviewed current-code faults. Every before-anchor occurs exactly once in current source. Original23 uses the accepted public-route witness; the fault itself is unchanged.

Shareable XML/results are sanitized derivatives: parameterized test names are replaced with deterministic case hashes, and raw failure diagnostics remain only in the external local campaign directory. `report.json` records raw and derivative file hashes and exact transformations. Method/class, outcomes, exception types, counts and timings remain available. Mapping and runner sources are included.

**Limits:** this is the original49 handoff mutation requirement, not full H277/provider/native acceptance or a current full backend result. The preceding full backend and HUD milestones retain their own dated source scopes. No push, merge, deploy or live provider activation.

| # | Original label | Outcome |
|---:|---|---|
| 1 | `roles_pick_legacy_wins_over_role_name` | killed_assertion |
| 2 | `roles_pick_shadowed_legacy_not_reported` | killed_assertion |
| 3 | `roles_pick_legacy_fallback_dropped` | killed_assertion |
| 4 | `roles_vision_view_legacy_url_wins` | killed_assertion |
| 5 | `roles_vision_view_provider_not_validated` | killed_assertion |
| 6 | `roles_validate_supported_set_check_dropped` | killed_behavioral_exception |
| 7 | `roles_main_becomes_env_selectable` | killed_behavioral_exception |
| 8 | `roles_env_role_default_provider_ollama` | killed_assertion |
| 9 | `roles_env_role_unset_model_guard_dropped` | killed_assertion |
| 10 | `roles_locality_or_instead_of_and` | killed_assertion |
| 11 | `roles_vision_lmstudio_default_url_dropped` | killed_assertion |
| 12 | `roles_describe_catches_wrong_error` | killed_behavioral_exception |
| 13 | `vlm_role_error_reason_masked` | killed_assertion |
| 14 | `model_config_override_flag_inverted` | killed_assertion |
| 15 | `judge_safe_mode_check_dropped` | killed_assertion |
| 16 | `judge_protocol_refusal_dropped` | killed_assertion |
| 17 | `judge_h378_findings_ignored` | killed_assertion |
| 18 | `judge_remote_gate_applies_to_local` | killed_behavioral_exception |
| 19 | `judge_allow_remote_inverted` | killed_assertion |
| 20 | `judge_strict_local_ignored` | killed_assertion |
| 21 | `judge_cloud_fallback_never_ignored` | killed_assertion |
| 22 | `judge_timeout_floor_dropped` | killed_assertion |
| 23 | `judge_public_leaks_remote_base_url` | killed_assertion |
| 24 | `judge_prompt_not_fenced` | killed_assertion |
| 25 | `judge_parse_extra_keys_allowed` | killed_assertion |
| 26 | `judge_parse_fractional_risk_allowed` | killed_assertion |
| 27 | `judge_parse_empty_why_allowed` | killed_assertion |
| 28 | `judge_parse_code_fence_unanchored` | killed_assertion |
| 29 | `judge_clamp_upper_bound_raised` | killed_assertion |
| 30 | `judge_rationale_fence_markers_kept` | killed_assertion |
| 31 | `judge_wants_unconfigured_guard_dropped` | killed_assertion |
| 32 | `judge_wants_skill_card_judged` | killed_assertion |
| 33 | `judge_wants_local_agent_sent_remote` | killed_assertion |
| 34 | `judge_wants_tainted_sent_remote` | killed_assertion |
| 35 | `judge_selection_pin_check_inverted` | killed_behavioral_exception |
| 36 | `queue_annotate_after_decision` | killed_assertion |
| 37 | `queue_annotate_second_answer_overwrites` | killed_assertion |
| 38 | `queue_annotate_low_score_auto_approves` | killed_assertion |
| 39 | `queue_snapshot_is_stored_item` | killed_assertion |
| 40 | `queue_judge_inherits_caller_context` | killed_assertion |
| 41 | `queue_short_lived_loop_not_judged_on_hub` | killed_assertion |
| 42 | `queue_decided_audit_drops_judge_identity` | killed_assertion |
| 43 | `queue_judged_audit_drops_judge_identity` | killed_assertion |
| 44 | `route_pending_drops_judge_key` | killed_behavioral_exception |
| 45 | `doctor_model_roles_attention_ignored` | killed_assertion |
| 46 | `doctor_model_roles_ignored_not_flagged` | killed_assertion |
| 47 | `hud_opinion_shown_on_skill_card` | killed_assertion |
| 48 | `hud_repoll_never_stops` | killed_assertion |
| 49 | `hud_opinion_advisory_label_dropped` | killed_assertion |
