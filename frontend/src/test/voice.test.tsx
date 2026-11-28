// @ts-nocheck
/* BUG-2b.3 / M2.6 — useVoice state-machine tests.

   The live browser path needs a real mic, but the hook's control flow is pure enough
   to exercise in jsdom with mocked getUserMedia, MediaRecorder, AudioContext, fetch,
   Audio, and streaming TTS.
*/
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React, { useEffect } from 'react';
import { act, render, screen, waitFor, fireEvent } from '@testing-library/react';

vi.mock('../api/ttsStream', () => ({ streamTts: vi.fn() }));

import { streamTts } from '../api/ttsStream';
import { matchWakePhrase, useVoice } from '../voice';

function jsonResponse(data: any, opts: any = {}) {
  const status = opts.status ?? 200;
  return {
    ok: opts.ok ?? status < 400,
    status,
    json: async () => data,
    blob: async () => new Blob(['audio'], { type: 'audio/mpeg' }),
  };
}

function installFetch(capabilities: any = { stt: true, tts: true }) {
  const fn = vi.fn(async (url: string) => {
    const path = String(url);
    if (path === '/api/voice/capabilities') return jsonResponse(capabilities);
    if (path.startsWith('/api/voice/stt')) return jsonResponse({ text: 'hello jarvis' });
    if (path === '/tts') return jsonResponse({});
    throw new Error('unexpected fetch ' + path);
  });
  global.fetch = fn as any;
  return fn;
}

function installMediaMocks() {
  const track = { stop: vi.fn() };
  const stream = { getTracks: () => [track] };
  const getUserMedia = vi.fn().mockResolvedValue(stream);

  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia },
  });

  class FakeMediaRecorder {
    static isTypeSupported = vi.fn(() => true);
    state = 'inactive';
    ondataavailable: any = null;
    onstop: any = null;

    constructor(public mediaStream: any, public opts: any = {}) {}

    start() {
      this.state = 'recording';
      setTimeout(() => {
        this.ondataavailable?.({
          data: new Blob(['x'.repeat(2048)], { type: 'audio/webm' }),
        });
        this.stop();
      }, 0);
    }

    stop() {
      if (this.state === 'inactive') return;
      this.state = 'inactive';
      setTimeout(() => this.onstop?.(), 0);
    }
  }

  class FakeAudioContext {
    resume = vi.fn();
    close = vi.fn();
    createMediaStreamSource = vi.fn(() => ({ connect: vi.fn() }));
    createAnalyser = vi.fn(() => ({
      fftSize: 1024,
      getByteTimeDomainData: (buf: Uint8Array) => buf.fill(128),
    }));
  }

  Object.defineProperty(window, 'MediaRecorder', { configurable: true, value: FakeMediaRecorder });
  Object.defineProperty(globalThis, 'MediaRecorder', { configurable: true, value: FakeMediaRecorder });
  Object.defineProperty(window, 'AudioContext', { configurable: true, value: FakeAudioContext });
  Object.defineProperty(globalThis, 'AudioContext', { configurable: true, value: FakeAudioContext });

  return { getUserMedia, track };
}

function installAudioMocks() {
  class FakeAudio {
    onended: any = null;
    onerror: any = null;
    pause = vi.fn();

    constructor(public src: string) {}

    play() {
      setTimeout(() => this.onended?.(), 0);
      return Promise.resolve();
    }
  }

  Object.defineProperty(globalThis, 'Audio', { configurable: true, value: FakeAudio });
  Object.defineProperty(window, 'Audio', { configurable: true, value: FakeAudio });
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:voice');
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
}

function VoiceHarness({ opts = {}, onState = () => {} }: any) {
  const voice = useVoice(opts);
  useEffect(() => {
    onState({
      supported: voice.supported,
      caps: voice.caps,
      status: voice.status,
      error: voice.error,
      transcript: voice.transcript,
      active: voice.active,
      bargeInterrupted: voice.bargeInterrupted,
    });
  }, [voice.supported, voice.caps, voice.status, voice.error, voice.transcript, voice.active, voice.bargeInterrupted]);

  return (
    <div>
      <button onClick={() => voice.start()}>start</button>
      <button onClick={() => voice.stop()}>stop</button>
      <button onClick={() => voice.speak('spoken reply')}>speak</button>
      <output data-testid="status">{voice.status}</output>
      <output data-testid="barge">{String(voice.bargeInterrupted)}</output>
      <output data-testid="error">{voice.error || ''}</output>
      <output data-testid="transcript">{voice.transcript}</output>
    </div>
  );
}

