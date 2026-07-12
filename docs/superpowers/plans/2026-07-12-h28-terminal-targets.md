# H28.3 Named Terminal Targets — Implementation Plan

1. Add red tests for the built-in inventory, three-state policy, validation, durable hash
   chain, tamper refusal, and concurrency.
2. Implement the pure target/audit types on top of `backend_profiles()`.
3. Export the public target primitives from `agents.core.environments`.
4. Run environment/file-RPC/sandbox/operator suites plus lint, compile, and Bandit.
5. After #669 releases shared files, update H28.1-H28.3 and generated counters in the batch PR.
