# H277 native vision response normalization

Goal: continue full local Hermes parity through the real native image/video
consumers. Base/head before implementation `173a5a840f8bff27b2ef41a474837ec73e44f18c`;
branch `codex/h277-vision-normalization-20261002`. Generated 2026-10-02.
Pinned Hermes `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`:
`agent/auxiliary_client.py:8098` extracts visible content, then reasoning fields
and reasoning details; `agent/gemini_native_adapter.py:618` translates native
thought text to structured reasoning; `tools/vision_tools.py:721` repeats only
when extraction is empty. This corrects a functional gap, including thought-only
Gemini replies previously treated as empty. It does not complete H277.

## Contract

Normalize compatible native replies once through a small shared pure helper:
require one message-shaped completion, reject explicit error envelopes at response,
choice or message, refusal/tool/function/audio outputs and blocked finish reasons.
Legacy absent/null finish metadata and visible text with length termination remain
accepted; valid-empty retries still require the existing explicit stopped/raw-empty
predicate. Missing/null content permits structured reasoning fallback. Non-string
content is not stringified into a fabricated answer. Ordinary provider metadata
(model, usage, identifiers) stays allowed. The native contract remains typed JSON;
SDK objects/bare strings and non-native adapters are separate work.

Prefer visible string content after the existing thinking filter and whitespace
cleanup. If empty, collect nonblank string reasoning and reasoning_content, then
one string summary/content/text per reasoning_details item (that priority), preserving
order and deduping normalized pieces, separated by blank lines. Skip encrypted/opaque/non-string detail data rather than expose
its serialization. Visible text wins; unused reasoning does not displace it.
The shared normalized_vision_text helper removes the nine closed tags from pinned
Hermes think_scrubber.THINK_TAG_NAMES, then uses Nerva's existing filter, which also
hides unterminated think blocks; no global base-backend filter change. Keep caller
response/output bounds. Length termination does not suppress useful structured
reasoning, matching the pinned extraction contract. Empty-string refusal metadata
remains compatible with the existing valid-empty predicate; meaningful or malformed
refusal remains terminal.

Use the helper in both VLM response paths (budget disabled/enabled) and compatible
video dispatch. Extract useful reasoning before considering retry; this uses the
already-received response, adds no provider call, and does not widen raw-empty retry
eligibility. Whitespace/raw-blank continues through the prior retry contract;
inline-thought-only content without structured reasoning stays outside that retry
predicate. Ordinary text/direct VLM calls still gain no retry authority.

Native Gemini: one unblocked STOP candidate, typed parts, and no explicit nested
error envelopes. Prefer normalized visible text, otherwise concatenate raw well-formed
thought text in part order, then normalize once as the pinned adapter/extractor does
(parts can split a word or a thinking tag). Nonblank visible content stripped to empty without useful thought output must not
gain retry eligibility. Pure blank typed
parts still raise the existing typed-empty result; non-text/function/audio parts
and malformed mixed output refuse even alongside visible text. Allow native
thoughtSignature string metadata but never expose it as answer text. Deliberately
replace the old fixture that silently ignored a thought-marked function call, and
replace thought-only refusal expectations with real successful reasoning-fallback
expectations. Refusal is terminal, with no unauthorized fallback/retry. Retain
safety, source, signed kernel execution, consent, policy freshness and cleanup.

## Execution, tests and boundaries

Two independent Sol High writers, no subdelegation. Compatible writer owns
`agents/core/llm/native_response.py`, `vlm.py`, `agents/core/video_analysis.py`,
new normalization tests and only conflicting compatible image/video expectations.
Gemini writer owns `agents/core/llm/video_native.py`, `tests/test_h277_video_native.py`,
`tests/test_h277_video_gemini.py`, and a new native-normalization producer module.
Coordinator owns the shared `tests/test_h277_video_empty_retry.py` and
`tests/test_h277_video_retry.py` expectations,
config/docs/status/evidence and integration. Shared empty predicate is preserved;
no writer changes retry budgets, transport hooks, credentials, routes or UI shapes.

Test first with actual governed HTTPX image/video consumers and literal payloads:
visible precedence; each reasoning field/details; deduplication; malformed/error
with otherwise visible content; true blanks; thought-only answers; signature
metadata; blocked/tool output; no second call for a useful fallback; authority
revocation and unchanged empty budget behavior. Preserve failing red receipts,
then focused integration and a single serial full backend milestone. Frontend,
route schema and generated assets are unchanged, so reuse their prior verified
source snapshot. Scoped mutation checks should target realistic output/extra-send
failures, not private implementation shape. Review evidence whole-row freshness;
refresh only reviewed rows current at this base, with no H277 promotion.

Standing owner local authorization covers this design and implementation. No new
permission, dependency, live provider, paid service, push, merge or deploy. Rollback
is the coherent normalization diff; no persisted data migration or authority-budget
change. Remaining provider discovery, credentials, additional adapters, larger video
uploads, native mobile and backlog accounting remain in the full goal.
