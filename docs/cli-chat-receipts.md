# CLI chat receipts

Use `nerva chat --usage-file run.json "your message"` to save a machine-readable
receipt. Add `-z` for scripted execution: a completed answer exits 0; an incomplete
turn exits nonzero and does not print an answer to stdout.

The JSON uses `schema: "nerva.chat.usage.v1"` and is written atomically. It records
the exit code, completion status, timestamps, refusal reason and any pending
approval IDs. A queued approval remains queued; the receipt does not approve it.
A failure to write the file warns on stderr without changing the turn's outcome.

## Requested and observed sessions

- `requested_session_id` records the `--session` argument, or null when absent.
- `session_id` records the valid session ID returned by `POST /chat`, or null when
  the hub did not supply a usable ID. It never falls back to the requested value.

For example, a `/new` turn requested in `topic-a` may select a new session. The
relevant fields in its receipt can be:

```json
{
  "schema": "nerva.chat.usage.v1",
  "status": "completed",
  "completed": true,
  "session_id": "session_new_topic",
  "requested_session_id": "topic-a"
}
```

Use `session_id` to correlate with the session the hub reported. Use
`requested_session_id` to correlate with the request, including when the hub was
unreachable or the request was interrupted. A valid returned ID remains available
for refused or approval-queued chat replies too; session attribution and turn
completion are separate facts.

Missing or malformed response IDs are left null, without trimming or coercion.
Older hubs that omit the field cannot confirm a session through this receipt.
Errors before a decoded chat response also leave it null. Image turns use the
separate vision endpoint and have no observed chat session; `--session` remains
unsupported for an image turn.

Every receipt produced by this version includes `requested_session_id`, even
when null. Older v1 receipts without that key used `session_id` as a caller echo;
do not reinterpret those historical values as hub-confirmed IDs. No stored
receipt is migrated. Tools that previously used `session_id` to recover the
request argument should read `requested_session_id` in new receipts.

## Completion and generation usage

The hub carries source-assigned tool-loop stops in `runtime_stops`, independently
of the final response wording. A specialist's deadline, iteration limit or other
known stop therefore remains incomplete after synthesis rewrites its reply. The
exact thinking-budget exhaustion sentinel is recorded before synthesis too.
Terminal agent timeouts, generation failures, policy refusals and continuation
refusals also carry source-assigned reasons; exception text is not telemetry. Any
known stop, malformed present stop metadata or queued approval prevents one-shot
success and keeps stdout empty. An empty stop list does not prove success: existing
empty-answer and refusal checks still apply. Older hubs that omit this metadata
retain the limits of text-based classification. Interactive chat retains its
normal stdout and exit behavior, while its receipt can report incomplete.

The hub attaches a request-owned `nerva.turn.usage.v1` snapshot to `/chat` replies
and `/chat/stream` end events. The CLI validates it before copying its usage fields
into the receipt. Missing, malformed or legacy snapshots leave those fields null
with `usage_basis` and `cost_basis` set to `unavailable`. Image turns still use the
separate vision endpoint and do not supply this chat snapshot.

`api_calls` counts accepted generation HTTP dispatch attempts, including retries,
specialists, streamed generation, synchronous response-producing auxiliary calls
and synthesis. It is not a count of successful answers or proof of provider billing.
Control probes, embeddings, audio, background title generation, background review
and cache-management jobs are outside this generation receipt.

`input_tokens` includes ordinary input and cache-read/write input; `output_tokens`
is the provider's output count. Both require complete, valid usage from every
accepted attempt. An earlier retry without usage makes aggregate tokens and cost
unknown, even if a later attempt succeeds. Generation through an unobserved path
also stays unknown. These fields remain independent of session attribution and
whether the turn completed.

| Basis | Meaning |
| --- | --- |
| `usage_basis: measured_zero` | The observed command invoked no generation. Calls and tokens are zero. |
| `usage_basis: provider_complete` | Every counted attempt supplied complete provider counters. |
| `usage_basis: unknown` | Some usage or generation observation is unavailable; token totals are null. |
| `cost_basis: measured_zero` | The observed command invoked no generation. |
| `cost_basis: local_zero` | Complete counters and positive local route/provider evidence; no metered provider cost. |
| `cost_basis: price_table` | Estimate from the exact model's repository rates, dated by `price_verified_at`. |
| `cost_basis: unknown` | No trustworthy complete estimate; `estimated_cost_usd` is null. |

Repository rates are estimates, not invoices. Unsupported cache-write premiums,
known Gemini Pro contexts above 200,000 input tokens, unknown models and ambiguous
model identity do not receive a numeric estimate. A model name that resembles a
local model cannot establish zero cost on a remote route.

`provider` identifies the HTTP backend adapter and `model` the selected model
confirmed against its request selector. They do not attest which weights a remote
proxy actually served. Mixed provider/model pairs leave the scalar identities
null and appear in `breakdown`, capped at 16 rows; `breakdown_truncated` reports
omitted rows. The top-level totals still cover all observed attempts unless a
collector bound is exceeded, in which case they become unknown. No prompt, tool
argument, credential or endpoint URL is copied into this telemetry.
