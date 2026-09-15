# Isolate concurrent tool-result spill writers

Base: `11e043a47b7be7fa4e6391098dc86dd156a0fbf0`. Plan recorded before implementation.

H298 requires oversized tool results to remain recoverable. Read-only reassessment
found a concrete violation: `open_stream` names its temporary file with the tool,
process ID and store object's ID, so overlapping uses of one shared store reopen
the same file. Two real writers reproduce a mismatched first receipt and a missing
second receipt. Whole-result spills also share a temporary filename for identical
content and can race during final rename.

1. Add failing regressions for overlapping same-tool streams, independent discard,
   and concurrent identical whole-result spills. Assert persisted bytes, digest and
   receipt validity, rather than temporary naming details.
2. Give every write an exclusively created temporary file in the existing spill
   root, then retain the existing content-addressed atomic finalization. Remove a
   failed writer's own temporary file; never remove another live writer's file.
3. Run focused store, actual agent-loop spill, output-limit, code-tool and session
   suites. Review source changes affecting H298 since its prior assessment before
   refreshing any evidence. Run independent review and integrated release checks.

Scope: `agents/core/tool_result_store.py`, its tests and this module plan. No change
to thresholds, retention policy, authority, sandbox selection or caller APIs.
Incomplete/cancelled streams and unavailable storage must not be described as
complete recoverable output. This repair does not introduce an orphan-recovery
service or promise durability after arbitrary filesystem loss.

Verification: seven new regressions first reproduced shared-file corruption,
missing receipts, failed-write leftovers and an unclosed handle after a flush
failure. After the localized repair, all 180 focused tests passed (store, actual
agent-loop spill, environment limits, code tools and session kernels). Whole-tree
Ruff and baseline Bandit passed. Independent review found no issues and repeated
67 store/actual-loop checks successfully on macOS; Windows behavior was inspected
but not executed. Integrated full-backend verification remains pending. The separate
H298 reassessment also identified ordinary Ollama effective-window budgeting as a
remaining gap; this isolated durability repair does not claim whole-row equivalence.
