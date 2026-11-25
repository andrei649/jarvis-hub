# H485 denial feedback checkpoint verification

Generated UTC: 2026-10-03T09:17:06.511931+00:00.
Base / preceding HEAD: `802b3b4bd1d2f310a334794bddd0cf15ffbe2d38`.
Branch: `codex/h277-provider-discovery-20261002`.
Delivery: local checkpoint only; no publication or runtime flag activation.

**Execution Plan:**

Bind committed guardian DENYs to the original authenticated chat consumer,
count them transactionally, reset with new epochs on recorded approvals and
surface one latest valid warning before older FIFO observations. Preserve exact
revision acknowledgement, 256-consumer retention and the 4 KiB budget. One
Sol/high implementer and one Sol/high read-only reviewer had bounded ownership;
the coordinator integrated real chat tests and final verification. No delegation
by the subagents and no paid-provider calls.

**Files Modified:**

19 paths in this increment. Preceding local commit 802b3b4b separately fixes
Nous result invariants and global SAST; its report is in the Nous plan.

| Path | Rationale |
|---|---|
| `.env.example` | Document the trusted warning threshold without activating it. |
| `BACKLOG.md` | Record next-turn delivery and remaining synchronous/hook gaps. |
| `GO_LIVE_PLAN.md` | Regenerate dependent status/count evidence; no new completion credit. |
| `HERMES_STATUS.md` | Regenerate dependent status/count evidence; no new completion credit. |
| `NERVA.md` | Regenerate dependent status/count evidence; no new completion credit. |
| `README.md` | Regenerate dependent status/count evidence; no new completion credit. |
| `STATUS.md` | Regenerate dependent status/count evidence; no new completion credit. |
| `agents/core/approval_outcomes.py` | Insert constant validated warning inside the existing byte budget. |
| `agents/core/autonomy/queue.py` | Exact CAS-bound observational tallies, epochs, validation, priority and retention. |
| `docs/HERMES_CAPABILITIES.md` | Regenerate dependent status/count evidence; no new completion credit. |
| `docs/hermes/assessment.json` | Refresh six previously-current collateral reviews; preserve all verdicts. |
| `docs/hermes/evidence/h485-denial-feedback-mutations-2026-10-03.json` | Seven killed faults, restored baseline and exact-source receipt. |
| `docs/hermes/evidence/h485-denial-feedback-mutations-2026-10-03.py` | Reproducible isolated feedback fault probes; no live edits. |
| `docs/hermes/evidence/h485-denial-feedback-verification-2026-10-03.md` | This verification report and complete changed-path inventory. |
| `docs/hermes/h485-denial-feedback-plan-2026-10-03.md` | Source-grounded design, review corrections, boundaries and verification. |
| `mobile/PARITY.md` | Record server flow and open native/device coverage. |
| `project-status.json` | Regenerate dependent status/count evidence; no new completion credit. |
| `tests/test_h485_denial_feedback_integration.py` | 15 real chat/stream and rendering regressions with mocked HTTP. |
| `tests/test_h485_denial_feedback_queue.py` | 34 queue regressions including corruption, races, reset and backlog. |

**Verification Results:**

- Corrective focused union: **327 passed**, zero failures/errors/skips.
- New H485 cases: **49 passed** (34 queue, 15 real in-process chat/stream/rendering).
  Native guardian HTTP is mocked; no command is executed in these denial flows.
- Isolated mutations: **7/7 killed**, zero surviving/invalid cases; restored
  49-case baseline passes, and exact source/test/public-config hashes match.
  [Reproducible receipt](h485-denial-feedback-mutations-2026-10-03.json).
- Global Bandit 1.9.4 with the unchanged workflow baseline: zero findings and
  zero scan errors. Repository Ruff and whitespace checks pass.
- First complete backend run: **21,563 passed, one failed, 34 skipped, one xfailed**,
  67 warnings, 1,128.28 seconds; raw-env-read count was 118 over the unchanged
  cap 117. Reproduced isolated red, moved only the new read to env_str, and
  preserved the guard and its cap. Second full backend: **21,564 passed, 34 skipped, one xfailed**, 67 warnings, 1,119.03 seconds, exit zero.
- Frontend/mobile count reuse is explicit: 1,884/142 were not rerun for these
  backend-only changes. Backend collection is 21,599.
- No Python coverage instrumentation or threshold is configured. Test case
  counts are not line coverage. Prior frontend coverage is parent evidence only.
- Source freeze: seven captured source/test/harness hashes remain unchanged
  throughout the full backend run; all seven were confirmed again after exit zero.
- Explicit Graft build and freshness check pass; the local wiring graph is current.
  The optional semantic layer was not built.
- Review red cases: incomplete/noncanonical DENY records and a breaker behind
  eight older observations. Both were reproduced and corrected. One additional
  B608 finding was corrected with fixed SQL/bound values, not a baseline change.
- An overlapping corrective mutation run detected import-order source drift and
  is not final evidence; the campaign was rerun after source freeze.
- First isolated mutation attempt: 40 passes and four setup errors because the
  public agents.yaml was missing. That run is invalid and receives no credit.
- Task/status, execution fingerprint, smart receipt verification, mediated claim
  and stranded-running reaper ASTs match the parent. Signing payloads are unchanged.

**Remaining Risks:**

H277/H485 stay partial. Feedback arrives on the next authenticated owner turn and
is advisory guidance; it does not physically block retries or deliver Hermes'
same-turn tool-result warning. Broader flagged shell/script placement,
forced-redacted observer hooks, native mobile settings/labels and live
provider/channel/device acceptance remain open. No runtime feature flag was activated; shipped smart-approval defaults remain off.

Six previously-current affected rows (H277/H288/H468/H472/H485/H504) are re-read
and retain their verdicts. H504's only collateral change is three commented
threshold lines in .env.example; TLS configuration and its source/tests are
unchanged. Inherited stale H487 remains stale. The documented parity total stays
**182/697 (26.1%)**; this increment earns no new equivalence credit.

Next action: implement bounded forced-redacted guardian observers, then resolve
synchronous pre-escalation terminal/shell coverage with independent acceptance.

## Final source freeze

- `agents/core/autonomy/queue.py`: `b1c9a18d0032286b30ce06900f47b447b4c4f54a4ddf1f88e0cf438aaa4a004a`
- `agents/core/approval_outcomes.py`: `167df36987ccf61e78b2deb37fed3c1e32fae11d3898a0f48608974c55467943`
- `tests/test_h485_denial_feedback_queue.py`: `b2dea352d18a1bb8b5f0047cc034e7f90094372590ca77c97d410c918a3105fb`
- `tests/test_h485_denial_feedback_integration.py`: `e033ef48e2f94d62fa101a140a3c6ddfe8aca4602df1bcc72aa953c919675ccb`
- `agents/core/llm/nous_auth.py`: `64eabc660325ff2caffad3731be3b0a14a02f834a01cc61126d80041d7b0828c`
- `tests/test_h277_nous_runtime_invariants.py`: `f0f25821f5561de0bfdf09e4c347e4438879b852c5162f4bb12ca307dd6a3bbc`
- `docs/hermes/evidence/h485-denial-feedback-mutations-2026-10-03.py`: `5be8296d29daa06b5605488086701c219b46bdc191e71d57fb9619d0a538433a`
