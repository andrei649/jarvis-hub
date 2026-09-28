// @ts-nocheck
/* H222 — the HUD forwards whether Nerva is listening to the desktop shell's tray: the
   hub's state from a token-bearing stream (else a poll), or listening while this
   window's own mic is on. Outside the desktop app it asks the hub nothing. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import React from 'react';
import { render, cleanup, act } from '@testing-library/react';

const apiGet = vi.fn();
const apiFetchOnce = vi.fn();
vi.mock('../api/client', () => ({ apiGet: (...a) => apiGet(...a), apiFetchOnce: (...a) => apiFetchOnce(...a) }));
const pushed = [];
let bridge = true;
vi.mock('../desktop', () => ({ hasDesktopBridge: () => bridge, setDesktopListening: (s) => pushed.push(s) }));

import { POLL_MS, followListening, loudest, readListening, useListeningIndicator } from '../listening';

const enc = new TextEncoder();
function streamOf(chunks) {
  const queue = chunks.map((c) => ({ value: enc.encode(c), done: false }));
  return { ok: true, status: 200, body: { getReader: () => ({ read: async () => queue.shift() || { value: undefined, done: true } }) } };
}
const frame = (o) => `data: ${JSON.stringify({ type: 'listening', ...o })}\n\n`;
const flush = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };

beforeEach(() => { cleanup(); apiGet.mockReset(); apiFetchOnce.mockReset(); pushed.length = 0; bridge = true; });
afterEach(() => { vi.useRealTimers(); });

describe('listening indicator — H222', () => {
  it('reads a state and treats anything else as off', () => {
    expect(readListening({ state: 'armed' })).toBe('armed');
    for (const raw of [undefined, null, 'listening', {}, { state: 'LISTENING' }, { state: 1 }]) {
      expect(readListening(raw)).toBe('off');
    }
  });

  it('an open mic outranks everything else', () => {
    expect(loudest('speaking', 'listening', 'armed')).toBe('listening');
    expect(loudest('thinking', 'armed')).toBe('armed');
    expect(loudest('speaking', 'thinking')).toBe('thinking');
    expect(loudest('off', 'speaking')).toBe('speaking');
    expect(loudest()).toBe('off');
  });

  it('follows the stream with the HUD token path, then polls when it ends', async () => {
    vi.useFakeTimers();
    apiFetchOnce.mockResolvedValue(streamOf([frame({ state: 'armed', seq: 1 }), ': keepalive\n\n',
      'data: {not json}\n\n', frame({ state: 'listening', seq: 2 }).slice(0, 20), frame({ state: 'listening', seq: 2 }).slice(20),
      `data: ${JSON.stringify({ type: 'other', state: 'speaking' })}\n\n`]));
    apiGet.mockResolvedValue({ state: 'thinking' });
    const seen = [];
    const stop = followListening((s) => seen.push(s));
    await flush();
    expect(apiFetchOnce).toHaveBeenCalledWith('/api/voice/listening/stream', expect.objectContaining({ accept: 'text/event-stream' }));
    expect(apiGet).toHaveBeenCalledWith('/api/voice/listening');      // the stream ended: poll
    await flush();
    // a frame of another type is not a listening state
    expect(seen).toEqual(['armed', 'listening', 'thinking']);
    apiGet.mockClear();
    await act(async () => { vi.advanceTimersByTime(POLL_MS); await flush(); });
    expect(apiGet).toHaveBeenCalledTimes(1);
    stop();
    apiGet.mockClear();
    await act(async () => { vi.advanceTimersByTime(POLL_MS * 3); await flush(); });
    expect(apiGet).not.toHaveBeenCalled();
  });

  it('polls when the stream is refused, and keeps the last state through a failed poll', async () => {
    vi.useFakeTimers();
    apiFetchOnce.mockResolvedValue({ ok: false, status: 401, body: null });
    apiGet.mockResolvedValueOnce({ state: 'armed' }).mockRejectedValueOnce(new Error('down'));
    const seen = [];
    const stop = followListening((s) => seen.push(s));
    await flush();
    expect(seen).toEqual(['armed']);
    await act(async () => { vi.advanceTimersByTime(POLL_MS); await flush(); });
    expect(seen).toEqual(['armed']);
    expect(apiGet).toHaveBeenCalledTimes(2);
    stop();
  });

  it('a refused stream is not read, whatever its body says', async () => {
    apiFetchOnce.mockResolvedValue({ ...streamOf([frame({ state: 'listening', seq: 1 })]), ok: false, status: 401 });
    apiGet.mockResolvedValue({ state: 'off' });
    const seen = [];
    const stop = followListening((s) => seen.push(s));
    await flush();
    expect(seen).toEqual(['off']);
    stop();
  });

  it('a stopped follower reports nothing more', async () => {
    let release;
    apiFetchOnce.mockReturnValue(new Promise((r) => { release = r; }));
    const seen = [];
    const stop = followListening((s) => seen.push(s));
    stop();
    release(streamOf([frame({ state: 'listening', seq: 1 })]));
    await flush();
    expect(seen).toEqual([]);
    expect(apiGet).not.toHaveBeenCalled();
  });

  it('in the desktop app it pushes the loudest of the hub and its own mic to the tray', async () => {
    apiFetchOnce.mockResolvedValue(streamOf([frame({ state: 'armed', seq: 1 })]));
    apiGet.mockResolvedValue({ state: 'armed' });
    function Probe({ mic, demo = false }) { useListeningIndicator(demo, mic); return null; }
    const { rerender, unmount } = render(<Probe mic={false} />);
    await act(async () => { await flush(); });
    expect(pushed[pushed.length - 1]).toBe('armed');
    rerender(<Probe mic={true} />);
    expect(pushed[pushed.length - 1]).toBe('listening');
    rerender(<Probe mic={true} demo={true} />);
    expect(pushed[pushed.length - 1]).toBe('off');
    rerender(<Probe mic={true} />);
    expect(pushed[pushed.length - 1]).toBe('listening');
    unmount();                                            // a closing window leaves nothing lit
    expect(pushed[pushed.length - 1]).toBe('off');
  });

  it('outside the desktop app it asks the hub nothing and pushes nothing', async () => {
    bridge = false;
    function Probe() { useListeningIndicator(false, true); return null; }
    render(<Probe />);
    await act(async () => { await flush(); });
    expect(apiFetchOnce).not.toHaveBeenCalled();
    expect(apiGet).not.toHaveBeenCalled();
    expect(pushed).toEqual([]);
  });
});
