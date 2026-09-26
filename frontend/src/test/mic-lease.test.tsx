// @ts-nocheck
/* H247 — the HUD's voice loop asks the hub for this device's microphone before it opens
   it, renews the lease while it runs, gives it back when it stops, and stops when the hub
   says another surface took it. Only a hub refusal (403 not allowed, 409 held elsewhere)
   stops it; a hub that cannot answer does not. fetch, getUserMedia and the recorder are
   mocked. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor, act, cleanup } from '@testing-library/react';

vi.mock('../api/ttsStream', () => ({ streamTts: vi.fn() }));

import { useVoice } from '../voice';
import { InputBar } from '../cockpit';
import { RENEW_MS, micClientId } from '../mic-lease';
import { MicLeases } from '../mic-leases';

let calls;
let armReply;

function reply(status, body = {}) {
  return { ok: status < 400, status, json: async () => body, blob: async () => new Blob(['a']) };
}

function install() {
  calls = [];
  armReply = () => reply(200, { ok: true, lease: {} });
  global.fetch = vi.fn(async (url, init = {}) => {
    const path = String(url);
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ path, method: init.method || 'GET', body });
    if (path === '/api/voice/capabilities') return reply(200, { stt: true, tts: true });
    if (path === '/api/voice/mic/arm') return armReply(body);
    if (path === '/api/voice/mic/stop') return reply(200, { ok: true, stopped: true });
    if (path.startsWith('/api/voice/stt')) return reply(200, { text: '' });
    return reply(404, {});
  });
  const track = { stop: vi.fn() };
  const getUserMedia = vi.fn(async () => { calls.push({ path: 'getUserMedia' }); return { getTracks: () => [track] }; });
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia } });
  class FakeMediaRecorder {
    static isTypeSupported = () => true;
    state = 'inactive'; ondataavailable = null; onstop = null;
    constructor() {}
    start() { this.state = 'recording'; }
    stop() { if (this.state === 'inactive') return; this.state = 'inactive'; setTimeout(() => this.onstop?.(), 0); }
  }
  class FakeAudioContext {
    resume() {} close() {}
    createMediaStreamSource() { return { connect() {} }; }
    createAnalyser() { return { fftSize: 1024, getByteTimeDomainData: (b) => b.fill(128) }; }
  }
  Object.defineProperty(window, 'MediaRecorder', { configurable: true, value: FakeMediaRecorder });
  Object.defineProperty(window, 'AudioContext', { configurable: true, value: FakeAudioContext });
  return { getUserMedia, track };
}

function Harness() {
  const voice = useVoice({ mode: 'hands-free' });
  return (
    <div>
      <button onClick={() => voice.start()}>start</button>
      <button onClick={() => voice.stop()}>stop</button>
      <button onClick={() => voice.takeOver()}>take</button>
      <button onClick={voice.start}>start-as-handler</button>
      <output data-testid="error">{voice.error || ''}</output>
      <output data-testid="holder">{voice.micHolder || ''}</output>
      <output data-testid="active">{String(voice.active)}</output>
    </div>
  );
}

const arms = () => calls.filter((c) => c.path === '/api/voice/mic/arm');

beforeEach(() => { cleanup(); try { sessionStorage.clear(); localStorage.clear(); } catch { /* ignore */ } });
afterEach(() => { vi.useRealTimers(); });

