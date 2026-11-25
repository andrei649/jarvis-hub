import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', () => ({ apiGet: vi.fn() }));
import { apiGet } from '../api/client';
import { resetPolling } from './poll';
import {
  useApprovalMode, useAttention, useAuditVerify, useAway, useComponentsHealth, useEgressLedger, useHeartbeats, useInterrupts,
  useKillSwitchReading, useLastSeenAt, useObserver, usePaymentsWaiting, usePressureReading, useRunningTasks, useSlots, useSubagents, useVerdict,
} from './hooks';
import { LAST_SEEN_KEY } from './away';
import { T0, hubOf } from './test-support';

const get = apiGet as unknown as ReturnType<typeof vi.fn>;
const refusal = (status: number) => Object.assign(new Error(`GET -> ${status}`), { status });

/** The hub answering every path the signal hooks read, healthy. */
function healthy(path: string): unknown {
  if (path === '/autonomy/mode') return { mode: 'ask' };
  if (path === '/autonomy/interrupts') return { remaining: 3, per_day: 4, used: 1 };
  if (path === '/api/security/audit/verify') return { valid: true, first_invalid_id: null, entries: 921, tamper_evident: true };
  if (path === '/autonomy/observer') return { enabled: true, probes: 2, tracked: 7, unhealthy: [] };
  if (path === '/api/security/kill-switch') return { global: false, any_halted: false, halted_count: 0 };
  if (path === '/api/health/components') return { components: {}, failed: [], summary: '0/0 components ok' };
  if (path === '/api/system/pressure') return { boot_id: 'b', conditions: [], worst: null };
  if (path.startsWith('/autonomy/tasks')) return { tasks: [], total: 0 };
  if (path.startsWith('/api/dashboard/today')) return { items: [], counts: {} };
  if (path === '/heartbeat/status') return { scheduler_running: true, heartbeats: [], blocked: [] };
  if (path === '/api/status/slots') return { slots: { turns: { running: 0, per_session: 1, cap: 4 }, lanes: [], subagents: { running: 0, cap: 2 } }, holders: [], holders_total: 0 };
  if (path === '/api/subagents') return { spawns: [], stats: { active: 0, cap: 4 } };
  if (path === '/api/payments') return { payments: [] };
  if (path === '/api/admin/network/calls') return { external_egress_total: 42, model_egress_total: 0, ledger: {} };
  throw refusal(404);
}

let answers: (path: string) => unknown = healthy;
beforeEach(() => {
  resetPolling();
  get.mockReset();
  answers = healthy;
  get.mockImplementation(async (path: string) => answers(path));
  localStorage.clear();
});
afterEach(() => { resetPolling(); vi.restoreAllMocks(); });

function Show({ id, use }: { id: string; use: () => { state: string; reason?: string; intervalMs?: number; source?: string; value: unknown } }) {
  const r = use();
  return <output data-testid={id}>{JSON.stringify({ state: r.state, reason: r.reason, intervalMs: r.intervalMs, source: r.source })}</output>;
}
const read = (id: string) => JSON.parse(screen.getByTestId(id).textContent as string);

