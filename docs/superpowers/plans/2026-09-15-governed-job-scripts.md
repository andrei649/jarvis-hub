# Governed scheduled Python scripts implementation plan

Goal: a scheduled self-contained Python script proposes fresh approved work per firing, then records and delivers its actual outcome. Base/head before work: cbb342a36198dbde882cab8fb51e60046ab3d9cb. Generated 2026-09-15. Scope: jobs runtime/helper/health, minimal existing coordinator intake wiring, focused tests. Parent owns global reports and integration.

## Authority and supported contract

The existing terminal.exec contract fingerprints argv, not referenced files (environments/terminal_contract.py). The existing trusted terminal_run executor verifies the accepted durable payload (autonomy_coordinator.py). Therefore each firing snapshots bounded UTF-8 .py source from JARVIS_HOME/scripts into literal `sys.executable -I -c SOURCE` argv, using no encoding or shell. The exact argv source is persisted in the approval payload; later file mutation cannot change an approved run. Existing hardline checks, target flags, cwd jail, per-fire ask approval and e-stop remain authoritative. No protected files change.

This slice supports self-contained Python source (maximum 2000 UTF-8 bytes and existing 4000-character command cap). Script-file-relative imports and __file__ semantics are not provided by Python -c. Shell files, arbitrary workdir, model/provider/tool-context overrides remain explicitly unsupported. No production host script is executed during development. Tests may run harmless scripts in temporary roots through the real approved transport.

Options script/no_agent are accepted only for ask actions. no_agent requires script, skips process(), delivers bounded stdout with existing quiet-hours handling, and stays silent for empty stdout. Otherwise successful script stdout supplements the existing job prompt and notepad. No cwd/environment global mutation.

## Persistence and failure model

Use an additive bounded attempt table in the JobStore database, linked to one pending job_runs row, freezing job/action/options and exact terminal payload at reservation. A SQLite immediate transaction reserves repeat allowance and prevents overlapping active attempts across connections. State is submitting -> pending -> completing -> done/failed. The queue stays the authority for execution.

Each submission has a unique origin; reconciliation can recover a queue row by that origin after a crash between enqueue and task-id persistence. Never automatically resubmit an ambiguous submission. Completion is claimed atomically; an expired interrupted completion becomes an explicit unknown outcome and is not automatically re-delivered. This is at-most-once automatic delivery, not exactly-once transport: channels have no transaction/idempotency contract. Keep uncertain outcomes visible. No pending attempt is marked successful on enqueue.

Periodic reconciliation and manual tick use the same path, including after repeat exhaustion. Deletion/pause must not fabricate cancellation of an already approved external task; suppress subsequent delivery for a deleted job, preserve evidence for the actual task, and expose pending state rather than hiding it. Existing task/result payloads are revalidated before their stdout is trusted as the script outcome. A failed nested ToolRPC result is failure even if the outer worker marked the task done.

## Execution steps

- [x] Baseline focused jobs tests with isolated canonical JARVIS_HOME and existing socket/timeouts.
- [x] Red regressions: byte snapshot survives file edit; root/symlink/oversize/mode refusals; approved task required; pending run status and repeat/parallel reservations; task failure/no-agent silence/agent prompt; restart/task-origin recovery; completion claim/no duplicate delivery; read-only diagnostics.
- [x] Implement pure source snapshot and mode predicates; literal argv must roundtrip existing parse_argv and pass existing hardline check. No transport/policy weakening.
- [x] Implement durable pending attempt store and bounded reconciliation with explicit unknown handling. Wire trusted worker.govern_enqueue (never raw queue fallback) and existing queue reads through coordinator-owned callbacks.
- [x] Integrate JobRunner options, pending fire, reconciliation, empty stdout behavior and health predicates. Existing API/CLI JSON options expose the contract without new unmanaged entry points; broader Jobs UI waits for runtime proof.
- [x] Run targeted pytest per step; approved harmless local transport integration; e-stop/approval/quiet-hours/repeat regressions; lint/diff. Commit one coherent tested slice only.

Rollback: revert commit; additive tables retain audit data. Existing non-script jobs remain unaffected. Dependencies: existing SQLite/asyncio/governed queue/terminal transport only.

## Verification and limits

The focused final command uses `/usr/bin/python3 /tmp/nerva-run-isolated.py` with this worktree, `/usr/bin/env NERVA_PUBLIC_PROFILE=0`, and the main repository Python 3.12 venv. `TMPDIR=/private/tmp`; the launcher sets a fresh canonical JARVIS_HOME, JARVIS_TESTING=1 and PYTHON_DOTENV_DISABLED=1. All final tests retain pytest.ini socket restrictions and 30-second thread timeouts. Targets: test_job_scripts, test_jobs_routes, test_nerva_cli, test_owner_jobs, test_jobs_advanced, test_jobs_doctor, test_jobs_edit, test_local_transport and test_h28_terminal_targets. Final evidence is `/private/tmp/jobs-scripts-final.txt` and `/private/tmp/jobs-scripts-final.xml`.

New runtime tests cover literal approved source surviving mutation of its original file through the existing real local transport with an injected approval predicate and grant. This is harmless test-only process execution, not unattended authority or a complete production-kernel integration claim. Deferred approval tests use durable-task doubles. Source size, symlink, root, shell, failure, quiet-hour, restart, uncertain submission/delivery, empty stdout, agent prompts, pause incident and pending scheduler outcomes are covered. Async regressions reproduce deletion/e-stop during a blocked model response and between delivery targets. Source approval remains per firing. Interrupted or partially issued sends are explicitly uncertain and never automatically retried.

Review found and fixed pruning of a pending run after more than 200 later skipped runs. Active linked rows now survive generic pruning, exact run lookup avoids display pagination, and finalization retains the completed row within the bounded history. A 205-skip regression protects this behavior. API returns 202/pending and CLI returns success for an accepted pending request; neither claims completed execution. Broader workdir/model/provider/tool contexts and a script authoring UI remain unsupported and unclaimed.

## Bounded verification followup

The final instrumented focused suite passes 283 tests with one existing Starlette deprecation warning. Coverage 7.16.1 is loaded only from the preexisting temporary `/tmp/nerva-coverage-tool`, via PYTHONPATH after the isolated launcher; no dependency files or product environments changed. `coverage run --branch --source=agents.core.autonomy.jobs_scripts -m pytest` retains pytest.ini guards. Evidence: `/private/tmp/jobs-script-coverage-final.txt`, `/private/tmp/jobs-script-coverage-final.xml`, and `/private/tmp/jobs-script-coverage.json`. New-module branch-inclusive coverage rose from 81% to 88%; remaining gaps chiefly concern exceptional filesystem/SQLite failures and losing concurrent claims. This followup adds 18 collected tests, for 45 script tests and 47 total new tests in the slice.

Additional review fixes: the stdout supplement uses the existing untrusted-tool fence around a single-line JSON object, so embedded delimiters/role text remain JSON data. The agent call uses existing scoped job-channel origin binding (inbound) and resets it in finally; the general process helper itself does not bind this origin. Direct no_agent output is unchanged. Reconciliation now advances a bounded 50-row cursor across calls and wraps, preventing old waiting attempts from starving later work. Its 51-attempt regression deliberately raises only the test authoring cap to exercise paging independently of the current 50-live-job limit.

H453 script-as-context also skips the model on empty or whitespace-only stdout. Two added failing regressions reproduce the previous unnecessary model call; successful nonempty context and no-agent delivery remain covered. Wake JSON gates, monitor hashes/diffs and `[SILENT]` model suppression remain separate open contracts.
