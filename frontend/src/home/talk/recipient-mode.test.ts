/* The recipient's approval mode, resolved as agents/core/autonomy/mode.py resolve() does: the
   agent's own override, else the global mode; a global Off is a floor no override loosens. Without
   the overrides, only a global Off is known for every agent; anything else is not guessed. */
import { describe, expect, it } from 'vitest';
import type { Reading } from '../../signals/types';
import type { ApprovalModeReading } from '../../signals/wire';
import { parseModePolicy, recipientMode, type ModePolicy } from './recipient-mode';

const reading = <T>(state: Reading<T>['state'], value: T | null, extra: Partial<Reading<T>> = {}): Reading<T> =>
  ({ state, value, checkedAt: 1, lastGoodAt: value ? 1 : null, ...extra });
const policyOf = (global: 'auto' | 'ask' | 'off', agents: Record<string, 'auto' | 'ask' | 'off'> = {}): ModePolicy =>
  ({ global, agents: new Map(Object.entries(agents)) });
const globalOf = (mode: 'auto' | 'ask' | 'off'): Reading<ApprovalModeReading> => reading('live', { mode });

describe('parseModePolicy', () => {
  it('reads the global mode and every override', () => {
    const p = parseModePolicy({ global: 'ask', agents: { frigga: 'auto', stark: 'off' }, looser: { frigga: 'auto' } });
    expect(p.global).toBe('ask');
    expect([...p.agents]).toEqual([['frigga', 'auto'], ['stark', 'off']]);
    expect(parseModePolicy({ global: 'auto' }).agents.size).toBe(0);
  });

  it('refuses anything but the three words, for the global mode and for every override', () => {
    expect(() => parseModePolicy({ global: 'turbo', agents: {} })).toThrow();
    expect(() => parseModePolicy({ global: 'ask', agents: { frigga: 'yolo' } })).toThrow();
    expect(() => parseModePolicy({ global: 'ask', agents: ['frigga'] })).toThrow();
    expect(() => parseModePolicy(null)).toThrow();
  });

  it('keeps an agent id that names an object property as plain data', () => {
    const p = parseModePolicy({ global: 'ask', agents: { constructor: 'auto' } });
    expect(p.agents.get('constructor')).toBe('auto');
    expect(p.agents.get('toString')).toBeUndefined();
  });
});

describe('recipientMode', () => {
  it('is the agent\'s own override when it has one', () => {
    const r = recipientMode(reading('live', policyOf('ask', { frigga: 'auto' })), globalOf('ask'), 'frigga');
    expect(r.value).toEqual({ mode: 'auto', source: 'agent' });
    expect(r.state).toBe('live');
  });

  it('is the global mode for an agent without one', () => {
    expect(recipientMode(reading('live', policyOf('ask', { frigga: 'auto' })), globalOf('ask'), 'jarvis').value)
      .toEqual({ mode: 'ask', source: 'global' });
  });

  it('keeps a global Off for every agent, whatever its override', () => {
    expect(recipientMode(reading('live', policyOf('off', { frigga: 'auto' })), globalOf('off'), 'frigga').value)
      .toEqual({ mode: 'off', source: 'global' });
  });

  it('keeps a stale or offline policy\'s last good answer, with its state', () => {
    const r = recipientMode(reading('offline', policyOf('auto', { frigga: 'ask' }), { reason: 'network' }), globalOf('auto'), 'frigga');
    expect(r.state).toBe('offline');
    expect(r.value).toEqual({ mode: 'ask', source: 'agent' });
  });

  it('without the overrides, knows only a global Off, and guesses nothing else', () => {
    const refused = reading<ModePolicy>('refused', null, { reason: 'credential', status: 403 });
    expect(recipientMode(refused, globalOf('off'), 'frigga').value).toEqual({ mode: 'off', source: 'global' });
    const unknown = recipientMode(refused, globalOf('ask'), 'frigga');
    expect(unknown.value).toBeNull();
    expect(unknown.state).toBe('refused');
    const checking = recipientMode(reading<ModePolicy>('unknown', null, { reason: 'checking' }), reading('unknown', null, { reason: 'checking' }), 'frigga');
    expect(checking.value).toBeNull();
    expect(checking.reason).toBe('checking');
  });
});