describe('the signal hooks: paths, credential and cadence (§5.6)', () => {
  const CASES: [string, (opts?: any) => any, string, boolean, number][] = [
    ['useApprovalMode', useApprovalMode, '/autonomy/mode', true, 60_000],
    ['useInterrupts', useInterrupts, '/autonomy/interrupts', true, 60_000],
    ['useAuditVerify', useAuditVerify, '/api/security/audit/verify', false, 300_000],
    ['useObserver', useObserver, '/autonomy/observer', true, 60_000],
    ['useAway', useAway, '/api/dashboard/today?days=1&limit=50', false, 60_000],
    ['useHeartbeats', useHeartbeats, '/heartbeat/status', false, 300_000],
    ['useSlots', useSlots, '/api/status/slots', false, 30_000],
    ['useSubagents', useSubagents, '/api/subagents', false, 30_000],
    ['useRunningTasks', useRunningTasks, '/autonomy/tasks?status=running', true, 30_000],
    ['useEgressLedger', useEgressLedger, '/api/admin/network/calls', true, 60_000],
    ['usePressureReading', usePressureReading, '/api/system/pressure', false, 60_000],
    ['useKillSwitchReading', useKillSwitchReading, '/api/security/kill-switch', false, 30_000],
    ['useComponentsHealth', useComponentsHealth, '/api/health/components', false, 300_000],
    ['usePaymentsWaiting', usePaymentsWaiting, '/api/payments', true, 60_000],
  ];

  it.each(CASES)('%s reads %s (admin %s) every %i ms', async (_name, hook, path, admin, interval) => {
    render(<Show id="r" use={() => hook()} />);
    expect(read('r')).toMatchObject({ state: 'unknown', reason: 'checking' });
    await waitFor(() => expect(['live', 'empty']).toContain(read('r').state));
    expect(read('r')).toMatchObject({ intervalMs: interval, source: path });
    expect(get).toHaveBeenCalledTimes(1);
    expect(get).toHaveBeenCalledWith(path, admin ? { admin: true } : undefined);
  });

  it.each(CASES)('%s never touches the network in demo or when disabled', (_name, hook) => {
    render(<><Show id="d" use={() => hook({ demo: true })} /><Show id="z" use={() => hook({ enabled: false })} /></>);
    expect(read('d').state).toBe('demo');
    expect(read('z').state).toBe('disabled');
    expect(get).not.toHaveBeenCalled();
  });

  it('tells a refused admin read from a switched-off feature and from a hub that is not there', async () => {
    answers = (path) => { throw path === '/autonomy/mode' ? refusal(403) : path === '/autonomy/observer' ? refusal(503) : new TypeError('Failed to fetch'); };
    render(<><Show id="m" use={() => useApprovalMode()} /><Show id="o" use={() => useObserver()} /><Show id="a" use={() => useAuditVerify()} /></>);
    await waitFor(() => expect(read('m').state).toBe('refused'));
    await waitFor(() => expect(read('o')).toMatchObject({ state: 'unknown', reason: 'unavailable' }));
    await waitFor(() => expect(read('a')).toMatchObject({ state: 'offline', reason: 'network' }));
  });

  it('an interrupt budget the hub has not wired is unknown (not reported), never 0 of 0', async () => {
    answers = (path) => (path === '/autonomy/interrupts' ? { remaining: null, per_day: null, used: null } : healthy(path));
    render(<Show id="i" use={() => useInterrupts()} />);
    await waitFor(() => expect(read('i')).toMatchObject({ state: 'unknown', reason: 'not-reported' }));
  });

  it('an answer that is not the hub\'s shape is malformed, not empty', async () => {
    answers = (path) => (path === '/autonomy/mode' ? { mode: 'turbo' } : healthy(path));
    render(<Show id="m" use={() => useApprovalMode()} />);
    await waitFor(() => expect(read('m')).toMatchObject({ state: 'unknown', reason: 'malformed' }));
  });

  it('nothing pending is "empty" for payments and running tasks, an answer and not a gap', async () => {
    render(<><Show id="p" use={() => usePaymentsWaiting()} /><Show id="t" use={() => useRunningTasks()} /><Show id="n" use={() => usePressureReading()} /></>);
    await waitFor(() => expect(read('p').state).toBe('empty'));
    await waitFor(() => expect(read('t').state).toBe('empty'));
    await waitFor(() => expect(read('n').state).toBe('empty'));
  });

  it('shares one request between callers of the same path (the docket\'s feed, the stop)', async () => {
    render(<><Show id="a" use={() => useKillSwitchReading()} /><Show id="b" use={() => useKillSwitchReading()} /></>);
    await waitFor(() => expect(read('a').state).toBe('live'));
    expect(get).toHaveBeenCalledTimes(1);
  });
});

function Verdicts({ lang = 'en', demo = false }: { lang?: string; demo?: boolean }) {
  const v = useVerdict(hubOf({ checkedAt: Date.now(), lastGoodAt: Date.now() }), lang, { demo });
  return <output data-testid="v">{JSON.stringify({ state: v.state, rule: v.rule, headline: v.headline, missing: v.missing ?? null })}</output>;
}

