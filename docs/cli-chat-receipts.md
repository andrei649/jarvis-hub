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

## Completion and unavailable usage

The exact thinking-budget exhaustion reply reports an incomplete turn, including
when wrapped with a specialist label. Arbitrarily rephrased model replies still
have the existing limits of text-based classification. Interactive chat retains
its normal stdout and exit behavior, while its receipt can report incomplete.

Per-turn model/provider, token counts, API-call counts and estimated cost remain
null with `cost_basis: "unavailable"` until the CLI obtains attributable values.
Null is not a measured zero. These fields are independent of session attribution.
