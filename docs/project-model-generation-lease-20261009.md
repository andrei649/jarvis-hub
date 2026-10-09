# Local model protection across loading and generation

- Generated: 2026-10-09 UTC.
- Base: ef56dd389976a2acc3ebaab3f594a2ff80eaa90e.
- Tested source checkpoint: efac393a1219c8b87478fd694af7cd01334c9ae7.
- Branch/worktree: codex/local-model-generation-lease-20261009,
  /workspace/jarvis-hub-model-generation-lease.
- Goal: protect the requested local text model before residency work in both
  Agent.process and Agent.synthesize.
- Delivery: local; draft PR #1247 is a separate previously published unit.
- [Contract, ownership, tests and rollback](plans/2026-10-09-local-model-generation-lease.md).

## Behavior and limits

Both Agent paths previously confirmed local model residency before entering the
manager's reference-counted context. A competing request could evict the model
between those operations. They now enter that existing context before awaiting
the route-aware residency hook and hold it through generation. Unknown-model
references transfer into a confirmed resident entry when the controller later
acknowledges its load; references by themselves never imply residency.

No new manager API or policy is introduced. ModelManager changes are usage
documentation only; its executable AST is unchanged. The route-aware hook,
exact controller acknowledgments, best-effort continuation after refusal,
coarse budget and no-victim overcommit behavior remain. The manager still
defaults off. Cloud routes and an absent manager retain their existing behavior.

Generation parameters are still read after residency work, so settings changed
during a load take effect at the same point. Prepared-route and data-handling
guards remain after that await. The process latency clock resets after residency,
keeping model-load time outside the generation measurement. Context cleanup
releases the reference after generation, guard refusal, exceptions or cancellation
inside the protected scope.

Two small accounting consequences follow from the protected scope: waiting to
acquire the reference now precedes the latency reset, and a generation-parameter
exception is handled by the existing process failure accounting while releasing
the reference. Ordinary parameter selection and generation remain unchanged.

This closes the software eviction window in these two local Agent text paths.
It does not establish universal or exclusive model leases, measured GPU residency,
provider/controller identity, owner-control coordination or ComfyUI integration.
Other generation consumers and ambiguous image submissions require separate
coordination; no admission-control or hardware-validation claim follows. H515
remains partial. Public routes/schema and web/native product flows are unchanged.

## Verification

The new deterministic regression pauses the real Agent route hook after the
manager confirms model A, then completes a competing model B request under a
one-model budget. Before the change, both process and synthesize fail because A
was unloaded. The corrected paths must preserve A through generation and release
references afterward. A separate regression exposed an intermediate parameter
snapshot drift: both paths used old settings when the residency hook changed
them. The final ordering keeps parameter selection after that hook.

The writer's eight-file focused union passes **330/330**, including **22 new
cases**, no skips/failures/errors (14.435 seconds). Root's separate 16-file
integration union passes **336/336**, no skips/failures/errors (11.402 seconds).
The latter covers route-preserving guardrails, strict-local routing and synthesis,
safe mode, identity, session recap, controller adapters and route/OpenAPI parity.
These are 666 distinct cases across the two unions. Ruff passes all three changed
Python files; whitespace and Hermes/generated-status checks pass.

Canonical collection records **21,274 backend cases** (+22), 555 routes. The
unchanged frontend/native 2,009 and mobile 306 inventories retain their preceding
passing evidence; no JS/native execution is relabeled as new.

The complete backend suite at the source checkpoint passes: **21,237 passed,
37 skipped, zero failures/errors**, 21,274 total in **268.450 seconds**, exit 0.
The skipped test identities exactly match the preceding ComfyUI milestone.
Executed-count verification confirms 21,274 against the tracked inventory.
Hermes/generated-status and whitespace checks pass. The final follow-up commit
changes evidence documents only. No real model, GPU, controller service, cloud
request or physical device is used.

## Review and freshness

One gpt-6-sol/high writer owns the two source files and the new regression module;
a second independently reviews control flow and named collateral claims. A
read-only gpt-6-luna/medium inventory compares hashes with the exact base. Root
owns integration, metadata and commits. No nested delegation.

The independent frozen review found no Critical/Important issue. Named claim
reviews support refreshing nine previously current Agent pins: H275/H283/H298/
H441/H490/H513/H670/H671/H679. Their existing explicit Agent coordinates are at
or before line 1026 and do not move. Root separately reviewed H515: every manager
executable AST node is unchanged, the two Agent paths close the reproduced race,
and the protected scope retains its wider coordination limitations. Its current
manager pin is refreshed and direct Agent/new-test evidence is added.

In total **ten current pins are refreshed, two H515 pins added**, and **eight
preexisting stale Agent pins remain stale**: H146/H363/H364/H387/H449/H672/H673/
H696. Only H515 summary/remaining text changes; its partial status and every
other assessment claim/status remain unchanged. Root's AST comparison confirms
the other 27 Agent methods and the rest of that module are unchanged.

Scratch evidence: model-generation-lease-red.log,
model-generation-lease-params-red.log,
model-generation-lease-focused.{xml,log},
model-generation-lease-integration-focused.{xml,log},
model-generation-lease-backend-final.{xml,log},
model-generation-lease-status-sync.log,
model-generation-lease-pin-inventory.{json,md},
model-generation-lease-collateral-review.md,
model-generation-lease-ast-review.json and h515-lease-design-review.md.
