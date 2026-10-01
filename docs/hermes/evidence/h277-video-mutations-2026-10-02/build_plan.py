#!/usr/bin/env python3
"""Generate the reviewed, bounded H277 video mutation cases."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
V = "agents/core/video_analysis.py"
P = "agents/core/llm/video_policy.py"
R = "agents/core/llm/model_roles.py"
C = "agents/core/autonomy_coordinator.py"
T = "agents/core/tool_rpc.py"
A = "tests/test_h277_video_analysis.py::"
F = "tests/test_h277_video_fallback.py::"
M = "tests/test_h277_model_roles.py::"

cases = []


def add(label, file, a, b, *tests, invariant):
    cases.append(dict(label=label, file=file, a=a, b=b, tests=list(tests), invariant=invariant))


add("canonical_kind_ignored", V,
    'getattr(task, "kind", None) == "tool.rpc" and isinstance(payload, dict)',
    'isinstance(payload, dict)', A+"test_video_handler_refuses_noncanonical_task_even_if_context_is_trusted",
    invariant="Only canonical tool.rpc video tasks may execute.")
add("canonical_target_ignored", V,
    'payload.get("tool") == payload.get("target") == "video_analyze"',
    'payload.get("tool") == "video_analyze"', A+"test_server_owned_class_and_dispatcher_refuse_other_canonical_payloads",
    invariant="Video tool and target must both be server-owned video_analyze.")
add("unsigned_intake_allowed", V,
    'if (self.queue is None or self.queue.mediation_mode != "enforce"\n                or self.queue.classify_mediation("tool.rpc") is not True):',
    'if (self.queue is None or self.queue.classify_mediation("tool.rpc") is not True):',
    A+"test_accepted_unsigned_canonical_video_row_cannot_run_with_mediation_off",
    invariant="Intake requires enforce-mode signed mediation.")
add("unsigned_execute_allowed", V,
    'if (self.queue is None or self.queue.mediation_mode != "enforce"\n                    or self.queue.classify_mediation("tool.rpc") is not True):',
    'if (self.queue is None or self.queue.classify_mediation("tool.rpc") is not True):',
    A+"test_signed_row_cannot_run_after_mediation_mode_changes_to_off",
    invariant="Execution rechecks enforce-mode signed mediation.")
add("receipt_validation_removed", C,
    'if not queue.validate_mediated_execution(\n                            task, queue.execution_fingerprint(task)):',
    'if False:', A+"test_registered_signed_worker_path_sends_native_video_only_after_approval",
    A+"test_accepted_unsigned_canonical_video_row_cannot_run_with_mediation_off",
    invariant="Coordinator validates durable mediation receipt before trusted execution.")
add("persisted_payload_equality_removed", C,
    'and persisted.payload == getattr(task, "payload", None)',
    'and True', A+"test_server_owned_class_and_dispatcher_refuse_other_canonical_payloads",
    invariant="Trusted execution is bound to the persisted exact payload.")
add("toolrpc_class_compare_removed", T,
    'if labels.get("class") != payload.get("class"):',
    'if False:', A+"test_server_owned_class_and_dispatcher_refuse_other_canonical_payloads",
    invariant="ToolRPC compares server-recomputed class with approved class.")
add("kernel_denial_ignored", V,
    'if self.kernel_check(args, task):', 'if False:',
    A+"test_registered_signed_worker_path_sends_native_video_only_after_approval",
    invariant="Video execution rechecks the action kernel.")
add("remote_call_approval_ignored", P,
    'allow_remote is True and env_flag("JARVIS_ROLE_VIDEO_ALLOW_REMOTE")',
    'env_flag("JARVIS_ROLE_VIDEO_ALLOW_REMOTE")',
    F+"test_inherited_remote_route_needs_video_consent_and_privacy_controls",
    invariant="Every remote call needs explicit per-call allow_remote.")
add("remote_role_consent_ignored", P,
    'if not identity.local and not row["acknowledged"]:', 'if False:',
    F+"test_inherited_remote_route_needs_video_consent_and_privacy_controls",
    invariant="Remote video role needs independent consent.")
add("strict_local_ignored", P,
    'if env_flag("JARVIS_STRICT_LOCAL"):', 'if False:',
    F+"test_inherited_remote_route_needs_video_consent_and_privacy_controls",
    invariant="Strict-local mode refuses remote video.")
add("local_only_actor_ignored", P,
    'if str(actor or "").strip().lower() in LOCAL_ONLY_AGENTS:', 'if False:',
    A+"test_remote_role_cannot_override_shared_privacy_posture[local_only_agent]",
    invariant="Local-only actor cannot send video to remote role.")
add("private_source_url_allowed", V,
    'or is_private_ip(parts.hostname):', 'or False:',
    A+"test_unsafe_video_urls_refused_at_intake[http://127.0.0.1/clip.mp4]",
    invariant="A private-IP source is refused before fetch.")
add("secret_query_allowed", V,
    'for key, _ in parse_qsl(parts.query, keep_blank_values=True))):',
    'for key, _ in [])):',
    A+"test_unsafe_video_urls_refused_at_intake[https://video.example/clip.mp4?token=secret]",
    invariant="Credential-bearing query parameters are rejected.")
add("descriptor_nofollow_removed", V,
    'os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd',
    'os.O_RDONLY | os.O_NONBLOCK, dir_fd=fd',
    A+"test_workspace_source_is_descriptor_scoped_and_rejects_symlink_swap",
    invariant="Final workspace descriptor cannot follow a symlink.")
add("local_file_byte_cap_removed", V,
    'data = stream.read(MAX_VIDEO_BYTES + 1)', 'data = stream.read()',
    A+"test_actual_file_bytes_must_match_the_approved_snapshot",
    invariant="Local source reads stay bounded before encoding.")
add("redirect_revalidation_removed", V,
    '_source(current, FileScope.from_env())', 'None',
    A+"test_public_url_uses_pinned_client_and_rejects_private_redirect",
    invariant="Each redirect target is validated before next DNS/GET.")
add("http_stream_byte_cap_removed", V,
    'if len(data) > MAX_VIDEO_BYTES:', 'if False:',
    A+"test_public_url_refuses_stream_byte_overflow",
    invariant="Streaming HTTP video source is byte bounded.")
add("source_physical_recheck_removed", V,
    'self._video_check()\n                if request.headers.get("Authorization")',
    'None\n                if request.headers.get("Authorization")',
    A+"test_role_revoked_at_physical_source_get_blocks_model",
    invariant="Authority is checked at physical source GET.")
add("actual_file_hash_compare_removed", V,
    'if actual_class != task.payload.get("class"):', 'if False:',
    A+"test_actual_file_bytes_must_match_the_approved_snapshot",
    invariant="Actual file bytes must match the approved signed class.")
add("native_direct_transport_removed", P,
    'require_direct_async_transport(client, request.url)', 'None',
    A+"test_registered_signed_worker_path_sends_native_video_only_after_approval",
    invariant="Model request must use a direct transport.")
add("native_url_guard_removed", P,
    'or request.method != "POST" or str(request.url) != identity.request_url',
    'or request.method != "POST"',
    A+"test_registered_signed_worker_path_sends_native_video_only_after_approval",
    invariant="Physical model URL exactly matches approved native endpoint.")
add("native_method_guard_removed", P,
    'or request.method != "POST" or str(request.url) != identity.request_url',
    'or str(request.url) != identity.request_url',
    A+"test_registered_signed_worker_path_sends_native_video_only_after_approval",
    invariant="Physical model method is POST.")
add("native_auth_guard_removed", P,
    'or request.headers.get("Authorization", "") != identity.authorization',
    'or False', F+"test_signed_toolrpc_worker_uses_inherited_route",
    invariant="Physical Authorization header matches approved identity.")
add("native_cookie_guard_removed", P,
    'or request.headers.get("Cookie") or not valid):',
    'or not valid):', A+"test_registered_signed_worker_path_sends_native_video_only_after_approval",
    invariant="Physical model request carries no Cookie header.")
add("native_body_guard_removed", P,
    'or request.headers.get("Cookie") or not valid):',
    'or request.headers.get("Cookie")):',
    A+"test_physical_model_guard_rejects_extra_unapproved_message",
    A+"test_adapter_cannot_mutate_expected_body_before_physical_send",
    invariant="Native request body is an immutable exact approved payload.")
add("cleanup_disclosure_recheck_removed", V,
    'check()  # A close hook or transport cleanup can revoke authority.',
    'None  # A close hook or transport cleanup can revoke authority.',
    A+"test_revocation_during_model_client_cleanup_withholds_answer",
    F+"test_inherited_key_change_during_client_cleanup_withholds_answer",
    invariant="Consent/configuration is checked after client cleanup before disclosure.")
add("inherited_provider_route_removed", R,
    'if provider or base:', 'if provider or base or True:',
    F+"test_video_inherits_resolved_vision_route_and_uses_video_model_override",
    F+"test_signed_toolrpc_worker_uses_inherited_route",
    invariant="Unpinned video route inherits the resolved vision provider and URL.")
add("video_model_precedence_removed", R,
    'chosen_model = model or vision.model', 'chosen_model = vision.model',
    F+"test_video_inherits_resolved_vision_route_and_uses_video_model_override",
    invariant="Explicit video model overrides resolved vision model.")
add("full_url_key_gate_reduced_to_provider", P,
    'and str(httpx.URL(native.request_url)) == str(httpx.URL(request_url))):',
    'and True):', F+"test_exact_native_endpoint_and_provider_required_to_borrow_vision_key",
    invariant="Vision key crosses only to identical provider and complete native URL.")
add("invalid_vision_falls_back_to_default", R,
    'if vision_selected:\n        source =', 'if vision_selected and not model:\n        source =',
    F+"test_invalid_configured_vision_does_not_select_another_video_destination",
    invariant="Invalid selected vision route never silently selects default video destination.")

plan = {
    "source_ref": "c60918ed1382ccae260706b4ee6a28184535f73e",
    "snapshot_policy": "Pinned git archive only, no dirty overlay. Serial mutations in /tmp; finally restore and hash every archived file.",
    "required_untracked": [],
    "baseline_tests": ["tests/test_h277_video_analysis.py", "tests/test_h277_video_fallback.py",
                       "tests/test_h277_model_roles.py", "tests/test_h277_role_routes.py"],
    "mutations": cases,
}
(OUT / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
print(len(cases))
