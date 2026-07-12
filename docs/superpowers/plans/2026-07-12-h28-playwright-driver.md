# H28.1 Real Playwright Driver — Implementation Plan

1. Add failing adapter tests for host gating, lifecycle, bounded observations, mutating
   primitives, download/upload safety, cleanup, and unchanged GovernedBrowser mediation.
2. Implement the optional async Playwright adapter with an injectable startup factory.
3. Add the explicit `from_env()` host gate and opt-in live Chromium smoke test.
4. Run H15/H28 browser, SSRF, approval, park-guard, lint, compile, and security suites.
5. After draft PR #669 releases shared files, rebase, update H28.1/backlog/status in the
   same feature PR, then run full CI and merge.
