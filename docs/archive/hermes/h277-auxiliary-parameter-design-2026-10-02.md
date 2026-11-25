# H277 local auxiliary parameter recovery

Goal: advance full pinned-Hermes parity by recovering real unattended local text
calls when the selected model rejects temperature. Base/head before edits:
cd2aa666ed0a690e9bf9138747b95c15ffe9ee37. Branch:
codex/h277-auxiliary-recovery-20261002. Generated 2026-10-02.
Reference: Hermes59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e,
agent/auxiliary_client.py:_parameter_rungs and _ladder_parameter_rungs.

Selected bounded approach: retain the existing backend and H513 guards, adding
an operation scope bound to the exact backend object and selected model. The
five nonstreaming auxiliary producers enter that scope; LMStudioBackend._post_chat
may strip only temperature after an actual HTTP400 response whose bounded
structured error identifies that parameter as unsupported. Accept exact code/param
or a bounded error.message naming temperature with explicit unsupported/unknown/
unrecognized markers, not an arbitrary exception string. Do not log response text.
An error naming a different structured param cannot be overridden by message text.

The initial request and caller-owned payload remain unchanged. Title/rewrite first
send retains temperature0 and /no_think; on the explicit rejection only, omitting
temperature deliberately selects the provider default. This is an intentional
exception to the earlier exact-zero-temperature claim, not preservation of it. Retry uses a copied payload,
same client/model/prompt/output-token cap, and the existing fresh physical H513
check. Each call allows one temperature repair and the existing one model-unloaded
repair, in either order, with at most three sends. No policy/guard/cancellation,
timeout, authentication, payment, malformed JSON, oversized error or unrelated
status is a parameter-recovery signal. No retry after a second rejection of the
same kind. Closed/inherited scopes must not authorize late recovery.

This is not generic backend fallback: ordinary conversation/tool calls and streamed
compression retain their existing behavior. No credential rotation, provider
change, token-limit removal, settings/API route, dependency, global cache or live
provider call. SDK/provider discovery, other parameter repairs and empty-output
recovery remain required follow-up, not redefined away.

Alternatives rejected for this batch: a video parameter helper has no real caller
because its payload currently has no temperature; generic exception-string retry
would blur the boundary between provider rejection and guard denial. Rewriting
all adapters would expand an independently reversible compatibility change.

Owned implementation: agents/core/llm/auxiliary_recovery.py (new),
agents/core/llm/auxiliary_text.py, agents/core/llm/base.py,
tests/test_h277_auxiliary_parameter_recovery.py (new). Coordinator owns records.

Plan: (1) red tests at actual producers with native offline HTTPX transport;
(2) implement scoped typed recovery; (3) focused regression covering auxiliary,
acquisition, unload, H513 and strict-local dispatch; (4) independent bounded review;
(5) inspect affected Hermes evidence and update truthful records, then freeze source
and run full backend once serially. Retain socket and90-second test guards.
Acceptance includes both repair orders, hard send caps, unchanged token caps,
revocation before retry, swallowed denial, scope cleanup/nesting, no global cache,
provider-body sanitation and no recovery outside the five intended producers.

Standing owner autonomy supplies design/implementation authority. Local only:
no push, merge, deployment, credential import or paid/provider calls. Rollback:
revert this coherent local feature commit; existing work/history stay preserved.
