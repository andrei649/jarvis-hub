// @ts-nocheck
/* BUG-2b.3 / M2.6 — useVoice state-machine tests.

   The live browser path needs a real mic, but the hook's control flow is pure enough
   to exercise in jsdom with mocked getUserMedia, MediaRecorder, AudioContext, fetch,
   Audio, and streaming TTS.
*/
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React, { useEffect } from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

vi.mock('../api/ttsStream', () => ({ streamTts: vi.fn() }));

import { streamTts } from '../api/ttsStream';
import { useVoice } from '../voice';

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
    });
  }, [voice.supported, voice.caps, voice.status, voice.error, voice.transcript, voice.active]);

  return (
    <div>
      <button onClick={() => voice.start()}>start</button>
      <button onClick={() => voice.stop()}>stop</button>
      <button onClick={() => voice.speak('spoken reply')}>speak</button>
      <output data-testid="status">{voice.status}</output>
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

  it('refuses to start when JARVIS mic trust is muted', async () => {
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
    render(
      <VoiceHarness
        opts={{ mode: 'ptt', ttsSource: 'off', lang: 'en', onTurn }}
        onState={(s) => states.push(s)}
      />,
    );

    await waitFor(() => expect(states.at(-1).caps).toMatchObject({ stt: true }));
    fireEvent.click(screen.getByText('start'));

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
});
