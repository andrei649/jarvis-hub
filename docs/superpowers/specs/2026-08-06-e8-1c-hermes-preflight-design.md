# E8.1c Hermes Invocation and Supply-Chain Preflight — Design

**Date:** 2026-08-06

**Issue:** #844 (child of #804; epic #766)

**Status:** Accepted working design for an evidence-only preflight. No Hermes
runtime, dependency, adapter, registration, route, credentials or authority.

## 1. Goal

Close the factual gap between the accepted provider-neutral E8.1b contract and
any later Hermes adapter proposal. The package must identify one immutable
upstream invocation/distribution candidate, bind every claim to exact source
artifacts, and make unresolved supply-chain, side-effect, compatibility,
isolation and benchmark questions machine-visible.

The preflight answers **what could be tested later and what is still unknown**.
It does not answer whether Hermes is compatible, safe, beneficial or eligible
to execute.

## 2. Non-goals and authority ceiling

- Do not install, import, initialize or execute Hermes.
- Do not add a Python dependency, lock entry or third-party manifest entry.
- Do not implement or register an execution provider, route or capability.
- Do not provide credentials, filesystem/network grants or trusted kernel
  context.
- Do not copy or vendor upstream source.
- Do not claim transitive closure, platform compatibility, isolation, safety,
  E9 benefit, provider readiness, completion or release readiness.
- Do not change Ultron / `nerva.action.v1` as the only privileged-action
  authority.

B7/#818 blocks any adapter that could execute or persist an effect. It does not
block this static, public-source evidence record.

## 3. Selected architecture

Use a data-only canonical JSON artifact plus a deterministic, offline checker.
Generate a Markdown view from the validated JSON. The checker imports no Hermes
module, makes no network request and performs no subprocess execution of
upstream code.

The artifact records:

1. **snapshot identity** — observation time, #844/#804/#766 relationships and
   non-release state;
2. **upstream identity** — repository, release tag, commit, tree, tag object and
   exact source blobs/content digests;
3. **distribution boundary** — source package identity, PyPI channel state and
   the exact console-script mapping found in the pinned `pyproject.toml`;
4. **invocation decision** — a future out-of-process console entrypoint is the
   only candidate; direct internal imports remain rejected/unverified;
5. **side-effect inventory** — statically observed startup/import surfaces,
   explicitly separated from executed observations;
6. **supply chain** — direct requirements, range/pin policy, optional groups,
   transitive-license/CVE/SBOM evidence and fail-closed unknowns;
7. **compatibility/isolation plan** — an unexecuted fixture and the minimum
   subprocess envelope a later package would need;
8. **E9 plan** — dimensions and negative cases remain `not_measured`;
9. **authority and repository effects** — every state-changing capability is
   false and every forbidden integration is absent from this package.

### Why JSON plus generated Markdown

JSON gives the validator a closed-world contract and makes contradictory facts
rejectable. Generated Markdown gives reviewers an inspectable, deterministic
view without maintaining a second source of truth. The artifact is a
time-bounded evidence snapshot, not a live network health claim.

### Why the console boundary is only a candidate

E8.1a found no stable public Python API. Internal imports would couple Nerva to
unversioned module initialization and registration behavior. A console script
provides a narrower process boundary and a complete native rollback path, but
its actual startup, cancellation, I/O, network, filesystem and retention
behavior remains untested here. The preflight therefore records
`candidate_not_executed`, never `compatible` or `approved`.

## 4. Validation contract

The checker must fail closed on:

- duplicate JSON keys, non-finite numbers, excessive nesting and hostile types;
- unknown fields, missing required fields or non-canonical identifiers;
- moving refs (`main`, branches, tag-only fetches) used as the evidence pin;
- inconsistent tag/commit/tree/blob/content-digest relationships;
- a console-script mapping that differs from the pinned source evidence;
- observations without source URL, immutable identity, timestamp or method;
- inferred/imported/executed claims presented as static inspection;
- unresolved transitive, license, CVE, SBOM, platform or side-effect evidence
  marked complete;
- any authority, registration, execution, credential, route, dependency,
  manifest, promotion, completion or release flag set true;
