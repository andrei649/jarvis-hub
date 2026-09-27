# H277 completion plan — 2026-09-27

Base: `bd2bb70ead1b493043a335e77713fc42c47d4013` plus verified local round-2 diffs.
Goal: finish the handoff verification and the authorized missing integration,
without promoting incomplete role/provider/video behavior to equivalence.

1. Run old and new mutations serially on a disposable source snapshot; record
   fingerprints and distinguish test kills from invalid/unmatched mutations.
2. Add a user-authenticated read-only `/api/llm/roles` view using the existing
   secret-free role projection. It reports configuration, not reachability.
3. Apply local-only and model-selection checks before constructing the VLM client
   in `/api/vlm/describe`, using the actual requested override model when present.
   A refusal must send no image bytes. Do not change the resolver's legacy contract.
4. Add advisory task/Decision Inbox integration after persisted blocked enqueue,
   with annotations outside signed action payload/receipts. Final exact ownership
   follows the bounded architecture trace before implementation.
5. Run related and full suites serially, correct failures, and update H277 records
   using inspected evidence only. Video/provider expansion remains explicit until
   implemented; other Hermes rows cannot be closed by refreshing hashes alone.

Coordinator owns models_llm.py, multimodal.py and tests/test_h277_role_routes.py.
Mutation agent owns docs/handoff/h277/verification only. The kernel integration
agent receives separate exact paths after its read-only design.

Architecture trace completed: Decision Inbox uses SQLite TaskQueue, whereas tool
approvals use JsonStore ActionApprovalQueue. Kernel QUEUE already reaches
govern_enqueue; no direct kernel authorization change is needed. The backend
implementer owns the shared runner/task adapter, autonomy queue/worker,
orchestrator wiring, autonomy router and new task-judge tests. The UI implementer
owns DecisionInboxPanel in frontend/src/gap.tsx and its tests. Annotations use a
separate SQLite table and compare persisted BLOCKED state and execution digest;
signed payloads, receipts and action decisions remain untouched.

UI contract: optional per-task judge and judge_pending, and top-level public judge
status with timeout. Polling uses per-card wall deadline 17*timeout+5 seconds.

Verification: endpoint authentication, no secret/base-URL leaks, no inferred
reachability, remote VLM no-dispatch, model guard no-dispatch, successful local
vision and model override, then relevant VLM/model-control suites. Rollback each
slice's diff only; preserve policy changes and prior verified H277 corrections.
No push, merge, deployment, paid-provider calls or personal-profile imports.

## Integration findings and verification

- Round2: 73/74 mutations killed; the remaining eager private-state cleanup
  mutation is observationally equivalent. Shared-runner follow-up: 14/14 killed.
  Mutation survivors strengthened loop selection, memory-only revocation, direct
  remote depth refusal, delayed browser timers and capacity reuse regressions.
- New role/VLM API suite plus related guards: 168 passed before kernel integration.
  Final URL projection hardening plus task/action roles and local model routes:
  335 passed. Public local addresses now expose only a loopback HTTP origin;
  credentials, path, query and fragment cannot appear in status/doctor output.
- Initial full backend run: 18,574 executed, 18,515 passed, 35 skipped,
  14 failed and 10 fixture errors. macOS path/socket/process-identity assumptions,
  mocked optional adapter state, new route UI coverage and stale generated records
  were separated rather than hidden by weakening gates.
- macOS socket pressure exposed a real `ENOBUFS` retry gap in `sd_notify`; only
  EAGAIN/EWOULDBLOCK/ENOBUFS use the existing bounded retry. CLI file diagnostics
  preserve the filename when shortening long paths. Security symlink checks stay.
- Initial frontend: 1,792 passed; installed versions differed from the lockfile.
  Root/frontend dependencies were then reinstalled from unchanged locks and the
  suite rerun. New model-role viewer tests: 2 RED then 2 GREEN; role+Inbox: 25 passed.
- Legacy HUD coverage: 228 tests passed, 69.27% lines (required minimum60%).
  Whole-tree Bandit1.9.4 passed against the existing baseline after replacing five
  silent exception branches in model controls with credential-free diagnostics.
- Manual checker: updated GOV and API chapters pass; existing unrelated missing
  worldview paths and malformed security-table row remain reported by that checker.

Final milestone: **18,548 backend passed, 35 skipped, zero failures/errors**;
**1,794 pinned frontend passed**; TypeScript/build passed. Normal socket/timeout
options were retained. Test counts and generated status are synchronized. Gitleaks
8.30.1 (release-checksummed Darwin binary) found no leaks in a source-only snapshot
under the existing repository configuration. Exact source hashes, commands and
counts: `evidence/h277-local-integration-2026-09-27.json`.

Current
Hermes counts are conservative: stale file hashes remain needs_review until their
behavior is inspected. No blanket refresh or equivalence promotion was performed.

Next active implementation: H487 reasons/expiry, following its separate scoped plan.
The passing milestone above is frozen evidence; subsequent changes need their own
verification and do not inherit this result automatically.
