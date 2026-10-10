# Hermes full-contract closure — batch 06

Generated 2026-10-10 UTC. Goal: continue the 697 accepted contracts with H049
named log reading and H015 scheduled-job operations. Base/initial head:
`d5e36b02` (144/697 local); branch `codex/hermes-closure-06-20261010`.
Local only: no publication, deployment, paid providers or personal-state reads.
Current state: H049 and H015 implementation authorized on the interfaces below.
No new count credit yet.

## H049 named logs

Preserve `nerva logs [-n N]`; add an optional exact configured basename or
numbered rotation, plus `logs list` for discovery. Select only names from
`log_tail.list_files(log_path(ctx.environ))`. With no name, select the first
available file (primary, otherwise lowest numbered rotation). Never accept an
arbitrary path, neighbor, symlink, nonregular entry or nonexistent logical log.
`--name` disambiguates a configured filename literally named `list`; reject it
when a positional selection was also supplied.
Always use the existing redacted bounded `read_path` reader, including its
no-follow open and regular-file check after enumeration. Missing/redaction/race
errors remain failures and never fall back to a raw file read.

Keep the established CLI `-n` behavior above 500 records; its byte-window and
per-record limits still apply. Do not claim the admin API's 500-record limit for
this CLI. This service has one configured rotating log, so native exact basenames
are the accepted name mapping. No upstream follow/filter or nonexistent
multi-service log claim. Printed metadata and filenames must be terminal-safe.

Owner: review_1233 (`gpt-6-sol/high`), `agents/cli/nerva.py` and a new dedicated
`tests/test_h049_named_logs.py`. Read/run existing log tests; change other tests
only if necessary and agreed. No core log-reader source change is expected.
Root owns this plan, docs/backlog, critical review and evidence. No subdelegation.

Red-first proof: explicit rotation/count/order, primary and rotation fallback,
safe listing, no-files guidance, traversal/absolute/neighbor/symlink rejection
before read, fail-closed redaction, selected-secret masking, and deletion or
symlink replacement between enumeration and open. Run relevant existing log/CLI
regressions and preserve recursive completion behavior.

## H015 design boundary

Read-only review found remaining durable incident ID/state/ack operations,
history retention after deletion, multi-key notepad operations, explicit
continuity control, and governed scheduled-task intake under enforced mediation.
Existing script and URL-monitor approvals remain fresh tier-3 ASK per attempt;
URL fetch remains `plugin.egress`. Jobs never carry a standing GRANT.

### Durable job operations and shared interfaces

Core owner: repair_1247 (`gpt-6-sol/high`), `agents/core/autonomy/jobs.py`,
new `jobs_incidents.py` and `jobs_notepad.py` beside it, `jobs_scripts.py`,
and the dedicated binding seam in `agents/core/autonomy_coordinator.py`.
Own new `tests/test_h015_job_operations.py` and necessary focused job test updates;
coordinate additional paths first. Surface owner: review_1233,
`agents/core/routers/jobs.py`, `agents/cli/nerva.py`, and new
`tests/test_h015_job_operations_api.py`. Root owns docs, generated types/parity,
critical governance review and milestone evidence. One writer per file.

Add SQLite helpers on JobStore's existing connection and lock. Additive tables
leave old job/run rows readable. Public helper methods acquire the lock once;
private transaction helpers support callers already inside the same transaction.
Use immediate write transactions where cross-process bounds/CAS require them.

`store.incidents` exposes `list(job_id=None, state=None, limit=100)`,
`ack(incident_id)`, and the internal observation seam. Results are plain bounded
dicts with numeric `id`, `job_id`, `state`, `first_seen`, `last_seen`,
`occurrences`, `failure_count`, `error_code`, `safe_error`, and `acknowledged_at`.
Unknown ack returns None; existing ack is idempotent. State is
`detected | alerted | closed`. Each actual failed attempt records a detected
incident, grouped by job and a stable signature of normalized redacted error.
Same-signature repeats increment once and never reopen a closed incident; a
changed signature creates a new one. Preserve the three-failure automatic pause.
Record run/status/incident together for direct and script completion, respecting
script CAS and retries. Redact bounded diagnostics before storing them; redactor
failure yields a fixed unavailable diagnostic. Never persist raw payload/stdout
in an incident. Existing best-effort E_JOB_PAUSED logging is not proof of an
alert, so it does not set `alerted`. Owner ack persists across restart/resume/delete.

`store.notepad_kv` exposes `list(job_id)` returning sorted dicts of `key`, `value`,
`updated_at`; `get(job_id,key)` returns string or None; `set(job_id,key,value)`;
and `delete(job_id,key)` returns bool. Require a live job (KeyError otherwise).
Reject invalid/empty/control keys and invalid Unicode/non-string values. Caps:
128 key characters, 16 KiB UTF-8 per value, 64 KiB per job over key+value bytes,
and 256 keys. Enforce totals transactionally; rejected writes leave data unchanged.
Keep legacy `Job.notepad` as previous model output, separate from owner KV.
Inject KV and optional previous output as fenced untrusted data using the native
quarantine mechanism; values cannot terminate the fence or acquire authority.
Normal ask and delayed script/monitor ask use the same formatter. Delayed attempts
freeze KV with their existing job snapshot at reservation; later edits affect
the next attempt. no-agent and unchanged monitors do not invoke a model.

Accept exact boolean `options.continuity`; absent remains true for compatibility.
False omits prior model output but retains KV. Continue saving the latest bounded
model output so re-enabling has a defined value. CLI create/edit use mutually
exclusive `--continuity`/`--no-continuity` with None default. A standalone edit
flag sends a strict additive PATCH `continuity` field; the store atomically
merges it into the latest options in the same edit transaction, preserving other
fields and concurrent option edits. Explicitly supplied `--options` retains its
documented replacement semantics, with the CLI folding an explicit flag into
that object. Reject an API body containing both `options` and `continuity`.
Do not clear provider/model/toolsets or monitor settings incidentally. Opposite
CLI continuity flags are mutually exclusive.

