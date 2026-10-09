# H067 Telegram ingress — partial local checkpoint

Goal: all697 original pinned Hermes capabilities. Head
a7ffad6676cfb28e7ac374d495b4a5889e5f4646; generated2026-10-05.
Preserved dirty local worktree; no staging, commit, publication or deployment.

850 affected/RPC tests passed with no failures/errors/skips and zero drift across
2037 frozen Python/contract inputs. Three review findings each failed before their
fix and passed afterward. Ruff, scoped Bandit and the strict eight-file source scan
passed. Report.json records raw hashes, bounded review and metadata verification.

The actual Telegram polling/chat-lane code now resolves a delivered clarification
without queuing behind its waiting turn or spending a new-model-message rate slot.
Fresh pairing, group authorization, sender/topic and inbound origin/principal still
precede resolution. Edited/forwarded/media input remains ineligible through normal
fallback and mixed batching. Claimed Decision Inbox reasons keep precedence;
rate-rejected prose does not cancel a waiting question. Production startup wires
the two pending-only hooks explicitly. Ordinary messages retain rate/batching/order.

Tests use a stub model, synthetic getUpdates pages and controlled delivery; no live
Telegram/provider acceptance. Default-off preview remains. An invalid-selection
retry awaits its bounded transport send in polling; this is not asynchronous retry
delivery. Full backend/frontend evidence is still the earlier H063 snapshot.

Next: native clarification cards/Other/multi-select, destructive new/reset/undo
confirmation, owner/generation/session-lease fencing and real governed persistent
Always. CLI/HUD/other chats, governed workspace receipts and ephemeral command
memory bypass remain open. Then full integrated suites and current H277 original49
mutation/kernel/provider work. H067 remains partial; the697-capability goal is active.

Seven collateral pins matched the immediate preimages and were reviewed/refreshed.
105 already-stale collateral pins were preserved, with no verdict upgrades. The
previous [groundwork checkpoint](../2026-10-05-pending-input-groundwork/README.md)
is historical evidence rather than a claim about these later sources.

## Paths changed

| Path | Rationale |
| --- | --- |
| agents/core/channels/gateway.py | Pending-only route before model rate admission |
| agents/core/channels/telegram.py | Pre-lane/group-authorized ingress, reason precedence, batch eligibility |
| agents/core/channels/pending_input_runtime.py | Non-mutating early preflight for prose/commands |
| agents/core/orchestrator.py | Inbound origin/principal binding and pending-only resolution |
| agents/web.py | Explicit production hook wiring |
| tests/test_pending_input_ingress.py | Polling, saturated rate, authority, fallback, batching and review regressions |
| tests/test_telegram_pairing_shared_store.py | Real lifespan wiring assertions |
| docs/hermes/pending-input-plan-2026-10-05.md | Recorded ingress contract before implementation |
| docs/hermes/assessment.json | H067 stays partial; bounded current preimage refresh |
| HERMES_STATUS.md, docs/HERMES_CAPABILITIES.md | Generated697-row status |
| This directory | Sanitized results, frozen inputs, review and scope limits |

Rollback uses localized reverse diffs against the ingress preimages under /tmp;
never restore full shared files over inherited changes. Source/report pins must
be reassessed after subsequent edits rather than blindly refreshed.