- E9 dimensions represented as measured, estimated or beneficial;
- Markdown drift from the canonical JSON.

The checker also verifies repository-local guardrails: no `hermes-agent`
dependency or manifest enrolment exists while the snapshot says those gates are
open. Those guards are deliberately expected to require an explicit evidence
update before a future integration package can land.

## 5. Evidence semantics

Every observation uses one of these states:

- `verified_static`: inspected without importing or executing upstream code;
- `recorded_metadata`: reported by an authoritative distribution/API surface
  but not independently cryptographically verified;
- `not_verified`: evidence was not obtained;
- `blocked`: a named prerequisite prevents the observation;
- `not_measured`: an E9/runtime dimension has no run evidence.

`verified_static` proves only that the recorded bytes or metadata said what the
artifact reports at the observation time. It does not prove runtime behavior,
safety, compatibility, authenticity or absence of vulnerabilities.

## 6. Files and collision boundary

This package initially owns only:

- `docs/superpowers/specs/2026-08-06-e8-1c-hermes-preflight-design.md`;
- `docs/superpowers/plans/2026-08-06-e8-1c-hermes-preflight.md`;
- `docs/nerva2/EXECUTION_PROVIDER_E8_1C_PREFLIGHT.json`;
- `docs/nerva2/EXECUTION_PROVIDER_E8_1C_PREFLIGHT.md`;
- `scripts/check_nerva_e8_1c_preflight.py`;
- `tests/test_nerva_e8_1c_preflight.py`.

Draft PRs #842 and #843 lock shared ledgers and generated truth. This package
does not edit `BACKLOG.md`, `STATUS.md`, `project-status.json`,
`docs/OWNER_TASKS.md`, the Nerva program manifest or the roadmap workflow until
those drafts integrate or release the files. If final CI enrolment is needed,
it will be reconciled from the then-current `main` as a separate final commit.

No user-facing endpoint changes, so HUD/mobile parity files are out of scope.

## 7. Test strategy

Use TDD: first add tests that fail because the artifact/checker do not exist,
then implement the minimum validator and evidence record.

### Positive checks

- canonical artifact validates without network or upstream execution;
- generated Markdown is byte-deterministic and current;
- exact upstream identities, distribution route and console mapping agree;
- every runtime/E9/authority state remains blocked or unmeasured;
- repository dependency and manifest surfaces remain unchanged.

### Hostile checks

- mutable or malformed ref, substituted commit/tree/blob/digest;
- changed entrypoint symbol or distribution identity;
- unknown/duplicate fields and hostile JSON scalar/container types;
- false boolean aliases (`1`, `0`) at authority boundaries;
- unverified transitive/CVE/license/platform/side-effect evidence promoted to
  complete;
- any adapter/registration/execution/promotion/release claim;
- Markdown drift, unsafe output target and invalid CLI input;
- accidental `hermes-agent` dependency or manifest enrolment.

### Verification envelope

Run the focused tests and checker first, then adjacent E8.1b/import/manifest
tests, Ruff, `py_compile`, `git diff --check`, repository status generation in
check mode, and the full suite before any completion claim. Hosted exact-head
checks and an independent review remain mandatory.

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Static inspection is mistaken for runtime proof | Explicit evidence states and all runtime dimensions unmeasured. |
| Upstream or PyPI changes after observation | Immutable source identities plus timestamp; drift remains a later gate. |
| Dependency inventory looks transitively complete | Direct and transitive evidence are separate; unknown closure blocks. |
| Checker itself causes upstream side effects | Standard-library-only, offline, data-only implementation. |
| Future adapter silently invalidates preflight assumptions | Repository guard tests require an explicit evidence transition. |
| Active PRs overwrite shared truth | Unique files now; shared reconciliation serialized after #842/#843. |

## 9. Rollback

Revert the six owned files as one unit. No runtime, dependency, configuration,
database, route, provider state or upstream artifact requires cleanup. Native
execution remains byte-for-byte unchanged.

## 10. Completion truth

Merging this package may establish only **preflight evidence complete**. E8.1
remains `BUILDING`; E8.1c adapter execution remains blocked; E9 remains
unmeasured; owner/hardware and release readiness remain false.
