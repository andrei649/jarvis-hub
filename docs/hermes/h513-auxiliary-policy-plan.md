# H513 auxiliary request policy

Status: implemented and integrated, 2026-09-27. The full backend milestone passed
18,838 tests with 35 skips and no failures; [exact evidence](evidence/chat-outcomes-auxiliary-integration-2026-09-27.json)
retains the initial failures, repairs and verified source hashes. Base/head:
`bd2bb70ead1b493043a335e77713fc42c47d4013` plus preserved
local sprint changes. Goal: apply the existing actual-provider data policy to
session titles, recall query rewriting, background/on-demand review and context
compression. Next action: cover acquisition and presence direct calls, retaining
their current selection and validation rules. No publication or paid provider calls.

## Scope and contract

These four orchestrator paths select `router.local_backend` directly. Selection
stays unchanged, with no new fallback provider. A local adapter configured outside
loopback resolves to unknown data handling; it must require the owner's existing
audited scope acknowledgment before these unattended requests. A background task
can inherit an interactive owner's context, so authorization must explicitly use
an internal principal and generated origin rather than the ambient turn identity.

Add a shared context manager in `agents/core/llm/data_handling.py` which checks
`authorize` before dispatch and binds the same fresh callback through
`physical_request_scope` for the full awaited generation/stream. Capture the
actual backend and model, never cached consent. Recheck every physical request,
including retries; copied child requests after scope closure fail closed. Call
`authorize` directly so the base LLMRouter is covered too. This does not expand
the scope around ToolRPC, model selection or unrelated asynchronous work.

Wire only `_session_titler`, `_query_rewriter`, `_review_llm` and
`_compression_summarizer`. Preserve token limits, Qwen switches, streaming idle
limits and each existing degraded outcome: first-word title, original query,
skipped review, deterministic compression digest. Retain existing job-pin
exclusions and add the missing review exclusion. Keep warnings visible after
acknowledgment. Update the coverage string truthfully; judge/VLM/embeddings and
other independent clients remain outside this slice.

## Ownership and verification

One writer owns data_handling.py and helper tests. A second owns only these
orchestrator integration methods and their tests, after the H487 writer freezes
that file. The coordinator owns this plan, evidence and integration. No other
configuration, provider selection or settings API changes are required.

Demonstrate refusal before I/O for unknown endpoints with copied owner context,
fresh revocation between physical retries, swallowed refusal propagation,
stream/background lifetime closure, all four job-pin exclusions, loopback
success and preservation of documented fallbacks. Use synthetic backends with
explicit provider profiles/loopback endpoints; do not weaken the guard for mocks.
Run focused title, query rewrite, review, compression, job-pin and H513 suites.
Broaden only for failures or the next integration milestone.

Rollback removes these four new scopes and their helper without modifying
existing provider configuration, consent, transcripts or queued tasks. H513 stays
partial until its other direct-client consumers and acceptance gaps are covered.
