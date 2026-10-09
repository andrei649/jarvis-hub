# H277 Nous OAuth runtime invariants and SAST

Goal: close the three Bandit 1.9.4 findings in Nous OAuth without weakening the
baseline or changing its network, credential, owner or profile policy.
Base / preceding HEAD: `16544990841bd910d563b72b30fa2b5db626b561`.
Branch: `codex/h277-provider-discovery-20261002`. Generated 2026-10-03.

Observed source: poll_login and prepare_credentials rely on assertions that their
result exists. Assertions disappear under Python -O. Normal service branches
already assign a result or error; no live attacker path is claimed. A dependency
fault must still produce a typed safe error rather than a null successful result.
The logout finding is a literal boolean presence flag, not a hardcoded credential.

Plan: reproduce missing results under normal and optimized Python with synthetic
store/formatter faults, including a successful token rotation followed by a
missing formatter result. Replace the two assertions with explicit typed failure
outside the transaction so rotated grants and terminal quarantine still commit.
Explain the boolean-only B105 suppression at that exact logout line. Re-run
Nous/auth/consumer regressions, repository Ruff and the unchanged Bandit baseline.
Refresh only previously-current affected Hermes reviews and generated counts.

Likely paths: agents/core/llm/nous_auth.py, one optimized-mode regression module,
this plan/verification record, affected assessment rows and generated reports.
No new provider calls, SDK, dependencies, flags, credential imports or publication.

Rollback: revert this localized runtime-invariant increment. Existing OAuth flows,
refresh locking, destination checks, encrypted storage and public shape remain.
Next action: H485 session-bound guardian denial feedback and redacted observer hooks.
This Nous increment is ready for a local checkpoint; no publication is authorized.


## Verification (2026-10-03)

The red run reproduced six missing-result failures: normal Python raised an
AssertionError, while optimized Python returned null. The initial cached-token
fixture used a 100-second TTL, below the service's actual 120-second safety
margin; it was corrected to 1,000 seconds without changing the expected no-refresh
behavior. The source guards remain outside the credential-store transaction,
and the rotation regression proves the new refresh grant survives a missing
formatter result. These are dependency-fault probes, not an asserted live exploit.

Fresh resumed verification: 152 focused Nous auth/credentials/API/vision/model
tests pass, including six new normal/-O cases, with no failures, errors or skips.
Bandit 1.9.4 over all agents/scripts with the unchanged workflow baseline exits
zero: no findings and no scan errors. The logout presence flag remains boolean;
its B105 suppression is narrow and justified inline. Repository Ruff and
whitespace checks are separate required gates before commit.

Backend collection is now 21,550; unchanged frontend/mobile counts (1,884/142)
were explicitly reused, not rerun. The complete backend run at parent 16544990
passed 21,509 cases, 34 skipped and one xfailed. It was not rerun for this
localized guard delta; the next authority integration milestone needs fresh
complete-suite evidence. Existing H277 verdict stays partial. No secrets, live
provider requests, settings activation, push, merge or deployment occurred.

Source-bound hashes:
- `agents/core/llm/nous_auth.py`: `64eabc660325ff2caffad3731be3b0a14a02f834a01cc61126d80041d7b0828c`.
- `tests/test_h277_nous_runtime_invariants.py`: `f0f25821f5561de0bfdf09e4c347e4438879b852c5162f4bb12ca307dd6a3bbc`.
