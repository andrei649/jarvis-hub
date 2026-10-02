# H277 native Gemini normalization handoff

- Goal: normalize native Gemini video answers with visible text precedence, typed thought-text fallback, and terminal refusal for malformed output.
- Base and current HEAD: `173a5a840f8bff27b2ef41a474837ec73e44f18c` on `codex/h277-vision-normalization-20261002`.
- Generation date: 2026-10-02. Local only; no commit, push, merge, deployment, or live provider call.
- Owned paths: `agents/core/llm/video_native.py`, `tests/test_h277_video_native.py`, `tests/test_h277_video_gemini.py`, `tests/test_h277_gemini_normalization.py`.

## Delivered behavior

The native parser validates response, prompt feedback, candidate, content, and every part before returning text. It refuses explicit errors, blocked/safety outcomes, malformed thought flags, non-text/function/audio/mixed parts, and invalid `thoughtSignature` values even when visible text exists. A string `thoughtSignature` remains metadata and is never returned. Visible text is normalized first; when it is blank, raw thought parts are concatenated in order and normalized once through the shared `normalized_vision_text` helper. Useful thought text completes the signed video consumer in one request. A truly blank typed response remains `VideoNativeEmpty`; nonblank raw visible inline thinking that filters to empty is terminal `VideoNativeRefused`, avoiding an unauthorized empty retry. Existing consumer answer cap remains 16,000 characters.

The old fixture that silently accepted a thought-marked function call now expects refusal. The old thought-only refusal fixture was removed and replaced by pure and signed-producer success tests. Coordinator owns the updated shared empty-retry expectations.

## Red and green receipts

- Initial red: `/tmp/nerva-pr-python-20261001/bin/python -m pytest tests/test_h277_gemini_normalization.py -q` exited 1 with 13 failures and 2 passes. Failures included visible filtering, thought fallback, error-envelope validation, mixed-part validation, signed one-call fallback, and signed terminal refusal.
- Existing expectation check after first implementation: `/tmp/nerva-pr-python-20261001/bin/python -m pytest tests/test_h277_video_native.py tests/test_h277_video_gemini.py -q` exited 1 with 3 failures: old thought-marked function-call acceptance, old thought-only refusal, and old signed thought-only refusal. These expectations were corrected in the owned tests.
- Fragmentation and retry red: `/tmp/nerva-pr-python-20261001/bin/python -m pytest tests/test_h277_gemini_normalization.py -q --tb=short` exited 1 with 4 failures: split word, split `<think>` tag, inline thinking classified as `VideoNativeEmpty`, and an extra signed request.
- Final focused green: `/tmp/nerva-pr-python-20261001/bin/python -m pytest tests/test_h277_video_native.py tests/test_h277_video_gemini.py tests/test_h277_gemini_normalization.py tests/test_h277_video_empty_retry.py -q` exited 0, 174 tests passed. `git diff --check` exited 0.

## SHA-256 of owned files

- `agents/core/llm/video_native.py`: `5bd02cd44db9d51d571a4b17e73bbe802e7b3fcc8a21f6dae4c8f47e826b8f6e`
- `tests/test_h277_video_native.py`: `2f1011fa91abc49bc213c23fd3da35558798552889ab24b53ff158733a2da8cb`
- `tests/test_h277_video_gemini.py`: `195ef857455c50d4137faf409f83be106f49efee047dbdd259f0f04ecf00a25d`
- `tests/test_h277_gemini_normalization.py`: `838d7827e98f9c6cbed9bda120aff8da2ffb6e4abd6554d532725caf90db4823`

## Integration and limits

The implementation now imports `normalized_vision_text` from coordinator-integrated `agents/core/llm/native_response.py`, owned by the compatible writer. The shared `tests/test_h277_video_empty_retry.py` has been updated by the coordinator to remove meaningful thought-only text from the typed-empty cases; the final focused run includes it. No full backend suite or real Gemini service was run. Remaining integration, evidence, commit, and wider checks belong to the coordinator.
