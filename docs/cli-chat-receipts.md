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

Ctrl-C exits 130 and attempts an interrupted receipt, including when it arrives
while preparing input or printing a decoded response. Already observed session,
usage, stop and queued-approval details remain available. An interrupt cannot
retract text already written to the terminal.

The hub attaches a request-owned `nerva.turn.usage.v1` snapshot to `/chat` replies
and `/chat/stream` end events. The CLI validates it before copying its usage fields
into the receipt. Missing, malformed or legacy snapshots leave those fields null
with `usage_basis` and `cost_basis` set to `unavailable`. Image turns still use the
separate vision endpoint and do not supply this chat snapshot.

Authentication and early owner/session checks retain their HTTP error codes.
When they refuse before a collector returns a snapshot, the CLI still writes a
failure receipt with unavailable usage. A deterministic synthesis fallback can
return completed specialist answers; its failed generation attempt still leaves
usage unknown if the provider supplied no complete counters.

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

## Questions the turn asks while it runs (H226)

Run from a terminal (stdin not piped), `nerva chat` answers the turn's own prompts
right where you are, while the turn waits:

- **A question (clarify).** The question and its numbered choices appear on stderr.
  Type a number, a label, several numbers separated by commas when it allows more than
  one, or your own answer. `/cancel` (or an empty input at end of file) declines and the
  turn goes on without an answer. A batch of questions is asked one at a time; each
  answer goes to its own question once. Your answer reaches the same turn as data the
  model must not obey, exactly like an answer typed in the HUD, and it raises the
  turn's taint, so an action built on it still asks for approval.
- **A missing secret (an API key).** The turn names the secret and why it needs it. The
  value is read without echo and sent only to the hub's secret store (the route the
  HUD's Secrets panel uses); the conversation receives the name and its
  `{{secret:NAME}}` handle, never the value. Nothing is printed, logged or written to
  the receipt. An empty line declines. Only the owner is asked: a terminal holding a
  user token, not the admin token, is never offered a secret prompt, and the store
  refuses it. A hub reached over plain http on another machine is never sent a secret.
  The turn can ask only for an upper-case key name (`WEATHER_API_KEY`) that a skill you
  installed and vouched for declares as required — never a provider key, a hub token or
  a key a Nerva component keeps (house, camera, peer and connector keys) — and never once
  it has read a web page, a tool result from outside or another untrusted message. A key
  your administrator manages, or any key in managed mode, is refused. A key already held,
  in the store or in a vault source, is not asked for again.
- **What is Nerva's and what is the turn's.** Lines Nerva prints start at the left edge.
  Everything the model or the turn wrote (a question, a choice, a reason, a card's
  title or command) is shown behind a `│` bar, with direction-changing and invisible
  characters removed, so it cannot pose as a Nerva prompt. Nerva asks for a key only
  with its own `! Nerva needs the key NAME …` line followed by a prompt that does not
  show what you type; an answer that looks like a key or token is never sent as an
  ordinary answer.
- **Approvals (confirm and sudo-class commands).** In Nerva these are approval cards: a
  turn that needs one queues it and stops. After the answer, `nerva chat` shows each
  card the turn queued (tier, reversibility, the exact command or path, the rollback
  plan) and asks `[a]ccept, [r]eject, [d]efer, or Enter to leave it queued`. The
  decision goes through the same admin route as the HUD and `nerva approvals`; there is
  no batch accept, and a terminal without the admin token leaves the card queued.

A script never sees any of this: with stdin piped, `--json`, or `--no-prompts`, nothing
is read from the terminal and the exit codes above are unchanged.

Questions and secret prompts need the clarification preview to be on:
`nerva config set channels.pending_inputs_enabled true`, then restart the hub. It is
off by default; while it is off the model has no `clarify` or `request_secret` tool.

## The interactive chat: `nerva chat -i` (H224)

`nerva chat -i` keeps a conversation open on the terminal. It needs a terminal on stdin
and stdout, writes no receipt, and refuses the scripted-turn flags (`MESSAGE`, `-f`, `-z`,
`--json`, `--usage-file`, `--image`, `--no-prompts`). `--session`, `-r`/`-c` (the hub's
own sessions), `--agent` and `--reasoning` apply to every turn. It is built on GNU
readline from the standard library.

