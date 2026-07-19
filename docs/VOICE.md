# Jarvis Hub — Voice Subsystem

> How voice works end-to-end, what is real vs. scaffolded, and how to extend it.
> Module index: [ARCHITECTURE.md](ARCHITECTURE.md) §3 · backlog: [../BACKLOG.md](../BACKLOG.md)
> Delivered: PR #162 (browser loop + settings), PR #164 (opt-in barge-in).

---

## 1. Two voice paths (don't confuse them)

Jarvis has **two independent voice front-ends** that share the same engines:

| Path | Mic lives on | Status | Entry point |
|------|--------------|--------|-------------|
| **A. Server-side pipeline** ("Howard") | the **host** running `serve.py` | scaffolded, optional deps, hardware-required | `agents/core/voice/pipeline.py` |
| **B. Browser HUD loop** | the **user's browser** (`/v2`) | **real**, shipped, degrades honestly | `frontend/src/voice.ts` |

The engines (`stt.py`, `tts.py`) were originally written for **Path A** — a microphone wired
to the server. But the HUD runs in a browser on a different machine, so its mic button used
to be a dead toggle. **Path B** is the bridge that makes "talk to Jarvis in the interface"
actually work. Most users want Path B.

---

## 2. Path B — the browser HUD loop (the one that ships)

### Data flow (hands-free)

```
mic (getUserMedia)
  → MediaRecorder, VAD-segmented utterance      [voice.ts: recordUtterance]
  → POST /api/voice/stt  (raw audio body)        [web.py: stt_endpoint → STTEngine]
  → transcript
  → runTurn(text)  → POST /chat/stream           [app.tsx: runTurn, resolves final reply]
  → reply text
  → speak(reply): POST /tts (cloned voice)        [voice.ts: speak → web.py /tts]
        ↳ fallback: browser speechSynthesis (fully local, no network)
  → playback
  → loop back to listen (hands-free) until toggled off
```

Push-to-talk mode runs one pass of the same flow per mic tap.

### Backend endpoints (`agents/web.py`)

| Endpoint | Purpose | Honest degradation |
|----------|---------|--------------------|
| `POST /api/voice/stt?lang=ro` | Raw audio body (browser `MediaRecorder` blob) → local Whisper transcript `{text, lang}`. Engine cached via `_stt_engine()`. | `503 {stt:false, error:"…pip install faster-whisper"}` when Whisper absent — **never a fabricated transcript**. |
| `GET /api/voice/capabilities` | What this host can actually do: `{stt, tts, tts_local, providers}`. Drives the HUD's honest state. | Always returns real booleans; browser knows it always has a local `speechSynthesis` fallback. |
| `POST /tts` | Text → audio (cloned voice). `TTSEngine.speak` fallback chain. | `503` when `edge-tts` absent (and no other provider). |
| `POST /tts/stream` | **Sentence-level streaming (H5.16, opt-in).** Splits the reply into sentences (`core/voice/sentence_stream.py:split_sentences`) and streams each sentence's audio as soon as it's synthesized, so playback can start after sentence #1 instead of the whole reply. | `409 {enabled:false}` when the `voice.sentence_streaming` setting is off (**default**); `503` when `edge-tts` absent. |

> **Sentence-level streaming wire framing.** `/tts/stream` returns a single
> `application/octet-stream` body of ordered frames, one per sentence:
> a single-line JSON header `{"idx","text","lang","bytes","done"}` + `\n` + exactly
> `bytes` raw audio bytes. A terminal `{"done":true,"bytes":0}` frame closes the
> stream; a sentence that failed to synthesize gets `bytes:0` (skip it). Segmentation
> is pure/unit-tested (`SentenceAggregator` also supports incremental token streams);
> only per-chunk synthesis touches a backend. Gated by `voice.sentence_streaming`
> (default off — fully back-compatible; the browser loop still uses `/tts`).