describe('mic lease — H247', () => {
  it('arms this tab’s lease before opening the microphone, and releases it on stop', async () => {
    const { getUserMedia } = install();
    render(<Harness />);
    fireEvent.click(screen.getByText('start'));
    await waitFor(() => expect(screen.getByTestId('active').textContent).toBe('true'));
    const id = micClientId();
    expect(arms()[0].body).toEqual({ surface: 'hud', client: id, take_over: false });
    const order = calls.map((c) => c.path);
    expect(order.indexOf('/api/voice/mic/arm')).toBeLessThan(order.indexOf('getUserMedia'));   // asked first
    expect(getUserMedia).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText('stop'));
    await waitFor(() => expect(calls.some((c) => c.path === '/api/voice/mic/stop')).toBe(true));
    expect(calls.find((c) => c.path === '/api/voice/mic/stop').body).toEqual({ surface: `hud:${id}` });
    expect(micClientId()).toBe(id);                                        // stable for the tab
  });

  it('a microphone held elsewhere is named, never opened, and can be taken over', async () => {
    const { getUserMedia } = install();
    armReply = (body) => (body.take_over ? reply(200, { ok: true }) : reply(409, { error: 'mic_busy', holder: { surface: 'host:hub' } }));
    render(<Harness />);
    fireEvent.click(screen.getByText('start'));
    await waitFor(() => expect(screen.getByTestId('error').textContent).toBe('The microphone is held by host:hub.'));
    expect(screen.getByTestId('holder').textContent).toBe('host:hub');
    expect(getUserMedia).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('take'));
    await waitFor(() => expect(screen.getByTestId('active').textContent).toBe('true'));
    expect(arms().map((c) => c.body.take_over)).toEqual([false, true]);
    expect(screen.getByTestId('error').textContent).toBe('');
  });

  it('a surface the owner has not allowed never opens the microphone', async () => {
    const { getUserMedia } = install();
    armReply = () => reply(403, { error: 'not_consented' });
    render(<Harness />);
    fireEvent.click(screen.getByText('start'));
    await waitFor(() => expect(screen.getByTestId('error').textContent).toMatch(/has not allowed it/));
    expect(screen.getByTestId('holder').textContent).toBe('');
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it('a hub that cannot answer does not stop the loop', async () => {
    const { getUserMedia } = install();
    armReply = () => { throw new Error('offline'); };
    render(<Harness />);
    fireEvent.click(screen.getByText('start'));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
    armReply = () => reply(404, {});
    fireEvent.click(screen.getByText('stop'));
    fireEvent.click(screen.getByText('start'));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(2));   // an older hub without the route
  });

  it('renews while it runs, and stops when the hub says the microphone was taken', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { track } = install();
    render(<Harness />);
    fireEvent.click(screen.getByText('start'));
    await waitFor(() => expect(screen.getByTestId('active').textContent).toBe('true'));
    await act(async () => { vi.advanceTimersByTime(RENEW_MS + 10); });
    await waitFor(() => expect(arms()).toHaveLength(2));                  // renewed
    armReply = () => reply(409, { error: 'mic_busy', holder: { surface: 'mobile:pixel' } });
    await act(async () => { vi.advanceTimersByTime(RENEW_MS + 10); });
    await waitFor(() => expect(screen.getByTestId('error').textContent).toBe('The microphone was taken by mobile:pixel.'));
    expect(screen.getByTestId('active').textContent).toBe('false');
    expect(track.stop).toHaveBeenCalled();                                // the tracks are closed
    const n = arms().length;
    await act(async () => { vi.advanceTimersByTime(RENEW_MS * 2); });
    expect(arms()).toHaveLength(n);                                        // no renewal after it stopped
  });

  it('a button wired straight to start never takes over, and the renewal comes well inside the lease', async () => {
    install();
    expect(RENEW_MS).toBe(20000);                                          // the hub drops a lease 45 s after its last renewal
    render(<Harness />);
    fireEvent.click(screen.getByText('start-as-handler'));                 // the click event arrives as the argument
    await waitFor(() => expect(arms()).toHaveLength(1));
    expect(arms()[0].body.take_over).toBe(false);
  });

  it('a start cancelled while the hub answers gives the lease straight back', async () => {
    const { getUserMedia } = install();
    let answer;
    armReply = () => new Promise((resolve) => { answer = () => resolve(reply(200, { ok: true })); });
    render(<Harness />);
    fireEvent.click(screen.getByText('start'));
    await waitFor(() => expect(arms()).toHaveLength(1));
    fireEvent.click(screen.getByText('stop'));
    await act(async () => { answer(); });
    await waitFor(() => expect(calls.some((c) => c.path === '/api/voice/mic/stop')).toBe(true));
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it('an unmounted loop gives the microphone back', async () => {
    install();
    const { unmount } = render(<Harness />);
    fireEvent.click(screen.getByText('start'));
    await waitFor(() => expect(screen.getByTestId('active').textContent).toBe('true'));
    unmount();
    await waitFor(() => expect(calls.some((c) => c.path === '/api/voice/mic/stop')).toBe(true));
  });

  it('the voice pill offers the take-over only when another surface holds the microphone', () => {
    const takeOver = vi.fn();
    const voice = { active: false, error: 'The microphone is held by host:hub.', micHolder: 'host:hub', takeOver, status: 'error' };
    const { rerender } = render(<InputBar onSubmit={() => {}} voice={voice} t={{}} />);
    fireEvent.click(screen.getByLabelText('take the microphone from host:hub'));
    expect(takeOver).toHaveBeenCalledTimes(1);
    rerender(<InputBar onSubmit={() => {}} voice={{ ...voice, micHolder: null, error: 'Microphone permission denied' }} t={{}} />);
    expect(screen.queryByText('take over')).toBeNull();
  });

  it('the voice settings name who holds each microphone, and pause, resume or stop a lease', async () => {
    install();
    let status = { devices: [{ device: 'host', holder: { surface: 'host:hub', state: 'armed' } }],
      paused: [{ surface: 'hud:tab9', device: 'host', paused_by: 'host:hub' }], allowed: ['hud', 'mobile', 'host'] };
    global.fetch = vi.fn(async (url, init = {}) => {
      const path = String(url).replace(/^https?:\/\/[^/]+/, '');
      const body = init.body ? JSON.parse(init.body) : undefined;
      calls.push({ path, method: init.method || 'GET', body });
      if (path === '/api/voice/mic') return reply(200, status);
      if (path === '/api/voice/mic/resume') return reply(409, { error: 'mic_busy', detail: 'the microphone of host is held by host:hub' });
      return reply(200, { ok: true });
    });
    render(<MicLeases />);
    await waitFor(() => expect(screen.getByText('host · host:hub')).toBeTruthy());
    expect(screen.getByText('host · hud:tab9 (paused by host:hub)')).toBeTruthy();
    expect(screen.getByText('allowed: hud, mobile, host')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('pause host:hub'));
    await waitFor(() => expect(calls.find((c) => c.path === '/api/voice/mic/pause').body).toEqual({ surface: 'host:hub' }));
    fireEvent.click(screen.getByLabelText('resume hud:tab9'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('the microphone of host is held by host:hub'));
    status = { devices: [], paused: [], allowed: [] };
    fireEvent.click(screen.getByLabelText('stop host:hub'));
    await waitFor(() => expect(screen.getByText('no microphone is open')).toBeTruthy());
    expect(calls.find((c) => c.path === '/api/voice/mic/stop').body).toEqual({ surface: 'host:hub' });
    expect(screen.getByText('allowed: none')).toBeTruthy();
  });
});
