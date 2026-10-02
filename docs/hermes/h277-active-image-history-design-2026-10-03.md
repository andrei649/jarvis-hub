# H277 active image history for reviewed conversation turns

Pinned reference: Hermes `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.
Nerva base: `70a4cdd9`. This design advances native multipart history while
retaining Nerva's one-use image review, selected-route and data-handling rules.
It does not close H277 or claim live provider acceptance.

## Current behavior and required outcome

The selected browser image turn is already committed to the real conversation.
Its durable user row contains the question and an image-count marker; its
assistant row contains the actual answer. That is enough for a later text
prompt to read the *answer*, but the image bytes are gone. Hermes keeps native
image parts in its active transcript and projects them to text markers only
when persisting (`agent/image_routing.py:build_native_content_parts`,
`agent/session_persistence.py:_durable_content`). A later Nerva turn cannot
ask a vision model about a detail the first answer omitted.

An ordinary `/chat` or `/chat/stream` turn must not silently replay old bytes:
Nerva's selected image route requires a one-use owner review and binds the
actual model, destination, question and ordered image digests. Silent replay
would bypass that contract and could send personal images to a newly selected
remote model. The product outcome is therefore an **explicit visual follow-up**
in the shared composer: while the server process still holds the selected
session's images, the owner can choose prior image turns, review the combined
image count and current destination, then ask a new question. Each send consumes
a fresh one-use review. Ordinary text chat remains text-only.

## In-process ownership

An `ActiveImageHistory` owned by each `ConversationMemory` holds immutable validated
raster bytes for successful selected image turns only. No global cache or disk,
checkpoint, vector, trace, audit or session-log field contains bytes, base64,
data URI, raw digest or credential. A handle is random, opaque, non-authorizing
and only valid for the exact session instance and agent. The store caps each
image at the current 4 MiB raster limit, eight images per reviewed request,
16 MiB total resident bytes and 32 handles per orchestrator. Oldest entries
evict first. It evicts on session clear/reset, process restart, TTL expiry and
session-instance mismatch; a missing entry is an ordinary review failure.
`ConversationMemory.clear` and any replacement of a session's in-process turn
list invalidate its entries before the new history becomes visible.

The cache records after the conversation commit succeeds. If a response fails,
is cancelled or the client disconnects before commit, it records nothing. If
the cache cannot retain a successful turn because of its bounds, the durable
text answer remains valid and the UI reports that visual follow-up is
unavailable. A cache handle is never sufficient to send bytes on its own.

## Reviewed replay

`POST /api/vlm/composer/active-history` returns only opaque handles, image
counts and bounded question labels for the current selected agent/session;
it does not return bytes or digests. Preparation accepts an ordered list of
those handles plus zero or more new image digests. The server resolves and
freezes the exact prior bytes under the session lease, rejects missing/stale
handles, and binds their ordered digests, current transcript fingerprint and
selected route into the review token. The preparation response discloses the
**total** images that will be sent and the existing remote/training/cost
requirements. The owner must explicitly select the visual follow-up in the
HUD; there is no implicit reuse.

Submission re-resolves handles under the same session lease, consumes the
review, verifies the image bytes and order, then invokes the existing physical
vision guard on the current selected native-capable route. It includes the
earlier question/answer text with the corresponding image parts, followed by
the new question and any new images. Each supported native codec receives
the same ordered logical messages; a codec that cannot represent the history
refuses before egress. Current response and byte caps, physical URL/body/auth
checks, transport identity, H513 policy, local-only restrictions and cancellation
remain in force. The new answer is committed once through the existing
selected-image post-turn seam, with a durable text marker and provenance for
the number of images actually sent. No second model call is invented.

New image bytes may be retained after a successful follow-up; reused bytes
remain attached to their original active handle. A resumed or restarted
session keeps the durable question and answer, but has no active image bytes.
The UI must say so instead of implying visual memory survived restart.

## Verification gates

1. Red-first test: image turn, explicit follow-up, one physical selected-model
   request containing prior image parts and prior question/answer, then a
   committed answer in the same session. A plain text turn sends no old bytes.
2. Review tests: handle/session/agent mismatch, reset, eviction, expiry,
   changed source bytes/order, transcript/route/key drift and a reused token
   refuse before egress. A remote follow-up needs fresh destination, training
   and cost confirmation as applicable.
3. Persistence tests: snapshots, append logs, embeddings, checkpoint and
   returned history expose only bounded text/provenance. Restart drops active
   handles but restores durable turns. Disconnect/provider failure commits no
   successful pair or active entry.
4. Native codec tests cover the supported selected-main providers and reject
   unrepresentable or malformed history before transport. Request and response
   size caps cover the **combined** historical and new media.
5. Run scoped suites per step, full backend/frontend at the milestone, Graft
   rebuild/check, exact Hermes row restamp and staged secret scan. Keep H277
   partial until the broader adapter, discovery, recovery and live gaps close.

No push, merge, deployment or paid provider request belongs to this work.
