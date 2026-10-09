# Typed tool-loop exits — local H396 slice

Generated 2026-10-09 UTC. Base `ad571c36f78253be9b3f0ede220ca699d42f9636`;
branch `codex/tool-loop-exit-result-20261009`. This unit is local. PR #1247
continues to contain only its earlier published mobile-session change.

The runtime now retains why one tool loop returned. `run_result` returns frozen,
slotted `ToolLoopResult(reply, exit_reason)`; legacy `run` unwraps the identical
reply string, so Agent and injected run-only runtimes retain their contract.
Fourteen enum values are assigned at the actual return branches. No reply-text
matching, shared last-result state or new outcome ContextVar is used.

`model_response` means the provider returned without tool calls, including an
empty answer or prose identical to a fixed refusal. It does not prove that tools
succeeded or that the user's objective was met. The existing compaction boolean
can refuse for size, clock invalidation or failed clock commit, so its reason is
the broader `context_refused`. Explicit revoked-clock, replay, invalid-window
and replay-fan-out decisions remain distinct. All fixed replies and approval
warning suffixes retain their bytes.

The outer result owner makes one best-effort INFO diagnostic attempt after a
normal result and tool-turn reset. Its fixed format carries only the enum reason
and bounded, escaped agent identity. No prompt, reply, tool arguments, result,
path or raw exception is added. A logging failure does not replace the reply.
Escaping errors and cancellation remain exceptions, with no fabricated normal
result. A cancellation-resistant child may outlive a deadline result; it cannot
change the returned immutable value or emit a second terminal diagnostic.

This does not classify the whole owner turn. Plain generation, commands, handled
refusals, parallel agents, synthesis and orchestrator timeouts require their own
attribution before any public field is added. The H686 HTTP/SSE outcome remains
latency-only. Pending-result/WARNING semantics, mutation footers, accounting and
client explanations remain open. No ToolEventLog event, settings, endpoint,
dependency, data migration or authority change is introduced.

## Verification

- Tests-only RED on the exact unchanged base: core 14 new-method availability
  failures and one legacy string control passing; lifecycle four feature failures
  and three controls passing. Root verified four production hashes before release.
  New-method absence is feature-availability evidence, not a reproduced branch bug.
- The initial lifecycle fixture incorrectly registered a synchronous ToolRPC
  handler. Root found its caught `TypeError`; the writer replaced it with an
  async handler and asserted the real successful observation before the missing
  diagnostic assertion. Corrected RED retained four expected failures, three
  controls and no errors. First artifacts are preserved as lifecycle-red-first.
- Final new tests: **18/18 branch/result +9/9 lifecycle**. They cover all 14
  reasons, inner/outer replay refusal, real compaction withdrawal, empty and
  fixed-looking model prose, approval suffix, real successful ToolRPC results,
  concurrency, immutable deadline result/late child, cancellation/provider/gate
  failures, private bounded diagnostic, post-reset logging, log failure and
  Agent run-only compatibility.
- Combined focused integration: **325/325**, zero failures/errors/skips,
  6.011 s across 16 modules. Includes the new tests and existing Agent runtime,
  repeats/caps, compaction, spill, taint, tool events, offer/profile execution,
  effective window, conversation clock and route-preserving guardrails.
- AST review proves 38 unrelated runtime methods unchanged. After unwrapping
  result constructors and return annotations, both `_run_turn` and `_run_loop`
  execution bodies exactly match the base. Independent source and named fresh-pin
  collateral reviews found no Critical/Important issue. Ruff and diff checks pass.
- Full backend milestone is pending on the frozen source. Collection reports
  **21705 cases**, adding 27; frontend/native **2039** and mobile **316** are
  reused from the previous completed unit because client code is unchanged.
  Routes remain 555 and agents 18. No live provider or device test was run.

Artifacts: `/workspace/scratch/h396-*` contains the design, RED/green/focused
results, AST/source manifests, exact-base pin inventory and independent reviews.
Two gpt-6-sol/high agents split source/branch tests and lifecycle tests, then
reviewed independently; gpt-6-luna/medium performed the read-only pin inventory.
Root owned contract, RED release, critical integration, metadata and git; maximum
four active agents, no nested delegation.

Thirteen base-fresh pins refresh after bounded review: twelve runtime claims and
the unchanged identity-band claim in ARCHITECTURE. Moved runtime citations target
the same statements, including the binding moved from `run` to `run_result`.
H396's stale runtime pin receives an explicit bounded reassessment and four new
result/caller/test pins. Eleven other stale runtime pins and H396's older unrelated
pins stay unchanged. All 226 stored review statuses/identities and inventory hash
remain unchanged; H396 stays partial, with older broad evidence still unrefreshed.

Rollback is this runtime/source/test/docs unit. The existing string API, public
outcome and persisted state do not require a migration.
