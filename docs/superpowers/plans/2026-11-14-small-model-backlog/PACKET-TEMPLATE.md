# Template: one implementation packet

Copy the schema of `packets/core.json`; assign a new unique SM id. This template is
for the coordinator, not a request for the implementer to make missing design decisions.

1. **Goal:** one user-visible result or one reproduced failure fixed. Quote the
   exact residual clause from `taskpack.py show Hxxx`; link the source SHA.
2. **State:** `ready` only after the following decisions exist. `needs_design`
   means planning work only; `external` names the missing device/access and an
   offline alternative. Neither state authorizes speculative implementation.
3. **Dependencies:** use concrete SM ids with interfaces, not “finish backend”.
   Map duplicate BACKLOG/Hermes references to the same packet; do not implement twice.
4. **Owned files:** at most three production files per worker by default, plus
   tests/docs needed by that behavior. Name every exception and split broad WIP
   branches before assignment. One writer per file, especially orchestrator.py,
   nerva.py, settings_db.py, schema.gen.ts and assessment.json.
5. **Interfaces:** actual existing signature and caller; exact proposed new
   signature where required. State identity, persistence boundary, error shape,
   return type and cancellation semantics. Mark new paths explicitly. Do not
   use placeholder names or ask a small model to invent a cross-module protocol.
6. **Acceptance:** named tests with given/when/then and concrete values. Include
   success, invalid/denied input, retry/cancellation, persistence/reload when
   relevant, and one test through the real application caller. Name exactly which
   platform/provider tests remain external. Existing mocks are not live proof.
7. **Steps:** read the listed slices → reproduce the named failure → change only
   owned code → run the packet's focused tests → check the affected integration →
   submit diff and receipts. An integration packet may start green but must prove
   a behavior that the old source did not already provide.
8. **Commands:** exact commands from repository root using the project Python;
   separate collecting tests, executing tests and CI results. Describe expected
   assertions, not a guessed test count. No global suite for a prose change.
9. **Stop conditions:** concrete missing dependency, public API disagreement,
   unexpected cross-file changes or an authority/data boundary the packet does
   not define. A worker stops this packet and returns a finding; independent
   ready packets can continue.
10. **Rollback:** revert this coherent source change; define migration/data
    compatibility separately. Never delete user data to make rollback appear easy.

Before changing `spec_state` to `ready`, the coordinator checks actual current
symbols, file fingerprints and caller behavior. A copied historical plan is
`needs_design` until reconciled. No automatic upgrade of Hermes verdicts occurs.

Required JSON keys: `id`, `title`, `spec_state`, `priority`, `risk`, `hermes_ids`,
`backlog_ids`, `goal`, `non_goals`, `depends_on`, `owned_files`, `read_files`,
`interfaces`, `acceptance` (`case/given/when/then`), `steps`, `commands`
(`cmd/expected`), `review_focus`, `stop_conditions`, `rollback`, `source_refs`.
