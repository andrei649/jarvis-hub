# Attachment preview request lifetime

## Problem and scope

`BinaryCard` starts an authenticated blob request when the owner selects Load attachment. Its cleanup currently revokes only a URL already present in React state. If the card unmounts while a response is pending, the continuation can allocate a new object URL after cleanup. Gallery search and navigation can trigger this lifecycle.

## Implementation plan

1. Reproduce unmount during both fetch and body reading with deferred responses; require cancellation and no late object URL allocation, including transports that ignore abort.
2. Keep one identity-bound request controller and an owned object URL reference in BinaryCard. Abort/invalidate on unmount, suppress late state updates, and retain the existing URL cleanup for accepted previews. Do not change attachment authentication, endpoints, mutation semantics or blob limits.
3. Verify successful preview/download and URL cleanup, failure/retry, and cancellation. Run focused component tests, both TypeScript checks and the frontend suite; rebuild shipped assets deterministically before integration.

No backend, dependency or authority changes are required. This is request lifetime cleanup, not a new artifact persistence feature.

## Verification

The two late fetch/body regressions failed before the fix and pass afterward. Four new tests cover cancellation, successful download/cleanup and retry; nine focused tests and both TypeScript checks passed. Independent review passed five lifecycle/attachment tests. The integrated frontend suite passes all 1,266 tests.
