# Prospective #1365 integration after #1363

Read-only preview,2026-11-14 UTC. Shared repo /tmp/nerva-delivery1368 was already in coordinator-owned merge state; it was neither checked out nor reset/staged/modified by this review.

Inputs: #1363 cac4704cf9012d4fa86ac55f4cb479862405236a as prospective-main source, #1365 17eaceaa2c89872c58528dfc3e36a33b151aeb38; common ancestor/current-main a5dc55fbebe70c8359e50a63c5fe1ae7fc4af06d. Command git merge-tree --write-tree <1363> <1365> returned1. Its generated conflicting tree9ae6bc54c0c8cc133fddf1352761ca1090876a12 is NOT a clean/reviewed candidate and must not be used as publication evidence. No actual main merge or CI run occurred.

62 unique unmerged path entries:17 production source,10 tests,21 generated HUD artifact paths (including old/new rename bookkeeping names),14 docs/ledgers/status. Thus #1363 integration will require real source reconciliation in #1365, not just generated-header regeneration, if these exact trees are retained.

Production conflicts:
- agents/cli/nerva.py
- agents/core/autonomy/jobs.py
- agents/core/channels/base.py, manager.py, outbound_safety.py, telegram.py
- agents/core/commands.py, env_config.py, llm/tokenizer.py, orchestrator.py, orchestrator_bindings.py, quick_commands.py
- agents/web.py; serve.py
- frontend/src/panels/sessions.tsx
- mobile/src/api/client.ts; mobile/src/components/SessionsModal.tsx

Test conflicts include session organization/transcript web/native tests, outbound safety, parity, model-client inventory, compaction, job gates, Telegram streaming and Windows OCR fixture. Documentation/ledger conflicts include BACKLOG, Hermes status/areas/assessment, HUD roadmap, foreign-session notes, mobile parity and five generated project-status surfaces. Built HUD assets/index contain rename/rename and modify/delete conflicts.

Safe future reconciliation guidance: preserve both exact input heads/receipts; create an isolated integration candidate from the actual new main only after #1363's required checks/merge succeed. Resolve source contracts explicitly using the existing reviewed gateway/session and cumulative-source evidence; avoid blanket ours/theirs or overlaying either whole tree. Keep original integration branches intact. Source conflicts touching lifecycle code do not authorize retrying the platform-blocked review; keep that hold visible and obtain the applicable safe scope before implementation.

After source/test reconciliation, regenerate HUD assets/schema/status artifacts with existing canonical tooling rather than hand-merging hashed chunks or inventing totals. Preserve ledger verdicts/provenance; new hashes alone grant no acceptance. Run the relevant combined checks on the actual resulting head; old separate green CI does not certify this prospective combination. This preview makes no claim that resolving textual conflicts resolves the cumulative security/platform/data-loss holds.

Exact conflict paths are retained in [the preview manifest](2026-11-14-prospective-conflicts.json). Scope was conflict paths only; no broad code, lifecycle or application execution performed.
