# Integration Authority State Machine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify the fail-closed external acceptance state-machine library for issue #906.

**Architecture:** A deterministic Python library validates an externally provisioned policy and
exact pull-request tuple against a strictly parsed, externally stored JSON state. State writes use
an injected compare-and-swap interface; the package has no GitHub client, network, filesystem,
credential, check-publication, or merge capability.

**Tech Stack:** Python 3.12 standard library, dataclasses, typing protocols, JSON, pytest, Ruff.

## Global Constraints

- Base is `origin/main@4b854d8cfde98615bccf47285b3709aa9970fdc3`.
- Risk is `R3`; builder, reviewer, and integrator remain separate before activation.
- Candidate-controlled files are not authority; only an owner-pinned external deployment may use
  this library to support a protected App check.
- No GitHub App/settings/secrets/rulesets, runtime code, generated status ledgers, or current draft
  paths. The required Max run receipt is the only append-only delivery-ledger change.
- Missing, malformed, unavailable, or concurrently changed external state always denies.
- Review dismissal/state changes revoke the matching accepted review; state and collections are
  bounded and fail closed at capacity without candidate-controlled pruning.
- Review revisions come from trusted external GitHub/ledger state, advance monotonically for a
  repository-scoped review ID, are bounded before serialization, cannot rebind that ID to another
  subject or reviewer even after a rejected first observation, and make revocation terminal for
  that review ID.
- No third-party dependency.

---

### Task 1: Exact-head external acceptance state machine

**Files:**

- Create: `services/integration_authority/__init__.py`
- Create: `services/integration_authority/state.py`
- Test: `tests/test_integration_authority_state.py`

**Interfaces:**

- Consumes: `AuthorityPolicy`, `PullRequestTuple`, `ReviewEvent`, and an injected
  `AtomicStateStore` whose `read() -> bytes | None` and
  `compare_and_swap(expected: bytes, replacement: bytes) -> bool` operations are externally
  atomic.
- Produces: `AcceptanceStateMachine.process_review(event) -> AcceptanceResult`,
  `AcceptanceStateMachine.verdict_for(subject) -> AcceptanceResult`, and
  `empty_state_bytes() -> bytes` for explicit owner provisioning.

- [x] **Step 1: Write the failing exact-tuple and independent-review tests**

  Add tests constructing an in-memory compare-and-swap store, a policy for repository `42` and
  base `main`, and a pull-request tuple. Assert a distinct allowlisted reviewer accepts, while
  author, last-pusher, owner, unallowlisted reviewer, and a non-approved review state do not.

- [x] **Step 2: Run the focused tests and verify RED**

  Run:

  ```powershell
  .venv\Scripts\python.exe -m pytest tests/test_integration_authority_state.py -q
  ```

  Expected: collection/import failure because `services.integration_authority` does not exist.

- [x] **Step 3: Implement the minimal immutable inputs, policy validation, and acceptance path**

  Define frozen dataclasses for the policy, tuple, review event, and result. Reject booleans and
  non-positive numeric identities, non-canonical SHAs, empty/mismatched base refs, empty reviewer
  allowlists, and non-approved review states. Export the public API from `__init__.py`.

- [x] **Step 4: Run the focused tests and verify GREEN**

  Run the focused pytest command. Expected: the first test group passes.

- [x] **Step 5: Add failing exact-match, stale-head, replay, and corrupt-state tests**

  Parameterize mutations of repository ID, PR number, base ref, base SHA, and head SHA. Add tests
  for changed-head invalidation; identical and conflicting delivery replay; missing state; invalid
  JSON; duplicate keys; unsupported schema; malformed records; store exceptions; and atomic-write
  conflicts.

- [x] **Step 6: Run the focused tests and verify RED**

  Expected failures must identify the missing strict parser, replay ledger, or fail-closed branch,
  not test syntax or fixture errors.

- [x] **Step 7: Implement strict canonical state and compare-and-swap persistence**

  Parse a closed schema with duplicate-key rejection. Record bounded delivery fingerprints and
  results, append one acceptance for a valid exact tuple, serialize deterministically, and publish
  acceptance only after compare-and-swap succeeds. `verdict_for()` must use an exact full-tuple
  comparison and deny on every state/store failure.

- [x] **Step 8: Run focused and adjacent verification**

  ```powershell
  .venv\Scripts\python.exe -m pytest tests/test_integration_authority_state.py tests/test_ai_workflow_policy.py -q
  .venv\Scripts\python.exe -m ruff format --check services/integration_authority tests/test_integration_authority_state.py
  .venv\Scripts\python.exe -m ruff check services/integration_authority tests/test_integration_authority_state.py
  .venv\Scripts\python.exe scripts/check_ai_workflow_policy.py
  git diff --check
  ```

  Expected: exit `0` for every command, with no test failures or Ruff findings.

- [x] **Step 9: Review the exact diff and commit the coherent rollback unit**

  Confirm only the six planned paths changed, no generated status ledger changed, and no App or
  settings code exists. Stage only those paths and commit with:

  ```powershell
  git commit -m "feat(governance): add external acceptance state core"
  ```

- [x] **Step 10: Close exact-head review revocation and capacity findings**

  Add hostile tests for post-approval dismissal/change/comment events, unrelated-review isolation,
  fresh-review restoration and capacity exhaustion. Persist immutable revocation records, derive
  verdicts only from unrevoked acceptances, and bound every state collection.

- [x] **Step 11: Close hostile ordering and saturated-state authority findings**

  Bind fingerprints and persisted observations to a trusted monotonic review revision, reject
  delayed/conflicting approvals and terminally revoked review IDs, and deny existing verdicts when
  the bounded ledger is saturated and cannot record a required revocation. The revision is a
  required constructor input; saturated capacity explicitly overrides accepted delivery replay.

- [x] **Step 12: Close exact-head replay, identity-binding, and delivery-ledger findings**

  Make terminal revocation apply to the repository-scoped review ID, deny accepted-delivery replay
  after revocation, reject subject or reviewer rebinding, validate those immutable bindings while
  parsing persisted state, and persist every distinct processed delivery with its full canonical
  event identity and revision. Bind rejected first observations, reject oversized numeric inputs,
  reject security-primitive subclasses, make the final capacity-filling write return denial, and
  bound non-built-in-byte store output to a fail-closed result rather than allowing backend behavior
  to escape.
