/* HUD v2 · voice loop — browser-side, hands-free conversation.

   The engines (Whisper STT, edge-tts/XTTS) live on the server, but they were built
   for a mic wired to the host. The HUD runs in a browser, so THIS is the missing
   bridge: capture mic audio (getUserMedia + MediaRecorder), VAD-segment one utterance,
   POST it to the local Whisper endpoint (/api/voice/stt), hand the transcript to the
   chat turn, then speak the reply back — server /tts (your cloned voice) with a
   fully-local browser speechSynthesis fallback. Loops until you toggle it off.

   HONESTY: it degrades loudly, never fakes. No mic permission, no local STT installed,
   or an unsupported browser → a clear status/error, not a pretend transcript.

   Covered by jsdom state-machine tests with mocked browser audio APIs; live mic/audio
   still needs a real browser + device. Auto barge-in (interrupt the spoken reply by
   talking over it) is OPT-IN and default-off (EXPERIMENTAL): it relies on the mic's
   echo cancellation, so it needs on-device tuning to avoid the assistant cutting
   itself off. With it off, tap the mic to cut a reply short. */
import { useEffect, useRef, useState, useCallback } from 'react';
import { getToken } from './api/client';
import { streamTts } from './api/ttsStream';

const SILENCE_MS = 1100;     // trailing silence (after speech) that ends an utterance
const SPEECH_RMS = 0.025;    // mic RMS treated as "speaking"
const MAX_UTTER_MS = 15000;  // hard cap per utterance
const WAIT_SPEECH_MS = 7000; // give up a turn if no speech after listening starts
const BARGE_RMS = 0.045;     // higher bar than SPEECH_RMS — only real speech, not TTS echo, triggers barge-in
const BARGE_MS = 360;        // sustained over-talk before we cut the reply

function browserSpeak(text, lang, cancelled) {
  return new Promise((resolve) => {
    try {
      if (typeof window === 'undefined' || !('speechSynthesis' in window)) return resolve(null);
      if (cancelled && cancelled()) return resolve(null);
      const u = new SpeechSynthesisUtterance(text);
      u.lang = lang === 'ro' ? 'ro-RO' : 'en-US';
      u.onend = () => resolve(null);
      u.onerror = () => resolve(null);
      window.speechSynthesis.speak(u);
    } catch { resolve(null); }
  });
}

