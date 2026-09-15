# Bounded script monitor implementation plan

> Execute inline with writing-plans, executing-plans and test-driven-development. Parent coordinates review/integration; no delegation.

**Goal:** Approved script observations suppress unchanged model runs and supply bounded baseline/diff context on changes.
**Base:** 018b99f7f1102e01c94037fd30a25c8106f98890. Generated 2026-09-15. Head: implementation branch codex/backlog-job-monitor. Next action: failing capture tests.
**Spec:** Frozen H453 / 31-automation.md automation.cron-monitor-mode. Existing script approval remains required per fire.
**Architecture:** Existing read_capped_stream sink feeds a trusted bounded raw digest/UTF8 validator. Local transport adds metadata without persisting raw bytes or changing authority. Jobs keep an additive generation/baseline table; detection and baseline advancement commit before model execution. Existing attempt claims/recovery remain authoritative.

## Boundaries

- Source option monitor_script is an alternative to script, only for ask jobs, and cannot combine with no_agent. URLs remain unsupported.
- Monitor stdout is literal observed data; wakeAgent JSON is not interpreted. This composition is explicit because frozen inventory does not establish combining the pre-check wake protocol with monitor sources.
- Complete successful UTF8 stdout snapshots within the existing transport output cap are supported. Over-limit, invalid UTF8, incomplete/malformed metadata or source failure leave baseline unchanged and fail explicitly. Full-output digest still covers over-limit raw bytes but cannot manufacture a complete diff snapshot.
- ToolRPC secret scrubbing stays unchanged. Compare the trusted raw digest; retain only scrubbed text snapshots. Label scrubbed comparisons whenever the delivered snapshot hash differs from the raw digest.
- A first empty observation is a baseline/model event; unchanged empty observations are no_change. Persist new hash/snapshot at detection, before model await, so model failure never repeats the same change.
- Configuration generation advances on authored configuration writes; stale attempts cannot overwrite a new baseline or deliver after replacement. Frozen source SHA distinguishes script-file edits on subsequent approved attempts. Never reread a file to change an already approved task's meaning.
- No protected policy/security files, URL egress, dependencies, global reports or remote mutations. No raw output files. One bounded pytest process with existing guards.

## Steps

- [x] Add failing capture tests: exact full digest across chunks and discarded middle; invalid/split UTF8; complete snapshot flags; real harmless local transport metadata and timeout behavior.
- [x] Add capture helper using hashlib SHA256 and incremental strict UTF8 decoder. Feed via existing sink; add sealed metadata only after EOF and process success. Keep normal stdout/stderr rendering.
- [x] Add failing monitor runtime tests: baseline/change/no_change, empty, byte distinctions, invalid/overcap/source failures, model failure non-realert, source edits/generation replacement, persisted restart and redaction-safe diff.
- [x] Implement additive schema/config-generation triggers and atomic detection on the claimed attempt; connect monitor authoring/intake/runtime and metadata-only diagnostics. Fence bounded structured monitor context and retain scoped inbound origin.
- [x] Run relevant jobs/transport/output regressions, lint/diff and targeted coverage; obtain parent-coordinated review. Document explicit limits and tested outcomes in module guide. Commit explicit scoped files only.

## Test matrix and rollback

Tests use isolated canonical JARVIS_HOME, TMPDIR=/private/tmp, JARVIS_TESTING=1, PYTHON_DOTENV_DISABLED=1 and NERVA_PUBLIC_PROFILE=0 with pytest.ini socket/timeouts. Compare changes in whitespace/newlines, changes hidden between identical truncated ends, parser metadata forgery in stdout, and split multibyte characters. Check baseline survives failed model and failed source; repeated/concurrent reconciliation does not double-send; edits during pending/model work suppress stale generation. Rollback is one commit revert; additive tables contain only bounded scrubbed snapshots and metadata.

## Verification outcome

The scoped final suite passes 364 tests with one existing Starlette deprecation warning. New cases: 26 (8 capture, 18 monitor). Capture tests first failed 6 cases, then 114 capture/local/output tests passed. Monitor tests first failed on unsupported authoring, then exercised baseline/change/no_change, empty observation, failed-model non-realert, capture refusals, source edits, stale configurations, restart/CAS concurrency and actual approved harmless local transport. A newline-only change regression failed before adding the standard missing-final-newline diff marker.

Final evidence: /private/tmp/job-monitor-final.txt and /private/tmp/job-monitor-final.xml. Temporary coverage 7.16.1 from /tmp/nerva-coverage-tool measured jobs_monitor at 93%, output_capture at 100%, combined 95% branch-inclusive; remaining gaps are losing a claimed attempt and transaction rollback. Existing pytest.ini timeout/socket guards remain active, no dependency changes. Scoped Ruff and diff checks passed. Parent coordinates final independent review and integration.

Persistent baseline source identity covers frozen terminal arguments (including interpreter, target and approved source bytes) together with configuration generation. Generation is captured with the actual stored configuration in the reservation transaction. A pre-delivery claim checks the generation under the same store lock; awaited sends recheck it. No policy changes or URL authority are introduced. Local transport cancellation cleanup behavior predates this slice and is unchanged; cancellation yields no completed observation metadata.
