# Pending input completion batch — 2026-10-05

H067 remains partial. This batch closes previously started workspace confirmation,
batch clarification, ephemeral transport and restart paths; it does not claim
all 697 capabilities, live accounts, or a fresh whole backend/frontend milestone.

The pure choice/batch functions are copied from pinned Hermes tools/clarify_tool.py;
only modern Python annotations and the async Nerva callback loop are adapted.
MIT attribution remains in module headers and the existing donor license file.
The real ToolRPC/gateway accepts three questions, maps decorated choices to bare
answers, preserves completed answers on timeout and never sends invalid batches.

Slack/Discord owner commands require explicit channels.owner_senders identities:
Slack team:user (for example T1:U2), Discord decimal user ID. Active pairing is
also required; pairing alone grants no owner authority. Setting preview enable
still controls pending producers. Real signed native delivery and kernel
permission.grant tests cover cancel/once/always, durable history preservation,
owner/pairing revocation and transport replacement. Always remains pending until
the owner approves the distinct durable grant; no local per-chat flag widens it.

Temporary replies carry their TTL through signed channel.reply payloads (at most
one day, zero keeps them). Slack/Discord delete only acknowledged bot-produced
message receipts; shutdown and generation replacement fence delayed cleanup.
Telegram Other callbacks explain typed fallback even if edit and instruction
messages fail. Stop cannot reopen a pending runtime; explicit start reopens the
persisted route index and Telegram HTTP/deletion lifecycle, retaining history.

Integration: 1,277 cases passed, zero failures/errors/skips. A later localized
Telegram restart correction has its own final-transport XML; counts overlap.
Earlier source hashes are retained separately from the final manifest. No test
was weakened: real cwd, durable history and permanent-grant assertions remain.
Ruff and diff-check pass. Bandit reports one inherited LOW empty-token default;
strict source scan reports the inherited empty GA4 property setting (AST value
length0). The proof scan matches eight entries in the public file-path/SHA256 manifests;
these are not credentials. No scanner baseline changed and no actual credential
was identified.

Remaining acceptance: larger native prompts need digest-bound content references
within the signed kernel envelope; producers outside these three chat transports
need their real entry points. Full milestone verification and broader H277 work
remain open. Everything is local and uncommitted.

## Typed ntfy continuation

The real subscription now reads typed answers while its serial model turn waits.
Prompts and notices cross the existing signed reply queue. HTTP acceptance,
configuration, pairing and live binding checks precede human-wait credit.
Once/Always/Cancel use durable history and the governed permission executor;
standing consent is scoped to the server and topics. Hermes text-only own-answer
behavior is adapted without changing native choice semantics.

19 new cases;619 earlier affected and126 final cases pass. Counts overlap and
the619 stage predates the localized consent/own-answer corrections. The final
probes cover them plus actual Slack/Discord SDK/RPC regressions and vault/config
startup impact. See ntfy-report.json, exact JUnit artifacts and ntfy-scoped-inputs.
Strict frozen-source scan and scoped Bandit/Ruff pass. This is not a full-suite,
provider or697 completion claim. Other typed producers and busy-control paths
remain open.

Use the existing private ntfy server/topic configuration and opt-in inbound
subscription. Pair the receive topic through the existing pairing controls.
Enable Settings → Channels → Chat clarification preview and restart the hub.
For history commands, set Command owners JSON to {"ntfy":["your_receive_topic"]};
the configured receive topic is the identity, not a publisher-supplied sender.
Ordinary paired users can answer clarifications; history changes require the
explicit owner mapping. ntfy retains ephemeral notices because it has no delete
transport.

Explicit cancellation continuation:261 affected cases pass on the final source
with6 new actual-path cases. Whole /cancel and !cancel release a delivered
clarification across Telegram/Slack/Discord/ntfy without another model call or
rate debit. Wrong sender/topic, command suffixes and FIFO neighbours remain
isolated. A choice named Cancel still selects that option. Evidence:
`cancel-report.json`, `cancel-scoped-inputs.json`, `cancel-result.xml`.
The ntfy settings source scan has one inherited generic-api-key finding at
settings_db.py385: empty GA4 property declaration verified through AST and
unchanged preimage. It was not suppressed. H067 remains partial.

Authenticated streaming HUD continuation: enable the existing Chat clarification
preview and restart. A model clarification opens choices, multiselect, Other/
free text and cancellation in the live chat. The same user credential answers
through /chat/pending/{prompt_id}/answer; another token, stale ID or untrusted
channel identity cannot answer or create this producer. Failed answers stay for
retry. Stop/disconnect, expiry and credential revocation retire the wait.
Proof: web-report.json, web-scoped-inputs.json, web-build-inputs.json and three
web-*-result.xml files.344 backend,60 HUD and54 contract cases pass (overlap).
Nonstream HTTP, email/CLI and busy prose/other commands remain open. H067 partial.

Nonstream HTTP continuation: with Chat clarification preview enabled, POST /chat
can now wait on ToolRPC clarify. While that request remains open, the same
credential polls GET /chat/pending, optionally scoped by session_id (offset/limit
bound the page), then posts the selected answer to the existing answer route.
The discovery response contains questions and has_more; each question contains
id, session_id, question, choices and multi_select. Read another page by advancing
offset; answer one question and poll again for a consecutive batch question.
Use the same token and session throughout. No new model request is necessary.
GET is no-store and response completion acknowledges delivery. A failed body send
does not admit an answer; missing/other/revoked tokens, expiry, cancellation and
actual disconnect events are covered by offline production-path tests.
CLI/email question handling and busy prose/other commands are still open.
See http-poll-report.json and http-poll-*-result.xml for this continuation.

Final gateway acceptance: H067 is now equivalent against its frozen gateway
contract, with354 final affected and173 additional contract cases passing.
The fixed inventory and the earlier Completion batch plan make CLI/HUD separate
contracts; later notes incorrectly added them as H067 completion gates. The
canonical requirement covers clarify-by-next-message, typed/native three-way
confirmation, destructive history confirmation with governed durable opt-out,
and ephemeral notices. These are integrated and verified on the supported
gateway transports. CLI/email extensions, live accounts and the full697
milestone remain separate open work. See gateway-acceptance-report.json and
gateway-contract-result.xml. Historical partial checkpoints above are retained.
