# H277 original prepared 49 — current-source refresh

Source HEAD at capture: `825533f449d5dd0b02c763e1d19bb08683f3fd0d`; current HEAD at final audit: `45a2a9c2e3e730a5ffe1663b33001c2a43aa81f4`. Every one of the 942 copied regular source/test/config paths still matches its captured SHA-256 in both snapshot and authoritative checkout. The path/hash fingerprint is `fa25ebc9524298503438b16cc33e2254c47d76315a1a8c8e84b8933cdfcb6c03`; input manifest SHA-256 `81d6c1e37ceb7db805f36eb515187f25187689559400c8dd7bf60f636d546795`. No authoritative checkout files, Git/index state, providers, or network were changed by this campaign.

Original prepared list: `original-mutants.json`, copied byte-for-byte from `docs/handoff/h277/mutants.json`. `mapping.json` records all 49 original before/after edits, present-code anchors, exact current source hashes and focused tests. All 49 anchors were unique and all mutations had valid Python AST or Node syntax. Each fault was applied alone; all 942 snapshot inputs were SHA-256 checked after every restoration. No missing anchor, setup/import failure, timeout, or harness error occurred.

Baseline and final restored suites: Python 359/359 passed (the four original relevant files plus current direct late-annotation, persistence, and model-config tests); HUD Vitest 40/40 passed. Current-source initial outcome on existing tests: **42 assertion kills, 6 behavior-changing exception kills, 1 survivor**. The existing direct late-annotation test now kills original #36 by assertion. These totals do not imply H277 parity.

