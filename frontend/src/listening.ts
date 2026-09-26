/* H222 — whether Nerva is listening, forwarded to the desktop shell's tray so it shows
   while the HUD windows are hidden or unfocused. The hub's state (its voice pipeline and
   satellites) comes from GET /api/voice/listening/stream, read with the HUD's own token
   (EventSource cannot send one), else from polling GET /api/voice/listening; this
   window's own mic counts as listening. Read-only: nothing here opens or closes a mic,
   and outside the desktop app it asks the hub nothing. */
import { useEffect, useState } from 'react';
import { apiFetchOnce, apiGet } from './api/client';
import { hasDesktopBridge, setDesktopListening } from './desktop';

export const LISTENING_STATES = ['off', 'armed', 'listening', 'thinking', 'speaking'] as const;
export type Listening = typeof LISTENING_STATES[number];
/** Loudest first: an open mic outranks everything else. */
const ORDER: Listening[] = ['listening', 'armed', 'thinking', 'speaking', 'off'];
export const POLL_MS = 5000;

/** The hub's payload (or a stream frame) as a state; anything malformed is "off". */
export function readListening(raw: unknown): Listening {
  const state = raw && typeof raw === 'object' ? (raw as any).state : undefined;
  return (LISTENING_STATES as readonly unknown[]).includes(state) ? (state as Listening) : 'off';
}

export function loudest(...states: Listening[]): Listening {
  return ORDER.find((s) => states.includes(s)) || 'off';
}

/** Follow the hub's listening state until the returned stop is called: the stream while
 *  it lasts, then a poll every POLL_MS. */
export function followListening(onState: (s: Listening) => void): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const ctrl = new AbortController();
  const poll = () => {
    if (stopped) return;
    apiGet('/api/voice/listening')
      .then((raw) => { if (!stopped) onState(readListening(raw)); })
      .catch(() => { /* hub down or refused: keep the last state */ })
      .finally(() => { if (!stopped) timer = setTimeout(poll, POLL_MS); });
  };
  (async () => {
    try {
      const res = await apiFetchOnce('/api/voice/listening/stream', { accept: 'text/event-stream', signal: ctrl.signal });
      if (!res.ok || !res.body) throw new Error(`listening stream -> ${res.status}`);
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (value) buf += dec.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop() || '';
        for (const line of lines) {
          const text = line.trim();
          if (!text.startsWith('data:')) continue;
          try {
            const frame = JSON.parse(text.slice(5));
            if (!stopped && frame && frame.type === 'listening') onState(readListening(frame));
          } catch { /* malformed frame — ignore */ }
        }
        if (done) break;
      }
    } catch { /* no stream: poll instead */ }
    poll();
  })();
  return () => { stopped = true; ctrl.abort(); if (timer) clearTimeout(timer); };
}

/** The state this window shows the tray: the hub's, or listening while its own mic is on. */
export function useListeningIndicator(demo: boolean, ownMic: boolean): Listening {
  const [hub, setHub] = useState<Listening>('off');
  const desktop = hasDesktopBridge();
  useEffect(() => {
    if (demo || !desktop) { setHub('off'); return undefined; }
    return followListening(setHub);
  }, [demo, desktop]);
  const shown = demo ? 'off' : loudest(hub, ownMic ? 'listening' : 'off');
  useEffect(() => { if (desktop) setDesktopListening(shown); }, [shown, desktop]);
  useEffect(() => () => { if (desktop) setDesktopListening('off'); }, [desktop]);
  return shown;
}
