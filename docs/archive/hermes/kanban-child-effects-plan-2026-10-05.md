# Signed Kanban child effects integration

Goal: complete all 697 accepted Hermes capabilities locally, including the H277 handoff. This unit implements independently approved worker file/terminal effects; it does not redefine parity around the existing port.

Generated: 2026-10-05. Base/head: `a7ffad6676cfb28e7ac374d495b4a5889e5f4646`; dirty inherited workspace/project/HUD changes are preserved. No publication or real worker/provider activation.

1. Reproduce the registered file mutation producer failure under enforced mediation. Map only exact file write/delete producer kinds to the physical file contract and wire server-owned finalized intake; preserve H506/H507 labels. Ordinary owner effects remain governed; worker effects require durable child bindings.
2. Persist exact parent submission/queue/run, board/task/profile/session, canonical workspace, cwd identity, tool arguments and child queue/enqueue identity. Park the parent as `needs_input` in the same board transaction as binding. Missing binding cannot execute; queue/board crash gaps remain inert.
3. Require the child's independently consumed queue permit and current signed receipt. Open a fresh, expiring workspace scope tied to the exact blocked source run. Recheck board/project/owner roots, cwd inode, arguments and child state before physical effects. A parent permit never authorizes a child.
4. Use the real registered file handlers and local terminal runner with fixed cwd. Mark success only after nested operation success; prevent ambiguous effect replay. Rejection, expiry and failure retain the blocked parent. Successful reconciliation may propose a fresh governed resume, never manufacture approval.
5. Run meaningful RED/GREEN tests per step, focused integration, dependent route/docs/status checks and then serial frozen full suites. Build/check the local Graft cache explicitly after source changes. Coverage/native/provider/live claims require their own evidence.

Ownership: root owns coordinator, queue classification, child adapter, block transaction composition and integration tests. One Sol/high implementer owns only new child storage/tests; a second owns only HUD gap records/parity tests. No child delegation or overlapping writers.

Rollback: reverse only this unit's localized diffs after inspection; preserve the pre-existing dirty changes. Next action: typed file intake RED, then durable binding and actual child effect tests. Remaining original scope includes other Kanban worker controls and all incomplete Hermes rows.
