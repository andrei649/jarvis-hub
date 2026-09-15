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
