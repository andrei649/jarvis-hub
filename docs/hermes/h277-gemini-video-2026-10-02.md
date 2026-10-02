# H277 native Gemini video — local integration

Generated 2026-10-02 Europe/Bucharest. Base `198debe9`.
H277 remains partial. No live provider call, paid spend or publication.

## Implementation

Explicit primary or fallback `gemini` routes send the approved video's actual
base64 bytes as native `inline_data`, with an isolated `x-goog-api-key` credential.
The video-only default is Google's generateContent base; explicit custom native
endpoints remain supported. Global Gemini and vision credentials are never borrowed.
Existing providers retain their no-chain approval class and consent scope.

The pure codec validates native URL/model inputs, declared container MIME, strict
base64 and compact UTF-8 JSON size. MOV/AVI/MKV declarations now identify their own
containers for all adapters. Gemini refuses Matroska at intake. Every configured
native candidate's payload is checked before any model client or lane send; actual
wire bytes are checked again against the local bound below20,000,000bytes.

The signed worker reuses the existing source, consent, whole-chain authority,
direct-transport, one-send-per-lane, deadline and cleanup guards. Both credential
headers are checked for exact expected presence/value and duplicates. Native
responses require one unblocked STOP candidate and visible text; thoughts are
omitted, and blocked/malformed/empty success grants neither disclosure nor fallback.

## Focused verification

- Pure codec:66passed. Initial missing-module collection failure is not counted as
  behavioral red evidence; subsequent host-protocol/safety/thought cases failed
  before their corrections.
- Signed integration:30new cases. Gemini resolver/intake, wire-size inflation and
  raw-key validation regressions failed before fixes. The wider selected video,
  role, consent, signed-media and image regression set passed707tests with zero
  failures/errors/skips; one third-party deprecation warning remains.
- Cases include both fallback orders, real audited per-slot consent, source URL
  fetched once, MOV/AVI exact wire MIME, mixed-chain MIME/size refusal, key rotation,
  cleanup-time consent revocation, injected/duplicate credential headers and a
  five-lane notification within200characters. The pre-existing independent old
  HMAC/scope assertion remains unchanged and passed in this selection.
- Bounded independent source/spec review found no blocking correctness issue; it
  did not rerun tests or make live calls.
- Scoped Ruff and whitespace checks passed. Documentation reference tests:6passed.
- Frontend and schema have no diff from the previously tested`2d9a3c39` source;
  its1838passing tests, typecheck and build remain separate existing evidence.

Full-backend verification will be recorded against the frozen integration commit
in a separate machine-readable receipt; focused results do not establish it.

## Remaining work

Container declarations do not decode or certify media. Native Gemini upload/file
lifecycle for larger videos, live model acceptance, broader auxiliary adapters,
shared routing/discovery, same-provider retries and SDK credential recovery remain
open. Native mobile controls and inbound media integration also remain open.
The prior31-case video mutation campaign predates both the configured chain and
this Gemini increment; it is not mutation coverage of these changes.

Next design input: [same-provider retry investigation](h277-retry-investigation-2026-10-02.md).
The current single-send approval contract must be explicitly addressed before
introducing retries. See the [design](h277-gemini-video-design-2026-10-02.md) for
native request, credential and response boundaries.

## Decisions taken under standing owner autonomy

The existing local execution and Sol High implementer plan replaced interactive
design/commit gates; written plans and scoped review make the result reviewable,
with possible design rework as the cost. The local native request bound is below
20,000,000bytes because inspected official guidance is inconsistent; this can
refuse larger inputs until upload support exists and is not a vendor-limit claim.
