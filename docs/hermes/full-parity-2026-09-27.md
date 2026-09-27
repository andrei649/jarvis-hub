# Jarvis / Hermes: full functional parity

Owner directive: 2026-09-27 — everything Hermes can do should be available in
Jarvis. Local development only; publication is deferred. This supersedes the old
product assumption that 107 excluded rows need never be implemented. They are
now explicitly readmitted for reassessment, not converted into completed work.
Assessment schema 2 records the 107 identity-bound scope reopenings; the frozen
inventory remains unchanged. See `scope-reopening-plan-2026-09-27.md`.

## Reference and scope

- Nerva base: `bd2bb70ead1b493043a335e77713fc42c47d4013`, PR #1207 branch,
  plus the owner's uncommitted local-autonomy policy changes.
- Hermes source: NousResearch/hermes-agent at
  `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e` (2026-09-27).
- Source archive downloaded and extracted outside Nerva. No Hermes installation,
  dependency installation, personal-profile import, or execution performed.
- [Reference manifest](upstream-reference-2026-09-27.json) records the local path,
  archive digest, inspected source digests, former exclusions and stale evidence.
- Existing inventory: 697 capabilities from v2026.8.31. Preserve their IDs;
  identify September additions separately before an explicit inventory migration.

Goal: usable behavioral equivalence across models, tools, skills, memory,
automation, channels, media, desktop, web, CLI/TUI, plugins, ACP and MCP.
Copy compatible implementations with their attribution where useful; adapt
interfaces to Nerva's architecture. Full parity does not require identical source
layout. A UI-only facade or an unconnected backend does not satisfy a capability.

Non-goals for this inspection: replacing Nerva wholesale, importing user secrets
or history, enabling paid providers, publishing changes, or claiming parity from
file counts. No product capability implementation is delivered by this document.

## Evidence baseline

The saved HERMES_STATUS page says 190/697. Recomputing evidence on this working
tree yields **154 equivalent, 309 partial, 65 missing, 107 excluded and 62 needing
review**. The 62 are stale evidence, not 62 demonstrated functional regressions.
Only 46 of the 154 equivalents have current reviewed evidence; 108 retain the
original audit. This is not a newly executed end-to-end benchmark.

The old 590-row accepted scope is no longer the target. All 697 old rows plus
verified upstream additions must receive an explicit disposition under the new
directive. Preserve the original ledger until its identity migration is prepared;
do not edit completion percentages to imply that reassessment is implementation.

## Initial source inspection

| Surface | Hermes source inspected | Implication for Jarvis |
|---|---|---|
| Auxiliary models | `agent/auxiliary_client.py` | Task-specific routing has fallback, cancellation and timeout behavior; compare these as well as role names in H277. |
| Providers | `providers/base.py` | Provider metadata includes transport and authentication behavior; adding a provider name alone is insufficient. |
| Code execution | `tools/code_execution_tool.py` | Local execution uses a persistent per-conversation kernel and tool RPC; test session state, isolation and remote-backend semantics separately. |
| Delegation | `tools/delegate_tool.py` | Children have separate conversations and task identities; compare parallel execution, cancellation and parent-visible results. |
| Video | `tools/video_generation_tool.py` | Current upstream ships no in-tree video provider for this tool; a plugin supplies generation. Edit/extend are explicitly absent from this surface. |
| Automation | `cron/scheduler.py` | Scheduler behavior includes failure handling and resource cleanup; job creation alone is not equivalent. |
| ACP | `acp_adapter/server.py` | Compare session listing/loading/forking/resumption, model selection, permissions and streamed events. |

These are targeted static observations, not a complete audit of upstream. The
root LICENSE and the four productivity skill LICENSE files currently read MIT;
old notes about these exact subtrees must be rechecked against this revision.
Preserve applicable notices when porting and inspect each copied subtree's terms.

## Execution sequence and acceptance

1. Finish H277's seven round-2 defects using the existing handoff, mutation cases
   and regression suites. Then extend kernel/Decision Inbox integration under the
   owner's new authorization. Keep existing audit behavior and explicit remote opt-in.
2. Reassess the 62 stale evidence rows against actual code and tests. Do not merely
   refresh hashes. Record each remaining gap honestly.
3. Map the upstream revision against all existing IDs, review the 107 former
   exclusions, and record new capabilities without renumbering old ones. Include
   terminal surfaces, profiles, provider breadth and plugin/skill functionality
   previously rejected on product-fit grounds.
4. Continue H487 and the existing queue, grouping overlapping rows by usable
   end-to-end behavior. Preserve the H277 handoff's work rather than restarting it.
5. For each capability: pin Hermes behavior and relevant upstream tests, reproduce
   the missing Jarvis behavior, implement a localized change, run regression tests,
   and verify the user entry point. Mark equivalent only after the whole contract
   passes. Real-account/hardware validation remains a separate recorded outcome.
6. Run common scenario tests against both implementations with synthetic inputs,
   matching model/settings where applicable, and report failures on either side.

Likely implementation paths: `agents/core/llm`, `agents/core/autonomy`,
`agents/core/kernel`, relevant routers, tool/skill modules, HUD/desktop clients and
their tests. Each increment records its own exact paths and dependencies before
editing. This inspection changes only `docs/hermes` and local source/index caches.

Rollback: remove these two inspection artifacts to undo this step. Subsequent
capability changes remain separate reversible diffs; preserve the existing policy
changes and user state. No remote or running service has been modified.

The initial N1 regression and round2 are now implemented and mutation-verified.
Current continuation: `h277-completion-plan.md`; next approval-lifecycle slice:
`h487-implementation-plan.md`. H277 remains partial while video/provider parity
and native/live acceptance remain open. The evidence baseline above is the dated
inspection snapshot; use generated `HERMES_STATUS.md` for current hash-bound counts.
