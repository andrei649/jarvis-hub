import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', () => ({ apiGet: vi.fn() }));
import { apiGet } from '../api/client';
import { EMPTY_SNAPSHOT, outcomeOf, readingFromSnapshot, refreshPolled, resetPolling, usePolled, type PollOptions } from './poll';

const get = apiGet as unknown as ReturnType<typeof vi.fn>;
const refusal = (status: number) => Object.assign(new Error(`GET -> ${status}`), { status });

function Probe({ path, id, opts }: { path: string; id: string; opts?: PollOptions<any> }) {
  const r = usePolled(path, opts);
  return <output data-testid={id}>{`${r.state}|${r.value === null ? 'null' : JSON.stringify(r.value)}|${r.reason ?? ''}`}</output>;
}
const text = (id: string) => screen.getByTestId(id).textContent;

let visibility: DocumentVisibilityState = 'visible';
beforeEach(() => {
  resetPolling();
  get.mockReset();
  visibility = 'visible';
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visibility });
});
afterEach(() => {
  resetPolling();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  delete (document as any).visibilityState;
});

describe('usePolled', () => {
  it('starts as checking — unknown, never a 0 — before the first answer', () => {
    get.mockReturnValue(new Promise(() => {}));
    render(<Probe path="/autonomy/mode" id="a" />);
    expect(text('a')).toBe('unknown|null|checking');
  });

  it('shares one request between every caller of a path, and keeps the admin request apart', async () => {
    get.mockResolvedValue({ mode: 'ask' });
    render(<><Probe path="/autonomy/mode" id="a" /><Probe path="/autonomy/mode" id="b" opts={{ intervalMs: 60_000 }} />
      <Probe path="/autonomy/mode" id="c" opts={{ admin: true }} /></>);
    await waitFor(() => expect(text('a')).toBe('live|{"mode":"ask"}|'));
    expect(text('b')).toBe('live|{"mode":"ask"}|');
    await waitFor(() => expect(text('c')).toBe('live|{"mode":"ask"}|'));
    expect(get).toHaveBeenCalledTimes(2);
    expect(get).toHaveBeenCalledWith('/autonomy/mode', undefined);
    expect(get).toHaveBeenCalledWith('/autonomy/mode', { admin: true });
  });

  it('tells refused apart from offline and from a switched-off feature', async () => {
    get.mockImplementation((path: string) => Promise.reject(
      path === '/refused' ? refusal(401) : path === '/forbidden' ? refusal(403)
        : path === '/off' ? refusal(503) : path === '/broken' ? refusal(500) : new TypeError('Failed to fetch')));
    render(<><Probe path="/refused" id="r" /><Probe path="/forbidden" id="f" /><Probe path="/offline" id="o" />
      <Probe path="/off" id="u" /><Probe path="/broken" id="e" /></>);
    await waitFor(() => expect(text('r')).toBe('refused|null|credential'));
    expect(text('f')).toBe('refused|null|credential');
    await waitFor(() => expect(text('o')).toBe('offline|null|network'));
    await waitFor(() => expect(text('u')).toBe('unknown|null|unavailable'));
    await waitFor(() => expect(text('e')).toBe('unknown|null|http'));
  });

  it('parses with the caller\'s parser, says malformed when it throws, and empty when asked', async () => {
    get.mockResolvedValue({ tasks: [] });
    const tasks = (raw: any) => { if (!Array.isArray(raw?.tasks)) throw new Error('no tasks'); return raw.tasks; };
    const strict = () => { throw new Error('nope'); };
    const isEmpty = (list: unknown[]) => list.length === 0;
    render(<><Probe path="/autonomy/tasks?status=blocked" id="a" opts={{ admin: true, parse: tasks, isEmpty }} />
      <Probe path="/autonomy/tasks?status=blocked" id="b" opts={{ admin: true, parse: strict }} /></>);
    await waitFor(() => expect(text('a')).toBe('empty|[]|'));
    expect(text('b')).toBe('unknown|null|malformed');
    expect(get).toHaveBeenCalledTimes(1);
  });

  it('never touches the network in demo or when disabled', () => {
    render(<><Probe path="/x" id="d" opts={{ demo: true, demoValue: { n: 3 } }} /><Probe path="/x" id="z" opts={{ enabled: false }} /></>);
    expect(text('d')).toBe('demo|{"n":3}|');
    expect(text('z')).toBe('disabled|null|');
    expect(get).not.toHaveBeenCalled();
  });

  it('asks again on refresh, and once more when a refresh arrives during a request', async () => {
    let n = 0;
    get.mockImplementation(() => Promise.resolve({ n: ++n }));
    render(<Probe path="/x" id="a" />);
    await waitFor(() => expect(text('a')).toBe('live|{"n":1}|'));
    await act(async () => { await refreshPolled('/x'); });
    expect(text('a')).toBe('live|{"n":2}|');
    await act(async () => {
      const first = refreshPolled('/x');
      void refreshPolled('/x');
      await first;
    });
    await waitFor(() => expect(text('a')).toBe('live|{"n":4}|'));
    expect(get).toHaveBeenCalledTimes(4);
  });

  it('resolves a refresh asked during a request only when the follow-up\'s answer has landed', async () => {
    const pending: Array<(value: unknown) => void> = [];
    get.mockImplementation(() => new Promise((resolve) => { pending.push(resolve); }));
    render(<Probe path="/x" id="a" />);
    await waitFor(() => expect(pending.length).toBe(1));
    let settled = false;
    let follow!: Promise<void>;
    act(() => { follow = refreshPolled('/x').then(() => { settled = true; }); });
    void refreshPolled('/x');                          // a second ask joins the same follow-up
    await act(async () => { pending[0]({ n: 1 }); });
    await waitFor(() => expect(text('a')).toBe('live|{"n":1}|'));
    await waitFor(() => expect(pending.length).toBe(2));
    expect(settled).toBe(false);
    await act(async () => { pending[1]({ n: 2 }); await follow; });
    expect(settled).toBe(true);
    expect(text('a')).toBe('live|{"n":2}|');
    expect(get).toHaveBeenCalledTimes(2);
  });

  it('says malformed, not offline, when a 2xx answer is not JSON (the real client)', async () => {
    const real = await vi.importActual<typeof import('../api/client')>('../api/client');
    get.mockImplementation(real.apiGet);
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<!doctype html><title>a proxy page</title>',
      { status: 200, headers: { 'Content-Type': 'text/html' } })));
    render(<Probe path="/proxied" id="a" />);
    await waitFor(() => expect(text('a')).toBe('unknown|null|malformed'));
  });

  it('asks again when the window regains focus, only for callers that want it', async () => {
    get.mockResolvedValue({ ok: true });
    render(<><Probe path="/focus" id="a" opts={{ refreshOnFocus: true }} /><Probe path="/plain" id="b" /></>);
    await waitFor(() => expect(text('a')).toBe('live|{"ok":true}|'));
    await waitFor(() => expect(text('b')).toBe('live|{"ok":true}|'));
    expect(get).toHaveBeenCalledTimes(2);
    await act(async () => { window.dispatchEvent(new Event('focus')); });
    await waitFor(() => expect(get).toHaveBeenCalledTimes(3));
    expect(get.mock.calls.map((c) => c[0])).toEqual(['/focus', '/plain', '/focus']);
  });

  it('turns stale when answers stop, and polls on its interval', async () => {
    vi.useFakeTimers();
    get.mockResolvedValueOnce({ n: 1 }).mockReturnValue(new Promise(() => {}));
    render(<Probe path="/x" id="a" opts={{ intervalMs: 10_000 }} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(text('a')).toBe('live|{"n":1}|');
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(get).toHaveBeenCalledTimes(2);        // the next poll went out (and hangs)
    expect(text('a')).toBe('live|{"n":1}|');
    await act(async () => { await vi.advanceTimersByTimeAsync(15_100); });
    expect(text('a')).toBe('stale|{"n":1}|');
  });

  it('pauses while the page is hidden and catches up when it is shown', async () => {
    vi.useFakeTimers();
    get.mockResolvedValue({ ok: true });
    render(<Probe path="/x" id="a" opts={{ intervalMs: 10_000 }} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(get).toHaveBeenCalledTimes(1);
    visibility = 'hidden';
    act(() => { document.dispatchEvent(new Event('visibilitychange')); });
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(get).toHaveBeenCalledTimes(1);
    visibility = 'visible';
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); await vi.advanceTimersByTimeAsync(0); });
    expect(get).toHaveBeenCalledTimes(2);
    expect(text('a')).toBe('live|{"ok":true}|');
  });
});

