import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { actionFailures, apiPost, clearActionFailures } from '../api/client';
import { resetPolling } from '../signals/poll';
import { stopRefusalText } from './StopButton';
import { ARMED, HALTED, stubHub, type HubAnswer } from './test-support';
import { KILL_SWITCH_PATH, isHalted, isStopPressFailure, killSwitchFrom, useKillSwitch, type StopResult } from './useKillSwitch';

beforeEach(() => { resetPolling(); clearActionFailures(); localStorage.clear(); });
afterEach(() => { resetPolling(); clearActionFailures(); vi.unstubAllGlobals(); });

/** A hub whose POST and GET answers are given; the GET may change once the POST arrived. */
function hubAnswering(post: HubAnswer, before: HubAnswer, after: HubAnswer = before) {
  let posted = false;
  return stubHub((method) => {
    if (method === 'POST') { posted = true; return post; }
    return posted ? after : before;
  }, vi.stubGlobal);
}

async function press(lang: 'en' | 'ro' = 'en'): Promise<StopResult> {
  const { result } = renderHook(() => useKillSwitch(lang));
  await waitFor(() => expect(result.current.reason).not.toBe('checking'));
  let outcome!: StopResult;
  await act(async () => { outcome = await result.current.stop(); });
  return outcome;
}

describe('killSwitchFrom', () => {
  it('reads only the hub\'s exact public shape', () => {
    expect(killSwitchFrom(ARMED)).toEqual({ halted: false });
    expect(killSwitchFrom(HALTED)).toEqual({ halted: true });
    expect(() => killSwitchFrom({ global: false, halted: {} })).toThrow();
    expect(() => killSwitchFrom({ global: true, any_halted: false, halted_count: 0 })).toThrow();
    expect(() => killSwitchFrom(null)).toThrow();
  });
});

