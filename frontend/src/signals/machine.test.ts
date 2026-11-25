import { describe, expect, it } from 'vitest';
import { stringProblems } from '../frame/strings';
import type { StatusSys } from '../api/types';
import { MACHINE_KEYS, MACHINE_STRINGS, machineLabel, machineReadings, machineValue } from './machine';

const sys = (over: Partial<StatusSys> = {}): StatusSys => ({
  host: 'h', cpu: 'c', ram_used: 36, ram_total: 192, gpu: 'NVIDIA RTX 4090', vram_used: 23, vram_total: 24, gpu_load: 3,
  backend: 'ollama', model: 'gemma', latency: 0, uptime: '1d', sessions: 0, ...over,
});
const read = (s: StatusSys | null, hubState: any = 'live', hubReason?: any, lang = 'en') => machineReadings({ sys: s, hubState, hubReason }, lang);
const by = (rs: ReturnType<typeof read>, key: string) => rs.find((r) => r.key === key)!;

describe('machine readings', () => {
  it('has complete strings and a label for every key', () => {
    expect(stringProblems(MACHINE_STRINGS)).toEqual([]);
    expect(MACHINE_KEYS.map((k) => machineLabel(k))).toEqual(['RAM', 'VRAM', 'GPU load', 'Latency p50']);
    expect(machineLabel('gpu', 'ro')).toBe('Încărcare GPU');
  });

  it('reads RAM, VRAM and GPU load as percentages of their totals, with the detail line', () => {
    const rs = read(sys());
    expect(rs.map((r) => r.key)).toEqual(['ram', 'vram', 'gpu', 'latency']);
    expect(by(rs, 'ram')).toMatchObject({ state: 'live', pct: 19, used: 36, total: 192, unit: 'GB', detail: '36 of 192 GB' });
    expect(by(rs, 'vram')).toMatchObject({ state: 'live', pct: 96, detail: '23 of 24 GB' });
    expect(by(rs, 'gpu')).toMatchObject({ state: 'live', pct: 3, unit: '%', detail: 'NVIDIA RTX 4090' });
    expect(machineValue(by(rs, 'ram'))).toBe('19%');
    expect(read(sys({ ram_used: 36.5, ram_total: 192.4 }))[0].detail).toBe('36.5 of 192.4 GB');
    expect(read(sys(), 'live', undefined, 'ro')[0].detail).toBe('36 din 192 GB');
  });

  it('a figure with no total is unknown, never 0%', () => {
    const rs = read(sys({ ram_used: 0, ram_total: 0, vram_used: 0, vram_total: 0, gpu_load: 0, gpu: 'unknown' }));
    for (const key of ['ram', 'vram', 'gpu']) {
      expect(by(rs, key), key).toMatchObject({ state: 'unknown', reason: 'not-reported', pct: null });
      expect(machineValue(by(rs, key))).toBe('Unknown — not reported');
    }
  });

  it('GPU load is unknown while the GPU probe did not measure (no VRAM total), whatever gpu_load says', () => {
    const rs = read(sys({ vram_total: 0, vram_used: 0, gpu_load: 0 }));
    expect(by(rs, 'gpu')).toMatchObject({ state: 'unknown', pct: null });
    expect(by(read(sys({ gpu: 'unknown' })), 'gpu').detail).toBeUndefined();
  });

  it('a 0 used or 0 load next to a measured total is the hub\'s default fill, so it is unknown, never 0%', () => {
    // Apple Silicon: the probe measures only the total (vram_used_mb and load_pct are None, filled with 0).
    const apple = read(sys({ gpu: 'Apple M2 Max', vram_total: 96, vram_used: 0, gpu_load: 0 }));
    expect(by(apple, 'vram')).toMatchObject({ state: 'unknown', reason: 'not-reported', pct: null });
    expect(by(apple, 'gpu')).toMatchObject({ state: 'unknown', reason: 'not-reported', pct: null });
    expect(machineValue(by(apple, 'vram'))).toBe('Unknown — not reported');
    expect(by(apple, 'vram').detail).toBeUndefined();
    // AMD: total and used, no load.
    const amd = read(sys({ vram_total: 16, vram_used: 4, gpu_load: 0 }));
    expect(by(amd, 'vram')).toMatchObject({ state: 'live', pct: 25 });
    expect(by(amd, 'gpu')).toMatchObject({ state: 'unknown', pct: null });
  });

  it('clamps to 0–100 and ignores non-numbers', () => {
    expect(by(read(sys({ ram_used: 300, ram_total: 192 })), 'ram').pct).toBe(100);
    expect(by(read(sys({ ram_used: 'x' as any })), 'ram').state).toBe('unknown');
    expect(by(read(sys({ ram_total: -4 })), 'ram').state).toBe('unknown');
  });

  it('latency is never measured, whatever the hub sends', () => {
    for (const s of [sys({ latency: 0 }), sys({ latency: 412 }), null]) {
      const l = by(read(s), 'latency');
      expect(l).toMatchObject({ state: 'unknown', reason: 'not-measured', pct: null });
      expect(machineValue(l)).toBe('Unknown — not measured');
    }
    expect(machineValue(by(read(sys()), 'latency'), 'ro')).toBe('Necunoscut — nemăsurat');
  });

  it('without /status.sys: checking, offline, demo or not reported — never a number', () => {
    expect(read(null, 'unknown', 'checking').slice(0, 3).map((r) => [r.state, r.reason])).toEqual([['unknown', 'checking'], ['unknown', 'checking'], ['unknown', 'checking']]);
    expect(machineValue(read(null, 'unknown', 'checking')[0])).toBe('Checking…');
    expect(by(read(null, 'offline'), 'ram')).toMatchObject({ state: 'offline', reason: 'network', pct: null });
    expect(machineValue(by(read(null, 'offline'), 'ram'))).toBe('Unknown — the hub is not answering');
    expect(by(read(null, 'demo'), 'ram')).toMatchObject({ state: 'demo', pct: null });
    expect(machineValue(by(read(null, 'demo'), 'ram'))).toBe('Demo sample');
    expect(by(read(null, 'live'), 'ram')).toMatchObject({ state: 'unknown', reason: 'not-reported' });
  });

  it('keeps the last values, as stale, while the hub is stale', () => {
    expect(by(read(sys(), 'stale'), 'ram')).toMatchObject({ state: 'stale', pct: 19 });
  });
});
