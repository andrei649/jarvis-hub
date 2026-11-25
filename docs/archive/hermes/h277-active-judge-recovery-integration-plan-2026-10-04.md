# H277 active approval-judge parameter recovery integration

Generated 2026-10-04. Goal: all697 pinned Hermes capabilities; guarded active
auxiliary recovery dependency. Base/head before integration:
`23af87a931a8f16a4c457af4436901eb527ae535`. Root owns checkout writes.

## Scope and invariants

Integrate the two-path prototype, patch SHA-256
`9c6d80430f0c6f2b5a3d4f9c212259696fb0232788e0b7a216538559dc6a07f0`:
`agents/core/autonomy/approval_judge.py` and
`tests/test_h277_auxiliary_active_route_recovery.py`. The explicitly configured
and currently acknowledged native OpenAI-compatible approval judge may repeat
one request only after its first physical structured HTTP400 unsupported
`temperature` response. The sole payload difference is omission of temperature.
Both requests preserve the exact caller output cap, model, system/user messages,
stream setting, URL and authorization. At most two sends share one total timeout.
Every new judgement starts with its original temperature; no learned remote cache.

Current role configuration, job selection, H513 acknowledgement, safe mode,
queue/smart validity, direct transport and physical request/hook identity are
checked before each send and after cleanup. Smart observers see each actual
authorized attempt. Unrelated/malformed/oversized/auth/transport failures do not
replay; HTTPX diagnostics are sanitized. Cancellation and timeout close the owned
client. Preserve all seven existing strictly local auxiliary routes and settings.
No output-cap omission, SDK retry, provider fallback, default activation or paid
call. This is a dependency, not completion of broad H277 auxiliary parity.

## Review finding and root correction

Root and independent source review identified that the new missing/final-egress
hook check raises before the owned client's cleanup `try/finally`. Add real
zero-send refusal/client-closed regressions for missing and late recorder hooks;
watch them fail on the integrated prototype, then move the refusal check inside
the existing cleanup scope. Preserve the guard and all request invariants.

## Steps and acceptance

1. Rehash exact original/proposed source, new test and patch; verify current five
   owner-once overlay hashes and `git apply --check`. Baselines match current HEAD.
2. Apply the new test only; run the real native advisory/smart recovery test.
   Expect two failures (one provider behavioral exception and one smart assertion)
   without setup errors.
3. Apply production delta; run the full new module. Add the two cleanup regressions
   RED, repair only cleanup placement, then rerun all focused cases GREEN.
4. Run the deduplicated existing judge, H513, smart and local auxiliary recovery
   suite and current owner-once overlap suite. Check exact output caps, late route
   revocation, body tampering, queue decisions, shared timeout and cancellation.
5. Ruff, baseline-aware Bandit, doc references and exact selected-index secret
   scan; record actual XML/log/source hashes and commit the local unit separately.
6. Reconcile shared counts, architecture and reviewed collateral claims after
   both source units. Freeze clean integrated source and run full suites serially.

Rollback: reverse this unit's bounded source/test delta, keeping owner-denial and
other work. No route/HUD/mobile endpoint added. No push, merge, deployment,
provider activation, network, real device/terminal effect or paid service. Remote
output-cap handling and other tasks/providers/SDKs remain real full-goal work.
Next action: test-only native RED, source GREEN, cleanup RED/GREEN.
