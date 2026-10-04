# H277 OpenRouter native-video five-fault mutation check

Current source HEAD `4f265c6cdbe8d04d905230919bd0e717d6a3c5c4`; exact input path/hash fingerprint `4bccde9ea61c6da62463306178a20886a0be231009f4cb4a8dcfa20def35e005`. The snapshot copied 2066 current regular source/test files named by the prototype baseline/supplemental keys plus `tests/test_h277_openrouter_video.py` (SHA-256 `0a6bf2b57d0849ef549bc8555ce1127a143a28caaa325e0a7fc2aaeff5dcd860`). The prior prototype hashes were not used as source identity.

The video module collected 22 cases. Baseline and final runs each passed 22/22 using `JARVIS_TESTING=1` and the repository pytest socket and timeout guards. All five edits had one unique anchor and valid Python syntax. Each focused mutant test ran one behavioral case and failed; no broadening was needed.

| Fault | Current file | Classification | Exact test failure |
|---|---|---|---|
| `omit_openrouter_physical_provider_block` | `agents/core/video_analysis.py` | `killed_behavioral_exception` | test_signed_openrouter_request_emits_full_video_and_provider_block: KeyError: 'provider' |
| `omit_primary_provider_preference_binding` | `agents/core/llm/video_policy.py` | `killed_assertion` | test_approved_openrouter_route_change_refuses_before_dispatch[preference]: AssertionError: assert [<Request('PO...ompletions')>] == [] |
| `borrow_vision_key_across_physical_url` | `agents/core/llm/video_policy.py` | `killed_expectation` | test_explicit_openrouter_may_reuse_only_exact_matching_guarded_vision_key: Failed: DID NOT RAISE VideoPolicyRefused |
| `openrouter_fallback_uses_primary_key` | `agents/core/llm/video_routes.py` | `killed_assertion` | test_approved_openrouter_fallback_uses_only_slot_key_and_frozen_provider_block: AssertionError: assert 'Bearer wrong-primary-key' == 'Bearer synthetic-slot-key' |
| `allow_openrouter_without_dedicated_or_matching_vision_key` | `agents/core/llm/video_policy.py` | `killed_expectation` | test_explicit_openrouter_requires_valid_dedicated_key_without_matching_vision[missing]: Failed: DID NOT RAISE VideoPolicyRefused |

The missing physical provider block produced a test-body `KeyError: provider`, a behavioral exception rather than an assertion failure. The omitted primary preference binding and wrong fallback key produced `AssertionError` failures, including one unexpected physical request and a header containing the primary key. The two credential-gate faults caused `pytest.raises(VideoPolicyRefused)` to fail with `DID NOT RAISE`; these are expected-refusal failures, not Python `AssertionError`s. `results.json` and the per-case JUnit XML/log files contain the full traces.

`mapping.json` records each exact single edit and focused test. Every copied file was restored and SHA-256 checked after each fault. `final_audit.json` shows zero snapshot/source mismatches across all 2,066 inputs, no extra snapshot files or dependency link, and unchanged HEAD. No real checkout, index, docs or tests were edited by this audit.
