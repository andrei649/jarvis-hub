# H485 guardian observer checkpoint verification

Generated UTC: 2026-10-03T10:06:52.899712+00:00.
Base / preceding HEAD: `1459916af2e09b6f2ea0c9f46163390a5350882b`.
Branch: `codex/h277-provider-discovery-20261002`.
Delivery: local only; no publication, provider spend or runtime activation.

**Execution Plan:**

Integrate pinned Hermes `_smart_verdict` observer semantics through Nerva's
signed/consented sandbox event bus. Emit one validated native send attempt and
only its matching committed smart APPROVE/DENY. Keep failures, outputs, timeout
and backlog outside execution authority. Root owns shared contracts/bus/integration,
one Sol/high implementer owns judge seams/native tests, and one Sol/high reviewer
checks the final boundary. No subagent delegation.

**Files Modified:**

23 paths in this increment.

| Path | Rationale |
|---|---|
| `BACKLOG.md` | Record delivered guardian observers and remaining synchronous scope. |
| `GO_LIVE_PLAN.md` | Regenerate dependent status/count evidence; no new completion credit. |
| `HERMES_STATUS.md` | Regenerate dependent status/count evidence; no new completion credit. |
| `NERVA.md` | Regenerate dependent status/count evidence; no new completion credit. |
| `README.md` | Regenerate dependent status/count evidence; no new completion credit. |
| `STATUS.md` | Regenerate dependent status/count evidence; no new completion credit. |
| `agents/core/autonomy/advisory_judgements.py` | Fresh per-judgement holder and committed observer emission before audit/promotion. |
| `agents/core/autonomy/approval_judge.py` | Smart-only callback after native physical identity and live request checks. |
| `agents/core/autonomy/smart_observers.py` | Exact per-request identity, sanitized excerpt cache, disabled-parent propagation and best-effort events. |
| `agents/core/extensions/events.py` | Strict guardian fields, forced full-input masking and fresh asynchronous delivery contexts. |
| `agents/core/extensions/manifest.py` | Two explicit new observer subscriptions under existing manifest consent. |
| `docs/ARCHITECTURE.md` | Document the observer boundary without changing identity behavior. |
| `docs/EXTENSIONS.md` | Payload/privacy/delivery contract and correction of historical active exclusions. |
| `docs/HERMES_CAPABILITIES.md` | Regenerate dependent status/count evidence; no new completion credit. |
| `docs/hermes/assessment.json` | Reread twelve parent-current affected reviews; retain existing verdicts. |
| `docs/hermes/evidence/h485-smart-observers-mutations-2026-10-03.json` | Reproducible isolated nine-fault campaign and exact-source receipt. |
| `docs/hermes/evidence/h485-smart-observers-mutations-2026-10-03.py` | Reproducible isolated nine-fault campaign and exact-source receipt. |
| `docs/hermes/evidence/h485-smart-observers-verification-2026-10-03.md` | This complete changed-path and verification report. |
| `docs/hermes/h485-smart-observers-plan-2026-10-03.md` | Design, ownership, failure/fix evidence and next actions. |
| `mobile/PARITY.md` | Record server-only observer path and open native/device management. |
| `project-status.json` | Regenerate dependent status/count evidence; no new completion credit. |
| `tests/test_h485_smart_observer_dispatch.py` | Red-first queue/native HTTP or field/privacy/correlation regressions. |
| `tests/test_h485_smart_observer_events.py` | Red-first queue/native HTTP or field/privacy/correlation regressions. |

**Verification Results:**

- New cases: **38 passed**, 20 event-field/privacy and 18 actual queue/native
  HTTP/runner cases. Provider HTTP is mocked; no terminal command is executed.
- Combined focused 94-module run: **2,428 passed**, seven warnings, exit zero.
- Isolated mutations: **9/9 killed**, no survivor/invalid case, restored 38-case
  baseline passes and source hashes match. [Receipt](h485-smart-observers-mutations-2026-10-03.json).
- Global Bandit 1.9.4, unchanged workflow baseline: zero findings/scan errors.
  Repository-wide Ruff and whitespace pass.
