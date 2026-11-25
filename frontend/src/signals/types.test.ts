import { describe, expect, it } from 'vitest';
import { PRESSURE_CONDITIONS, noPressure, pressureFrom, residencyFrom, slotUsageFrom } from './types';

describe('pressureFrom (GET /api/system/pressure)', () => {
  const disk = { condition: 'disk_critical', dismissed: true, level: 'critical', percent: 97.4, paths: [{ path: 'C:\\', percent: 97.4 }] };
  const memory = { condition: 'memory_elevated', dismissed: false, level: 'elevated', percent: 88 };

  it('keeps every raised condition, dismissed or not, worst first, and recomputes the worst not dismissed', () => {
    const r = pressureFrom({ boot_id: 'b1', conditions: [memory, disk], worst: memory, sampled_at: 1 });
    expect(r.bootId).toBe('b1');
    expect(r.conditions.map((c) => c.condition)).toEqual(['disk_critical', 'memory_elevated']);
    expect(r.conditions[0]).toEqual({ condition: 'disk_critical', level: 'critical', dismissed: true, percent: 97, paths: [{ path: 'C:\\', percent: 97 }] });
    expect(r.worst).toMatchObject({ condition: 'memory_elevated', level: 'elevated', dismissed: false, percent: 88, paths: [] });
    expect(noPressure(r)).toBe(false);
  });

  it('reads an answer with nothing raised as empty, never as a guess', () => {
    const r = pressureFrom({ boot_id: 'b1', conditions: [], worst: null, sampled_at: null });
    expect(r).toEqual({ bootId: 'b1', conditions: [], worst: null });
    expect(noPressure(r)).toBe(true);
  });

  it('names the out-of-memory restart suspected, leaves unknown conditions out, and is worst-first by the hub\'s rank', () => {
    const r = pressureFrom({ boot_id: 'b', conditions: [{ condition: 'cpu_hot', dismissed: false }, { condition: 'oom_restart_suspected', memory_level: 'critical' }] });
    expect(r.conditions).toEqual([{ condition: 'oom_restart_suspected', level: 'suspected', dismissed: false, percent: null, paths: [] }]);
    expect(PRESSURE_CONDITIONS[0]).toBe('disk_critical');
  });

  it('throws on an answer that is not the hub\'s shape (the poller then says malformed)', () => {
    for (const raw of [null, 'x', {}, { boot_id: 'b' }, { conditions: [] }, { boot_id: '', conditions: [] }, { boot_id: 'b', conditions: 'none' }]) {
      expect(() => pressureFrom(raw), JSON.stringify(raw)).toThrow();
    }
  });
});

describe('slotUsageFrom and residencyFrom (/status)', () => {
  it('keeps the hub\'s counts and leaves what it could not count unknown', () => {
    expect(slotUsageFrom({ turns: null, lanes: [], subagents: null })).toEqual({ turns: null, lanes: [], subagents: null });
    expect(slotUsageFrom({ turns: { running: 0, per_session: null, cap: 4 }, lanes: [], subagents: { running: 0, cap: 2 } }))
      .toEqual({ turns: { running: 0, per_session: null, cap: 4 }, lanes: [], subagents: { running: 0, cap: 2 } });
    expect(slotUsageFrom({ turns: { running: 1.5 }, lanes: [], subagents: { running: 1 } })).toEqual({ turns: null, lanes: [], subagents: null });
    for (const raw of [null, [], 'x', { turns: { running: 1 } }]) expect(slotUsageFrom(raw), JSON.stringify(raw)).toBeNull();
  });

  it('knows the three residency words and nothing else', () => {
    expect(['known', 'unknown', 'offline'].map(residencyFrom)).toEqual(['known', 'unknown', 'offline']);
    expect([null, '', 'KNOWN', 1].map(residencyFrom)).toEqual([null, null, null, null]);
  });
});
