// @ts-nocheck
/* A recorder that never fires `onstop` — and the 60 ms level meter that used to
   outlive it.

   Cleanup of the VAD meter interval hung off `rec.onstop`. A real browser fires that
   event, so nothing looked wrong; a recorder that errors, is torn down mid-event, or
   is a test double that never fires it left the interval running forever, calling
   `setLevel()` on an unmounted component. In CI that surfaced as
   `ReferenceError: window is not defined` from `Timeout._onTimeout` after jsdom was
   gone — a real leak wearing a test failure's clothes.

   The fix is that `releaseStream()` clears the meter unconditionally, so teardown
   never waits for an event to arrive. This test pins that: with a recorder that
   swallows `onstop`, unmounting must leave no timer behind. */
import React, { useEffect } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, act } from '@testing-library/react';
import { useVoice } from '../voice';

vi.mock('../api/ttsStream', () => ({ streamTts: vi.fn().mockResolvedValue('disabled') }));

const track = { stop: vi.fn() };

class SilentRecorder {
  static isTypeSupported = vi.fn(() => true);
  state = 'inactive';
  ondataavailable: any = null;
  onstop: any = null;
  constructor(public mediaStream: any, public opts: any = {}) {}
  start() { this.state = 'recording'; }
  // Stops, and deliberately never calls onstop — the case the old cleanup missed.
  stop() { this.state = 'inactive'; }
}

function Harness() {
  const voice = useVoice({ mode: 'hands-free' });
  useEffect(() => { void voice.start(); }, []);
  return <output>{voice.status}</output>;
}

beforeEach(() => {
  vi.useFakeTimers();
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [track] }) },
  });
  for (const target of [window, globalThis]) {
    Object.defineProperty(target, 'MediaRecorder', { configurable: true, value: SilentRecorder });
  }
  global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
});

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe('the VAD level meter does not outlive the component', () => {
  it('leaves no interval running after unmount, even if onstop never fires', async () => {
    const cleared: number[] = [];
    const realClear = globalThis.clearInterval;
    const started: number[] = [];
    const realSet = globalThis.setInterval;
    vi.spyOn(globalThis, 'setInterval').mockImplementation((...args: any[]) => {
      const id = realSet(...args);
      started.push(id);
      return id;
    });
    vi.spyOn(globalThis, 'clearInterval').mockImplementation((id: any) => {
      cleared.push(id);
      return realClear(id);
    });

    const { unmount } = render(<Harness />);
    await act(async () => { await Promise.resolve(); vi.advanceTimersByTime(200); });
    unmount();
    await act(async () => { await Promise.resolve(); });

    // Every interval the hook started is cleared by teardown. Before the fix the
    // meter's interval was missing from this list and kept firing into a dead DOM.
    for (const id of started) {
      expect(cleared, `interval ${id} survived unmount`).toContain(id);
    }
  });
});