Retain `job_runs` on delete. Add `store.runs_recent(limit=100, job_id=None)` and
keep `store.runs(job_id,limit)` readable after deletion. Preserve the per-job 200
retention and prune to 10,000 newest terminal historical rows globally while
protecting active script/request references. Active protected rows may exceed
that limit. Deletion removes configuration, held delivery, ticks and KV; pending
job follow-up must not deliver or requeue. It cannot undo an already dispatched
independently approved external action. Historical reads expose existing bounded
run metadata, never frozen script payloads or captured output.

Critical review found direct actions only wrote their run after awaiting the
effect/model. Add durable direct-attempt start before that await: atomically
reserve its repeat/one-shot slot and create one pending run, tagged separately
from script attempts. Finish that same row with CAS to ok/failed/unknown and
commit live job counters/notepad plus any failure incident together. Never
double-reserve one-shots or insert a second completion row. Cancellation marks a
fixed unknown result and re-raises; storage failure cannot claim success. Recover
orphaned direct attempts only while holding the existing per-job OS execution
gate, on registration or the next firing. A held live gate forbids recovery;
elapsed time alone is never proof. Recovery does not replay an effect. This native
gate proof does not close H451's separate pid/start-time/watchdog contract.
Deleted jobs retain attempt history but suppress further model-result delivery;
already dispatched independently authorized effects remain uncertain.

Script attempts likewise reserve their one-shot slot exactly once in the script
CAS transaction. The outer runner must not spend the slot before that reservation.
Shared model asks prefer the orchestrator's detailed result and treat an explicit
error as a failed attempt before delivery. A nonempty fixed refusal is not a
successful answer. Ordinary queued-approval output and the silent sentinel keep
their existing meanings; this does not blanket-classify every tool stop as failure.

Add `JobRunner.bind_task_intake(submit=...)`, wired by the coordinator to the
actual autonomy worker's `govern_enqueue`. No raw queue fallback in any posture.
Preserve original kind/payload and requested risk floor (default 3), pass explicit
`autonomy_level='ask'` and reviewed `origin='inbound:job:<id>'`, and require a
positive non-boolean task ID before reporting queued. The inbound prefix must
retain job identity and trigger untrusted-origin handling. Policy/kernel may
tighten or deny; unknown kinds and missing intake remain refused. Manual, first
run and tick converge on this path; each attempt needs its own decision.

### API and CLI

Every new route uses admin_guard. Static routes precede `/{job_id}`.
GET `/api/jobs/incidents` accepts optional state/job_id and bounded limit;
POST `/api/jobs/incidents/{incident_id}/ack` closes it (404 unknown).
GET `/api/jobs/runs` lists global or selected history with bounded limit;
GET `/api/jobs/{job_id}/runs` remains usable after deletion.
GET `/api/jobs/{job_id}/notepad/keys` lists notes, or reads one with optional
`?key=`. PUT at that path uses strict JSON `{key: string, value: string}`;
DELETE uses required `?key=`. Keys are values rather than path fragments, so
slashes and Unicode cannot alter routing. Missing job/key returns 404,
invalid/budget-exceeding writes 422. Keep existing legacy notepad PUT compatible.

CLI: `jobs incidents [list|ack] [ID] --state ... --job-id ...`;
`jobs runs [JOB_ID] --limit ...`; `jobs notepad JOB_ID [list|get|set|delete]
[KEY] [VALUE]`. Keep explicit legacy `--text` replacement, rejecting conflicting
KV operations. Default notepad display includes independent KV plus the legacy
continuity note for compatibility; --json preserves structured identities.
All user/diagnostic text printed to terminal is sanitized. Correct remove/delete
help to say history is retained. Acknowledgement never resumes or approves a job.
Notepad get returns the full bounded value with useful line breaks preserved;
only list uses a preview. JSON output preserves all stored text through escaping.

Focused proof includes first/repeated/changed/acknowledged failures, restart and
delete persistence, exactly-once script reconciliation, concurrent KV caps,
delimiter injection and continuity across both model paths, protected history
retention, and real enforced-mediation worker/kernel intake with exact kind/risk/
inbound origin and individual ASK. Unsupported intake must create no task.

## Verification and rollback

Focused red/green and integration checks per changed surface, actual disposable
CLI/API smoke, generated route/OpenAPI/parity updates for new endpoints, then one
serial frozen full backend milestone and failure-driven follow-up. Root reviews
the complete frozen contracts and only previously current collateral pins;
unrelated stale evidence and the frozen inventory remain untouched.

Review H145's existing bounded log UI and H684's existing read-only jobs doctor
against their entire frozen clauses as additional whole-contract candidates.
Neither is promoted solely because a neighboring implementation or hash changed.

Native adaptations reviewed before implementation: `jobs list` supplies global
scheduler status, and `jobs doctor` supplies health/overdue diagnostics; no separate
Hermes cron daemon or independent ticker-heartbeat claim is made. A completed
one-shot can be rearmed by editing its schedule to a distinct future time; an
immediate `jobs run` then uses the same gate and atomic one-shot reservation.
If the future trigger races, only one actual execution is admitted. Bare `jobs`
requiring a verb is an invocation difference, not a missing management operation.

H049 can be rolled back with its CLI/test/docs change independently. H015 will
form a separate source commit with schema additions designed to leave existing
rows readable; preserve owner data on rollback. Frontend/mobile gaps must be
recorded when API capabilities are added. No native/live-provider claims.
