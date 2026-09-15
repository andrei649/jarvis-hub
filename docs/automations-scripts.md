# Scheduled Python scripts

Jobs can propose a small Python script for each firing through Nerva's existing local terminal approval flow. The hub and scheduler must be running, the owner must have configured the local terminal target, and each execution needs its own approval. Creating a job does not grant unattended execution.

## Create a job

Place a self-contained UTF-8 `.py` file in the runtime data directory's `scripts/` folder. With an explicit `JARVIS_HOME`, this is `JARVIS_HOME/scripts/`. The default data-root rules are documented in `agents/core/paths.py`; it is not necessarily the source checkout. Files and intermediate directories must not be symlinks.

For a first check, use `sample.py` containing:

```python
print("Scheduled script completed")
```

Create a job that retains its result in history:

```sh
nerva jobs create --name 'Script check' --when '0 9 * * 1-5' \
  --action '{"type":"ask","deliver":false}' \
  --options '{"script":"sample.py","no_agent":true,"repeat":1}' --json
```

Use the returned job ID to inspect or request a firing:

```sh
nerva jobs status JOB_ID --json
nerva jobs run JOB_ID --json
nerva jobs runs JOB_ID --json
nerva jobs doctor --json
```

An accepted firing returns `pending` (HTTP 202); execution has not finished. Approve the corresponding terminal task through the existing approval interface. The scheduler checks outcomes every 30 seconds. A manual `jobs tick` reconciles outcomes when the scheduler is stopped; it refuses to compete with a running scheduler.

A pending execution consumes one repeat allowance, and another firing does not create an overlapping script proposal. After the repeat limit, the already proposed execution can still complete. Changing the source file after a proposal does not change that proposal: the exact source is embedded in its approved command. A later firing takes a new snapshot and requires a new approval.

## Summaries and delivery

Set `no_agent` to `false` and supply an `ask` prompt to ask the configured agent to interpret successful stdout. Script output is untrusted tool data; it does not grant tools or permissions. With `no_agent:true`, stdout is the result and the model is not called. Empty or whitespace-only stdout skips both the model and notification. The stored/delivered result is bounded to 2,000 characters.

For notifications, omit `action.deliver:false` and set `options.deliver` to existing configured channel names, for example `["ntfy"]`. An empty delivery list retains only history. The existing quiet hours and urgent interruption budget apply. The emergency stop suppresses completion delivery; deletion suppresses delivery even if a separately approved task has already run.

Restart recovery preserves pending attempts and their history. If submission or delivery was interrupted at an ambiguous point, the outcome is reported as unknown instead of automatically replaying the action. A partially issued notification cannot be recalled or assumed undelivered.

## Current limits

This runtime supports local POSIX targets and self-contained Python only: at most 2,000 UTF-8 source bytes within the existing terminal command limit. Execution uses the configured Python interpreter with `-I -c`; `__file__`, script-relative imports, shell scripts, arbitrary working directories, and per-job provider/model/toolset/skill overrides are unsupported. Source is visible in the durable approval payload, so use the existing secret mechanisms instead of embedding credentials in scripts.

The API and CLI accept these options; a dedicated script-authoring form is not implemented. Existing terminal target configuration, hardline refusals, approval, execution limits and emergency stop remain authoritative. See [the implementation and verification record](superpowers/plans/2026-09-15-governed-job-scripts.md).

## Wake and silence gates

A successful approved script can end with a JSON line such as `{"wakeAgent": false}`. The last non-empty line controls this gate: only the JSON boolean `false` suppresses both the model call and delivery. This also applies to `no_agent` jobs and is the exception to otherwise literal script-output delivery. Invalid JSON, a missing key, `true`, `0`, strings, and null continue normally. The gate inspects returned stdout before the display cap; truncated terminal output is not accepted as a complete gate and continues normally. Script failures remain failures.

Scheduled model replies can suppress delivery with `[SILENT]` as the whole reply or a standalone first or last line. Matching ignores surrounding whitespace and case. Whole-response `SILENT`, `NO_REPLY`, and `NO REPLY` also suppress delivery; mentions embedded in prose do not. This check happens before response truncation. A `no_agent` script printing `[SILENT]` still delivers that literal text: this convention belongs to model responses.

Completed suppression is visible in run history as `Suppressed: wake_gate` or `Suppressed: model_silent`, with successful status. It does not consume a delivery interrupt or create a missing/pending run. Script approval is still required for every firing. Monitor hashes, diffs, and URL monitoring are not implemented by these gates.

