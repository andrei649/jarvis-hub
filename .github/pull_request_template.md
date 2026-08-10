## Outcome

<!-- One observable result. Avoid a commit-by-commit narration. -->

## Design receipt

- Goal:
- Non-goals:
- Changed path manifest:
- Contract/generated consumers:
- Rollback:
- Dependencies / merge order:

## Risk classification

Select exactly one tier from `.github/ai-development-policy.json` and explain why.
Automated `verify_change.py` receipts map CI risk conservatively: `low -> R0`, `medium -> R2`,
`high -> R3`. `R1` remains available for a justified bounded-internal human classification.

- [ ] `R0` documentation-only
- [ ] `R1` bounded-internal
- [ ] `R2` runtime-or-contract
- [ ] `R3` authority-or-high-impact

Risk reason:

## Exact-head state receipt

<!-- ai-policy-receipt:start -->

```yaml
policy_id: nerva-ai-development-v1
policy_schema_version: 1
head_sha: REPLACE_WITH_40_CHARACTER_HEAD_SHA
risk_tier: REPLACE_WITH_R0_R1_R2_OR_R3
changed_paths:
  - REPLACE_WITH_EXACT_CHANGED_PATH
commands:
  - name: REPLACE_WITH_CHECK_NAME
    argv: [REPLACE_WITH, EXACT, ARGV]
    cwd: .
results:
  - command: [REPLACE_WITH, EXACT, ARGV]
    exit_code: REPLACE_WITH_INTEGER
    summary: REPLACE_WITH_CONCISE_OBSERVED_RESULT
producer: REPLACE_WITH_ACTOR_OR_AUTOMATION
generated_at: REPLACE_WITH_TIMEZONE_AWARE_TIMESTAMP
delivery_state: REPLACE_WITH_DELIVERY_STATE
ci_state: REPLACE_WITH_CI_STATE
governance_state: REPLACE_WITH_GOVERNANCE_STATE
lease_state: none
review_round: REPLACE_WITH_1_2_OR_ESCALATED
```

<!-- ai-policy-receipt:end -->

Evidence and approval are valid only for this exact head. Any new commit makes previous CI and
governance evidence stale.

## Verification evidence

| Command | Exit code | Result | Evidence head SHA |
|---|---:|---|---|
| `REPLACE_WITH_EXACT_COMMAND` | `REPLACE` | REPLACE | `REPLACE_WITH_40_CHARACTER_HEAD_SHA` |

Known failures, skips, environment limits, or reused evidence (include why reuse is valid):

## Review and authority

- Builder:
- Independent verifier/reviewer (required for R2/R3):
- Integrator (must be separate for R3):
- Unresolved findings / owner decision:
- [ ] Normal review is within the two-round limit, or escalation is documented above.
- [ ] Remote writes, credentials, hardware/live-service checks, and destructive actions stayed
      inside the explicit authorization boundary.

## Surface checks

- [ ] Targeted checks for the changed surface are recorded above.
- [ ] Generated truth is unchanged or regenerated and verified.
- [ ] `docs/ARCHITECTURE.md` is unchanged or updated when module structure changed.
- [ ] User-facing API/HUD/mobile parity is unchanged or reconciled.
- [ ] No unrelated user/agent changes were staged or included.
- [ ] No new silent exception (`except: pass`) was introduced.
- [ ] Overlapping work was inspected and coordinated explicitly. GitHub lease enforcement is
      planned but not implemented; this PR does not claim an active remote lease.
