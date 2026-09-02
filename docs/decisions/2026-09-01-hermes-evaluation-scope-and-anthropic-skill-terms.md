# Decision — Hermes evaluation scope and the four Anthropic-termed skill subtrees (DRA-45 / E8.1c / GAP-4)

> **Status: RATIFIED (owner, 2026-09-01).** This records the `docs/OWNER_TASKS.md` parking-lot
> call *"Before any future Hermes adapter proposal"*: the four productivity-skill subtrees that
> carry separate Anthropic terms are **not accepted** and are out of scope; a **static-only**
> fresh review is commissioned against the exact pinned artifact; permission to pull-for-execution,
> install or execute Hermes stays **withheld**.

## The question

`docs/nerva2/EXECUTION_PROVIDER_E8_1C_PREFLIGHT.md` flags exactly four files —
`skills/productivity/{docx,pdf,powerpoint,xlsx}/LICENSE.txt` — as
`separate_restrictive_anthropic_terms` with `owner_or_legal_acceptance=false`; the Hermes runtime
itself is MIT. The transitive-licence closure is `not_verified`, six CVE groups are recorded and no
SBOM exists. The parking-lot item asked whether those four subtrees are legally acceptable for the
intended use, and whether to commission a fresh CVE / transitive-licence / SBOM / platform review
before any adapter proposal or the GAP-4 head-to-head run.

## Decision

1. **The four subtrees are not accepted and are out of scope.** They are never imported into
   Nerva, never installed as Nerva skills and never exercised in any adapter or in T1–T10. Because
   the shipped importer allowlist already listed them, they were **removed from
   `agents/core/skills/hermes_pin_v1.json`** (82 → 78 pinned skills) and the E8.1a pin tests
   (`tests/test_hermes_import.py`) now assert the exclusion.
2. **A static-only fresh review is commissioned** against the exact pinned artifact
   (`v2026.8.3` / `3c27eb6` / OCI `sha256:1678…2c9e`) with inspection-only access: OSV/CVE
   re-query, transitive-licence closure, SBOM/provenance, platform review. Outcome:
   **PASS/HOLD pending** — recorded in the `BACKLOG.md` DRA-45 row when it lands.
3. **Permission to pull-for-execution, install or execute Hermes stays withheld.** E8.1c stays
   *EXECUTING ADAPTER BLOCKED* (its three re-request preconditions are in the DRA-58 row) and the
   GAP-4 head-to-head cannot be scheduled until the review passes.

## Consequence

- `docs/HERMES_HEAD_TO_HEAD.md` gate 1 and `docs/OWNER_TASKS.md` (parking lot, GPU-host GAP-4 item)
  point here; `BACKLOG.md` DRA-45 / DRA-58 carry the same wording.
- Reversal path: if legal acceptance of the four subtrees is ever wanted, that is a new owner
  decision that re-adds them to the pin under a fresh review — never a silent allowlist edit.