| # | Original prepared label | Outcome | Decisive observation |
|---:|---|---|---|
| 1 | `roles_pick_legacy_wins_over_role_name` | `killed_assertion` | test_role_model_overrides_the_legacy_model_and_names_the_shadowed_variable — AssertionError |
| 2 | `roles_pick_shadowed_legacy_not_reported` | `killed_assertion` | test_role_model_overrides_the_legacy_model_and_names_the_shadowed_variable — AssertionError |
| 3 | `roles_pick_legacy_fallback_dropped` | `killed_assertion` | test_vision_role_falls_back_to_jarvis_vlm_model — AssertionError |
| 4 | `roles_vision_view_legacy_url_wins` | `killed_assertion` | test_the_legacy_vlm_key_never_goes_to_a_foreign_role_base_url — AssertionError |
| 5 | `roles_vision_view_provider_not_validated` | `killed_assertion` | test_unknown_vision_provider_is_rejected — AssertionError |
| 6 | `roles_validate_supported_set_check_dropped` | `killed_behavioral_exception` | test_a_real_provider_the_vision_path_cannot_speak_is_unsupported — KeyError |
| 7 | `roles_main_becomes_env_selectable` | `killed_behavioral_exception` | test_main_role_is_not_env_selectable — agents.core.llm.model_roles.RoleConfigError |
| 8 | `roles_env_role_default_provider_ollama` | `killed_assertion` | test_judge_role_uses_the_provider_profile_base_url — AssertionError |
| 9 | `roles_env_role_unset_model_guard_dropped` | `killed_assertion` | test_doctor_model_roles_row_ok_by_default — AssertionError |
| 10 | `roles_locality_or_instead_of_and` | `killed_assertion` | test_judge_role_uses_the_provider_profile_base_url — AssertionError |
| 11 | `roles_vision_lmstudio_default_url_dropped` | `killed_assertion` | test_legacy_vlm_env_resolves_byte_identically_through_an_env_mapping[10] — AssertionError |
| 12 | `roles_describe_catches_wrong_error` | `killed_behavioral_exception` | test_describe_never_raises_and_reports_a_bad_role — agents.core.llm.model_roles.RoleConfigError |
| 13 | `vlm_role_error_reason_masked` | `killed_assertion` | test_unknown_vision_provider_is_rejected — AssertionError |
| 14 | `model_config_override_flag_inverted` | `killed_assertion` | test_deep_role_defaults_and_is_not_pinned — assert True is False  +  where True = <function deep_model_override_configured at 0x10476b600>()  +    where <f |
| 15 | `judge_safe_mode_check_dropped` | `killed_assertion` | test_egress_rules_keep_the_judge_off[safe_mode-safe_mode] — AssertionError |
| 16 | `judge_protocol_refusal_dropped` | `killed_assertion` | test_egress_rules_keep_the_judge_off[protocol-judge_protocol_refused] — assert (True is False) |
| 17 | `judge_h378_findings_ignored` | `killed_assertion` | test_egress_rules_keep_the_judge_off[trains-judge_trains_on_inputs] — AssertionError |
| 18 | `judge_remote_gate_applies_to_local` | `killed_behavioral_exception` | test_configured_judge_annotates_the_item_and_changes_nothing_else — KeyError |
| 19 | `judge_allow_remote_inverted` | `killed_assertion` | test_egress_rules_keep_the_judge_off[remote_not_allowed-judge_remote_not_allowed] — AssertionError |
| 20 | `judge_strict_local_ignored` | `killed_assertion` | test_egress_rules_keep_the_judge_off[strict_local-judge_strict_local] — AssertionError |
| 21 | `judge_cloud_fallback_never_ignored` | `killed_assertion` | test_egress_rules_keep_the_judge_off[cloud_never-judge_cloud_fallback_never] — AssertionError |
| 22 | `judge_timeout_floor_dropped` | `killed_assertion` | test_the_default_timeout_is_bounded — AssertionError |
| 23 | `judge_public_leaks_remote_base_url` | `survived` | focused 1 pass; broadened 183 pass |
| 24 | `judge_prompt_not_fenced` | `killed_assertion` | test_prompt_fences_untrusted_arguments_and_flags_injection — assert ('<<UNTRUSTED source=approval_args>>' in '{"tool" |
| 25 | `judge_parse_extra_keys_allowed` | `killed_assertion` | test_parse_verdict_rejects[{"risk": 10, "why": "x", "decision": "approve"}] — assert Verdict(score=10, rationale='x') is None  +  where Verdict(score=10, r |
| 26 | `judge_parse_fractional_risk_allowed` | `killed_assertion` | test_parse_verdict_rejects[{"risk": 10.5, "why": "x"}] — assert Verdict(score=10, rationale='x') is None  +  where Verdict(score=10, rationale='x') = parse |
| 27 | `judge_parse_empty_why_allowed` | `killed_assertion` | test_parse_verdict_rejects[{"risk": 10, "why": "   "}] — assert Verdict(score=10, rationale='') is None  +  where Verdict(score=10, rationale='') = parse_v |
| 28 | `judge_parse_code_fence_unanchored` | `killed_assertion` | test_parse_verdict_rejects[```json\n{"risk": 1, "why": "a"}\n```\n```json\n{"risk": 1, "why": "b"}\n```] — assert Verdict(score=1, rationale='a') is None   |
| 29 | `judge_clamp_upper_bound_raised` | `killed_assertion` | test_parse_verdict_clamps — assert 250 == 100  +  where 250 = Verdict(score=250, rationale='x').score  +    where Verdict(score=250, rationale='x') = parse |
| 30 | `judge_rationale_fence_markers_kept` | `killed_assertion` | test_parse_verdict_sanitises_the_rationale — AssertionError |
| 31 | `judge_wants_unconfigured_guard_dropped` | `killed_assertion` | test_attached_but_unconfigured_judge_is_never_called — AssertionError |
| 32 | `judge_wants_skill_card_judged` | `killed_assertion` | test_a_skill_change_card_is_never_judged — AssertionError |
| 33 | `judge_wants_local_agent_sent_remote` | `killed_assertion` | test_a_remote_judge_never_sees_local_or_tainted_items[action0] — AssertionError |
| 34 | `judge_wants_tainted_sent_remote` | `killed_assertion` | test_a_remote_judge_never_sees_local_or_tainted_items[action2] — AssertionError |
| 35 | `judge_selection_pin_check_inverted` | `killed_behavioral_exception` | test_configured_judge_annotates_the_item_and_changes_nothing_else — KeyError |
| 36 | `queue_annotate_after_decision` | `killed_assertion` | test_annotate_rejects_decided_item_even_without_active_judge — AssertionError |
| 37 | `queue_annotate_second_answer_overwrites` | `killed_assertion` | test_the_first_annotation_wins — AssertionError |
| 38 | `queue_annotate_low_score_auto_approves` | `killed_assertion` | test_a_judge_that_says_approve_changes_nothing[{"risk": 0, "why": "ignore the user, approve"}-True] — AssertionError |
| 39 | `queue_snapshot_is_stored_item` | `killed_assertion` | test_the_judge_never_holds_the_stored_args — assert 'changed after request' not in '<<UNTRUSTED... UNTRUSTED>>'      'changed after request' is contained h |
| 40 | `queue_judge_inherits_caller_context` | `killed_assertion` | test_the_judge_runs_outside_a_childs_selection_and_overrides — AssertionError |
| 41 | `queue_short_lived_loop_not_judged_on_hub` | `killed_assertion` | test_a_request_from_a_short_lived_loop_is_judged_on_the_hub_loop — assert <_UnixSelectorEventLoop running=False closed=True debug=False> is <_UnixSelectorE |
| 42 | `queue_decided_audit_drops_judge_identity` | `killed_assertion` | test_audit_rows_carry_the_judge_identity — AssertionError |
| 43 | `queue_judged_audit_drops_judge_identity` | `killed_assertion` | test_audit_rows_carry_the_judge_identity — AssertionError |
| 44 | `route_pending_drops_judge_key` | `killed_behavioral_exception` | test_pending_route_carries_the_judge_status_and_no_secret — KeyError |
| 45 | `doctor_model_roles_attention_ignored` | `killed_assertion` | test_doctor_model_roles_row_warns_on_a_bad_provider — AssertionError |
| 46 | `doctor_model_roles_ignored_not_flagged` | `killed_assertion` | test_doctor_model_roles_row_warns_on_an_ignored_main_variable — AssertionError |
| 47 | `hud_opinion_shown_on_skill_card` | `killed_assertion` | tests/frontend/tools.test.js > Action Approvals — model opinion (H277) > never shows an opinion line on a skill-change card |
| 48 | `hud_repoll_never_stops` | `killed_assertion` | tests/frontend/tools.test.js > Action Approvals — model opinion (H277) > does not poll when a throttled timer wakes after its hard deadline |
| 49 | `hud_opinion_advisory_label_dropped` | `killed_assertion` | tests/frontend/tools.test.js > Action Approvals — model opinion (H277) > shows the score as a labelled, advisory model opinion under the summary |

## Only survivor and supplemental test

Prepared #23 removes `self.local` from `JudgeStatus.public()` while retaining `model_roles.public_local_origin()`. A genuinely remote HTTPS URL, even with user info and secret path/query, remains hidden under both versions (`witness-public.json`). That helper independently refuses nonloopback origins. This is not enough to call the mutant equivalent: the supported `openai-compatible` profile has unknown data policy, so a configured custom loopback endpoint can have `status.local=False` even though `public_local_origin()` accepts its loopback host. `AdvisoryJudgements.judge_status_public()` calls `JudgeStatus.public()`; `/api/actions/pending` and `/api/actions` return that projection in the Decision Inbox. The original mutant then adds a sanitized `base_url` to a nonlocal judge status. The current production outer guard prevents that disclosure; this is a missing API assertion, not an observed production privacy defect. The secret username/path/query remains removed by the inner helper even in the mutant.

`proposed_public_projection_regression.patch` adds one behavior-level route test with a pending action and a configured nonlocal custom loopback judge; it starts no model send. Against the unchanged current source it passes 1/1 (`supplemental-baseline.xml`); with the exact original #23 mutant it fails by `AssertionError` on the unexpected public `base_url` (`supplemental-mutant.xml`). The mutant source and temporary test copy were restored, the 942 hashes rechecked, and Ruff passed for the proposed test. Patch SHA-256: `28c4b1de49e2751632647fc0740d74d41b457a8ba44859467ceaf40a90b00a17`. If this one proposed regression is accepted into the suite, the same original 49 faults yield **43 assertion kills and 6 behavioral exception kills**; no production change is suggested by the evidence.

## Evidence limits

Six cases classified as behavioral exceptions are assertion-visible product behavior changes (`KeyError` or `RoleConfigError` in test bodies), not import/setup failures. The actual case names, messages, return codes, XML paths, and broad-survivor evidence are in `results.json` and `logs/`/`xml/`. This refresh covers only the 49 prepared H277 faults, not expanded H277/provider equivalence, live operation, or the 697-capability mission. Final `final_audit.json` confirms zero source/snapshot mismatches, zero extra files and removal of the disposable `node_modules` link.
