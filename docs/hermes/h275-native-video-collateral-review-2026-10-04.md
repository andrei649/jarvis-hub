# H275 video safe-mode collateral review

## Finding

The H277 native Gemini/OpenRouter additions do not bypass H275's optional-video safe-mode refusal and do not widen capability while safe mode is on. The stale `agents/core/llm/video_policy.py` change is confined to video provider description, OpenRouter policy/key binding, and provider-block serialization. The central safe-mode gate is byte-for-byte unchanged from committed `HEAD` (`git show HEAD:agents/core/llm/video_policy.py`, also present in `a5b74939`): `authorization_check` checks the feature switch and then `safe_mode.enabled()` at lines 185–199, before authorization, dispatch, or user-byte reading. It re-resolves the selected exact target after the flag check.

The new OpenRouter descriptor branch (`agents/core/llm/video_policy.py:83–123`, `145–174`) only reads/validates configured routing policy and credentials, then binds them into the identity. It does not perform network I/O or construct the model client. Every route, including OpenRouter and Gemini, passes through the same `_binding` authorization loop (`agents/core/video_analysis.py:250–273`). The execution path calls that same binding in its initial `check()` before source bytes are read and again before route attempts (`video_analysis.py:448–474`); each attempt constructs the HTTP client only afterward (`video_analysis.py:378–394`), and its physical-request scope rechecks authority before dispatch and during cleanup (`video_analysis.py:388–429`). Therefore safe mode refuses before video bytes are read or a model client/request is used. Gemini's native body selection and OpenRouter's added body field do not alter this shared order.

## Prior evidence and test coverage

The filtered H275 assessment row says safe mode refuses optional video and that `authorization_check` is the gate; H275 `remaining` is empty. Its evidence pin for `agents/core/llm/video_policy.py` is the sole stale path from the supplied impact file. `tests/test_h275_safe_mode.py:655–707` continues to enforce that `video_policy.py` is among the direct safe-mode readers. `tests/test_h277_video_analysis.py:319–347` tests the shared authorization refusal under safe mode (using a remote OpenAI-compatible route). The new OpenRouter fixture has 22 focused cases but none explicitly turns on safe mode; its route-change and request-boundary cases are in `tests/test_h277_openrouter_video.py:160–344`. This leaves a small provider-specific regression-test opportunity, although source inspection finds no bypass branch.

## Refresh recommendation and limit

After the frozen full run terminates successfully, H275's existing equivalent semantic claim can be refreshed for this stale source path, with the current `video_policy.py` evidence pin and this collateral review recorded. This is not new H277 or live-provider equivalence credit. No tests were run for this review, and no OpenRouter/Gemini provider calls were made. A follow-up synthetic test could configure OpenRouter, enable safe mode, call the normal video intake/authorization boundary, and assert no model-client construction/request; it should not add live acceptance claims.

## Coordinator verification

The coordinator re-read the unchanged safe-mode gate, the all-route binding
loop, execution-before-read order and physical request checks. The frozen backend
finished with 22,383 passes,34 ordinary skips,one existing xfail and zero failures
or errors. All3,008 inputs were unchanged. The provider-specific test limitation
above remains. See [full evidence](evidence/h277-openrouter-video-full-2026-10-04.json).