describe('readingFromSnapshot', () => {
  const ok = { outcome: 'ok' as const, hasRaw: true, raw: { a: 1 }, status: null, checkedAt: 1_000, lastGoodAt: 1_000, tick: 0 };
  const parsed = { ok: true as const, value: { a: 1 } };

  it('is live up to 2.5 intervals after the last good answer, then stale', () => {
    expect(readingFromSnapshot(ok, { path: '/x', intervalMs: 30_000, parsed, now: 76_000 }).state).toBe('live');
    const stale = readingFromSnapshot(ok, { path: '/x', intervalMs: 30_000, parsed, now: 76_001 });
    expect(stale).toMatchObject({ state: 'stale', value: { a: 1 }, lastGoodAt: 1_000, source: '/x' });
  });

  it('keeps the last good value through offline, and drops it on refusal', () => {
    const offline = readingFromSnapshot({ ...ok, outcome: 'offline', checkedAt: 40_000 }, { path: '/x', intervalMs: 30_000, parsed, now: 40_000 });
    expect(offline).toMatchObject({ state: 'offline', value: { a: 1 }, lastGoodAt: 1_000, reason: 'network' });
    const refused = readingFromSnapshot({ ...ok, outcome: 'refused', status: 403 }, { path: '/x', intervalMs: 30_000, parsed, now: 2_000 });
    expect(refused).toMatchObject({ state: 'refused', value: null, reason: 'credential', status: 403 });
  });

  it('reads nothing into an empty snapshot', () => {
    expect(readingFromSnapshot(EMPTY_SNAPSHOT, { path: '/x', intervalMs: 30_000, parsed: null, now: 0 }))
      .toMatchObject({ state: 'unknown', value: null, reason: 'checking' });
  });

  it('classifies failures by status', () => {
    expect(outcomeOf(refusal(401)).outcome).toBe('refused');
    expect(outcomeOf(refusal(403)).outcome).toBe('refused');
    expect(outcomeOf(new TypeError('Failed to fetch')).outcome).toBe('offline');
    expect(outcomeOf(refusal(502)).outcome).toBe('offline');
    expect(outcomeOf(refusal(503)).outcome).toBe('unavailable');
    expect(outcomeOf(refusal(404)).outcome).toBe('http');
    expect(outcomeOf(new SyntaxError('Unexpected token <')).outcome).toBe('malformed');
  });

  it('keeps the last good value, as unknown, through an answer it could not read', () => {
    const odd = readingFromSnapshot({ ...ok, outcome: 'malformed', checkedAt: 40_000 }, { path: '/x', intervalMs: 30_000, parsed, now: 40_000 });
    expect(odd).toMatchObject({ state: 'unknown', reason: 'malformed', value: { a: 1 }, lastGoodAt: 1_000, checkedAt: 40_000 });
  });
});
