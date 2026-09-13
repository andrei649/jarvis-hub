// @ts-nocheck
/* The recorder stops itself when you stop talking — H530's other half.

   `useVoice` has had VAD-segmented capture since it was written: `recordUtterance`
   samples mic RMS every 60ms and ends the recording after SILENCE_MS of quiet,
   with a hard cap and a give-up for a turn where nobody speaks. None of it had a
   test, because the shared harness in `voice.test.tsx` uses a MediaRecorder that
   fires one data event and stops itself — which short-circuits the interval
   before it can decide anything.

   So these use a recorder that NEVER stops on its own. If a turn completes here,
   the only thing that could have ended it is the silence detector. That is the
   whole design of this file: the assertion is not "stop was called", it is "the
   turn finished, and it could only have finished this way".
*/
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React, { useEffect } from 'react';
import { render, screen, act } from '@testing-library/react';

vi.mock('../api/ttsStream', () => ({ streamTts: vi.fn() }));

import { streamTts } from '../api/ttsStream';
import { useVoice } from '../voice';

// Mirrors the constants in voice.ts. Duplicated on purpose: if someone changes
// SILENCE_MS there, these tests should fail and make them think about it, rather
// than importing the value and agreeing with whatever it becomes.
const SILENCE_MS = 1100;
const MAX_UTTER_MS = 15000;
const WAIT_SPEECH_MS = 7000;
const TICK_MS = 60;

/** Mic level the fake analyser reports, in RMS. Tests move this between ticks. */
let level = 0;
let recorders: any[] = [];

function jsonResponse(data: any) {
  return { ok: true, status: 200, json: async () => data,
           blob: async () => new Blob(['audio'], { type: 'audio/mpeg' }) };
}

/** A recorder that only ever stops when something calls stop() — never on its own. */
class PassiveRecorder {
  static isTypeSupported = vi.fn(() => true);
  state = 'inactive';
  ondataavailable: any = null;
  onstop: any = null;
  stopped = false;

  constructor(public stream: any, public opts: any = {}) {
    recorders.push(this);
  }

  start() {
    this.state = 'recording';
  }

  stop() {
    if (this.state === 'inactive') return;
    this.state = 'inactive';
    this.stopped = true;
    this.ondataavailable?.({ data: new Blob(['x'.repeat(4096)], { type: 'audio/webm' }) });
    this.onstop?.();
  }
}

class LevelledAudioContext {
  resume = vi.fn();
  close = vi.fn();
  createMediaStreamSource = vi.fn(() => ({ connect: vi.fn() }));
  createAnalyser = vi.fn(() => ({
    fftSize: 1024,
    // rms() computes sqrt(mean(((v - 128) / 128) ** 2)), so a constant offset
    // from 128 gives exactly that RMS back. `level` is the dial the tests turn.
    getByteTimeDomainData: (buf: Uint8Array) => buf.fill(Math.round(128 + level * 128)),
  }));
}

function Harness({ onTurn }: any) {
  const voice = useVoice({ onTurn });
  useEffect(() => { (window as any).__voice = voice; }, [voice]);
  return (
    <div>
      <button onClick={() => voice.start()}>start</button>
      <output data-testid="status">{voice.status}</output>
      <output data-testid="transcript">{voice.transcript}</output>
    </div>
  );
}

/** Advance the VAD interval by `ms`, letting promises settle between ticks. */
async function tick(ms: number) {
  const ticks = Math.ceil(ms / TICK_MS);
  for (let i = 0; i < ticks; i++) {
    await act(async () => {
      vi.advanceTimersByTime(TICK_MS);
      await Promise.resolve();
    });
  }
}

describe('the recorder ends an utterance on its own', () => {
  beforeEach(() => {
    localStorage.clear();
    level = 0;
    recorders = [];
    vi.mocked(streamTts).mockResolvedValue('disabled');
    global.fetch = vi.fn(async (url: string) => {
      const path = String(url);
      if (path === '/api/voice/capabilities') return jsonResponse({ stt: true, tts: false });
      if (path.startsWith('/api/voice/stt')) return jsonResponse({ text: 'pornește serverul' });
      return jsonResponse({});
    }) as any;

    const track = { stop: vi.fn() };
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [track] }) },
    });
    for (const target of [window, globalThis]) {
      Object.defineProperty(target, 'MediaRecorder', { configurable: true, value: PassiveRecorder });
      Object.defineProperty(target, 'AudioContext', { configurable: true, value: LevelledAudioContext });
    }
    vi.useFakeTimers({ shouldAdvanceTime: false });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  async function startListening(onTurn = vi.fn()) {
    render(<Harness onTurn={onTurn} />);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    await act(async () => { screen.getByText('start').click(); await Promise.resolve(); });
    // The mic opens asynchronously; give the promise chain a few turns to land.
    for (let i = 0; i < 8 && !recorders.length; i++) {
      await act(async () => { await Promise.resolve(); });
    }
    return onTurn;
  }

  it('keeps recording while there is speech, and stops after the silence window', async () => {
    const onTurn = await startListening();
    expect(recorders.length).toBe(1);
    const rec = recorders[0];

    level = 0.3;                 // well above SPEECH_RMS
    await tick(600);
    expect(rec.stopped).toBe(false);

    level = 0;                   // they stopped talking
    await tick(SILENCE_MS - 300);
    expect(rec.stopped).toBe(false);   // not yet — the window has not elapsed

    await tick(600);
    expect(rec.stopped).toBe(true);
  });

  it('gives the turn up when nobody says anything at all', async () => {
    const onTurn = await startListening();
    const rec = recorders[0];
    level = 0;

    await tick(WAIT_SPEECH_MS - 500);
    expect(rec.stopped).toBe(false);

    await tick(1000);
    expect(rec.stopped).toBe(true);
  });

  it('a silent recording never becomes a turn, whatever the recorder captured', async () => {
    /* The browser end of the same guarantee the backend filter provides.
       `/api/voice/stt` answers `[silence]` for a recording with nothing said in
       it — now including one where Whisper invented a subtitle credit, because
       the hallucination filter maps that to the same sentinel — and `voice.ts`
       drops any bracketed sentinel rather than treating it as speech. Without
       that, a quiet room would put words in the owner's mouth. */
    global.fetch = vi.fn(async (url: string) => {
      const path = String(url);
      if (path === '/api/voice/capabilities') return jsonResponse({ stt: true, tts: false });
      if (path.startsWith('/api/voice/stt')) return jsonResponse({ text: '[silence]' });
      return jsonResponse({});
    }) as any;

    const onTurn = await startListening();
    const rec = recorders[0];
    level = 0.3;
    await tick(400);
    level = 0;
    await tick(SILENCE_MS + 400);

    expect(rec.stopped).toBe(true);
    expect(onTurn).not.toHaveBeenCalled();
    expect(screen.getByTestId('transcript').textContent).toBe('');
  });

  it('caps one utterance even if the speaker never pauses', async () => {
    await startListening();
    const rec = recorders[0];
    level = 0.3;

    await tick(MAX_UTTER_MS - 1000);
    expect(rec.stopped).toBe(false);

    await tick(1500);
    expect(rec.stopped).toBe(true);
  });

  it('a silence that never arrives does not end the recording early', async () => {
    /* The mirror of the first test: speech keeps resetting the clock, so a
       recording longer than SILENCE_MS is not stopped as long as talking
       continues. A detector that fired on elapsed time rather than on elapsed
       *quiet* would cut the owner off mid-sentence. */
    await startListening();
    const rec = recorders[0];
    level = 0.3;
    await tick(SILENCE_MS * 3);
    expect(rec.stopped).toBe(false);
  });
});
