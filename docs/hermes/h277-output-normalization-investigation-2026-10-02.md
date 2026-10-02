# H277 next increment: response normalization investigation

Goal: continue local functional parity with pinned Hermes without weakening existing
request authority. Generated 2026-10-02; inspected Nerva head
`47ffd68f55c01fa3b45ba596ed94c0a9cb5b81ce`, branch
`codex/h277-image-empty-retry-20261002`. No runtime change in this investigation.
Hermes reference: `59b2aeef6c7a3ecbb2625a54c66111a56eb64e3e`.

## Observed source behavior

Hermes `agent/auxiliary_client.py:8098` defines `extract_content_or_reasoning`:
visible content with closed thinking blocks removed, then structured reasoning
fields/details as a fallback. `tools/vision_tools.py:721` repeats once only when
that extraction is empty. Nerva's completed image/video increments deliberately
cover valid-empty responses, not that entire extraction contract. Nerva image
`agents/core/llm/vlm.py` strips thinking from content; compatible video in
`agents/core/video_analysis.py` reads the first message content directly. Their
nonempty normalization is therefore still different.

Three pure synthetic probes of `agents/core/llm/video_native.py::gemini_video_answer`
returned `visible` on the inspected Nerva head:

- a non-text `thought: true` function-call part followed by a visible text part;
- a top-level error envelope alongside a STOP candidate with visible text;
- a visible text part also carrying a function-call field.

The first behavior is explicitly preserved by
`tests/test_h277_video_native.py::test_answer_omits_non_text_thought_part_before_visible_text`.
It must not be silently rewritten as part of empty-retry work. Error/mixed-part
checks are currently stricter for classifying **empty** than for accepting
**nonempty** output. The raw synthetic probe receipt is
`/tmp/nerva-next-normalization-observations-20261002.json`; no network/provider call
was made. These are output-validation observations, not proof of an authorization
bypass or a live-provider failure.

The presence explanation helper remains a separate issue:
`agents/core/house/presence.py::LocalPresenceExplainer` has local request-scope
protection, but source search found no production `.explain` caller in its house
module/route paths. Its tests establish the helper contract, not end-user wiring.
Do not count this seam as a delivered consumer.

## Next action and boundaries

Design a bounded response-normalization increment before editing runtime source.
Specify visible text, typed reasoning fallback, blocked/error/malformed envelopes,
provider-specific parts and empty-result classification together. Explicitly
reconcile the currently accepted non-text thought fixture. Use actual governed
consumer regressions and retain the same approved route, send budget, deadline,
cleanup and output bounds. Avoid introducing a second provider call merely to
normalize an otherwise valid result. Keep credential recovery, provider discovery,
native large-video uploads and presence UI wiring as separate increments.

Likely paths: the shared native-response helper, VLM/video codecs and their existing
consumer tests. Review whole-row evidence freshness again against the next batch's
actual base. No additional dependency, provider credential or paid service is
needed for the local design and synthetic regression work. The full Hermes goal
and H277 remain open; no status promotion is authorized by this investigation alone.
