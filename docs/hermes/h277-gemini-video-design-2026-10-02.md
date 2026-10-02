# H277 native Gemini video design

Generated 2026-10-02 Europe/Bucharest. Goal: move the approved video consumer toward
full pinned Hermes auxiliary parity by adding a real Gemini request adapter.
Base/head: `b3512adf1592c9967267d34f9891606bcd489295`.
Status: implemented with 707 focused regressions passing and bounded review clear.
Full backend on `c4231b64`: 20,402 passed, 34 skipped and one expected failure.
See the [immutable receipt](evidence/h277-gemini-video-integration-2026-10-02.json).
Next action: approval-bound transient retry design, then the remaining H277 scope.
No push, merge, deployment, live provider call, paid spend or credential import.

## Evidence and decision

The [provider investigation](h277-next-provider-review-2026-10-02.md) reproduced the
pinned Hermes converter dropping video_url parts on its native Gemini path. Copying
that converter would not prove video support. The existing Nerva Gemini backend uses
HTTPX generateContent; reuse that protocol family without changing the chat backend.
The [official protocol](https://ai.google.dev/gemini-api/docs/generate-content/video-understanding)
documents inline video MIME/base64 parts and the x-goog-api-key header. Its overview
and inline sections disagree about maximum size. Set an explicit local bound:
**serialized native request must be strictly smaller than 20,000,000 bytes**. This
is an implementation bound, not a claim that Google's current limit is exactly20MB.
Larger-video upload/lifecycle support remains required follow-up work.

Selected approach: one pure native codec plus narrow additions to the existing role,
identity and execution modules. A new general provider SDK or a global chat backend
rewrite is unnecessary. Supporting only another compatible gateway would leave the
native omission unresolved; migrating all auxiliary callers at once would obscure
this behavior's authority and verification boundaries.

## Contract

- Add `gemini` to explicit video primary and fallback providers. Primary without a
  base uses `https://generativelanguage.googleapis.com/v1beta` in the video resolver
  only. Custom native bases remain explicit: HTTPS remote or HTTP(S) loopback,
  no userinfo/query/fragment/control characters/backslash, same host-protocol gate.
  Do not modify global Gemini/chat defaults or enable vision-provider inheritance.
- Primary reads only JARVIS_ROLE_VIDEO_KEY; fallbacks only their fixed slot key.
  Never borrow GEMINI_API_KEY, main, vision or other-slot credentials. Keyless custom
  native servers remain valid; configuration is not reachability/entitlement proof.
  Bound primary Gemini keys to4096 printable ASCII characters as for fallback keys.
- Build `{base}/models/{model}:generateContent`. Permit an optional leading `models/`
  input prefix, followed by one ASCII model slug `[A-Za-z0-9][A-Za-z0-9._-]*`, total
  input length at most256. No path/query injection or implicit model discovery.
- Wire body: contents with one user entry, a text part and an inline_data part holding
  the exact prepared video bytes as base64 and correct MIME. No video_url body field.
  Response: exactly one candidate with STOP finish reason and nonempty text parts;
  omit parts marked thought=true. Refuse blocked feedback/blocked safety ratings,
  malformed parts, empty responses and other terminal reasons; no answer/fallback
  is authorized by a malformed HTTP200 result. No SDK or streaming adapter added.
- Correct extension MIME mapping for every adapter: mp4→video/mp4, webm→video/webm,
  mov→video/quicktime, avi→video/avi, mkv→video/x-matroska, mpeg/mpg→video/mpeg.
  This declares the container from its extension; it does not inspect or certify
  real media content. Gemini supports all listed MIME types except Matroska in this
  increment. If any approved candidate cannot accept the declared MIME, refuse at
  intake. Never disguise unsupported content as MP4 or drop the video part.
- Preserve old no-chain class bytes, primary consent scope and result shape for
  existing providers. Gemini binding additionally includes its native protocol and
  credential header name. VideoIdentity.authorization may hold the raw Gemini key
  as its opaque credential value; do not expose it in repr/status/errors.
- Dispatch only x-goog-api-key for Gemini and only Authorization for existing
  adapters. Validate both credential headers (including absence), exact URL/body,
  cookie absence, direct transport and full-chain authority at the final hook.
  Existing consent, remote/cost opt-ins, strict-local/local-only/safe-mode restrictions,
  single-send budget, deadlines, hook-error isolation and cleanup checks all remain.
- Validate native body size before constructing any model client or sending any lane,
  after source materialization. Also bound the actual serialized request bytes at
  the final physical hook, so semantically identical whitespace inflation cannot
  bypass the limit. Each attempt still creates its own mutable body.
  Existing bounded failure classifier handles reviewed status failures; do not
  reinterpret arbitrary native error text as permission to change provider.
- Primary/fallback consent uses existing finite targets and HUD. No endpoint/schema
  or frontend source change is needed. Compact route notices must distinguish Gemini
  correctly within200characters. Native mobile controls remain open.

## Verification and delivery

Pure codec tests pin URL rejection, MIME/base64/body bytes, exact size boundaries,
blocked/thought/empty response behavior. Signed ToolRPC/worker tests inspect native
HTTPX requests, real independent consent, key isolation/revocation, both chain
orders, swapped credential headers and mixed-chain payload refusal before any send.
Existing no-chain HMAC and full video/consent regressions stay green.

At most two Sol High implementers, one writer per file, no subdelegation. The
coordinator owns shared contracts, critical review, records and commits. Focused
red/green verification per task; one full backend milestone after coherent source
freeze. Reuse the unchanged frontend's previous exact-source evidence.
Rollback restores the prior configured two-adapter chain by reverting this batch;
existing grants and signed tasks for unchanged providers retain their old formats.
H277 stays partial for broader auxiliary selection/adapters, automatic discovery,
same-provider/SDK recovery, larger uploads and live acceptance. No exclusion from
the full goal is introduced.
