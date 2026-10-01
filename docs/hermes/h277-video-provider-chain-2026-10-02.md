# H277 configured video provider chain — local continuation

- Generated: 2026-10-02, Europe/Bucharest.
- Goal: bounded failure-driven video fallback with independently consented destinations.
- Base: `9290544390b151108948ae2af325bd955e508aae`.
- Parser commit: `2a69eb2678b9459850cc7706ca6114d05e29c4ae`.
- Consent/API/HUD commit: `2d9a3c39d3e4391fc5a35e3a6ff93567660afbe7`.
- Runtime head and final verification: pending final integration below.
- Publication: local only; no live or paid model calls.
- Status: H277 remains partial; this is a bounded native adapter increment.

## Execution Plan:

Resolve an explicit ordered chain before approval, bind every destination and credential
into the signed class, and recheck the complete chain at source access, each physical
request, cleanup and disclosure. Each configured fallback has its own audited model-data
consent. Prepare the source and prompt once, reconstruct mutable request bodies for each
attempt, and close the owned client before advancing.

## Files Modified:

- `agents/core/llm/video_routes.py`: strict pure parser for at most four explicit
  fallback records and fixed per-slot keys; no main-model credential discovery.
- `agents/core/llm/video_policy.py`: finite candidate identities, ordered approval
  binding and checks of the actual native request.
- `agents/core/video_analysis.py`, `agents/core/llm/video_failures.py`: sequential
  bounded native attempts and fixed, narrowly classified failure categories.
- `agents/core/llm/data_handling.py`, `agents/core/routers/security.py`,
  `frontend/src/panels/data-handling.tsx`: independent configured-candidate grants,
  revocation, usage and HUD controls; generated schema and HUD assets accompany them.
- Dedicated parser, consent, failure-classifier, signed-provider-chain and HUD tests.
- Configuration, mobile parity, Hermes evidence and continuation records.

## Verification Results:

- Parser and existing role/fallback selection: 80 focused cases passed after red-first
  validation fixes for Unicode surrogates and non-ASCII header credentials.
- Candidate consent: 14 focused cases passed; parent API/consent/video/schema integration
  passed 194 cases. Review strengthened address-only reordering, stale authorization,
  and grant preservation tests before acceptance.
- Full frontend: 1,838 passed, zero failed or pending. TypeScript checking and production
  build passed; the existing large-bundle advisory remains. OpenAPI was generated
  offline with the cached pinned 7.13.0 generator.
- Failure classifier: 61 focused cases passed, including bounded malformed/deep JSON,
  specific billing/auth/rate/model categories and excluded not-found/generic failures.
- Final focused runtime/integration selection: **627 passed, zero failures/errors/skips**
  (51 chain and 61 classifier cases included). Repository socket and timeout guards
  remained enabled. Scoped Ruff and diff whitespace checks passed.
- Review regressions failed before fixes for mutable cross-attempt bodies, request/response
  hook errors causing fallback, a second fresh auth-flow request on one lane, notice
  overflow/control characters, and approval lookup outside the execution deadline.
  Other acceptance cases cover cancellation, cleanup-time revocation, bounded responses
  and source reuse; no unrun pre-fix failures are claimed.
- Full-backend verification remains pending source freeze and final review.

The preceding [video mutation campaign](evidence/h277-video-mutations-verified-2026-10-02/report.md)
pins `92905443`: 29 detected mutations, two explained survivors, zero invalid cases,
168 passing baseline cases and all 4,130 source hashes restored. It predates this
provider-chain runtime and is not mutation coverage of the new fallback implementation.

## Remaining Risks:

Only native LM Studio and OpenAI-compatible video requests are implemented. There is
no implicit paid-provider discovery, subscription entitlement inference, same-provider
retry or SDK credential recovery. Shared auxiliary routing, additional native adapters,
upstream automatic discovery and live native-video acceptance remain unfinished.
Inbound video ingestion and native mobile controls are separate gaps.

The total video deadline is 180 seconds, with a 65-second attempt and 60-second HTTPX
timeout; source retrieval has its existing 35-second sublimit. A stricter executor
budget still wins. Each response is limited to 512,000 bytes. Local content-hash
revalidation can reread the file; the source URL is fetched once per execution.

Approval display uses sanitized origins without URL paths; full destinations remain
bound by the signed identity. Long chains/models/origins use compact labels and
six-character digests within the existing 200-character ToolRPC limit. This retains
route distinction but reduces human-readable detail; it does not change authority. Generic HTTP errors, source/consent/policy failures,
cancellation and hook/store failures must not authorize a switch of provider.
