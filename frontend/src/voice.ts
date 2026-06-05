// @ts-nocheck
/* HUD v2 · voice loop — browser-side, hands-free conversation.

   The engines (Whisper STT, edge-tts/XTTS) live on the server, but they were built
   for a mic wired to the host. The HUD runs in a browser, so THIS is the missing
   bridge: capture mic audio (getUserMedia + MediaRecorder), VAD-segment one utterance,
   POST it to the local Whisper endpoint (/api/voice/stt), hand the transcript to the
   chat turn, then speak the reply back — server /tts (your cloned voice) with a
   fully-local browser speechSynthesis fallback. Loops until you toggle it off.

   HONESTY: it degrades loudly, never fakes. No mic permission, no local STT installed,
   or an unsupported browser → a clear status/error, not a pretend transcript.

   Verified by typecheck/build only — live mic/audio needs a real browser + device,
   which a headless CI container can't provide. Auto barge-in (interrupt the spoken
   reply by talking over it) is intentionally deferred: it needs on-device echo-
   cancellation tuning to avoid the assistant interrupting itself. Tap the mic to cut a
   reply short for now. */
import { useEffect, useRef, useState, useCallback } from 'react';
import { getToken } from './api/client';

const SILENCE_MS = 1100;     // trailing silence (after speech) that ends an utterance
const SPEECH_RMS = 0.025;    // mic RMS treated as "speaking"
const MAX_UTTER_MS = 15000;  // hard cap per utterance
const WAIT_SPEECH_MS = 7000; // give up a turn if no speech after listening starts

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

export function useVoice({ lang = 'ro', onTurn } = {}) {
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

  // capabilities — honest "what can this host actually do"
  useEffect(() => {
    let alive = true;
    fetch('/api/voice/capabilities').then((r) => (r.ok ? r.json() : null)).then((c) => { if (alive && c) setCaps(c); }).catch(() => {});
    return () => { alive = false; };
  }, []);

  const tok = (extra) => { const h = extra || {}; const t = getToken(); if (t) h['X-User-Token'] = t; return h; };

  async function ensureStream() {
    if (streamRef.current) return streamRef.current;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    streamRef.current = stream;
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
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
    const fd = new FormData(); fd.append('audio', blob, 'rec.webm');
    const res = await fetch(`/api/voice/stt?lang=${encodeURIComponent(langRef.current)}`, { method: 'POST', headers: tok(), body: fd });
    if (res.status === 503) { setCaps((c) => ({ ...(c || {}), stt: false })); throw new Error('local STT not installed (pip install faster-whisper)'); }
    if (!res.ok) throw new Error('stt ' + res.status);
    const d = await res.json();
    const t = (d && d.text || '').trim();
    if (!t || t.charAt(0) === '[') return '';    // [silence] / [STT unavailable] → nothing said
    return t;
  }

  async function listenOnce() {
    setError(null); setStatus('listening'); setTranscript('');
    let blob = null;
    try { blob = await recordUtterance(); } catch { /* */ }
    setLevel(0);
    if (!activeRef.current) return '';
    setStatus('transcribing');
    try { return await transcribe(blob); }
    catch (e) { setError(String((e && e.message) || e)); setStatus('error'); activeRef.current = false; setActive(false); releaseStream(); return ''; }
  }

  const speak = useCallback(async (text) => {
    if (!text) return;
    if (cancelSpeakRef.current) cancelSpeakRef.current();
    let cancelled = false;
    cancelSpeakRef.current = () => {
      cancelled = true;
      try { if (audioRef.current) audioRef.current.pause(); } catch { /* */ }
      try { if (window.speechSynthesis) window.speechSynthesis.cancel(); } catch { /* */ }
    };
    try {
      const res = await fetch('/tts', { method: 'POST', headers: tok({ 'Content-Type': 'application/json' }), body: JSON.stringify({ text, lang: langRef.current }) });
      if (cancelled) return;
      if (res.ok) {
        const blob = await res.blob(); if (cancelled) return;
        const url = URL.createObjectURL(blob);
        await new Promise((resolve) => { const a = new Audio(url); audioRef.current = a; a.onended = () => resolve(null); a.onerror = () => resolve(null); a.play().catch(() => resolve(null)); });
        try { URL.revokeObjectURL(url); } catch { /* */ }
      } else {
        await browserSpeak(text, langRef.current, () => cancelled);  // local fallback, no network
      }
    } catch { await browserSpeak(text, langRef.current, () => cancelled); }
    finally { audioRef.current = null; }
  }, []);

  const cancelSpeak = useCallback(() => { if (cancelSpeakRef.current) cancelSpeakRef.current(); }, []);

  async function loop() {
    while (activeRef.current) {
      const text = await listenOnce();
      if (!activeRef.current) break;
      if (!text) continue;                       // silence → just listen again
      setTranscript(text);
      let reply = '';
      try { reply = (onTurnRef.current && (await onTurnRef.current(text))) || ''; } catch { /* */ }
      if (!activeRef.current) break;
      if (reply) { setStatus('speaking'); await speak(reply); }
    }
    if (status !== 'error') setStatus('off');
    setLevel(0);
  }

  const start = useCallback(async () => {
    if (!supported) { setError('Voice not supported in this browser'); setStatus('error'); return; }
    if (activeRef.current) return;
    if (caps && caps.stt === false) { setError('Local speech-to-text not installed on the server (pip install faster-whisper)'); setStatus('error'); return; }
    setError(null);
    try { await ensureStream(); } catch { setError('Microphone permission denied'); setStatus('error'); return; }
    activeRef.current = true; setActive(true); setStatus('idle');
    loop();
  }, [supported, caps]);

  const stop = useCallback(() => {
    activeRef.current = false; setActive(false);
    if (cancelSpeakRef.current) cancelSpeakRef.current();
    releaseStream(); setStatus('off'); setLevel(0);
  }, []);

  const toggle = useCallback(() => { if (activeRef.current) stop(); else start(); }, [start, stop]);

  useEffect(() => () => { activeRef.current = false; if (cancelSpeakRef.current) cancelSpeakRef.current(); releaseStream(); }, []);

  return { supported, caps, status, error, transcript, level, active, start, stop, toggle, speak, cancelSpeak };
}
