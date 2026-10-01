# H277 video analysis — local continuation

- Generated: 2026-10-02, Europe/Bucharest.
- Goal: a real approved video-understanding consumer; full Hermes parity remains active.
- Base: `9d5b3add85bd8c172bfe38ed1506a2852e2d6e5a`.
- Branch: `codex/local-hermes-continuation-20261001`.
- Initial implementation: `ee52e2fa`; canonical-task hardening: `e2e8617b`;
  isolated title-test fixture: `732f34ac`; vision inheritance: `bddf2172`.
- Final full-backend snapshot: `78780b6439d0cea1ed66d924127b6a8a888df7a5`.
- Publication: none. No push, merge, deployment, live model call or paid provider call.
- Status: this bounded video milestone passed final local verification. Full H277
  and Hermes parity remain unfinished.

## Execution Plan:

1. Re-read the pinned Hermes video consumer and H277 handoff. Re-run the separate
   shared-judge mutation campaign on the immutable main snapshot.
2. Add a default-off video ToolRPC consumer through canonical signed `tool.rpc`
   intake, owner approval, the governed worker and a real native HTTPX request.
3. Bind source, question, roots, model, destination and credentials to the approved
   class. Recheck current authority at physical requests and result disclosure.
4. Review and test file races, request mutation, cleanup revocation, privacy policy,
   unsigned tasks and bounded source/model streams. Add independent web consent.
5. Repair integration-test isolation, synchronize generated artifacts and records,
   implement bounded vision-route resolution fallback, then run final full checks.

## Files Modified:

- `agents/core/video_analysis.py`: scoped source reads, approved intake/execution,
  native video requests, response limits and refusal handling.
- `agents/core/llm/video_policy.py`: destination identity, privacy/consent policy,
  secret-keyed approval binding and immutable physical request validation.
- `agents/core/autonomy_coordinator.py`: opt-in registration, signed context checks
  and narrow canonical media dispatch. `agents/core/orchestrator_bindings.py`
  updates the positions of existing writers without changing their names.
- `agents/core/llm/model_roles.py`, `agents/core/job_toolsets.py`: consumer metadata
  and the video job toolset.
- `agents/core/llm/data_handling.py`, `agents/core/routers/security.py`,
  `frontend/src/panels/data-handling.tsx`: independent `role:video_analysis` consent.
- `frontend/src/api/schema.gen.ts`, `agents/web/v2/`: generated schema and HUD assets.
- `tests/test_h277_video_analysis.py`, `tests/test_h277_video_fallback.py`, `tests/test_h277_model_roles.py`,
  `frontend/src/test/governance-posture-panel.test.tsx`: new behavior and regressions.
- `tests/test_h275_safe_mode.py`: retain the exhaustive safe-mode reader inventory.
- `tests/test_h413_session_titles.py`: isolate the real checkpoint directory so
  earlier golden tests cannot supply an already-titled shared session.
- `.env.example`, `docs/FLAGS.md`, `mobile/PARITY.md`,
  `docs/design/HUD_V2_REMAINING.md`: configuration and explicitly unfinished UI work.
- Hermes assessment/reports and generated project status: current evidence and counts.

## Verification Results:

- The initial 624-case focused backend set passed; its implementer command cleared
  pytest addopts, so it is not the final verification under repository guards.
- Parent verification retained the repository timeout/socket settings: 25 initial
  video cases passed; after the canonical-task regression, 65 video/safe-mode cases
  passed. Ruff and diff whitespace checks passed.
- All 1,836 frontend tests passed; TypeScript checks, OpenAPI generation and the
  production build passed. The build retained its existing large-chunk advisory.
- Diagnostic backend run: 20,083 passed, 34 skipped, one expected failure and four
  failures. Those were the new safe-mode reader inventory, shared checkpoint state
  in H413, and two stale Hermes-report checks. This run was diagnostic; integration
  fixes landed while it ran, so it does not certify an immutable final tree.
- Running the stream-fanout tests before the H413 owner-title test reproduced the
  checkpoint contamination. The isolated fixture then passed all 135 ordered
  stream-fanout/H413 cases. The updated Hermes status tests passed all 48 cases.
- Final full backend verification on the immutable snapshot above: **20,108 passed,
  34 skipped, one expected failure, zero unexpected failures**, with 61 warnings in
  981.55 seconds. All 4,014 tracked regular files matched their pre-run hashes.
  Backend and frontend counts matched the generated project status; Hermes reports,
  generated status, scoped Ruff and diff checks passed. The
  [machine-readable receipt](evidence/h277-video-integration-2026-10-02.json) records
  source and test-artifact hashes plus the exact verification scope.
- Vision-route inheritance passed 307 focused tests with repository guards retained,
  including 19 new fallback cases. The initial new suite had seven expected failures
  before implementation. Scoped Ruff found three import-order issues during parent
  review; those were corrected before final verification.
- Parent verification after import-order cleanup passed 188 tests. Independent
  bounded review of the resolver, key inheritance and signed-dispatch tests found
  no concrete blocker; that reviewer did not run tests.
- The separate fresh mutation campaign killed 14/14 mutants with 203 baseline
  tests on `9d5b3add`. It predates video and does not establish video mutation coverage.

The first video production draft preceded its tests, contrary to the planned TDD
order. Later review regressions were demonstrated failing before their fixes:
actual file bytes differing from the approved hash, extra/mutated request content,
revocation during client cleanup, unsigned task execution, and the handler's
noncanonical-task contract. No isolated pre-feature baseline test run is claimed;
the old commit's missing consumer is static baseline evidence.

## Remaining Risks:

H277 remains partial. Native `video_url` support depends on the chosen model;
mocked transport tests do not establish live model acceptance. Local files require
POSIX descriptor support. New video mutation coverage, broader auxiliary providers,
runtime provider fallback, inbound video ingestion and native mobile controls remain
separate work. Mediation must be `enforce`; both video feature flags default off.
Existing backend warnings include deprecations and an unawaited-coroutine warning;
they were not treated as proof of a clean warning baseline. Local raw test artifacts
remain in `/tmp`; the committed receipt preserves outcomes and hashes.

The [bounded fallback plan](h277-video-fallback-plan-2026-10-02.md) selects one
destination before approval. Without video provider/base overrides, video inherits
the effective vision endpoint and model, with an optional video-model override.
Only a matching provider and complete normalized native URL can inherit the guarded
effective vision key. Changes invalidate approval before network dispatch; class
verification may reread the scoped local file once to verify its content hash.
Provider-failure retries, paid calls and automatic selection of a second destination
remain outside this increment. Prior mutation and real-Docker receipts retain their
original source/runtime scope.