describe('useVoice state machine', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(streamTts).mockResolvedValue('disabled');
    installFetch();
    installMediaMocks();
    installAudioMocks();
  });

  afterEach(() => {
    vi.clearAllTimers();
  });

  it('starts off and loads honest server voice capabilities', async () => {
    const states: any[] = [];
    render(<VoiceHarness onState={(s) => states.push(s)} />);

    expect(screen.getByTestId('status').textContent).toBe('off');
    await waitFor(() => expect(states.at(-1).caps).toMatchObject({ stt: true, tts: true }));
    expect(states.at(-1).supported).toBe(true);
  });

  it('refuses to start when Nerva mic trust is muted', async () => {
    const media = installMediaMocks();
    render(<VoiceHarness opts={{ micMuted: true }} />);

    fireEvent.click(screen.getByText('start'));

    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('error'));
    expect(screen.getByTestId('error').textContent).toContain('Mic is muted');
    expect(media.getUserMedia).not.toHaveBeenCalled();
  });

  it('refuses to start when server STT capabilities report unavailable', async () => {
    const media = installMediaMocks();
    installFetch({ stt: false, tts: true });
    render(<VoiceHarness />);

    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/voice/capabilities'));
    fireEvent.click(screen.getByText('start'));

    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('error'));
    expect(screen.getByTestId('error').textContent).toContain('Local speech-to-text not installed');
    expect(media.getUserMedia).not.toHaveBeenCalled();
  });

  it('drives one push-to-talk turn through listen, transcribe, onTurn, and back off', async () => {
    const media = installMediaMocks();
    const onTurn = vi.fn(async () => 'reply ignored because tts is off');
    const states: any[] = [];
    let resolveStt: (value: any) => void = () => {};
    const sttResponse = new Promise((resolve) => {
      resolveStt = resolve;
    });
    global.fetch = vi.fn(async (url: string) => {
      const path = String(url);
      if (path === '/api/voice/capabilities') return jsonResponse({ stt: true, tts: true });
      if (path.startsWith('/api/voice/stt')) return sttResponse;
      throw new Error('unexpected fetch ' + path);
    }) as any;

    render(
      <VoiceHarness
        opts={{ mode: 'ptt', ttsSource: 'off', lang: 'en', onTurn }}
        onState={(s) => states.push(s)}
      />,
    );

    await waitFor(() => expect(states.at(-1).caps).toMatchObject({ stt: true }));
    fireEvent.click(screen.getByText('start'));

    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('transcribing'));
    resolveStt(jsonResponse({ text: 'hello jarvis' }));

    await waitFor(() => expect(onTurn).toHaveBeenCalledWith('hello jarvis'));
    await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('off'));

    expect(screen.getByTestId('transcript').textContent).toBe('hello jarvis');
    expect(media.getUserMedia).toHaveBeenCalledWith({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    expect(media.track.stop).toHaveBeenCalled();
    expect(states.map((s) => s.status)).toEqual(expect.arrayContaining(['listening', 'transcribing', 'off']));
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/voice/stt?lang=en',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('tries streaming TTS first, then falls back to whole-reply /tts when streaming is disabled', async () => {
    render(<VoiceHarness opts={{ ttsSource: 'server', lang: 'ro' }} />);

    fireEvent.click(screen.getByText('speak'));

    await waitFor(() => expect(streamTts).toHaveBeenCalledWith(
      'spoken reply',
      'ro',
      expect.any(Function),
      expect.objectContaining({ cancelled: expect.any(Function) }),
    ));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(
      '/tts',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ text: 'spoken reply', lang: 'ro' }),
      }),
    ));
  });

  /* Deferred-permission race (integration review, 2026-08-06). `getUserMedia()` can sit on
     a permission prompt for seconds. A stop() or unmount in that window used to release a
     stream that did not exist yet, and the late-resolving permission then opened the mic and
     entered the hands-free loop anyway — capture beginning AFTER authorization was withdrawn.
     These tests hold the promise open deliberately, which is the only way to see it. */
  describe('a permission that resolves after cancellation must not open the mic', () => {
    function deferredMedia() {
      const track = { stop: vi.fn() };
      const stream = { getTracks: () => [track] };
      let resolve: any;
      const pending = new Promise((r) => { resolve = r; });
      const getUserMedia = vi.fn(() => pending);
      Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } });
      return { getUserMedia, track, grant: () => { resolve(stream); return pending; } };
    }

    it('stop() while the prompt is open kills the tracks and never goes active', async () => {
      const media = deferredMedia();
      const states: any[] = [];
      render(<VoiceHarness onState={(st) => states.push(st)} />);
      await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/voice/capabilities'));

      fireEvent.click(screen.getByText('start'));          // permission prompt is now up
      await waitFor(() => expect(media.getUserMedia).toHaveBeenCalled());
      fireEvent.click(screen.getByText('stop'));           // user releases / trust lost

      await media.grant();                                  // permission arrives LATE
      await new Promise((r) => setTimeout(r, 20));

      expect(media.track.stop).toHaveBeenCalled();          // the granted mic is hung up
      expect(screen.getByTestId('status').textContent).toBe('off');
      expect(states.some((st) => st.active)).toBe(false);   // never went active at any point
    });

    it('a stale REJECTION after stop() must not overwrite the off state', async () => {
      const track = { stop: vi.fn() };
      let reject: any;
      const pending = new Promise((_r, rj) => { reject = rj; });
      const getUserMedia = vi.fn(() => pending);
      Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } });

      render(<VoiceHarness />);
      await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/voice/capabilities'));
      fireEvent.click(screen.getByText('start'));
      await waitFor(() => expect(getUserMedia).toHaveBeenCalled());
      fireEvent.click(screen.getByText('stop'));

      reject(new Error('NotAllowedError'));                 // permission denied, LATE
      await new Promise((r) => setTimeout(r, 20));

      expect(screen.getByTestId('status').textContent).toBe('off');
      expect(screen.getByTestId('error').textContent).toBe('');
      expect(track.stop).not.toHaveBeenCalled();
    });

    /* I previously claimed these two interleavings were not red-provable, because the running
       loop clears status/error on each iteration. That was wrong: the review pointed out the
       missing piece — hold the NEWER session in `listening` with a recorder that never
       completes an utterance, and a stale write becomes plainly visible. */
    function holdingRecorder() {
      class HoldingRecorder {
        static isTypeSupported = vi.fn(() => true);
        state = 'inactive';
        ondataavailable: any = null;
        onstop: any = null;
        constructor(public mediaStream: any, public opts: any = {}) {}
        start() { this.state = 'recording'; }      // never completes → the loop parks in `listening`
        stop() { this.state = 'inactive'; }
      }
      Object.defineProperty(window, 'MediaRecorder', { configurable: true, value: HoldingRecorder });
      Object.defineProperty(globalThis, 'MediaRecorder', { configurable: true, value: HoldingRecorder });
    }

    it('an older rejection must not report an error over a newer LIVE capture', async () => {
      holdingRecorder();
      const track = { stop: vi.fn() };
      const stream = { getTracks: () => [track] };
      let rejectFirst: any;
      const first = new Promise((_r, rj) => { rejectFirst = rj; });
      const getUserMedia = vi.fn()
        .mockImplementationOnce(() => first)
        .mockImplementationOnce(() => Promise.resolve(stream));
      Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } });

      render(<VoiceHarness />);
      await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/voice/capabilities'));
      fireEvent.click(screen.getByText('start'));            // gen 1 — hangs on the prompt
      await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
      fireEvent.click(screen.getByText('stop'));
      fireEvent.click(screen.getByText('start'));            // gen 2 — succeeds and parks
      await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('listening'));

      rejectFirst(new Error('NotAllowedError'));             // gen 1 rejects afterwards
      await new Promise((r) => setTimeout(r, 30));

      expect(screen.getByTestId('status').textContent).toBe('listening');   // newer capture intact
      expect(screen.getByTestId('error').textContent).toBe('');
    });

    /* Note on strength: this one asserts the observable contract but does not by itself
       red-prove the generation guard — React already no-ops setState after unmount, so it
       passes either way. It is kept because it pins the invariant against a future change
       that publishes through a store or ref surviving unmount. The guard's actual proofs
       are the two tests above, which do fail without it. */
    it('a rejection after unmount must publish nothing at all', async () => {
      holdingRecorder();
      let reject: any;
      const pending = new Promise((_r, rj) => { reject = rj; });
      const getUserMedia = vi.fn(() => pending);
      Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } });

      const states: any[] = [];
      const view = render(<VoiceHarness onState={(st) => states.push(st)} />);
      await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/voice/capabilities'));
      fireEvent.click(screen.getByText('start'));
      await waitFor(() => expect(getUserMedia).toHaveBeenCalled());
      view.unmount();
      const mark = states.length;

      reject(new Error('NotAllowedError'));                  // permission denied AFTER unmount
      await new Promise((r) => setTimeout(r, 30));

      expect(states.length).toBe(mark);                      // nothing published post-unmount
      expect(states.some((st) => st.status === 'error')).toBe(false);
    });

    it('unmount while the prompt is open kills the tracks and never goes active', async () => {
      const media = deferredMedia();
      const states: any[] = [];
      const view = render(<VoiceHarness onState={(st) => states.push(st)} />);
      await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/voice/capabilities'));

      fireEvent.click(screen.getByText('start'));
      await waitFor(() => expect(media.getUserMedia).toHaveBeenCalled());
      view.unmount();                                       // Esc out of the wall

      await media.grant();
      await new Promise((r) => setTimeout(r, 20));

      expect(media.track.stop).toHaveBeenCalled();
      expect(states.some((st) => st.active)).toBe(false);
    });

    it('surfaces bargeInterrupted and interrupted status when sustained over-talk cuts playback', async () => {
      holdingRecorder();
      let loud = false;
      class LoudAudioContext {
        resume = vi.fn();
        close = vi.fn();
        createMediaStreamSource = vi.fn(() => ({ connect: vi.fn() }));
        createAnalyser = vi.fn(() => ({
          fftSize: 1024,
          getByteTimeDomainData: (buf: Uint8Array) => buf.fill(loud ? 250 : 128),
        }));
      }
      const paused = vi.fn();
      class HangingAudio {
        onended: any = null;
        onerror: any = null;
        constructor(public src: string) {}
        pause = () => { paused(); this.onended?.(); };
        play() { return Promise.resolve(); }
      }
      Object.defineProperty(window, 'AudioContext', { configurable: true, value: LoudAudioContext });
      Object.defineProperty(globalThis, 'AudioContext', { configurable: true, value: LoudAudioContext });
      Object.defineProperty(window, 'Audio', { configurable: true, value: HangingAudio });
      Object.defineProperty(globalThis, 'Audio', { configurable: true, value: HangingAudio });
      global.fetch = vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith('/api/voice/capabilities')) return jsonResponse({ stt: true, tts: true });
        if (url.endsWith('/api/voice/mic/arm')) return jsonResponse({ ok: true });
        if (url.endsWith('/api/voice/mic/stop')) return jsonResponse({ ok: true });
        if (url.endsWith('/tts')) return jsonResponse({});
        return jsonResponse({});
      }) as any;

      const states: any[] = [];
      render(<VoiceHarness opts={{ barge: true }} onState={(st) => states.push(st)} />);
      await waitFor(() => expect(states.at(-1)?.caps).toMatchObject({ stt: true, tts: true }));

      fireEvent.click(screen.getByText('start'));
      await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('listening'));

      loud = true;
      fireEvent.click(screen.getByText('speak'));
      await waitFor(() => expect(screen.getByTestId('barge').textContent).toBe('true'), { timeout: 5000 });
      expect(states.some((st) => st.status === 'interrupted' && st.bargeInterrupted === true)).toBe(true);
      expect(paused).toHaveBeenCalled();

      fireEvent.click(screen.getByText('stop'));
      await waitFor(() => expect(screen.getByTestId('barge').textContent).toBe('false'));
    });

    it('matches wake phrases cleanly and activates the voice loop when opt-in wakeWord hears Hey Jarvis', async () => {
      expect(matchWakePhrase('random background chatter')).toEqual({ triggered: false, remainder: '' });
      expect(matchWakePhrase('Hey Jarvis')).toEqual({ triggered: true, remainder: '' });
      expect(matchWakePhrase('hey nerva, check morning tasks')).toEqual({
        triggered: true,
        remainder: 'check morning tasks',
      });

      let latestRec: any = null;
      const stopSpy = vi.fn();
      class FakeSpeechRecognition {
        continuous = false;
        interimResults = false;
        lang = '';
        onresult: any = null;
        onerror: any = null;
        onend: any = null;
        start = vi.fn(() => { latestRec = this; });
        stop = stopSpy;
      }
      Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: FakeSpeechRecognition });
      try {
        global.fetch = vi.fn(async (input: RequestInfo | URL) => {
          const url = String(input);
          if (url.endsWith('/api/voice/capabilities')) return jsonResponse({ stt: true, tts: true });
          if (url.endsWith('/api/voice/mic/arm')) return jsonResponse({ ok: true });
          if (url.endsWith('/api/voice/mic/stop')) return jsonResponse({ ok: true });
          if (url.includes('/api/voice/stt')) return jsonResponse({ text: '[silence]' });
          if (url.endsWith('/tts')) return jsonResponse({});
          return jsonResponse({});
        }) as any;

        const onTurn = vi.fn(async () => '');
        const view = render(<VoiceHarness opts={{ wakeWord: true, mode: 'ptt', onTurn }} />);
        await waitFor(() => expect(latestRec).not.toBeNull());
        expect(latestRec.continuous).toBe(true);

        await act(async () => {
          latestRec.onresult?.({
            resultIndex: 0,
            results: [[{ transcript: 'Hey Jarvis summarize today' }]],
          });
        });

        await waitFor(() => expect(onTurn).toHaveBeenCalledWith('summarize today'));
        expect(stopSpy).toHaveBeenCalled();
        view.unmount();
      } finally {
        delete (window as any).SpeechRecognition;
      }
    });

    it('preserves the microphone lease across standby-to-active wake-word handoff until active capture finishes', async () => {
      let latestRec: any = null;
      let resolveStt: (value: any) => void = () => {};
      const sttPending = new Promise((resolve) => {
        resolveStt = resolve;
      });
      let micStopCalls = 0;

      class HandOffSpeechRecognition {
        continuous = false;
        interimResults = false;
        lang = '';
        onresult: any = null;
        onerror: any = null;
        onend: any = null;
        start = vi.fn(() => { latestRec = this; });
        stop = vi.fn();
      }
      Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: HandOffSpeechRecognition });
      try {
        global.fetch = vi.fn(async (input: RequestInfo | URL) => {
          const url = String(input);
          if (url.endsWith('/api/voice/capabilities')) return jsonResponse({ stt: true, tts: true });
          if (url.endsWith('/api/voice/mic/arm')) return jsonResponse({ ok: true });
          if (url.endsWith('/api/voice/mic/stop')) {
            micStopCalls += 1;
            return jsonResponse({ ok: true });
          }
          if (url.includes('/api/voice/stt')) return sttPending as any;
          return jsonResponse({});
        }) as any;

        const view = render(<VoiceHarness opts={{ wakeWord: true, mode: 'ptt', onTurn: vi.fn(async () => '') }} />);
        await waitFor(() => expect(latestRec).not.toBeNull());

        await act(async () => {
          latestRec.onresult?.({
            resultIndex: 0,
            results: [[{ transcript: 'Hey Jarvis' }]],
          });
        });

        await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('transcribing'));
        expect(micStopCalls).toBe(0);

        await act(async () => {
          resolveStt(jsonResponse({ text: '[silence]' }));
        });
        await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('off'));
        expect(micStopCalls).toBeGreaterThanOrEqual(1);
        view.unmount();
      } finally {
        delete (window as any).SpeechRecognition;
      }
    });

    it('refuses to start wake-word SpeechRecognition when the hub denies the microphone lease', async () => {
      let started = false;
      class GuardedSpeechRecognition {
        continuous = false;
        interimResults = false;
        lang = '';
        onresult: any = null;
        onerror: any = null;
        onend: any = null;
        start = vi.fn(() => { started = true; });
        stop = vi.fn();
      }
      Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: GuardedSpeechRecognition });
      try {
        global.fetch = vi.fn(async (input: RequestInfo | URL) => {
          const url = String(input);
          if (url.endsWith('/api/voice/capabilities')) return jsonResponse({ stt: true, tts: true });
          if (url.endsWith('/api/voice/mic/arm')) {
            return jsonResponse({ ok: false, code: 'mic_busy', holder: 'desktop-tray', error: 'Microphone busy' }, { status: 409 });
          }
          return jsonResponse({});
        }) as any;

        const states: any[] = [];
        const view = render(<VoiceHarness opts={{ wakeWord: true }} onState={(st) => states.push(st)} />);
        await waitFor(() => expect(screen.getByTestId('status').textContent).toBe('error'));
        expect(started).toBe(false);
        view.unmount();
      } finally {
        delete (window as any).SpeechRecognition;
      }
    });
  });
});
