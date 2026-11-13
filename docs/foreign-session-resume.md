# Resume and foreign conversation import

Local development candidate, 2026-10-10. This extends the existing free recap;
it does not call a model to summarize a conversation.

`nerva chat -c "next request"` selects the most recently active unarchived
conversation. `nerva chat -r SELECTOR "next request"` accepts an exact ID, a
unique ID prefix, an exact title with normalized whitespace/case, or `latest`.
An exact ID named `latest` wins for `-r latest`; `-c` always means latest mode.
An ambiguous selection refuses with candidates and sends no chat request.
Exact selection can reopen an archived conversation without unarchiving it.
These flags are mutually exclusive with `--session`.

Selection uses the whole session store and does not change the hub's shared
active conversation. The chat request carries the resolved ID explicitly.
`nerva sessions continue` remains the separate operation that creates a new
compaction generation. There are no per-terminal breadcrumbs or expiry timers.

The recap shows the last ten exchanges and collapses tool calls to their names.
In one-shot `-z` mode it goes to stderr; stdout remains the final answer. Chat
does not prompt on a terminal to choose between sessions. JSON mode remains
structured output.

## Import from the CLI host

`nerva sessions import --from claude PATH.jsonl` and
`nerva sessions import --from codex PATH.jsonl` read an explicitly chosen local
file. `nerva chat -r @claude "next request"` and `-r @codex` discover files under
the CLI user's `.claude/projects` or `.codex/sessions` directory. An optional
`:EXTERNAL_ID` selects a source conversation; ambiguous discovery refuses and
asks for an explicit source file. These aliases import a transcript; they do
not choose a model or provider for the new answer.

Only bounded user/assistant text and tool names are imported. System/developer
messages, hidden reasoning, tool arguments/results and media are omitted.
Unreadable, changing, symlinked or oversized sources refuse. The source reader
currently caps files at 2 MiB, 2,000 lines and 100 imported turns, with at most
32,768 characters per turn. It reads local files and makes no provider call.
These limits are deliberate refusals, not silent whole-file truncation.

The owner-authenticated CLI sends canonical text to `POST /sessions/import` on
a loopback hub; this importer refuses remote hub URLs.
The server commits the session, immutable seed, instance, clock and import
receipt together in SQLite, and reads the result back before returning success.
Repeating the same source ID and canonical content returns the same local
session; changed content creates a new import. A request ID cannot be reused
for different content. Source attribution is an owner-attested claim, not a
vendor signature. Personal source paths are not stored in the hub receipt.

## Access and history integrity

`POST /sessions/resolve` and `POST /sessions/import` require owner access.
Imported and derived conversations are owner-only at chat, stream, resume,
active memory, checklist and session-stamp boundaries. Guest session and recent
checklist lists omit them. Ordinary native sessions retain their existing access
rules.

Foreign history is presented to models as escaped untrusted data. Resuming it
does not authorize any instruction found in the transcript: actions derived
from it carry recall taint into the existing Action Kernel approval boundary.
Continuation, rewind and compression preserve its provenance. Corrupt or missing
required lineage refuses instead of treating imported history as native.
Once a snapshot write is attempted, a durable receipt marker prevents an absent
later snapshot from silently restoring the original import and losing replies.
Selected-image turns currently refuse foreign history; ordinary native image
turns retain their existing behavior.

Shared automatic embeddings, reflection and learning must not promote this
private history or its derived replies into common persistent facts. Those
promotion paths omit imported/derived sessions until private provenance and
access can be carried through the destination store.

The existing HUD Sessions recap remains available. This candidate adds CLI/API
import and selector entry points; it adds no browser or native file picker.
Claude Code and Codex source discovery is host administration. Native-device,
Windows file-opening and live-provider acceptance are not claimed.

## Retained current conversation text

The owner can preview redacted retained user/assistant text with
`GET /sessions/{session_id}/transcript`, or request the same JSON as an attachment
with `?download=true`. Responses use `Cache-Control: no-store`. The scope is
`retained_current_history`: it excludes system messages, tool payloads, media,
compacted archives and deleted or rewound turns. The endpoint uses the exact
addressed session without changing the active/default session. Missing, busy,
unverifiable or oversized history refuses the request rather than reconstructing
a transcript. The projection accepts at most 100 retained turns and 2 MiB of
compact UTF-8 JSON before and after secret redaction. Redaction uses the existing
secret scanner; it does not promise removal of arbitrary personal information.

`nerva sessions transcript SESSION_ID` prints one validated JSON document.
`nerva sessions transcript SESSION_ID --out FILE` creates a private file only if
the destination does not exist; files, directories and symlinks are never
replaced. File publication requires secure private-file and hard-link APIs and
fails closed if unavailable. Use stdout where secure file export is unsupported.
`nerva sessions export` continues to export opt-in training trajectories.
In the browser Sessions panel, preview explicitly reads retained text without resuming
the session. Text is escaped, and closing or changing the session view invalidates
pending private responses. Download JSON streams with a header token when browser
file saving is supported; owner-session downloads report the request, not a
verified save. Native mobile transcript controls remain open; H005 stays partial.
