# Max run ledger

> Append-only. One row per Max run (`MAX.md` §3.6). The **next** column is the boot
> instruction for the following run — keep it specific enough to start without archaeology.
> Run names come from the entropy table in `MAX.md` §6; never reuse one.

| # | date | run name | slice shipped | PR | spark | next |
|---|------|----------|---------------|----|-------|------|
| 000 | 2026-08-11 | *(bootstrap)* | The Max protocol itself: `MAX.md`, this ledger, `docs/SPARKS.md`, the `max` trigger skill, CLAUDE/AGENTS/BACKLOG wiring | #893 | S-001 (run-name entropy ritual) | Reconcile `BACKLOG.md` top-of-queue: first unblocked 1.0 proof-track item (H23 tail / ⭐B0 prep), per `MAX.md` §3.1a |
| 001 | 2026-08-11 | nimble-beacon | **The $50 lean-in PR (#894).** Three audit-theme fixes + a spark: (1) **ADV-087** closed — the action-capability reality probe resolves `manifest.implementation` to the real actuator (fail-closed) and records it as evidence; (2) **SEC-B6** — the route-auth matrix now gates *reads*: every open GET is classified by handler substance, 13 personal-content reads flipped to `user_guard`, two new honesty tests; (3) **chapter-15 hermetic pass** — ADV-001 audit-chain forgery + ADV-015 forget both FIXED-SINCE, cross-confirmed, recorded in `docs/qa-runs/`. All nine `qa_audit_probes.py` claims CLOSED. | #894 | S-002 (`scripts/max_run_name.py`) | H23 tail stays owner-gated (⭐B0/RTX). Next agent-side: the SEC-B6 export/purge-list-drift gap noted in the qa-run (a test asserting `export_manifest ⊆ purged ∪ KEEP`), or the SEC-B5 dataflow-taint tail (mind the open `nerva2/sec-b5*` draft PRs — those files are locked) |
