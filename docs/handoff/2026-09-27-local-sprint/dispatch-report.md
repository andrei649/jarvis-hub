# H517 named speech dispatch — Task 2 frozen

Local-only implementation in the existing dirty working tree. Owned source/test paths only; no commits, full suite, installs, live providers or subagents. Existing source baseline preserved under `/tmp/h517-named-baseline/voice/`.

## Changes

Actual named TTS/STT execution now resolves typed command providers through the shared ProviderRegistry and existing guarded bounded process runners. Per-name stored approval, provider ID/revision, executable/file identity, arming and safe mode are checked initially and again after slot acquisition. Original selected ID remains pinned through async selection, slot waiting and the existing Whisper/thread fallback handoff. No new execution lane or importable plugin loader.

TTS explicit missing/invalid `provider:<id>` refuses before legacy/vendor dispatch. Valid named runtime failures retain existing safe fallback; persona consent and local_only remain enforced. STT retains auto/loaded-Whisper preference, whisper-only/command-only choices, exact unavailable/silence sentinels and legacy private override signatures. Cheap readiness/catalog metadata does not spawn or load models. Unreadable named storage refuses, without legacy named fallback.

## RED/GREEN evidence

- Genuine initial RED: three missing/invalid/reserved explicit TTS names incorrectly fell through to vendor output. `/tmp/h517-named-dispatch-red.xml`; initial three GREEN `/tmp/h517-named-dispatch-initial-green.xml`.
- Genuine additional RED: initial async loaded-Whisper selection followed by mode/selector change in the thread handoff produced beta speech instead of original alpha. `/tmp/h517-named-whisper-handoff-red.xml`. Thread-scoped ContextVar pin fixes the race while retaining self.transcribe override behavior and resetting in finally.
- Final normal-project pytest run: **188 passed, 0 failed/error/skipped**, 28.808 seconds. **30 new dispatch cases +158 existing voice/config/authority cases**. `/tmp/h517-named-dispatch-final.xml`.
- Final command: `.venv/bin/python3.12 -m pytest tests/test_h517_named_provider_dispatch.py tests/test_h613_piper_command_voice.py tests/test_voice_stt.py tests/test_stt_config.py tests/test_h517_voice_revision.py tests/test_h517_voice_authority_integration.py -q --junitxml=/tmp/h517-named-dispatch-final.xml`.
- Ruff all five owned paths and scoped git diff --check passed.

## Meaningful integration coverage

Real strict signed request/register/accept/tick installs approved named programs. Two programs on each side emit distinguishable synthetic WAV/transcript outputs through real bounded subprocess execution. Tests confirm registry lookup, default/language selection, selected-STT readiness, command-only missing-name refusal, vendor-prefix safety, consent/local_only refusal, unavailable store, unchanged private legacy overrides, hallucination/blank sentinels, unarmed/safe-mode no execution.

Real slot races independently prove selector drift continues the original program; same-argv table revision replacement and per-name revocation refuse the waiting request. The Whisper thread-handoff race also pins the original identity. No permission authority is fabricated; test programs/files and approved records are synthetic.

## Limits / remaining integration

No unresolved known defect in the owned slice. Parent owns HTTP/HUD/catalog/image joined tests and the full backend milestone; this report does not claim those gates. Vendor fallback is only mocked; no live provider/network was used. This closes named approved-command speech dispatch, not arbitrary host Python adapters or universal media-provider parity. Existing Starlette/httpx deprecation and two existing AsyncMock unawaited warnings in test_voice_stt remain; tests pass.

## Frozen source SHA256

- `agents/core/voice/local_providers.py`: `80f394d6b5e839b2a60d057176134bda8bb3270e17a52a0f13be0fdddc14ce17`
- `agents/core/voice/tts.py`: `5b48f339b97506bc4a4b5fff413b68b3da6fa41033818508381eb98f8b8c5d34`
- `agents/core/voice/stt.py`: `299c00661907a8088070d71622e65d5a166f6ac5b7b8bf32b6e8b553039026b9`
- `agents/core/voice/provider_registry.py`: `037649d895a07aadb6a347bd819ef865d6c264e329659718a28b2f51daefdf06`
- `tests/test_h517_named_provider_dispatch.py`: `958830a54f51fd381afc1bd76f3910b4d8ba5751ab30799902b2afe8145641f4`
