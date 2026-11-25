# Compatible native vision normalization handoff

Goal: normalize real compatible image and signed video replies without changing the existing raw-empty retry predicate or authority/transport budgets.
Base: `173a5a840f8bff27b2ef41a474837ec73e44f18c`
Branch: `codex/h277-vision-normalization-20261002`
Generated: 2026-10-02, Europe/Bucharest

Owned changed paths:
- `agents/core/llm/native_response.py`
- `agents/core/llm/vlm.py`
- `agents/core/video_analysis.py`
- `tests/test_h277_vision_normalization.py` (new)
- `tests/test_h277_image_empty_retry.py`

Behavior: `compatible_vision_answer` validates one typed compatible choice, rejects explicit error/refusal/tool/function/audio/blocked output and non-string content, prefers normalized visible text, then ordered deduplicated reasoning/reasoning_content/detail text. Each detail yields at most one of summary/content/text, joined with blank lines. `normalized_vision_text(text: str) -> str` strips pinned closed thought-tag aliases and applies existing Nerva filter, including its unterminated `<think>` behavior. Both VLM paths and signed video dispatch use the helper before considering any raw-empty retry. `compatible_empty_success` is unchanged.

TDD receipts (Python `/tmp/nerva-pr-python-20261001/bin/python`):
- Initial red: `/tmp/nerva-vision-compatible-red-20261002.xml`: 31 tests, 27 failures, 0 errors, 0 skips. Failures were missing reasoning fallback, malformed reply validation and video thought stripping.
- First green: `/tmp/nerva-vision-compatible-green-20261002.xml`: 31 tests, 0 failures/errors/skips.
- Pinned contract corrections red: `/tmp/nerva-vision-compatible-corrections-red-20261002.xml`: 36 tests, 7 failures, 0 errors/skips. Failures covered blank-line join, one-field-per-detail, length reasoning, empty refusal metadata and Latin/CJK tag suppression.
- Corrections green: `/tmp/nerva-vision-compatible-corrections-green-20261002.xml`: 36 tests, 0 failures/errors/skips.
- First focused integration: `/tmp/nerva-vision-compatible-focused-final-20261002.xml`: 293 tests, 0 failures/errors/skips. This preceded the image harness correction below.
- Governed image harness correction: `tests/test_h277_vision_normalization.py::_image` now enters the real `composer_request_scope` with a matching local `VLMConfig`, backend and web principal whenever the retry setting is enabled. The added producer cases therefore exercise the streamed/retry-enabled branch; direct calls still exercise the ordinary path. `/tmp/nerva-vision-compatible-governed-harness-20261002.xml`: 78 tests, 0 failures/errors/skips.
- Final current-source focused integration: `/tmp/nerva-vision-compatible-focused-current-20261002.xml`: 295 tests, 0 failures/errors/skips. Command: `python -m pytest tests/test_h277_vision_normalization.py tests/test_h277_image_empty_retry.py tests/test_h277_image_retry_scope_edges.py tests/test_h277_video_analysis.py tests/test_h277_video_provider_chain.py tests/test_h277_video_empty_retry.py tests/test_vlm_h13_1.py tests/test_h513_interactive_local_vision.py tests/test_h513_composer_vision_policy.py -q`.
- Final freeze after import-order cleanup: `/tmp/nerva-vision-compatible-focused-freeze-20261002.xml`: 295 tests, 0 failures/errors/skips (same command). Scoped Ruff import check on all five owned paths passed.
- `git diff --check` passed.

Source SHA-256 at handoff:
- `agents/core/llm/native_response.py`: `109fb7517622bcef381844709c8fea2572c079f6f4c73872b3edf1a730f2940b`
- `agents/core/llm/vlm.py`: `6dffe35c7528813381ceef30f113bef98309cf2e6d4e00a97c1d678282ebd78d`
- `agents/core/video_analysis.py`: `d96fd5ea6dfd5bbafa9c0c34c9b8ae2d61fce99dd4ed9ec550008e32c2e9747e`
- `tests/test_h277_vision_normalization.py`: `11adb95c6b109685ffc614704e99c8a444ebdc99629102e498fad64809ec40a1`
- `tests/test_h277_image_empty_retry.py`: `b1e96698c3250422d097e39e0e485da9d26c32a0f35e11b3479da5d1e34b92d7`

Caveats: no full backend suite, live provider test, push, merge or deploy in this worker. The shared `tests/test_h277_video_empty_retry.py` and Gemini files are owned by other writers; their concurrent edits were present during final focused validation. The final command passed against the then-current shared checkout, and parent should rerun integration after any later edits. No Graft rebuild was done in this worker; coordinator owns source index freshness and final integration evidence.
