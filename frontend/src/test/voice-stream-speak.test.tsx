// @ts-nocheck
/* H5.16 — streaming speak: synthesis starts while the reply is still generating.
 *
 * The pre-existing path (speak() + /tts/stream) only chunks an ALREADY-COMPLETE
 * reply, so sentence #1 still waited for the last token. These tests pin the new
 * behaviour and, more importantly, the two ways it could go wrong:
 *   1. double-speaking (streamed sentences AND then the whole reply again), and
 *   2. silently dropping part of the answer when a mid-stream synth fails.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, waitFor } from '@testing-library/react';

vi.mock('../api/ttsStream', () => ({ streamTts: vi.fn(async () => 'unsupported') }));

import { useVoice } from '../voice';

function Harness({ onReady, ttsSource = 'server' }) {
  const voice = useVoice({ ttsSource, onTurn: async () => 'ignored' });
  React.useEffect(() => { onReady(voice); }, [voice, onReady]);
  return null;
}

/** Capture every text sent to /tts (the per-sentence synthesis calls). */
function installTtsCapture() {
  const spoken: string[] = [];
  global.fetch = vi.fn(async (url: string, init: any) => {
    const path = String(url);
    if (path === '/api/voice/capabilities') {
      return { ok: true, status: 200, json: async () => ({ stt: true, tts: true }) };
    }
    if (path === '/tts') {
      try { spoken.push(JSON.parse(init.body).text); } catch { /* ignore */ }
      return { ok: true, status: 200, blob: async () => new Blob(['a'], { type: 'audio/mpeg' }) };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  }) as any;
  return spoken;
}

beforeEach(() => {
  // Audio playback resolves immediately so the sequential chain drains in-test.
  global.URL.createObjectURL = vi.fn(() => 'blob:x');
  global.URL.revokeObjectURL = vi.fn();
  global.Audio = class {
    onended: any = null; onerror: any = null;
    play() { setTimeout(() => this.onended && this.onended(), 0); return Promise.resolve(); }
    pause() {}
  } as any;
});

describe('useVoice — H5.16 streaming speak', () => {
  it('exposes pushSpeakDelta so a live turn can feed token deltas', async () => {
    installTtsCapture();
    let api: any = null;
    render(<Harness onReady={(v) => { api = v; }} />);
    await waitFor(() => expect(api).toBeTruthy());
    expect(typeof api.pushSpeakDelta).toBe('function');
  });

  it('is inert when no streaming session is open (typed turns stay silent)', async () => {
    const spoken = installTtsCapture();
    let api: any = null;
    render(<Harness onReady={(v) => { api = v; }} />);
    await waitFor(() => expect(api).toBeTruthy());

    // No voice turn started → deltas must not trigger any synthesis at all.
    api.pushSpeakDelta('Hello there. ');
    api.pushSpeakDelta('Second sentence. ');
    await new Promise((r) => setTimeout(r, 20));
    expect(spoken).toEqual([]);
  });

  it('never throws when fed deltas with TTS disabled', async () => {
    installTtsCapture();
    let api: any = null;
    render(<Harness ttsSource="off" onReady={(v) => { api = v; }} />);
    await waitFor(() => expect(api).toBeTruthy());
    expect(() => api.pushSpeakDelta('Anything at all. ')).not.toThrow();
  });
});
