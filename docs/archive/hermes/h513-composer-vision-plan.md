# H513 composer vision policy and physical request binding

Status: local implementation proposal, 2026-09-27; awaiting coordinator confirmation
of the current full-backend checkpoint before implementation. Base/head:
`bd2bb70ead1b493043a335e77713fc42c47d4013` plus preserved, verified sprint changes.
Coordinator authorized implementation after the frozen judge milestone passed
18,919 backend tests (35 skips). Composer helpers are isolated in vision_policy.py;
the shared data-handling module and egress hook are not edited by this writer.
Goal: cover explicit composer image requests with truthful data-policy warnings and
fresh configuration and actual-wire checks. Preserve per-request remote destination
acknowledgment, bounded transient images, and existing independent VLM callers.
No live or paid provider requests, publication or new durable consent target.

## Authority and scope

The authenticated `/api/vlm/composer/describe` route supplies an explicit
`Principal(channel="web", admin=False)` and a generated request-scoped guard.
Neither copied ambient owner context nor request body identities confer authority.
The existing `user_guard` remains the access gate, including its supported localhost
posture. The request's `remote_ack` remains mandatory whenever the configured
destination is remote, even if another provider or judge has durable consent.
It authorizes only this image request to the reviewed destination; it never grants
unattended work. There is no new durable vision target or provider-store entry.

Map configured `lmstudio` to the registered `lm-studio` profile and `custom` to
`openai-compatible`, retaining existing role/legacy configuration precedence.
Use existing `data_policy_for(model)` vocabulary and effective endpoint locality;
remote overrides of nominally local providers are unknown. Custom compatibility
endpoints remain unknown rather than asserting proxy/provider terms, including
loopback custom endpoints. Interactive unknown/training policies emit a warning;
they do not require an additional persistent owner grant. The existing locality
flag remains destination information, not a verified provider training claim.
This scope never enables a strict-local consumer to send remotely.
Existing H378 `selection_guards.evaluate(Choice("vision.model", provider, model))`
checks run initially and freshly before dispatch. Findings retain the existing
`409` `SelectionRefused.payload()` contract; remote acknowledgment does not clear
training/cost findings, and this increment adds no confirmation fields or UI.

## Frozen private identity and supported authentication

Resolve configuration once for initial validation, then freeze an immutable request
identity: selector/provider, model, full configured endpoint including userinfo and
query, effective wire endpoint, effective Authorization, resolved policy and
profile policy declarations. Do not add image bytes, prompt or user identities to
the destination metadata. The adapter/client must match this identity; its mutable
`is_local` claim is insufficient. Validate supported URL scheme and actual locality.

Preserve credential-bearing HTTP(S) URLs, with public destination projection still
removing userinfo, query and fragment. Define composer auth precedence explicitly:

- A nonempty resolved API key sends exactly `Authorization: Bearer <key>`, even
  when URL userinfo is present.
- Without an API key, URL userinfo uses native httpx Basic auth, matching its
  actual username/password decoding and encoding behavior.
- Without either, no Authorization is expected.

Offline inspection of installed httpx plus MockTransport showed that URL Basic
currently overrides an explicit Bearer header, even with request `auth=None`.
An explicit no-op `httpx.Auth()` preserves the Bearer header. Composer therefore
needs a narrowly scoped native adapter option to suppress URL-derived Basic when
the key is nonempty, while leaving historical unscoped VLM construction untouched.
Use httpx's own request/auth preparation to derive expected Basic, rather than a
second handwritten encoding implementation. Native composer construction is the
supported auth surface: arbitrary injected auth objects, cookies, inherited
unexpected Authorization or adapters with unknowable wire identity fail closed.
Synthetic clients in policy tests must declare truthful wire metadata.

Keep `destination_revision`'s private fingerprint plus persisted random public
revision model. Expand the private fingerprint to the frozen identity above,
including credentials and effective policy. Key/auth/model/endpoint/policy changes
rotate the revision. Public output contains the random revision, never a raw
credential digest or other offline verifier. Existing revision storage may rotate
once on migration and remains stable across restart/workers afterwards. No raw
credentials, prompts or images are stored in that metadata row.

## Fresh checks at physical dispatch

Reuse the planned backward-compatible
`physical_request_scope(check, *, request_check=None)`. Its configuration callback
re-resolves live config and policy, requires the same frozen identity, and repeats
the request's destination/ack validation. Bind only around actual awaited composer
generation; close inherited child lifetimes on completion/cancellation. Preserve
remembered-denial rethrow if a backend swallows a refusal.

The separate synchronous actual-request validator checks the prepared httpx request
after config validation and before transport: exact expected method `POST`, exact
URL produced by native client resolution of `/chat/completions`, payload model and effective
Authorization. Compare full wire identity privately, including query and userinfo;
never reconstruct from the sanitized public destination. Validate matching adapter
and client base URLs before generation too. Do not change existing endpoint/query
joining semantics silently. A followed redirect or an unexpected DELETE is denied
when this validator is active; the shared hook must invoke explicit validators for
DELETE as planned, while retaining cleanup behavior for older scopes without one.
No backend-global mutable hook or broad scope over unrelated model/tool work.

Check again after generation before returning success, so a frozen configuration
that changed while awaiting cannot be presented as a current successful response.
This does not undo an already authorized request sent before a change; race tests
must distinguish sent-first from changed-before-dispatch.

