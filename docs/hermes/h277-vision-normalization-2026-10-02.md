# H277 native image/video response normalization

Goal: advance complete local Hermes parity on the real native consumers.
Base `173a5a840f8bff27b2ef41a474837ec73e44f18c`, branch
`codex/h277-vision-normalization-20261002`; generated 2026-10-02.
Pinned Hermes `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e` provides the extraction
order and native Gemini thought-part translation. See the
[design](h277-vision-normalization-design-2026-10-02.md).

## Delivered behavior

Both native image response paths and signed compatible video dispatch use the
shared typed completion parser. Visible text wins after closed thinking-tag
removal, including the pinned Latin/CJK aliases. If visible text is absent, ordered
reasoning/reasoning_content and one typed summary/content/text per detail provide
the answer, deduplicated and separated by blank lines. Missing/null content permits
fallback; non-string content, explicit errors, refusal/tool/function/audio outputs
and blocked finish metadata refuse. Empty refusal strings and legacy missing finish
metadata remain accepted; length termination can yield useful text or reasoning.
Opaque detail data is not serialized into an answer. Existing thinking-filter
behavior, including unterminated think suppression, is retained without a global
base-backend edit.

Gemini validates all parts before accepting a single unblocked STOP candidate.
It prefers visible text and otherwise concatenates raw thought parts before
normalization, preserving split words/tags. String thought signatures are accepted
as metadata and never displayed. Non-text or malformed mixed parts and nested
error envelopes refuse, even alongside plausible visible text. Previously ignored
thought-marked function calls now refuse. Useful thought-only output is now an
answer, matching the pinned adapter/extractor; it no longer spends an empty retry.
Actual raw blanks retain the typed-empty contract. Nonblank visible inline thinking
that filters to empty is terminal, so normalization cannot add a retry.

All existing request authority, signed worker/kernel mediation, selected provider,
consent, prepared source, physical send checks, deadlines and response/output caps
remain. This increment adds no model call, credential, provider, dependency, route
or schema. The existing CLI/HUD answer surfaces receive normalized text. Native
mobile and live-provider acceptance are not claimed.

## Verification and review

Two bounded Sol High writers implemented compatible and Gemini paths; the
coordinator integrated and reviewed the actual consumer boundaries. Initial
red-first producer tests demonstrated missing extraction and validation; subsequent
corrections covered detail priority, length termination, empty refusal metadata,
Latin/CJK tags, fragmented native parts and accidental retry. Parent's two signed
worker cases failed before implementation. Review found that the first image test
helper set a flag without entering a governed request scope; the final helper enters
the real composer scope and exercises the enabled native stream path.

Final parent integration: **696 passed**, zero failures/errors/skips. The first
integration run had one outdated transient-retry test expecting thought-only Gemini
failure; its replacement verifies a useful result with exactly one primary send.
The original failed receipt is retained. Full Ruff and diff checks passed. Gemini
writer's focused174 and compatible writer's final295 checks passed; parent results
are the integrated acceptance evidence. Full backend and frozen-source mutation
results are recorded separately after source commit; this report does not imply
those checks have already run. Frontend/runtime assets and schema are unchanged
from the preceding verified image batch (1847 frontend tests, typecheck/build).

Changed source: native_response.py, vlm.py, video_native.py and video_analysis.py.
Tests cover both typed codecs and real governed/signed HTTPX consumers; old
thought-only refusal fixtures were deliberately replaced, not discarded silently.
The partial H277 status stays partial. Only previously-current evidence rows may be
refreshed after their complete base pins and changed claims are reviewed.

## Remaining work and rollback

SDK objects/bare-response adapters, non-native normalization/discovery, credential
recovery, additional auxiliary consumers and provider capability caching remain.
Nerva deliberately retains typed native envelope validation, Gemini STOP/safety
requirements and its existing thinking filter; this is not a claim of identical
behavior for every upstream malformed/heterogeneous input. Larger native-video
uploads and live model/device proof also remain. Revert this coherent normalization
increment to restore previous response behavior; no persisted migration is needed.
No push, merge or deployment is part of the local batch.
