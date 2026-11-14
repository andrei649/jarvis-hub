# Domain specifications: selecting the next bounded behavior

Use `catalog/index.json` only to locate an ID, then `taskpack.py show Hxxx`.
Every contract card contains the original requirement, governance, recorded
remaining clauses, existing files/tests and earlier design documents. Historical
text must be reconciled with the pinned/current code before assignment. The
table below defines the acceptance floor for a new packet; it does not silently
mark a whole domain ready.

| Area | Product outcome to slice | Integration boundary to keep | Required acceptance beyond the happy path |
|---|---|---|---|
| cli | One discoverable command completing one owner operation | Existing `agents/cli/nerva.py` parser plus domain handler and existing service/API; no second authority path | Real subprocess help/exit/JSON, absent optional dependency, invalid args and denied actor; no secret stderr |
| gateway | One command/message carried from ingress to the correct session | Gateway actor/channel/session binding, shared command catalog, transport wrapper | Wrong principal, group/private scope, cancellation, reconnect, duplicate delivery and shutdown with pending work |
| platforms | One channel flow delivering exactly the authorized content | Existing adapter and outbound gate; provider response parsed before receipt | Ambiguous send is not retried as safe; rate limit, late reply and revoked identity; live acceptance separate |
| web | One mounted workflow from an actual button to a result | Existing fetch/auth/session client and server schemas | Loading/empty/refused/error; account/session switch invalidates pending private response; no raw error/HTML injection |
| desktop | One native action or permission-dependent flow | Tauri/host driver and governed backend, not a new direct host shortcut | Unsupported OS refusal, permission denied, app restart and real OS probe; mock driver alone does not close acceptance |
| tui | One terminal interaction with truthful feedback | Existing event/turn lifecycle and terminal output policy | Non-TTY, NO_COLOR, TERM=dumb, resize/Unicode, control-character input and cancellation |
| config | One persisted option with unambiguous precedence | Existing settings schema, managed scope and credential store | Invalid type, missing/default, revision conflict, migration/reload, secret projection and pinned value |
| env | One typed environment option used consistently | env_config and alias/provenance rules, not new os.getenv families | Both NERVA/JARVIS spellings, precedence, malformed boolean/number and no raw-read growth |
| tools | One real tool outcome through registered dispatch | Schema, action classification, Kernel, revocation and bounded return | Unknown args, denied actor, timeout, cancellation, late completion, honest unavailable backend |
| skills | One owner skill lifecycle operation | Existing user root, package scanner, digest and explicit admission | Collision, malicious instructions, changed package between review/use, revocation; downloaded bytes stay staged |
| providers | One adapter/route capability with real request accounting | Model selection, H513 physical-request policy and strict-local routing | Missing credential, unconsented cloud, empty output, bounded retry and request identity; fake response vs live clearly separated |
| agent-core | One turn-state transition | Shared orchestrator/agent pipeline, actual callback and persistence contracts | Falsey/sync/async callbacks, cancellation, late tool result, blank answer, exactly one terminal outcome |
| memory | One scoped read/write/retrieval outcome | Existing provenance, taint, user identity, retention and permission controls | Cross-owner rejection, deletion/rewind fences, stale index, import conflict and no secret/context leakage |
| automation | One job or worker lifecycle result | Existing durable queue, approval, worker claims and receipts | Repeated dispatch, crash/lease expiry, ambiguous side effect, literal script output and genuine AI silence |
| security | One documented trust-boundary repair | Trusted policy, identity, consent, secrets and fail-closed boundary | Negative/adversarial regression for the actual path plus compatibility; no blanket suppression or self-authorized policy weakening |
| media | One selected input-to-artifact workflow | Exact source identity, bounded bytes, provider consent and private storage | Wrong/missing source, oversized/invalid input, revoked grant, late response and redacted export |
| editor-acp | One protocol interaction with a useful editor outcome | Existing ACP session/transport boundary | Request correlation, cancellation, malformed payload and disconnected client; no hidden second execution channel |
| mcp | One host/server/client operation | Scoped OAuth, host requests, explicit reload and tool authority | Expired/revoked token, late elicitation, replay, unavailable server and cancellation without lost ownership |
| agent-interop | One authenticated inter-agent exchange | Peer identity, signature, permission and message provenance | Replay/tamper, unknown peer, cross-principal scope and bounded duplicate recovery |
| extensions | One installed extension command/tool lifecycle | Package hash, grant revision, lazy startup and loadset | Revoked/regranted same digest, stale handler, unload during await, persisted metadata failure and no boot-time execution |
| feature-pages | One advertised feature usable through the normal entry | Reuse the implementation packet of the underlying capability | Actual UI/CLI journey plus absence/error states; documentation or endpoint counts alone are insufficient |
| user-journeys | One complete owner task across surfaces | Existing scenario fixture, identities and lifecycle | Fresh install/settings, retry/recovery and return-to-task; list which platform/provider was actually exercised |
| upstream-delta | One pinned upstream behavior adapted to Nerva | Exact upstream revision/license and existing architecture | Equivalent normal/refusal behavior without copying incompatible authority assumptions; platform claims require platform evidence |

## Interface decision checklist for the coordinator

For each residual clause answer these before a small model starts: exact entry
point; input and output types; authoritative actor and scope; persistence owner;
idempotency/replay behavior; cancellation/timeout result; error status and UI copy;
which existing test becomes red; what constitutes actual usable success. If any
answer changes a shared protocol, retain `needs_design` until reviewed.

Do not require every packet to deliver every interface at once. A narrow CLI,
web or mobile slice can ship independently if the remaining parity gap is named
and no existing caller is broken. A new mandatory API field must update all
existing callers in the same coherent packet, or use a reviewed compatibility path.