Initial stale destination and changes discovered during dispatch return bounded
`409` with existing `vlm_destination_changed`. Missing remote acknowledgment remains
`403`/`vlm_remote_ack_required`. Unavailable config/revision/policy resolution fails
before image I/O with bounded `503`; inference failures retain existing bounded
`502`/`vlm_generation_failed`. Never expose exception details or private wire values.

## Consumer and HUD contract

Retain all existing request fields and status/response fields. Add optional public
`data_policy` (existing finite vocabulary), `data_policy_note` and `warning` strings
to configured status and successful response. Values are bounded fixed/profile
metadata, never URLs, keys or user input. Status stays pure: no client construction,
reachability probe, actual-use notice or last-used update. Warnings may be present
before the request and remain present on an acknowledged remote result.

HUD displays the warning next to the reviewed destination and on the successful
vision result. Missing optional fields preserve older servers' behavior. Warning
display must not substitute for the existing checkbox or change its exact binding,
refresh reset, transient images, cancellation, response limits or normal text-chat
submission. Do not append warnings to model output or persist images in chat memory.
Use ordinary React text rendering for bounded warning strings. An API response
warning is retained separately from the vision answer and provenance.

## Exact implementation files and verification

Backend: `agents/core/routers/composer_vision.py`,
`agents/core/llm/vlm.py` (composer-only optional native auth/wire seam), and narrowly
needed pure/request-scope policy helpers in new `agents/core/llm/vision_policy.py`.
Shared physical validator implementation is owned separately; settle that interface
before dependent code. No edits to model role precedence or legacy VLM callers.

HUD: `frontend/src/composer-images.tsx`, `frontend/src/vision-turn.ts`, and
`frontend/src/cockpit.tsx` for result warning display. `frontend/src/app.tsx` only
if actual typed message propagation requires it; its existing answer spreading
should preserve optional fields without changes. Coordinator owns generated API
artifacts, coverage/status records and final checkpoint.

Tests: new `tests/test_h513_composer_vision_policy.py`, existing
`tests/test_composer_vision.py` and `tests/test_vlm_h13_1.py`; focused HUD additions
in `frontend/src/test/composer-images.test.tsx` and
`frontend/src/test/composer-vision-turn.test.tsx`. Update synthetic fixtures only
to represent supported actual metadata, preserving existing assertions.

RED/GREEN offline cases, using real native client + MockTransport where identity
matters:

- Missing `remote_ack` sends no images; durable primary/judge consent cannot bypass
  it. Explicit request principal remains interactive under copied owner context.
- Off-loopback LM Studio/custom policy is unknown, warnings survive acknowledgment,
  and unknown custom loopback is labeled honestly without changing its checkbox rule.
- URL Basic without key and Bearer-over-Basic with key both round-trip correctly;
  public status/result/errors omit all private endpoint/auth values.
- Key, URL password/query, model and policy changes invalidate reviewed bindings;
  revision survives restart/second-worker reads and is not a credential digest.
- Pause after initial validation but before physical transport, mutate config or
  actual client endpoint/auth, then release: zero transport calls and bounded stale
  refusal. Include actual final prepared request mismatch/redirect refusal.
- Concurrent native requests use isolated scopes; closed copied children cannot
  send; cancellation closes backend/lifetime; swallowed denial cannot become success.
- Status does not construct a client or record actual use; failed revision storage
  sends nothing. Preserve success provenance, image bounds and checked failure.
- Native legacy `generate_vision` still returns its existing sentinel on failure;
  legacy `generate`/constructor/from_env behavior is unchanged outside composer.
- HUD renders status/result warnings, keeps per-binding remote checkbox/reset,
  tolerates absent optional fields and keeps ordinary text paths unchanged.

Run only these backend modules plus focused existing H513 helper regressions with
normal project pytest timeout/socket options; focused HUD files and typecheck.
Coordinator performs the next serial full milestone after sources freeze. No live
calls or synthetic "pass" claims before executing the corresponding regressions.

## Non-goals and rollback

Independent media-reader, screen locator/reflex, camera, legacy multimodal and
embedding clients remain excluded from this coverage statement. No global VLM
gate, unattended vision grant, new remote fallback, role settings, model probe,
provider terms claim, generic image persistence or new caller is introduced.

Rollback removes composer policy/request scopes and optional warning projection,
HUD display, and its bounded new tests. Restore only the composer-specific native
auth option while preserving all earlier H513 consumers/shared hook defaults.
The expanded private destination fingerprint may leave an opaque revised metadata
row; it grants no authority and old per-request bindings can safely require refresh.
Do not remove provider/judge consent, clear model config or purge transient/user data.

## Checkpoint release

Coordinator released implementation after the complete local judge milestone:
18,919 backend passes, 35 skips, zero failures; 1,804 frontend passes. Generation
date 2026-09-27; base/head `bd2bb70ead1b493043a335e77713fc42c47d4013`.
Next action: implement the owned paths above with focused RED/GREEN tests.
Composer-specific policy helpers belong in `agents/core/llm/vision_policy.py`;
embedding owns the shared data-handling and egress sync additions.

## Implementation checkpoint

The composer implementation is frozen. Its focused checkpoint passed 138 Python
cases, including 16 new policy cases and six added route cases; 12 focused HUD
cases passed. The complete frontend snapshot passed 1,806 tests, TypeScript and
the production build. Full backend integration is recorded separately after the
embedding changes freeze. No live provider call or native-mobile acceptance is
implied by these offline results.