describe('useVerdict', () => {
  it('goes from Checking… to Working normally once every reading has answered', async () => {
    render(<Verdicts />);
    expect(read('v')).toMatchObject({ rule: 13 });   // nothing has answered yet: unknown, never normal
    await waitFor(() => expect(read('v')).toMatchObject({ state: 'normal', rule: 12, headline: 'Working normally' }));
  });

  it('never says normal while a reading is refused: it names it', async () => {
    answers = (path) => { if (path === '/autonomy/observer') throw refusal(401); return healthy(path); };
    render(<Verdicts />);
    await waitFor(() => expect(read('v').rule).toBe(13));
    await waitFor(() => expect(screen.getByTestId('v').textContent).toContain('the service probes'));
    expect(read('v').state).toBe('unknown');
  });

  it('reads a down service and its pending restart from the shared feeds', async () => {
    answers = (path) => {
      if (path === '/autonomy/observer') return { enabled: true, probes: 2, tracked: 3, unhealthy: [{ key: 'service.qdrant', detail: 'qdrant not responding on 127.0.0.1:6333', severity: 'CRITICAL', since: '2026-11-23T08:14:00+00:00' }] };
      if (path === '/autonomy/tasks?status=blocked&limit=200') return { tasks: [{ id: 12, kind: 'restart_service', title: 'Restart qdrant?', agent: 'steve', payload: { service: 'qdrant' } }] };
      return healthy(path);
    };
    function Remedy() {
      const v = useVerdict(hubOf({ checkedAt: Date.now(), lastGoodAt: Date.now() }), 'en');
      return <output data-testid="r">{JSON.stringify({ rule: v.rule, remedy: v.remedy ?? null, since: v.since })}</output>;
    }
    render(<Remedy />);
    await waitFor(() => expect(read('r').rule).toBe(10));
    await waitFor(() => expect(read('r').remedy).toMatchObject({ taskId: 12 }));
    expect(read('r').remedy.href).toContain('#docket-entry-12');
    expect(read('r').since).toBe(Date.UTC(2026, 10, 23, 8, 14));
  });

  it('is the demo verdict in demo and asks for nothing', () => {
    render(<Verdicts demo />);
    expect(read('v')).toMatchObject({ state: 'demo', rule: 1 });
    expect(get).not.toHaveBeenCalled();
  });

  it('speaks the language it is given', async () => {
    render(<Verdicts lang="ro" />);
    await waitFor(() => expect(read('v').headline).toBe('Funcționează normal'));
  });
});

describe('useAttention', () => {
  function Notes({ demo = false }: { demo?: boolean }) {
    const a = useAttention({ demo });
    return <output data-testid="a">{JSON.stringify(a)}</output>;
  }
  it('has the stop\'s word at once as Unknown and Armed once the stop answers; no counts that nothing proved', async () => {
    render(<Notes />);
    expect(JSON.parse(screen.getByTestId('a').textContent as string)).toEqual({ killSwitch: { key: 'killSwitch', state: 'unknown' } });
    await waitFor(() => expect(JSON.parse(screen.getByTestId('a').textContent as string).killSwitch.state).toBe('armed'));
    expect(JSON.parse(screen.getByTestId('a').textContent as string)).toEqual({ killSwitch: { key: 'killSwitch', state: 'armed' } });
  });

  it('notes waiting payments and a down service from live answers, and a broken record', async () => {
    answers = (path) => {
      if (path === '/api/payments') return { payments: [{ status: 'pending' }] };
      if (path === '/autonomy/observer') return { enabled: true, probes: 1, tracked: 1, unhealthy: [{ key: 'service.n8n', detail: 'n8n down', severity: 'WARN' }] };
      if (path === '/api/security/audit/verify') return { valid: false, first_invalid_id: 9, entries: 12 };
      return healthy(path);
    };
    render(<Notes />);
    await waitFor(() => expect(JSON.parse(screen.getByTestId('a').textContent as string)).toMatchObject({
      payments: { key: 'payments', count: 1 }, services: { key: 'services', count: 1 }, record: { key: 'record', brokenAt: 9 },
    }));
  });

  it('asks for none of its own readings in demo', () => {
    render(<Notes demo />);
    // the docket summary is the docket engineer's hook and takes no demo flag; every reading this file owns stays off the network
    const asked = get.mock.calls.map(([path]: [string]) => path).filter((path: string) => !path.startsWith('/autonomy/tasks?status=blocked'));
    expect(asked).toEqual([]);
    expect(JSON.parse(screen.getByTestId('a').textContent as string)).toEqual({ killSwitch: { key: 'killSwitch', state: 'unknown' } });
  });
});

describe('useLastSeenAt', () => {
  function Seen() {
    const seen = useLastSeenAt();
    return <output data-testid="s">{String(seen)}</output>;
  }
  it('reads the stored visit once at mount and keeps it, and writes the time the page is hidden', () => {
    localStorage.setItem(LAST_SEEN_KEY, String(T0));
    render(<Seen />);
    expect(screen.getByTestId('s').textContent).toBe(String(T0));
    act(() => { window.dispatchEvent(new Event('pagehide')); });
    expect(Number(localStorage.getItem(LAST_SEEN_KEY))).toBeGreaterThan(T0);
    expect(screen.getByTestId('s').textContent).toBe(String(T0));   // the list does not jump while the page is open
  });
  it('is null without a stored visit', () => {
    render(<Seen />);
    expect(screen.getByTestId('s').textContent).toBe('null');
  });
  it('writes when the document is hidden', () => {
    render(<Seen />);
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
    act(() => { document.dispatchEvent(new Event('visibilitychange')); });
    delete (document as any).visibilityState;
    expect(localStorage.getItem(LAST_SEEN_KEY)).not.toBeNull();
  });
});