export function useVoice({ lang = 'ro', mode = 'hands-free', ttsSource = 'server', micMuted = false, barge = false, onTurn }: { lang?: string; mode?: string; ttsSource?: string; micMuted?: boolean; barge?: boolean; onTurn?: (...args: any[]) => any } = {}) {
  const supported = typeof navigator !== 'undefined'
    && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)
    && typeof window !== 'undefined' && 'MediaRecorder' in window;

  const [caps, setCaps] = useState(null);
  const [status, setStatus] = useState('off');  // off | idle | listening | transcribing | speaking | error
  const [error, setError] = useState(null);
  const [transcript, setTranscript] = useState('');
  const [level, setLevel] = useState(0);
  const [active, setActive] = useState(false);

  const streamRef = useRef(null);
  const acRef = useRef(null);
  const anRef = useRef(null);
  const recRef = useRef(null);
  const audioRef = useRef(null);
  const activeRef = useRef(false);
  const cancelSpeakRef = useRef(null);
  const onTurnRef = useRef(onTurn);
  onTurnRef.current = onTurn;
  const langRef = useRef(lang);
  langRef.current = lang;
  const modeRef = useRef(mode); modeRef.current = mode;             // 'hands-free' | 'ptt'
  const ttsRef = useRef(ttsSource); ttsRef.current = ttsSource;     // 'server' | 'browser' | 'off'
  const micMutedRef = useRef(micMuted); micMutedRef.current = micMuted;
  const bargeRef = useRef(barge); bargeRef.current = barge;          // opt-in talk-over interrupt (experimental)
  // Monotonic start generation. `getUserMedia()` can sit on a permission prompt for
  // seconds; a stop(), a lost permission or an unmount in that window must WIN. Every
  // start takes a generation, and anything that cancels bumps it — so a late-resolving
  // permission finds itself stale, kills the tracks it was handed, and publishes nothing.
  // Without this, releasing push-to-talk while the prompt is up still opens the mic.
  const startGenRef = useRef(0);
  const statusRef = useRef('off');
  const setStat = (s) => { statusRef.current = s; setStatus(s); };  // status + ref (avoids stale-closure reads)

  // capabilities — honest "what can this host actually do"
  useEffect(() => {
    let alive = true;
    fetch('/api/voice/capabilities').then((r) => (r.ok ? r.json() : null)).then((c) => { if (alive && c) setCaps(c); }).catch(() => {});
    return () => { alive = false; };
  }, []);

  const tok = (extra?: any) => { const h = extra || {}; const t = getToken(); if (t) h['X-User-Token'] = t; return h; };

  async function ensureStream(gen) {
    if (streamRef.current) return streamRef.current;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    if (gen !== startGenRef.current) {
      // superseded while the prompt was open — hang up on the mic and publish nothing
      try { stream.getTracks().forEach((t) => t.stop()); } catch { /* ignore */ }
      return null;
    }
    streamRef.current = stream;
    try {
      const AC = window.AudioContext || (window as typeof window & { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      const ac = new AC();
      try { ac.resume && ac.resume(); } catch { /* ignore */ }
      const src = ac.createMediaStreamSource(stream);
      const an = ac.createAnalyser(); an.fftSize = 1024;
      src.connect(an);
      acRef.current = ac; anRef.current = an;
    } catch { /* analyser optional — VAD just won't fire, manual stop still works */ }
    return stream;
  }

  function releaseStream() {
    try { if (recRef.current && recRef.current.state !== 'inactive') recRef.current.stop(); } catch { /* */ }
    try { if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop()); } catch { /* */ }
    try { if (acRef.current) acRef.current.close(); } catch { /* */ }
    streamRef.current = null; acRef.current = null; anRef.current = null;
  }

  function rms() {
    const an = anRef.current; if (!an) return 0;
    const buf = new Uint8Array(an.fftSize); an.getByteTimeDomainData(buf);
    let s = 0; for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; s += v * v; }
    return Math.sqrt(s / buf.length);
  }

  function pickMime() {
    const opts = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];
    for (const m of opts) { try { if (window.MediaRecorder && MediaRecorder.isTypeSupported(m)) return m; } catch { /* */ } }
    return '';
  }

  // Play one audio buffer to completion (or until cancelled). Sets audioRef so the
  // barge-in / cancelSpeak path can pause it. Resolves on end/error/cancel — never rejects.
  function playAudioBlob(blob, isCancelled) {
    return new Promise((resolve) => {
      if (isCancelled && isCancelled()) return resolve(null);
      let url;
      try { url = URL.createObjectURL(blob); } catch { return resolve(null); }
      const a = new Audio(url);
      audioRef.current = a;
      const done = () => { try { URL.revokeObjectURL(url); } catch { /* */ } resolve(null); };
      a.onended = done; a.onerror = done;
      a.play().catch(done);
    });
  }

  // record ONE VAD-segmented utterance → Blob | null
  function recordUtterance() {
    return new Promise((resolve) => {
      const stream = streamRef.current; if (!stream) return resolve(null);
      const chunks = [];
      let rec;
      try { const m = pickMime(); rec = m ? new MediaRecorder(stream, { mimeType: m }) : new MediaRecorder(stream); }
      catch { return resolve(null); }
      recRef.current = rec;
      rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
      rec.onstop = () => { clearInterval(iv); resolve(chunks.length ? new Blob(chunks, { type: chunks[0].type || 'audio/webm' }) : null); };
      const t0 = Date.now(); let speechAt = 0; let lastVoice = 0;
      const iv = setInterval(() => {
        const lv = rms(); setLevel(lv);
        const now = Date.now();
        if (lv >= SPEECH_RMS) { if (!speechAt) speechAt = now; lastVoice = now; }
        const dur = now - t0;
        const ended = (speechAt && now - lastVoice > SILENCE_MS) || dur > MAX_UTTER_MS || (!speechAt && dur > WAIT_SPEECH_MS);
        if (ended || !activeRef.current) { try { if (rec.state !== 'inactive') rec.stop(); } catch { /* */ } }
      }, 60);
      try { rec.start(); } catch { clearInterval(iv); resolve(null); }
    });
  }

  async function transcribe(blob) {
    if (!blob || blob.size < 1400) return '';   // too short to be real speech
    const res = await fetch(`/api/voice/stt?lang=${encodeURIComponent(langRef.current)}`, { method: 'POST', headers: tok({ 'Content-Type': blob.type || 'audio/webm' }), body: blob });
    if (res.status === 503) { setCaps((c) => ({ ...(c || {}), stt: false })); throw new Error('local STT not installed (pip install faster-whisper)'); }
    if (!res.ok) throw new Error('stt ' + res.status);
    const d = await res.json();
    const t = (d && d.text || '').trim();
    if (!t || t.charAt(0) === '[') return '';    // [silence] / [STT unavailable] → nothing said
    return t;
  }

  async function listenOnce() {
    setError(null); setStat('listening'); setTranscript('');
    let blob = null;
    try { blob = await recordUtterance(); } catch { /* */ }
    setLevel(0);
    if (!activeRef.current) return '';
    setStat('transcribing');
    try { return await transcribe(blob); }
    catch (e) { setError(String((e && e.message) || e)); setStat('error'); activeRef.current = false; setActive(false); releaseStream(); return ''; }
  }

  const speak = useCallback(async (text) => {
    if (!text || ttsRef.current === 'off') return;
    if (cancelSpeakRef.current) cancelSpeakRef.current();
    let cancelled = false;
    let bargeIv = null;
    cancelSpeakRef.current = () => {
      cancelled = true;
      try { if (audioRef.current) audioRef.current.pause(); } catch { /* */ }
      try { if (window.speechSynthesis) window.speechSynthesis.cancel(); } catch { /* */ }
      if (bargeIv) { clearInterval(bargeIv); bargeIv = null; }
    };
    // Opt-in barge-in: while the reply plays, watch the mic — sustained over-talk cancels
    // playback so the loop captures the user. EXPERIMENTAL (echo-cancellation dependent).
    if (bargeRef.current && anRef.current) {
      let voiceMs = 0;
      bargeIv = setInterval(() => {
        if (cancelled) return;
        const lv = rms();
        if (lv >= BARGE_RMS) { voiceMs += 130; if (voiceMs >= BARGE_MS && cancelSpeakRef.current) cancelSpeakRef.current(); }
        else voiceMs = Math.max(0, voiceMs - 130);
      }, 130);
    }
    try {
      // 'browser' → fully-local speechSynthesis; 'server' → cloned voice via /tts, fall back to local
      if (ttsRef.current === 'browser') {
        await browserSpeak(text, langRef.current, () => cancelled);
      } else {
        // H5.16: try sentence-level streaming first — each sentence plays as soon as it's
        // synthesized, so audio starts after sentence #1 instead of the whole reply. The
        // endpoint is opt-in server-side (default off → 409), so this falls back cleanly to
        // the whole-reply /tts path below. 'streamed' means we already played the audio.
        const streamed = await streamTts(
          text, langRef.current,
          (frame) => playAudioBlob(new Blob([frame.audio as BlobPart], { type: 'audio/mpeg' }), () => cancelled) as Promise<void>,
          { headers: tok(), cancelled: () => cancelled },
        );
        if (!cancelled && streamed !== 'streamed' && streamed !== 'cancelled') {
          // Whole-reply fallback (unchanged behavior): synthesize the full reply, then play.
          const res = await fetch('/tts', { method: 'POST', headers: tok({ 'Content-Type': 'application/json' }), body: JSON.stringify({ text, lang: langRef.current }) });
          if (!cancelled) {
            if (res.ok) {
              const blob = await res.blob();
              if (!cancelled) await playAudioBlob(blob, () => cancelled);
            } else {
              await browserSpeak(text, langRef.current, () => cancelled);  // local fallback, no network
            }
          }
        }
      }
    } catch { if (!cancelled) await browserSpeak(text, langRef.current, () => cancelled); }
    finally { if (bargeIv) clearInterval(bargeIv); audioRef.current = null; }
  }, []);

  const cancelSpeak = useCallback(() => { if (cancelSpeakRef.current) cancelSpeakRef.current(); }, []);

  async function loop() {
    while (activeRef.current) {
      const text = await listenOnce();
      if (!activeRef.current) break;
      if (text) {
        setTranscript(text);
        let reply = '';
        try { reply = (onTurnRef.current && (await onTurnRef.current(text))) || ''; } catch { /* */ }
        if (!activeRef.current) break;
        if (reply && ttsRef.current !== 'off') { setStat('speaking'); await speak(reply); }
      }                                          // (silence → just listen again in hands-free)
      if (modeRef.current === 'ptt') break;      // push-to-talk: exactly one turn per activation
    }
    // natural loop exit (PTT one-shot, or stop()) → free the mic and go idle
    activeRef.current = false; setActive(false); releaseStream();
    if (statusRef.current !== 'error') setStat('off');
    setLevel(0);
  }

  const start = useCallback(async () => {
    if (!supported) { setError('Voice not supported in this browser'); setStat('error'); return; }
    if (activeRef.current) return;
    if (micMutedRef.current) { setError('Mic is muted — unmute JARVIS to use voice'); setStat('error'); return; }
    if (caps && caps.stt === false) { setError('Local speech-to-text not installed on the server (pip install faster-whisper)'); setStat('error'); return; }
    setError(null);
    const gen = ++startGenRef.current;
    let stream = null;
    try { stream = await ensureStream(gen); } catch {
      // A rejection from a SUPERSEDED start must stay silent: it would otherwise overwrite
      // the OFF state a stop() just set, or report an error over a newer capture that is
      // already running. Only the current generation may publish permission-denied.
      if (gen !== startGenRef.current) return;
      setError('Microphone permission denied'); setStat('error'); return;
    }
    // cancelled while the permission prompt was up: never go active, never enter the loop
    if (!stream || gen !== startGenRef.current) return;
    activeRef.current = true; setActive(true); setStat('idle');
    loop();
  }, [supported, caps]);

  const stop = useCallback(() => {
    startGenRef.current++;               // invalidate any start still awaiting permission
    activeRef.current = false; setActive(false);
    if (cancelSpeakRef.current) cancelSpeakRef.current();
    releaseStream(); setStat('off'); setLevel(0);
  }, []);

  const toggle = useCallback(() => { if (activeRef.current) stop(); else start(); }, [start, stop]);

  useEffect(() => () => { startGenRef.current++; activeRef.current = false; if (cancelSpeakRef.current) cancelSpeakRef.current(); releaseStream(); }, []);

  return { supported, caps, status, error, transcript, level, active, start, stop, toggle, speak, cancelSpeak };
}
