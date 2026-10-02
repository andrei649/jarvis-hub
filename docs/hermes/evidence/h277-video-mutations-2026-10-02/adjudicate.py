#!/usr/bin/env python3
"""Manual trace review record for the immutable first and broad campaigns."""
import json
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent
plan = json.loads((OUT / "plan.json").read_text())
first = {r["label"]: r for r in json.loads((OUT / "results_provisional.json").read_text())["results"]}
broad = {r["label"]: r for r in json.loads((OUT / "results_broad.json").read_text())["results"]}

killed = {
    "canonical_kind_ignored": "Noncanonical task reached model transport and returned ok; canonical-kind refusal assertion failed.",
    "toolrpc_class_compare_removed": "Changed approved class reached model transport; class-mismatch assertion failed.",
    "strict_local_ignored": "After consent, strict-local refusal no longer raised.",
    "local_only_actor_ignored": "Remote use by local-only actor no longer raised refusal.",
    "private_source_url_allowed": "Private-IP URL preflight no longer raised ToolRPCValidationError.",
    "secret_query_allowed": "Credential-bearing URL query preflight no longer raised ToolRPCValidationError.",
    "source_physical_recheck_removed": "Revocation hook allowed a physical source GET; zero-request assertion failed.",
    "actual_file_hash_compare_removed": "Alternating scoped file bytes reached model transport; zero-request assertion failed.",
    "native_body_guard_removed": "Both extra-message and in-place body mutation reached model transport.",
    "cleanup_disclosure_recheck_removed": "Both explicit and inherited role revocation during client close disclosed an ok result.",
    "inherited_provider_route_removed": "Unpinned video role lost inherited vision endpoint; role and signed worker assertions failed.",
    "video_model_precedence_removed": "Explicit video model was replaced by vision model; precedence assertion failed.",
    "full_url_key_gate_reduced_to_provider": "Vision key followed same provider onto different native request path; no-key assertion failed.",
    "invalid_vision_falls_back_to_default": "Invalid selected vision route resolved to default LM Studio; refusal assertion failed.",
}
invalid = {
    "remote_call_approval_ignored": "The pre-consent check raised DataHandlingRefused instead of the expected explicit-approval refusal. It did not demonstrate physical remote use after consent.",
    "redirect_revalidation_removed": "After bypassing redirect validation the fixture repeated redirects until VideoPolicyRefused limit, rather than checking whether a private target was physically requested. This is a changed exception, not a proved SSRF boundary violation.",
}
survived = {
    "canonical_target_ignored": "Selected and broad tests did not present a tool=video_analyze/target!=video_analyze task through execution.",
    "unsigned_intake_allowed": "Other signed-mediation checks still refused the tested off-mode intake; this single guard was not isolated.",
    "unsigned_execute_allowed": "Coordinator/worker checks still refused off-mode execution; this guard was not isolated.",
    "receipt_validation_removed": "No selected/broad test altered a durable receipt while keeping the other task proofs valid.",
    "persisted_payload_equality_removed": "No selected/broad test changed only the live task payload while retaining an approved persisted row.",
    "kernel_denial_ignored": "Selected/broad video tests did not force a kernel denial at execution.",
    "remote_role_consent_ignored": "The inner authorize_role_target still refused missing acknowledgment; removing the outer row check did not change the tested behavior.",
    "descriptor_nofollow_removed": "Existing symlink test is refused by FileScope.resolve before final descriptor open; no resolution-to-open swap was exercised.",
    "local_file_byte_cap_removed": "Regular-file fstat and post-read length checks remain; tests did not exercise growth between fstat and read or measure allocation.",
    "http_stream_byte_cap_removed": "Existing overflow fixture includes Content-Length, so the header cap fires before streaming; chunked/no-length overflow was untested.",
    "native_direct_transport_removed": "No selected/broad test replaced transport after initial direct-transport check and before physical send.",
    "native_url_guard_removed": "No selected/broad test changed the physical model URL after approval.",
    "native_method_guard_removed": "No selected/broad test changed the physical model method after approval.",
    "native_auth_guard_removed": "No selected/broad test changed Authorization at the physical request seam.",
    "native_cookie_guard_removed": "No selected/broad test added Cookie at the physical request seam.",
}
assert len(killed) == 14 and len(invalid) == 2 and len(survived) == 15
assert set(killed) | set(invalid) | set(survived) == set(first)
assert set(broad) == set(survived)
assert all(first[label]["provisional"] == "assertion_failure" for label in killed)
assert all(first[label]["provisional"] == "invalid" for label in invalid)
assert all(first[label]["provisional"] == "survived" and broad[label]["provisional"] == "survived"
           for label in survived)

rows = []
for case in plan["mutations"]:
    label = case["label"]
    result, reason = (("killed", killed[label]) if label in killed else
                      ("invalid", invalid[label]) if label in invalid else
                      ("survived", survived[label]))
    rows.append({**case, "result": result, "reason": reason, "first_pass": first[label],
                 "broad_pass": broad.get(label)})
counts = dict(Counter(row["result"] for row in rows))
(OUT / "results.json").write_text(json.dumps({"head": plan["source_ref"], "counts": counts,
                                               "results": rows}, indent=2, sort_keys=True) + "\n")
print(counts)
