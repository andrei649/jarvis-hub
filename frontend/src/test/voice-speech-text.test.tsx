// @ts-nocheck
/* H526 — the HUD's voice speaks the reply as speech: no code, reasoning, markup or
 * emoji, whether the reply is spoken whole, by the browser's own voice, or sentence by
 * sentence while it streams. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React, { useEffect } from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

vi.mock('../api/ttsStream', () => ({ streamTts: vi.fn() }));

import { streamTts } from '../api/ttsStream';
import { useVoice } from '../voice';

const REPLY = '**Gata!** Uite 👍:\n```sh\nrm -rf /tmp/x\n```\n- 50% făcut -> [link](https://x.test)';
const SPOKEN = 'Gata! Uite: 50 la sută făcut spre link.';

function jsonResponse(data, opts = {}) {
  const status = opts.status ?? 200;
  return { ok: status >= 200 && status < 300, status, json: async () => data,
    blob: async () => new Blob(['audio'], { type: 'audio/mpeg' }) };
}

function installFetch({ ttsStatus = 200 } = {}) {
  const ttsBodies = [];
  global.fetch = vi.fn(async (url, init) => {
    const path = String(url);
    if (path === '/api/voice/capabilities') return jsonResponse({ stt: true, tts: true });
    if (path.startsWith('/api/voice/stt')) return jsonResponse({ text: 'salut' });
    if (path === '/tts') { ttsBodies.push(JSON.parse(init.body)); return jsonResponse({}, { status: ttsStatus }); }
    throw new Error('unexpected fetch ' + path);
  });
  return ttsBodies;
}

function installMedia() {
  const stream = { getTracks: () => [{ stop: vi.fn() }] };
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true,
    value: { getUserMedia: vi.fn().mockResolvedValue(stream) } });
  class FakeMediaRecorder {
    static isTypeSupported = vi.fn(() => true);
    state = 'inactive'; ondataavailable = null; onstop = null;
    constructor(s, o) { this.s = s; this.o = o; }
    start() {
      this.state = 'recording';
      setTimeout(() => { this.ondataavailable?.({ data: new Blob(['x'.repeat(2048)], { type: 'audio/webm' }) }); this.stop(); }, 0);
    }
    stop() { if (this.state === 'inactive') return; this.state = 'inactive'; setTimeout(() => this.onstop?.(), 0); }
  }
  class FakeAudioContext {
    resume = vi.fn(); close = vi.fn();
    createMediaStreamSource = vi.fn(() => ({ connect: vi.fn() }));
    createAnalyser = vi.fn(() => ({ fftSize: 1024, getByteTimeDomainData: (b) => b.fill(128) }));
  }
  for (const target of [window, globalThis]) {
    Object.defineProperty(target, 'MediaRecorder', { configurable: true, value: FakeMediaRecorder });
    Object.defineProperty(target, 'AudioContext', { configurable: true, value: FakeAudioContext });
  }
}

function installSpeechSynthesis() {
  const said = [];
  class Utterance { constructor(text) { this.text = text; } }
  const synth = { speak: vi.fn((u) => { said.push(u.text); setTimeout(() => u.onend?.(), 0); }), cancel: vi.fn() };
  Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: synth });
  Object.defineProperty(globalThis, 'SpeechSynthesisUtterance', { configurable: true, value: Utterance });
  Object.defineProperty(window, 'SpeechSynthesisUtterance', { configurable: true, value: Utterance });
  return said;
}

function Harness({ opts, text = REPLY, apiRef = null }) {
  const voice = useVoice(opts);
  useEffect(() => { if (apiRef) apiRef.current = voice; }, [voice, apiRef]);
  return (
    <div>
      <button onClick={() => voice.speak(text)}>speak</button>
      <button onClick={() => voice.start()}>start</button>
      <output data-testid="status">{voice.status}</output>
    </div>
  );
}

beforeEach(() => {
  localStorage.clear();
  vi.mocked(streamTts).mockReset();
  vi.mocked(streamTts).mockResolvedValue('disabled');
  class FakeAudio { onended = null; onerror = null; pause = vi.fn(); play() { setTimeout(() => this.onended?.(), 0); return Promise.resolve(); } }
  Object.defineProperty(globalThis, 'Audio', { configurable: true, value: FakeAudio });
  Object.defineProperty(window, 'Audio', { configurable: true, value: FakeAudio });
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:voice');
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
});

describe('useVoice — H526 speech, not markdown', () => {
  it('a whole reply reaches /tts/stream and /tts as speech', async () => {
    const bodies = installFetch();
    render(<Harness opts={{ ttsSource: 'server', lang: 'ro' }} />);
    fireEvent.click(screen.getByText('speak'));
    await waitFor(() => expect(bodies).toEqual([{ text: SPOKEN, lang: 'ro' }]));
    expect(vi.mocked(streamTts).mock.calls[0][0]).toBe(SPOKEN);
  });

  it('a reply with nothing to say is silence: no request at all', async () => {
    const bodies = installFetch();
    const said = installSpeechSynthesis();
    render(<Harness opts={{ ttsSource: 'server', lang: 'en' }} text={'```\nmake test\n```\n🎉'} />);
    fireEvent.click(screen.getByText('speak'));
    await new Promise((r) => setTimeout(r, 30));
    expect(bodies).toEqual([]);
    expect(streamTts).not.toHaveBeenCalled();
    expect(said).toEqual([]);
  });

  it("the hub's 204 (nothing to say) is silence, not the browser's fallback voice", async () => {
    installFetch({ ttsStatus: 204 });
    const said = installSpeechSynthesis();
    render(<Harness opts={{ ttsSource: 'server', lang: 'en' }} text="Hello there." />);
    fireEvent.click(screen.getByText('speak'));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/tts', expect.anything()));
    await new Promise((r) => setTimeout(r, 30));
    expect(said).toEqual([]);
    expect(URL.createObjectURL).not.toHaveBeenCalled();   // no empty clip played either
  });

  it("the browser's own voice speaks the normalised reply", async () => {
    installFetch();
    const said = installSpeechSynthesis();
    render(<Harness opts={{ ttsSource: 'browser', lang: 'ro' }} />);
    fireEvent.click(screen.getByText('speak'));
    await waitFor(() => expect(said).toEqual([SPOKEN]));
  });

  it('a live turn never speaks a code block split across deltas, nor an emoji-only sentence', async () => {
    installMedia();
    const bodies = installFetch();
    const apiRef = { current: null };
    const deltas = ['Salut! ', '👋. ', 'Rulează asta:\n``', '`sh\nrm -rf /tmp/x. ', 'și gata.\n`', '``\nApoi ', 'repornește.'];
    const reply = deltas.join('');
    const onTurn = vi.fn(async () => {
      for (const d of deltas) apiRef.current.pushSpeakDelta(d);
      return reply;
    });
    render(<Harness opts={{ ttsSource: 'server', lang: 'ro', mode: 'ptt', onTurn }} apiRef={apiRef} />);
    await waitFor(() => expect(apiRef.current?.caps).toMatchObject({ stt: true }));
    fireEvent.click(screen.getByText('start'));
    await waitFor(() => expect(onTurn).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('off'));
    const texts = bodies.map((b) => b.text);
    expect(texts).toEqual(['Salut!', 'Rulează asta: Apoi repornește.']);
    expect(texts.join(' ')).not.toMatch(/rm -rf|```|👋/);
  });

  async function liveTurn(deltas, ttsStatus = 200) {
    installMedia();
    const bodies = installFetch({ ttsStatus });
    const apiRef = { current: null };
    const onTurn = vi.fn(async () => {
      for (const d of deltas) apiRef.current.pushSpeakDelta(d);
      return deltas.join('');
    });
    render(<Harness opts={{ ttsSource: 'server', lang: 'ro', mode: 'ptt', onTurn }} apiRef={apiRef} />);
    await waitFor(() => expect(apiRef.current?.caps).toMatchObject({ stt: true }));
    fireEvent.click(screen.getByText('start'));
    await waitFor(() => expect(onTurn).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('off'));
    return bodies.map((b) => b.text);
  }

  it('a live turn speaks the tail the filter held back', async () => {
    // one clean pass, no fallback: the held "<b" must reach the last sentence itself
    expect(await liveTurn(['Verifică dacă a ', '<b'])).toEqual(['Verifică dacă a <b']);
  });

  it('a live turn plays nothing for a sentence the hub answers 204', async () => {
    installMedia();
    const bodies = installFetch({ ttsStatus: 204 });
    const apiRef = { current: null };
    const deltas = ['Verifică dacă a ', '<b'];
    const onTurn = vi.fn(async () => {
      for (const d of deltas) apiRef.current.pushSpeakDelta(d);
      return deltas.join('');
    });
    render(<Harness opts={{ ttsSource: 'server', lang: 'ro', mode: 'ptt', onTurn }} apiRef={apiRef} />);
    await waitFor(() => expect(apiRef.current?.caps).toMatchObject({ stt: true }));
    fireEvent.click(screen.getByText('start'));
    await waitFor(() => expect(onTurn).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('off'));
    expect(bodies.map((b) => b.text)).toContain('Verifică dacă a <b');
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});
