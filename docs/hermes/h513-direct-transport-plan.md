# H513 composer and approval-judge direct transport

Generation: 2026-09-27. Base/head:
`bd2bb70ead1b493043a335e77713fc42c47d4013` plus local sprint changes.
Goal: close the recorded environment-proxy gap for composer vision and approval
judging. This is a proposed bounded next slice; implementation starts only after
the H487 full-suite snapshot is recorded. No live provider calls or publication.

## Design and boundaries

Destination and credential checks currently bind the HTTP request URL but do not
prove the transport actually selected for that URL. An environment proxy or an
injected proxy mount can therefore introduce another recipient. Owned clients in
these two roles must disable environment proxy routing. Existing generic LLM
factory defaults and unrelated providers retain their contracts.

Use `llm/direct_transport.py:require_direct_async_transport(client, url)`, returning
None or raising DataHandlingRefused. Verify the actual bound selector's native
`__func__` and client `__self__`, including instance overrides. Accept the
native HTTPX route selector with a native AsyncHTTPTransport backed by the exact
httpcore AsyncConnectionPool, or exact MockTransport for offline injection.
Reject opaque/custom selectors, proxy pools and unsupported transport types.
Validate the actual selected route, including mounts, at the physical request
boundary and at scope entry. Do not mutate a borrowed ACTIVE judge client.
A borrowed client is usable only when its selected route passes the same check.
Configured remote judging/composer requests retain existing explicit consent;
this change neither enables remote use nor introduces proxy consent.

Composer-owned VLM construction sets trust_env=False only for its explicit
composer mode. Legacy independent VLM construction remains a separate scope.
Composer failures retain existing bounded policy errors. Judge-owned native
backends must construct their actual clients with trust_env=False without creating
and abandoning an earlier client. Any narrowly added constructor keyword must
preserve existing defaults and positional callers: keyword-only `trust_env=True`
on LMStudioBackend and OllamaBackend, False only for owned judge clients.
Compatible judge construction
sets the flag directly. Pure configured posture should not probe the network.

## Ownership and verification

Coordinator owns interfaces, this plan, integration and evidence. Proposed writer
A owns the new shared async transport validator/tests, vision_policy.py, the
composer-only vlm.py construction option and composer policy regressions. Writer
B owns approval_judge.py, any narrowly needed base.py constructor keyword, and
judge transport regressions. Freeze the helper contract before B consumes it.
At most two Sol High writers, no overlapping files and no subdelegation.

First demonstrate failing tests for ambient proxy construction, explicit proxy
mounts, selector overrides and a route changed by an earlier request hook. Keep
positive local/remote MockTransport paths and native direct selection, normal
credential/consent checks, cleanup and borrowed-client isolation. Tests must use
real HTTPX clients; no network or paid calls. Run focused suites after each step,
then one serial integration milestone with the appropriate broader suites.
Refresh only reviewed changed Hermes evidence; both H513 and H277 remain partial.

## Non-goals and rollback

No global proxy/default change, independent camera/media-reader/screen policy,
DNS attestation, stored-vector migration, new provider, native-mobile acceptance,
or mutation-campaign claim. A custom transport cannot establish direct routing by
merely reporting a local base URL. Supported explicit proxy authorization, if ever
needed, requires a separate destination/credential policy design.
Rollback is the localized helper plus its two integrations and tests; preserve
all earlier H487/H513 work. Next action: settle the judge constructor seam, record
the H487 milestone, then release implementation with this bounded contract.

## Implementation checkpoint

The preceding H487 snapshot is recorded and green: 19,054 backend passed,
35 skipped, 1,809 frontend passed. Both bounded contract reviews found no blocker.
Coordinator releases this plan for implementation. The shared helper contract is
frozen as specified above. Writer B may author its failing tests in parallel but
must consume the helper only after A freezes it. No production ASGITransport
exception is required by existing tests. Exact runtime judge fixtures may be
converted to native MockTransport clients while preserving their assertions.