describe('useKillSwitch', () => {
  it('is Checking… before the first answer, then reads armed or halted', async () => {
    let state: unknown = ARMED;
    stubHub(() => ({ status: 200, body: state }), vi.stubGlobal);
    const { result } = renderHook(() => useKillSwitch());
    expect(result.current).toMatchObject({ state: 'unknown', reason: 'checking', value: null });
    await waitFor(() => expect(result.current.state).toBe('live'));
    expect(result.current.value).toEqual({ halted: false });
    expect(isHalted(result.current)).toBe(false);
    state = HALTED;
    await act(async () => { await result.current.refresh(); });
    expect(isHalted(result.current)).toBe(true);
  });

  it('never reads a malformed or refused answer as armed', async () => {
    stubHub(() => ({ status: 200, body: { global: false, halted: {} } }), vi.stubGlobal);
    const { result } = renderHook(() => useKillSwitch());
    await waitFor(() => expect(result.current.reason).toBe('malformed'));
    expect(result.current.state).toBe('unknown');
    expect(isHalted(result.current)).toBe(false);
    expect(result.current.value).toBeNull();
  });

  it('stops with one POST {engage, scope: global, reason: hud}, then reads the state again', async () => {
    let halted = false;
    const calls = stubHub((method) => {
      if (method === 'POST') { halted = true; return { status: 200, body: { ok: true, engaged: true } }; }
      return { status: 200, body: halted ? HALTED : ARMED };
    }, vi.stubGlobal);
    const { result } = renderHook(() => useKillSwitch());
    await waitFor(() => expect(result.current.state).toBe('live'));
    let outcome: unknown;
    await act(async () => { outcome = await result.current.stop(); });
    expect(outcome).toEqual({ ok: true, answer: 'accepted', after: 'halted' });
    const posts = calls.filter((c) => c.method === 'POST');
    expect(posts).toEqual([{ method: 'POST', path: KILL_SWITCH_PATH, body: { engage: true, scope: 'global', reason: 'hud' } }]);
    const after = calls.slice(calls.indexOf(posts[0]) + 1);
    expect(after.some((c) => c.method === 'GET' && c.path === KILL_SWITCH_PATH)).toBe(true);
    expect(isHalted(result.current)).toBe(true);
  });

  it('offers the stop while the state is unknown, and says what is known after it', async () => {
    const calls = hubAnswering({ status: 200, body: { ok: true } }, { status: 503, body: { error: 'kill-switch not available' } });
    const outcome = await press();
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1);
    // accepted, but the switch cannot be read: not "stopped", not "refused"
    expect(outcome).toEqual({ ok: false, answer: 'accepted', after: 'unknown', reason: 'the hub did not answer when asked again' });
    expect(stopRefusalText(outcome, 'en')).toBe('The hub accepted the stop, but did not answer when asked again: whether everything is halted is unknown until it answers.');
  });

  it('says "Nothing was halted" for a refusal only when the state read again says armed, in the hub\'s own words', async () => {
    hubAnswering({ status: 403, body: { error: 'kernel denied: admin.kill_switch' } }, { status: 200, body: ARMED });
    const refused = await press();
    expect(refused).toEqual({ ok: false, answer: 'refused', after: 'armed', reason: 'kernel denied: admin.kill_switch' });
    expect(stopRefusalText(refused, 'en')).toBe('Stop was refused — kernel denied: admin.kill_switch. Nothing was halted.');
    expect(stopRefusalText(refused, 'ro')).toBe('Oprirea a fost refuzată — kernel denied: admin.kill_switch. Nu s-a oprit nimic.');
  });

  it('reads a gateway timeout as unanswered, and a re-read that says halted as a stop that worked', async () => {
    // the reviewer's probe: the POST answers 504 and the state read again says halted
    hubAnswering({ status: 504, body: { error: 'gateway timeout' } }, { status: 200, body: ARMED }, { status: 200, body: HALTED });
    const outcome = await press();
    expect(outcome).toEqual({ ok: true, answer: 'unanswered', after: 'halted' });
    expect(stopRefusalText(outcome, 'en')).toBeNull();
  });

  it.each([502, 504, 'down'] as const)('treats %s as no answer: never "refused", "nothing halted" only as "not yet" while it reads armed', async (lost) => {
    hubAnswering(lost === 'down' ? 'down' : { status: lost }, { status: 200, body: ARMED });
    const outcome = await press();
    expect(outcome).toMatchObject({ ok: false, answer: 'unanswered', after: 'armed', unanswered: true, reason: 'no answer from the hub' });
    const text = stopRefusalText(outcome, 'en') as string;
    expect(text).toBe('The stop got no answer from the hub, and the hub still reports no halt: nothing is halted yet.');
    expect(text).not.toMatch(/refused/);
  });

  it('says it does not know when neither the stop nor the state read again got an answer', async () => {
    hubAnswering('down', { status: 200, body: ARMED }, 'down');
    const outcome = await press('ro');
    expect(outcome).toMatchObject({ ok: false, answer: 'unanswered', after: 'unknown', reason: 'niciun răspuns de la hub' });
    expect(stopRefusalText(outcome, 'en')).toBe('The stop got no answer from the hub. Whether anything was halted is unknown until the hub answers.');
  });

  it('keeps a refusal when the state cannot be read again, without claiming nothing was halted', async () => {
    hubAnswering({ status: 403, body: { error: 'kernel denied: x' } }, { status: 200, body: ARMED }, { status: 503, body: { error: 'kill-switch not available' } });
    const outcome = await press();
    expect(outcome).toEqual({ ok: false, answer: 'refused', after: 'unknown', reason: 'kernel denied: x' });
    const text = stopRefusalText(outcome, 'en') as string;
    expect(text).toBe('Stop was refused — kernel denied: x. The hub did not answer when asked again, so whether anything is halted is unknown.');
    expect(text).not.toMatch(/Nothing was halted/);
  });

  it('says an accepted stop that still reads armed as such', async () => {
    hubAnswering({ status: 200, body: { ok: true, engaged: true } }, { status: 200, body: ARMED });
    const outcome = await press();
    expect(outcome).toEqual({ ok: false, answer: 'accepted', after: 'armed', reason: 'the hub still reports no halt' });
    expect(stopRefusalText(outcome, 'en')).toBe('The hub accepted the stop, but it still reports no halt: nothing is halted.');
  });

  it('owns the failure the API client records for its own POST, and only that one', async () => {
    hubAnswering({ status: 403, body: { error: 'kernel denied: x' } }, { status: 200, body: ARMED });
    await press();
    const own = actionFailures();
    expect(own).toHaveLength(1);
    expect(isStopPressFailure(own[0])).toBe(true);
    // the same route posted outside a press (a page's own resume or a test) is not the stop's
    await new Promise((resolve) => setTimeout(resolve, 5));
    await act(async () => { await apiPost(KILL_SWITCH_PATH, { engage: false }, { admin: true }).catch(() => {}); });
    const later = actionFailures()[0];
    expect(later.path).toBe(KILL_SWITCH_PATH);
    expect(isStopPressFailure(later)).toBe(false);
  });
});

describe('stopRefusalText', () => {
  it('says "Nothing was halted" only for a refusal the state read again confirms', () => {
    const combos: StopResult[] = [];
    for (const answer of ['accepted', 'refused', 'unanswered'] as const) {
      combos.push({ ok: true, answer, after: 'halted' });
      for (const after of ['armed', 'unknown'] as const) combos.push({ ok: false, answer, after, reason: 'r' });
    }
    for (const result of combos) {
      const text = stopRefusalText(result, 'en');
      if (result.ok) expect(text, JSON.stringify(result)).toBeNull();
      else expect(text?.includes('Nothing was halted'), JSON.stringify(result)).toBe(result.answer === 'refused' && result.after === 'armed');
      for (const lang of ['en', 'ro'] as const) expect(stopRefusalText(result, lang) ?? '').not.toMatch(/\{\w+\}|undefined/);
    }
  });
});