> **Raw body, not multipart.** `/api/voice/stt` reads `await request.body()` rather than an
> `UploadFile` — deliberately, so it needs **no `python-multipart`** dependency. (A `File(...)`
> route makes FastAPI demand `python-multipart` at *route registration*, which broke `import web`
> and 21 test files at collection — see PR #162's fix commit.) The frontend POSTs the `Blob`
> directly as the body with `Content-Type: audio/webm`.

### Frontend hook (`frontend/src/voice.ts`)

`useVoice({ lang, mode, ttsSource, micMuted, barge, onTurn })` →
`{ supported, caps, status, error, transcript, level, active, start, stop, toggle, speak, cancelSpeak }`.

- **Capture + VAD:** `getUserMedia({audio:{echoCancellation,noiseSuppression,autoGainControl}})`,
  an `AnalyserNode` computes mic RMS. `recordUtterance()` stops on trailing silence
  (`SILENCE_MS`), a hard cap (`MAX_UTTER_MS`), or no-speech timeout (`WAIT_SPEECH_MS`).
- **STT call:** `transcribe()` POSTs the blob; treats `[silence]`/`[STT unavailable]` and 503 as
  "nothing said" / honest error, never text.
- **Turn loop:** `loop()` = listen → `onTurn(text)` (the app's `runTurn`, which streams the chat
  reply and resolves the final text) → `speak(reply)` → repeat while `active`.
- **TTS:** `speak()` honors `ttsSource`: `'server'` (cloned voice via `/tts`, falls back to local),
  `'browser'` (fully-local `speechSynthesis`), `'off'` (silent). Cancellable (`cancelSpeak`).
- **Barge-in (opt-in, experimental):** when `barge` is on, a mic monitor runs during playback;
  sustained over-talk above `BARGE_RMS` for `BARGE_MS` cancels the reply so the loop captures the
  user. Default **off** — it depends on the mic's echo cancellation and needs on-device tuning.

### Settings (persisted in `localStorage['hud.voice']`)

Edited via the ⚙ popover next to the mic (`cockpit.tsx: InputBar`):

| Key | Values | Default | Meaning |
|-----|--------|---------|---------|
| `mode` | `hands-free` \| `ptt` | `hands-free` | Continuous loop vs. push-to-talk. |
| `tts` | `server` \| `browser` \| `off` | `server` | `server` = the `/tts` chain (your **cloned** voice *only if XTTS is configured*, else edge); `browser` = local `speechSynthesis`. |
| `lang` | `auto` \| `ro` \| `en` | `auto` | `auto` follows the HUD language. |
| `barge` | `off` \| `on` | `off` | Experimental talk-over interrupt. |

The mic respects `JARVIS_MIC_MUTED` (surfaced via `/api/trust/status` → `trust.mic`): when the
physical/soft mute is on, the loop won't start.

---

## 3. Path A — the server-side pipeline ("Howard")

For a mic attached to the **server** (e.g. a dedicated Jarvis box). Scaffolded; every part needs
an optional dependency and real hardware, and **fails silently (logs a warning) when absent** —
so a headless deploy is unaffected.

| File | Purpose | Optional dep |
|------|---------|--------------|
| `agents/core/voice/pipeline.py` (`VoicePipeline`) | wake → record → STT → orchestrator → TTS → play (`pygame`) | `pyaudio`, `pygame` |
| `agents/core/voice/wake_word.py` (`WakeWordDetector`) | always-on "jarvis"/"hub" detection | `openwakeword`, `pyaudio` |
| `agents/core/voice/stt.py` (`STTEngine`) | faster-whisper (CUDA/CPU), RO default | `faster-whisper`, `torch` |
| `agents/core/voice/tts.py` (`TTSEngine.speak`) | fallback chain **XTTS → ElevenLabs → Fish Audio → edge-tts → Kokoro** | `edge-tts` (+ XTTS server / `ELEVENLABS_API_KEY` / `FISH_AUDIO_API_KEY` for cloning) |
| `agents/core/channels/voice.py` (`VoiceChannel`) | wraps the pipeline as an orchestrator channel | — |
| `agents/core/voice/wyoming.py` (`WyomingServer`) | Wyoming protocol (Home Assistant satellites); **not auto-started**, gated by setting `voice.wyoming_enabled` (port 10700) | — |

TTS env: `XTTS_SERVER_URL` (default `http://localhost:8020/api/tts`), `XTTS_SPEAKER_WAV`
(default `data/voice_clone/andrei.wav`), `ELEVENLABS_API_KEY`, `FISH_AUDIO_API_KEY` +
`FISH_AUDIO_VOICE_ID` (reference voice; or `voice="fish:<reference_id>"`) + `FISH_AUDIO_MODEL`
(default `s1`).

**Emotion tags.** Replies may carry inline square-bracket emotion tags (`[calm]`, `[amused]`,
… — the full set is `tts.py:EMOTION_TAGS`). Fish Audio S-series models render them as delivery;
every other backend gets the text through `strip_emotion_tags()` so tags are never read aloud.
Fish voices count as cloned/persona voices — the same owner-consent gate as XTTS/ElevenLabs
applies (`voice.persona_voice_consent`).

**Spoken morning brief.** The HUD Autonomy panel's MORNING BRIEF header has a 🔊 SPEAK button
(`frontend/src/modes2.tsx`): it reads the brief aloud via `POST /tts` (the chain above) with
the fully-local `speechSynthesis` fallback — same honest degradation as the voice loop.

---

## 4. What's real vs. needs a device (headless / CI)

| Component | Headless-testable? | Notes |
|-----------|--------------------|-------|
| `/api/voice/capabilities`, `/tts` (edge-tts) | ✅ | HTTP-only; edge-tts mocked in tests. |
| `/api/voice/stt` logic | ✅ | `tests/test_voice_stt.py` mocks `HAS_WHISPER` + `_stt_engine` (no model load). |
| Whisper transcription (real) | ❌ | Needs `faster-whisper` + model download + CPU/GPU. |
| Browser mic / playback / VAD / barge-in | ❌ | Needs a real browser + audio device. **Verify on your workstation.** |
| Server-side wake-word + mic capture + `pygame` playback | ❌ | Needs hardware. |
| Wyoming protocol framing | ✅ | `tests/test_h12_4_wyoming.py` (offline). |

**The browser loop is verified by `tsc`/`vite build` + the mocked STT test only.** Live audio
behavior must be confirmed on a real device.

---

## 5. Try it / enable it

```bash
pip install faster-whisper          # local STT (required for Path B mic input)
pip install edge-tts                # online TTS (optional; or run an XTTS server for the clone)
# launch the hub, then open the HUD:
#   /v2  →  click the 🎤  →  speak.
#   ⚙ (next to the mic): MODE / SPEAK / LANG / BARGE-IN
```

If `faster-whisper` isn't installed, the HUD says so (amber note in the ⚙ popover) instead of
pretending to listen.

**Dictation cleanup (0.24, opt-in).** Setting `voice.dictation_cleanup` (default off) runs
`core/voice/dictation.py:clean_dictation` on every `/api/voice/stt` transcript — strips
fillers/stutters, applies spoken punctuation ("period" → "."), and reports the removal counts
in the response (`dictation.removed`) so the edit stays inspectable. Sentinel transcripts are
never touched.

---

## 6. Known gaps / future work

- **Barge-in tuning** — `BARGE_RMS` / `BARGE_MS` in `voice.ts` need on-device calibration vs. your
  room + speakers so the assistant doesn't interrupt itself. Currently opt-in/default-off.
- **Browser wake-word** ("hey jarvis" with no click) — needs a JS wake-word lib (Porcupine,
  licensed) or a cloud hop; not yet implemented. Path A's `openwakeword` is server-only.
- **Sentence-level TTS streaming** — **server side landed** (H5.16): `POST /tts/stream` +
  `core/voice/sentence_stream.py` split a reply into sentences and synthesize/emit each as it's
  ready (opt-in via `voice.sentence_streaming`, default off). **Remaining:** wiring the browser
  loop (`frontend/src/voice.ts`) to consume `/tts/stream` and play chunks back-to-back, and a
  fully token-streamed path (synthesize while the chat is still generating) — the building block
  for that (`SentenceAggregator`) exists and is tested, but the chat→TTS pipe still resolves the
  full reply first.
- **No live `voice_state`** — `/status` reports a static `"idle"`; the HUD owns loop state client-side.
