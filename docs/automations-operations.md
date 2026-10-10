# Inspect and maintain scheduled jobs

Use `nerva jobs list` for saved jobs and scheduler status, and `nerva jobs doctor`
for a health check. Doctor is read-only and exits nonzero when it finds a problem.
`nerva jobs status JOB_ID` shows one job and its recent runs.

## Runs and incidents

```bash
nerva jobs runs --limit 20
nerva jobs runs JOB_ID --limit 20
nerva jobs incidents --state detected
nerva jobs incidents ack INCIDENT_ID
```

Runs remain inspectable after `jobs remove JOB_ID`. Removing a job removes its
configuration and future follow-up, not its recorded history. History retains
200 recent rows per job and 10,000 terminal rows globally; active referenced
attempts are protected and can exceed those limits. Deleting a job cannot undo
an external action already dispatched under its own approval.

Direct actions record a pending attempt before execution. Success and failure
finish that same record. Interrupted attempts can remain unknown; they are not
automatically replayed. Recovery uses the job's execution lock to avoid declaring
a live attempt interrupted.

Model calls that explicitly report a failed or refused answer produce a failed
attempt and incident, even when they include explanatory text. A request queued
for approval remains a pending approval; incident acknowledgement cannot approve it.

Each failed attempt contributes to a durable incident with a stable ID and
redacted diagnostic. Repeated matching errors share the incident. Acknowledging
it closes that signature; a different error creates a new incident. The existing
three-consecutive-failure pause remains. Acknowledgement does not resume a job or
approve an action. Use `jobs resume JOB_ID` to resume after addressing the cause.

To rearm a completed one-shot, edit its schedule to a different future time.
Then `jobs run JOB_ID` can execute that newly armed slot immediately. The manual
and scheduled paths share the reservation, so a racing timer cannot execute it
twice.

## Independent notes and previous output

```bash
nerva jobs notepad JOB_ID set cursor "page-42"
nerva jobs notepad JOB_ID get cursor
nerva jobs notepad JOB_ID list
nerva jobs notepad JOB_ID delete cursor
nerva jobs edit JOB_ID --no-continuity
```

Named notes persist independently of model replies. Keys allow 128 printable
characters; each value allows 16 KiB of UTF-8 text. A job allows 256 keys and
64 KiB total key/value bytes. A write that exceeds a bound fails without changing
the notes. `get` returns the full value with terminal controls removed; list
shows previews. Add `--json` for the complete structured representation.

Continuity is on by default for compatibility. `--no-continuity` omits the
previous model output from the next prompt; named notes remain. The latest output
is still saved so `--continuity` can re-enable it. Standalone continuity edits
merge on the server without replacing other options. Explicit `--options` keeps
its documented whole-object replacement behavior. The two opposite continuity
flags cannot be supplied together.

The old `jobs notepad JOB_ID --text TEXT` command still replaces the legacy
previous-output note. It does not replace named notes or a verified latest-output
record. When both exist, a distinct legacy note remains available as unverified
context alongside the latest output. Both notes and previous
output enter model prompts as untrusted data and confer no execution permission.
Delayed script/monitor attempts use the notes frozen when they were reserved;
later edits apply to a later attempt. An unchanged monitor and a no-agent script
do not invoke a model.

## Use another job's output as context

```bash
nerva jobs edit DESTINATION_ID --context-from SOURCE_ID --no-continuity
nerva jobs edit DESTINATION_ID --context-from FIRST_ID --context-from SECOND_ID
nerva jobs edit DESTINATION_ID --clear-context-from
```

Use the actual 12-character lowercase hexadecimal IDs returned by `jobs list`.
The repeatable flag accepts up to eight distinct sources in order; `self` refers
to the destination's own previous output. These references replace the configured
source list. `--clear-context-from` removes it. Standalone edits merge atomically
with the current options. Explicit `--options` still replaces that object, with
any supplied flags folded into it. The API accepts `context_from` as a string or
list; null leaves it unchanged and an empty list clears it.

The next model prompt can use each live source's latest substantive successful
output. Missing, deleted or empty sources are skipped. A reference does not run
the source or wait for it: schedule or run the producer first. Sources belong to
the same profile. Turning off continuity omits the destination's own output,
including `self`, while preserving external sources and named notes. Previous
output carries guidance to continue without repeating it; all source content
remains fenced untrusted data.

Approval requests, queued-task receipts, suppressed replies, failures and unknown
attempts do not replace a source's latest useful result. Older legacy summaries
are not fabricated into cross-job output. Each saved result holds at most 8,000
characters and 32 KiB; external prompt context has a combined 64 KiB bound.
An abbreviated result is marked as such. Run-history summaries keep their own
smaller bound and are not the source of this context.

Delayed script/monitor attempts freeze source output when reserved. Later source
runs affect the next attempt. Deleting a source revokes its frozen contribution;
deleting the destination suppresses its later delivery. Removing a job deletes
its latest context output while retaining the historical run metadata.

Scheduled task actions use the governed intake and request approval for each
attempt. They retain their action kind, risk floor and job provenance. Missing
intake refuses the run; there is no direct-queue fallback or standing approval.

The CLI and admin API expose incident acknowledgement, named notes and global
historical runs. The current web Jobs panel retains its diagnostic view and
legacy note editor; dedicated controls for these operations and cross-job source
selection remain open.