## Bounded script monitors

Use `options.monitor_script` instead of `options.script` on an `ask` job to compare observations before calling the model. It names the same bounded Python file under the scripts root and still requires fresh approval for each firing. It cannot combine with `script` or `no_agent`. Monitor stdout is literal data: a JSON `wakeAgent` line is not interpreted as a wake gate in this mode. URL sources use the separately governed path described below.

The first successful observation supplies baseline context, even when stdout is empty. Identical subsequent observations finish as `Suppressed: no_change`, without a model call or delivery. Changes supply a unified diff and current output inside the existing untrusted-data fence. The comparison digest and snapshot are committed before the model runs, so a failed model response cannot repeatedly alert on the same change.

The trusted host hashes every stdout byte before display truncation. Monitor evaluation requires successful, complete, valid UTF-8 output whose complete snapshot fits the existing terminal cap (at most 50,000 bytes). Invalid, incomplete, or oversized observations fail explicitly and leave the baseline unchanged. Output rendering for other terminal uses remains unchanged. No raw output file is written.

The normal secret scrubber still applies before task results reach the jobs runtime. Comparison uses the trusted raw digest, while stored/displayed snapshots contain only scrubbed text. A `scrubbed` label identifies comparisons whose raw and displayed contents differ; changes in hidden secret values can therefore trigger a change with no visible text difference. Diffs are displayed up to 4,000 characters and current output up to 8,000, with explicit truncation indicators.

Editing the job configuration invalidates its baseline generation. Already approved work keeps its approved meaning, but a stale completion cannot replace the new baseline or deliver the old configuration's answer. Editing the source file affects only subsequent approvals and starts a new source baseline. Baselines survive restarts; interrupted model/delivery work follows the existing explicit unknown-outcome behavior rather than automatic replay.


## URL monitors with approval per request

`options.monitor_url` is an alternative to `monitor_script` on an `ask` job. It cannot combine with `script`, `monitor_script`, or `no_agent`. Example options: `{"monitor_url":"https://example.com/status.txt","deliver":["ntfy"]}`. Use the same existing jobs create/edit interface. There is no new background fetch outside the task queue.

Authoring requires the live coordinator, secret screening, enabled Action Kernel, and enforced signed task mediation. Missing enforcement or signing refuses this feature; a queued decision alone never grants network access. Each firing proposes one exact `plugin.egress` GET with a frozen URL, plugin identity, generation, attempt, and hop. Approve it through the existing task decision interface. Any redirect, including same-host, becomes another blocked approval; at most five redirects are supported. No cookies or authorization headers carry between hops.

Only HTTP(S), credential-free ASCII URLs without fragments are accepted. User information, credential-shaped query parameters, known secret values (including escaped forms), and secret handles are rejected before job/task storage. Existing public-address DNS validation and IP pinning still apply, so local/private destinations are not supported. Do not put credentials in monitor URLs.

Each hop has one 30-second overall deadline and a 256 KiB raw-body bound. The request asks for identity encoding; compressed responses are refused rather than decompressed without a bound. Final successful responses must be valid UTF-8. Failed/interrupted/invalid captures and redirects do not advance the baseline. Responses are scrubbed before task results or baseline snapshots are stored. Baseline/diff/model/delivery behavior otherwise follows the script monitor above, including inbound taint, quiet hours, e-stop, and generation checks.

A claimed fetch that is interrupted is not automatically replayed. The existing worker records/reaps unknown running work; a pending job observes that outcome rather than submitting another request. This does not guarantee that a remote server never saw an interrupted GET. Tests use the real signed queue/worker/executor with injected DNS/HTTP and no live egress.

## Approved script working directory

For `script` with `no_agent:true`, optional `options.workdir` selects an existing absolute directory inside the configured local terminal roots. The server rejects missing directories, symlinks, outside paths and model/monitor workdir combinations. The canonical directory is frozen in each proposed task's `cwd`; every run still requires approval and execution rechecks current terminal roots. Job edits do not relabel a pending task. This does not change the hub process cwd, create directories, broaden roots or grant model filesystem access. Approved host Python is not a filesystem sandbox or a snapshot of directory contents.

The Jobs advanced form authors script/no-agent/workdir and displays configured cwd. CLI create/edit accepts `--workdir` together with a complete `--options` document; empty `--workdir ''` removes it from that document. Doctor reports unavailable directories without repairing them. Project instruction loading and model terminal/file/code workspace isolation remain unsupported. See [verified plan](superpowers/plans/2026-09-15-job-workdir.md).
