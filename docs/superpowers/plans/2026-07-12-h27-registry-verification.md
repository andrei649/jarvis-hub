# H27.5 Registry Verification — Implementation Plan

1. Add failing tests for stable refs, exact coverage, one-to-one mapping, honest seam
   behavior, and hermetic execution against the real booted registries.
2. Add plugin/component/skill verification-name helpers.
3. Implement dynamic plugin policy probes plus component and skill construction probes.
4. Expose `registry_reality_cases(orch)` and `all_reality_cases(orch)` without changing
   the static `CASES` contract.
5. Update H27.5 and generated status counters only after focused and extended tests pass.
6. Run full verification, inspect the complete diff, create a draft PR, wait for every
   required CI check, squash-merge, and remove the isolated worktree.
