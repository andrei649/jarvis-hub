# Approved URL monitor implementation

Base bb10dac4d2714b4c9776e728b92aa19c39565c46. Scope H453 URL source only; existing script monitor remains unchanged. Parent coordinates independent review; no delegation or live egress.

## Design and authority

One URL hop is one exact plugin.egress task with autonomy_level=ask. Payload freezes fixed plugin and GET method, screened URL, job generation, attempt and hop IDs, and identity UTF-8 representation. Only enforced signed queue mediation can dispatch. TaskExecutor's existing guard consumes the worker permit; a second adapter-owned one-use ContextVar claim binds handler invocation to that guard and detached task fingerprint. Direct handler calls and prefix-matched sibling kinds fail closed.

A fresh PluginHTTPClient subclass per hop retains pinned DNS/public-address validation and transport while replacing only its permissive kernel hook with a fail-closed live callback. Callback revalidates the exact persisted running task, kernel availability/verdict, e-stop and current job generation at the final pre-dial point. A QUEUE decision is merely a veto check result: only the prior signed human-approved execution claim grants the GET. No fallback raw queue/client, no global hook mutation, no protected source changes.

Use one 30-second overall timeout, follow_redirects=False, Accept-Encoding: identity, raw bytes capped at 256KiB and strict UTF-8; reject any non-identity response encoding. Each response is closed and client destroyed, preventing cookies crossing approved hops. Only successful final 2xx text captures enter the existing monitor baseline transaction; intermediate redirects create a fresh ASK (including same-host), with bounded hop count. Known secrets and credential-shaped URL components are rejected before job/task persistence and before dial; redact response text before returning it to the worker. Failures expose constant errors, never response bodies/URLs. Unknown interrupted attempts are never replayed.

## Integration

A narrow adapter in core/autonomy/jobs_url.py owns validation, intake and executor. Coordinator composes it with the existing worker/executor and secret broker. Jobs options permit monitor_url only when the store has the live screening callback installed, mutually exclusive with script, monitor_script and no_agent. Reuse existing persistent attempt lifecycle, generation fencing, pre-model atomic baseline, taint, delivery/e-stop checks. Store URL hop identity separately; source identity remains original monitor URL across redirects.

## TDD gates

1. Before authoring integration, real signed TaskQueue/AutonomyWorker/TaskExecutor plus injected pinned HTTP prove blocked ASK, one successful approved GET, direct/replayed/sibling refusals, off/hold/signing/receipt/payload refusal and live deny/e-stop/breaker.
2. Prove strict representation, cap, timeout/cancel, scrubbed persistence and same/cross-host redirects return proposals without a second send.
3. Integrate persistent URL attempts only after executor tests pass. Prove baseline/change/unchanged, per-hop ASK, replacement generation, restart/unknown non-replay and concurrent reconciliation.
4. One focused pytest process with existing pytest.ini restrictions, isolated canonical JARVIS_HOME, TMPDIR=/private/tmp, dotenv disabled. Scoped Ruff/diff; commit scoped source/tests/guide/plan only. Parent owns global ledgers and counts.

## Verification

Implemented unprotected adapter/coordinator composition and persistent URL authoring after executor gates passed. Independent review pending.

- First RED: 12 executor cases failed on missing adapter, /tmp/nerva-job-url-red.log. First GREEN:12passed after raw-stream fixture correction (httpx prebuffered content is not an aiter_raw stream).
- Integration RED:3cases failed before authoring/proposal wiring, /tmp/nerva-job-url-integration-red.log. Initial combined33passed.
- Final focused suite:232passed in8.23s; /tmp/nerva-job-url-final.log. Newtest delta+35. One stale exact binding inventory failure was repaired by updating only9source locations(+19lines); no guard relaxation.
- Command via isolated launcher: python3.12 -m pytest tests/test_job_url_executor.py tests/test_job_url_monitor.py tests/test_job_monitor.py tests/test_job_scripts.py tests/test_job_gates.py tests/test_jobs_doctor.py tests/test_owner_jobs.py tests/test_runtime_coordinator_boot.py tests/test_orchestrator_bindings.py.
- No protected source, live egress, provider calls, global metadata, dependencies, push or PR changes. Coordinator registration retains other executor guards; exact URL handler claim prevents prefix and direct-call bypass.


Scoped Ruff and git diff --check passed. Receipt expiry/malformed receipt and redirect credential redaction are included in the final suite.
