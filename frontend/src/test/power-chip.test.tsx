// @ts-nocheck
/* H182 — the HUD says when the machine is on battery (and background jobs wait), when it
   woke from sleep, and what keep-awake is doing; a plugged-in machine shows nothing. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import React from 'react';
import { render, screen, cleanup, act } from '@testing-library/react';

const apiGet = vi.fn();
vi.mock('../api/client', () => ({ apiGet: (...a) => apiGet(...a) }));

import { POWER_UNKNOWN, PowerChip, powerLabels, readPower, usePower } from '../power-chip';

const payload = (over = {}) => ({
  power: { battery: true, on_battery: true, percent: 34.4, plugged: false, resumed_at: null, seq: 3 },
  defer_percent: 50, background_deferred: true,
  keep_awake: { enabled: false, active: false, holders: 0, backend: '', refused: null, error: null },
  ...over,
});

class FakeEventSource {
  static last = null;
  constructor(url) { this.url = url; this.closed = false; FakeEventSource.last = this; }
  close() { this.closed = true; }
}

beforeEach(() => { cleanup(); apiGet.mockReset(); FakeEventSource.last = null; });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('power state — H182', () => {
  it('reads the hub payload and treats anything malformed as nothing to say', () => {
    expect(readPower(payload())).toEqual({
      onBattery: true, percent: 34, deferred: true, resumedAt: null,
      keepAwake: { enabled: false, active: false, refused: null, error: null },
    });
    for (const raw of [undefined, null, 'on', 3, [], {}]) {
      expect(powerLabels(readPower(raw))).toEqual([]);
    }
    const odd = readPower({ power: { on_battery: 'yes', percent: '34', resumed_at: 'soon' },
      background_deferred: 'true', keep_awake: { enabled: 1, refused: '  ', error: 42 } });
    expect(odd).toEqual(POWER_UNKNOWN);
    expect(readPower({ power: { on_battery: true, percent: 180 } }).percent).toBe(100);
    expect(readPower({ power: { on_battery: true, percent: -3 } }).percent).toBe(0);
    expect(readPower({ keep_awake: { enabled: true, refused: 'x'.repeat(500) } }).keepAwake.refused).toHaveLength(200);
  });

  it('says on battery, the percent, and that heavy jobs wait', () => {
    expect(powerLabels(readPower(payload()))).toEqual(['on battery 34% · background jobs deferred']);
    const noPct = readPower(payload({ power: { on_battery: true, percent: null }, background_deferred: false }));
    expect(powerLabels(noPct)).toEqual(['on battery']);
    const plugged = readPower(payload({ power: { on_battery: false, percent: 90 }, background_deferred: false }));
    expect(powerLabels(plugged)).toEqual([]);
  });

  it('says when the machine woke from sleep', () => {
    const at = new Date(2026, 8, 26, 7, 5).getTime() / 1000;
    const woke = readPower(payload({ power: { on_battery: false, resumed_at: at }, background_deferred: false }));
    expect(powerLabels(woke)).toEqual(['woke from sleep at 07:05']);
  });

  it('says what keep-awake is doing, a refusal and its reason first', () => {
    const ka = (k) => powerLabels(readPower({ keep_awake: { enabled: true, active: false, refused: null, error: null, ...k } }));
    expect(ka({})).toEqual(['keep-awake ready']);
    expect(ka({ active: true })).toEqual(['keeping the machine awake']);
    expect(ka({ error: 'keep-awake helper exited (code 1)' })).toEqual(['keep-awake: keep-awake helper exited (code 1)']);
    expect(ka({ refused: 'Action Kernel is required to keep the machine awake', error: 'x' }))
      .toEqual(['keep-awake off: Action Kernel is required to keep the machine awake']);
    expect(powerLabels(readPower({ keep_awake: { enabled: false, active: true, refused: 'r' } }))).toEqual([]);
  });

  it('shows nothing on a plugged-in machine with keep-awake off', () => {
    const { container, rerender } = render(<PowerChip state={POWER_UNKNOWN} />);
    expect(container.innerHTML).toBe('');
    rerender(<PowerChip state={readPower(payload())} />);
    expect(screen.getByTestId('power-chip').textContent).toBe('on battery 34% · background jobs deferred');
  });

  it('loads, polls and follows the stream; demo mode asks nothing', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('EventSource', FakeEventSource);
    apiGet.mockResolvedValue(payload());
    const seen = [];
    function Probe({ demo }) { const s = usePower(demo); seen.push(s); return <PowerChip state={s} />; }

    const { rerender, unmount } = render(<Probe demo={true} />);
    expect(apiGet).not.toHaveBeenCalled();
    expect(FakeEventSource.last).toBeNull();

    rerender(<Probe demo={false} />);
    await act(async () => { await Promise.resolve(); });
    expect(apiGet).toHaveBeenCalledWith('/api/power');
    expect(screen.getByTestId('power-chip').textContent).toContain('on battery 34%');
    expect(FakeEventSource.last.url).toContain('/api/power/stream');

    await act(async () => {
      FakeEventSource.last.onmessage({ data: JSON.stringify({ type: 'power', ...payload({
        power: { on_battery: false }, background_deferred: false,
        keep_awake: { enabled: true, active: true } }) }) });
    });
    expect(screen.getByTestId('power-chip').textContent).toBe('keeping the machine awake');
    await act(async () => { FakeEventSource.last.onmessage({ data: '{not json' }); });
    await act(async () => { FakeEventSource.last.onmessage({ data: JSON.stringify({ type: 'other', power: {} }) }); });
    expect(screen.getByTestId('power-chip').textContent).toBe('keeping the machine awake');

    apiGet.mockClear();
    await act(async () => { vi.advanceTimersByTime(60_000); await Promise.resolve(); });
    expect(apiGet).toHaveBeenCalledTimes(1);

    apiGet.mockRejectedValue(new Error('GET /api/power -> 401'));
    await act(async () => { vi.advanceTimersByTime(60_000); await Promise.resolve(); });
    expect(screen.getByTestId('power-chip').textContent).toContain('on battery 34%');  // kept, not blanked

    const es = FakeEventSource.last;
    FakeEventSource.last.onerror();
    expect(es.closed).toBe(true);
    unmount();
    apiGet.mockClear();
    await act(async () => { vi.advanceTimersByTime(120_000); });
    expect(apiGet).not.toHaveBeenCalled();
  });
});