| Key | What it does |
|---|---|
| Enter | send |
| Alt+Enter, Shift+Enter | new line in the message. Shift+Enter works only where the terminal sends it as its own sequence (kitty and other CSI-u terminals, xterm with modifyOtherKeys). A trailing `\` also continues the message. |
| Ctrl+C | 1) clear the draft; 2) on an empty draft while a turn runs, stop it; 3) when idle, arm exit, and a second press within 3 s leaves |
| Ctrl+D | leave (on an empty line) |
| Ctrl+X Ctrl+E, `/edit [text]` | compose in `$VISUAL`/`$EDITOR`. The editor is run without a shell on an owner-only (0600) temporary file, which is removed afterwards; the saved text becomes the draft |
| Ctrl+L | redraw |
| Esc Esc | discard the draft (Ctrl+Y brings it back) |
| Tab, Shift+Tab | cycle completions: the slash commands this credential may run (`GET /api/commands`), the client commands below, and `@file:` references as the hub writes them (`GET /api/context-refs`; a path with a space comes quoted). The hub gets 1 s to answer; an unreachable hub is not asked again for 30 s, so Tab never hangs. A name holding a control, bidi or zero-width character is not offered |
| Up, Down | history |
| paste | bracketed paste: a multi-line paste is one message |

Client commands, never sent to the hub: `/edit`, `/image PATH` and `/paste-image` (the
next message goes to the vision model with the image, as `--image` does), `/switch`
(list your sessions, then `/switch N`, `/switch <id>` or `/switch new`), `/model` (the
hub's local models; switching uses the owner's admin route, so a user token is told
no), `/queue` (messages typed while a turn runs wait here: `/queue drop N`,
`/queue clear`), `/keys`, `/exit`. Any other line, hub slash commands included, is sent
to the hub. During a message continued with a trailing `\`, Ctrl+X Ctrl+E and `/edit`
open the whole draft in the editor and `/exit` discards it: none of them sends the
half-written message.

**Stopping a turn.** Ctrl+C calls `POST /chat/interrupt` for the turn that is on the
wire, named by the session it was sent to (still that one after a `/switch`) or, for the
first turn of a chat that has no session yet, by the turn id the client sent in the
`X-Nerva-Turn-Id` header of `POST /chat`. A request that names neither is refused (422):
there is no "stop everything". The hub stops only turns started with the same credential
as the caller. The stopped turn answers *Interrupted. Nothing more was done for this
message.* with a `turn_interrupted` notice: a step that was already running may still
finish, nothing after it is started, and a step already done is not undone. Questions
that turn had asked are dropped. Messages you queued during it are held: Enter sends
them, `/queue clear` drops them. An image turn cannot be stopped this way. An older hub
without the route says so, and the turn runs to its end.

**Switching during a turn.** `/switch` while a turn runs takes effect at once for the
next message; the running turn finishes (or is stopped) in its own conversation, and its
reply does not switch you back.

**History** is kept in your own config directory, not the hub's data folder (so it is
in no hub backup): `$XDG_CONFIG_HOME/nerva/chat_history.jsonl`, else
`~/.config/nerva/chat_history.jsonl`; `%APPDATA%\Nerva\chat_history.jsonl` on Windows,
`~/Library/Application Support/Nerva/chat_history.jsonl` on macOS. It is owner-only
(0600), the last 1,000 messages, multi-line messages kept whole, and never followed
through a symbolic link. A line that looks like a key or token, or that states a
password, passcode, passphrase or PIN in plain words ("my pin is …", "password: …"), is
never written. To keep no history: `--no-history` for one chat, or
`NERVA_CHAT_HISTORY=off` (also `JARVIS_CHAT_HISTORY`) in your environment for every chat.

Questions a turn asks while it runs, and the approval cards it queued, are shown when
they arrive; press Enter to answer them (the same prompts as above). Not available:
Up/Down through a completion menu (readline has none), detecting an image pasted with
Cmd/Ctrl+V, and the mouse. With macOS's libedit Python only Tab completion is bound,
and without readline (Windows) the prompt is plain input.