- Complete frozen backend milestone: **21,602 passed, 34 skipped, one xfailed**, 67 warnings, 1,119.27 seconds, exit zero.
- Record/doc/count gates: **180 passed** at the source-frozen checkpoint; final document/status checks follow this report.
- Backend collection: 21,637. Frontend/mobile counts reused: 1,884/142; those
  suites were not rerun. No Python coverage instrumentation/threshold exists;
  case counts are not line coverage.
- Explicit Graft build and freshness check pass; wiring graph is current.
  Optional semantic layer remains unbuilt.
- Independent read-only review found no actionable issue, including the bounded
  disabled-parent correction. Eight frozen source/test/harness hashes are listed
  below; all eight were confirmed unchanged after complete-suite exit zero.

Initial bus proof was six absent-feature failures/ten existing refusals. Initial
native proof was eight absent-observer failures. Four short-credential probes
failed before forcing CatalogueScanner alongside SecretScanner. Two preparatory
verification commands named missing test files and ran no tests; corrected
current-file discovery produced the 94-module green run.

A transient parent entropy failure was separately reproduced red: the wait_for
child retried preparation and emitted an unmatched request event. The disabled
scope marker now suppresses that retry, while the durable DENY and slot release
remain. The corresponding isolated mutation is killed.

**Remaining Risks:**

H277/H485 remain partial. Same-turn terminal/shell/script placement before human
notification, native labels/settings/observer management and real model/channel/
Docker/device acceptance are open. Other blocking/transforming lifecycle hooks
remain in the full backlog; they are not actively excluded. H571's extension
packs/distribution/config seeds are not delivered by these observer events.

Recognized secret patterns/named credentials/catalogue identifiers are masked,
but excerpts can contain private paths/prose or unrecognized opaque credentials.
The two subscriptions explicitly expand the consented manifest. A request event
means a validated send attempt, not proven remote receipt. Async best-effort
subscribers may see only a post after a drop or subscription change; no per-
subscriber pairing, durable delivery or execution ordering is promised. No
observer return channel exists. Shipped smart/extension defaults remain off.

Twelve parent-current collateral rows retain their existing verdicts, including
H513/H670 equivalence. H409's edited declaration citations were reread and mapped
to current AST ranges. H571's stale missing-runtime claim and active-exclusion
wording are corrected without new completion credit. Documented equivalence
remains **182/697 (26.1%)**, 74 reread equivalents and 108 inherited audit verdicts.

Next action: bounded same-turn review waiting/notification suppression for the
same exact terminal task, then broader flagged shell/script coverage. Preserve
cancel/revocation/CAS checks and all execution floors.

## Frozen source/test/harness hashes

- `agents/core/autonomy/smart_observers.py`: `ea3c1164e2fa09b71ef1ac7e33dea7e3f0b16b8a2b6506c300d35c4835332ee8`
- `agents/core/autonomy/approval_judge.py`: `63f493e46a4a71dfc03549a7b02e8d5ee5f898329c1fb3f0078c8868c23a7eea`
- `agents/core/autonomy/advisory_judgements.py`: `5fb6865ffc2cd89057bb00c370332f54fe46f0d754079178a45ec430c0e4c415`
- `agents/core/extensions/events.py`: `a83cb60144156741c9f32aad13937ec35593ddf63625be737952badaeec5658c`
- `agents/core/extensions/manifest.py`: `2913ef39451e538cdc1548423e5186ef22608e6e69570756d821ce1638439620`
- `tests/test_h485_smart_observer_dispatch.py`: `d99c6f30b3c44171de0cb435ed9850986c6ea83c50cc70b7e4fbd509d9bd2848`
- `tests/test_h485_smart_observer_events.py`: `5b22c11a7c843f51a33ac6408a80f51a9fbb28330ab24b1e732c210730d14775`
- `docs/hermes/evidence/h485-smart-observers-mutations-2026-10-03.py`: `86779c1212530144a939a4a76281304529e6e4abb70e02feb9160f7d8463824b`
