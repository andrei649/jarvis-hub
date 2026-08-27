# Integration Closure Sprint

## Freshness

| Field | Value |
| --- | --- |
| Goal | Reconcile overlapping delivery work and prepare only independently reviewable PRs. |
| Base SHA | `75e928114024869bae75ee77937974af9dda5db3` |
| Head SHA | `75e928114024869bae75ee77937974af9dda5db3` |
| Changed paths | Planning document only: this file. |
| Risk tier | R2 overall; it contains R0, R2, and R3 delivery lanes. |
| Generation time | `2026-08-23T11:01:57+03:00` |
| Next action | Review this design, then write the implementation plan. |
| Lease | none |

## Goal

Close the current local delivery inventory without duplicate PRs, unverified security claims, or
mixed rollback units. The sprint produces review-ready PRs, not an automatic merge train.

## Non-goals

- Do not add new product capabilities.
- Do not push, merge, or rebase any branch without explicit authorization.
- Do not combine R3 work with R0 or R2 PRs.
- Do not represent SEC-B4 preflight validation as transport-level DNS-rebinding protection.
- Do not modify BACKLOG.md until the final ownership and PR shape are agreed.

## Current Inventory

| Work | Local head | Classification | Current constraint |
| --- | --- | --- | --- |
| Event-loop wave: browser, ONVIF, memory KG, house actuation | Local wave branches | R2 | Overlaps open PR #945. |
| Codeintel event-loop offload | `0981daeb` | R2 | Does not appear in PR #945; needs exact diff and PR review. |
| Vision and flags documentation | `adf6ba09`, `7d8d9a09` | R0 | Can combine as one truthful documentation rollback unit. |
| HUD seeded-corpus honesty | Uncommitted on `fix/admin-observe-seeded-corpora` | R2 | Requires fresh frontend verification, generated-bundle decision, review, and commit. |
| WorldView F14 hardening | `17fda1de` | R2 | Compose configuration validated; Docker daemon was unavailable for build/runtime evidence. |
| QA4 ungoverned-actions counter | `8fd144ea` | R3 | Requires independent exact-head review and separate integrator. |
| SEC-B4 browser DNS offload | `590380b2` | R2 | Candidate independent PR after exact review. |
| SEC-B4 PluginHTTPClient preflight validation | `8c06f471` | R3 | Does not pin at transport connect time; hold from integration. |

## Delivery Design

### Gate 0: PR #945 Ownership Resolution

Open PR #945 (`fix/event-loop-blocking-io`) overlaps local work on browser routing, ONVIF,

1. Compare exact diffs, tests, and CI failures for #945 against the local branches.
2. Assign one owner per overlapping path: retain #945, retain the local slice, or create an explicit
   narrow successor after handoff.
3. Preserve only non-duplicative tests and fixes.
4. Do not push a competing event-loop PR until the ownership decision is recorded.

Acceptance: each overlapping file has one intended PR owner and the selected PR is rebased or

### Lane 1: Independent R0 and R2 Closure

These PRs can proceed only after an exact-head review and only when their paths do not conflict

| Candidate PR | Inputs | Required evidence | Rollback |
| --- | --- | --- | --- |
| Documentation truth refresh | `adf6ba09` + `7d8d9a09` | Diff review; factual citations rechecked; policy check | Revert one docs-only commit. |
| HUD seeded-corpus honesty | Current HUD branch | Fresh targeted Vitest, full frontend suite, typecheck, build; explicit generated-bundle decision | Revert one HUD commit. |
| Codeintel event-loop offload | `0981daeb` | Targeted codeintel and route-parity tests, exact diff review | Revert one router commit. |
| WorldView F14 hardening | `17fda1de` | Merged Compose config, Docker image build and runtime health smoke once daemon is available | Revert one deployment commit. |

The F14 PR may be opened as a draft before runtime evidence exists. It must not be marked ready

### Lane 2: R3 Security Holding Lane

R3 work is reviewed and integrated separately from Lane 1.

| Slice | Required next decision | Integration rule |
| --- | --- | --- |
| QA4 counter (`8fd144ea`) | Independent reviewer validates persisted-stamp semantics, counters, and no authorization behavior change. | Builder, reviewer, and integrator are separate. |
| SEC-B4 (`8c06f471`) | Design and implement connect-time pinning or a demonstrably equivalent transport mechanism. | Preflight-only validation remains held and must not be labeled as a completed rebinding fix. |

The browser-agent DNS offload commit can be separated from the held HTTP-client pinning commit

## Evidence and Review

Every candidate PR receives an evidence receipt at its exact head SHA with policy version, risk

R0 and R2 require an independent diff review before PR readiness.

R3 requires a builder, a separate reviewer, and a separate integrator. The integrator owns the

## Sprint Exit Criteria

- Gate 0 ownership is resolved for every #945-overlapping path.
- Each Lane 1 item is either a review-ready PR with exact-head evidence or explicitly parked with
  a named blocker.
- HUD work is committed separately from generated artifacts only if the artifact policy is
  confirmed; otherwise the generated delta is removed before PR creation.
- F14 runtime evidence is recorded or the PR remains draft.
- QA4 and SEC-B4 have an explicit R3 handoff; neither is silently included in a lower-risk PR.
- Delivery, CI, governance, and lease states are reported separately for every branch.

## Approved R3 Scope Amendment

The owner selected the safe R3 completion path on 2026-08-23:

- Replace QA4's caller-controlled payload marker with authenticated, SQLite-persisted intake
  evidence bound to the effective task fields.
- Implement true transport-bound pinning for PluginHTTPClient, including redirect validation and
  Host/SNI preservation.
- Make browser HTTP(S) navigation fail closed when transport-bound pinning is unavailable. A future
  authenticated loopback CONNECT proxy is a separate R3 slice; a Playwright route preflight is not
  treated as a pinning solution.

These R3 corrections remain separate from the R2 house request-path performance refactor. The R2
work may rebase after QA4 accepts the authenticated intake contract.

## Initial PR Order

1. Resolve #945 ownership and CI disposition.
2. Documentation truth refresh.
3. HUD seeded-corpus honesty.
4. Codeintel and selected non-overlapping event-loop successor(s).
5. F14 after runtime smoke.
6. R3 work only after its separate review and integration gates.
