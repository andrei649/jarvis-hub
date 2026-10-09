import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { TaskMediationCard } from '../../mobile/src/components/TaskMediationCard';
import { StatusScreen } from '../../mobile/src/screens/StatusScreen';
import { records, storage } from './support/storage';

vi.mock('react-native', async (importOriginal) => {
  const native = await importOriginal<typeof import('react-native')>();
  const react = await import('react');
  return { ...native, ScrollView: ({ refreshControl, children, ...props }: any) =>
    react.createElement(native.ScrollView, props,
      refreshControl ? react.createElement('button', { onClick: refreshControl.props.onRefresh }, 'Pull to refresh') : null,
      children) };
});

const config = { baseUrl: 'https://first.test', token: 'user-one', adminToken: 'owner-one' };
const key = 'jarvis.server.config.v1';
const counts = { authorized_enqueue: 2, governed: 3, refused_unmediated: 4, ungoverned_detected: 5 };
const valid = (mode: 'off' | 'hold' | 'enforce' = 'enforce') => ({ mode, valid: true, stats: counts });
const response = (body: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body }) as Response;
const deferred = () => { let resolve!: (value: Response) => void; const promise = new Promise<Response>(r => { resolve = r; }); return { promise, resolve }; };
let server: ReturnType<typeof useServer>;
const goToSettings = vi.fn();
function CardProbe() { server = useServer(); return <TaskMediationCard onGoToSettings={goToSettings} />; }
function ScreenProbe() { server = useServer(); return <StatusScreen onGoToSettings={goToSettings} />; }
const mountCard = () => render(<ServerProvider><CardProbe /></ServerProvider>);
const mediationCalls = () => (fetch as ReturnType<typeof vi.fn>).mock.calls.filter(([url]) => String(url).endsWith('/autonomy/mediation'));

beforeEach(() => {
  records.clear();
  records.set(key, JSON.stringify({ version: 2, config, appearance: null, chatScope: 'first-scope' }));
  goToSettings.mockReset();
  global.fetch = vi.fn(async (url: string) => response(String(url).endsWith('/autonomy/mediation') ? valid() : {},
    String(url).endsWith('/autonomy/mediation') ? 200 : 503)) as any;
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it('waits for hydrated admin settings, then reads with both credentials and no body or write', async () => {
  let finishHydration!: (value: string | null) => void;
  const hydration = new Promise<string | null>(resolve => { finishHydration = resolve; });
  vi.spyOn(storage, 'getItem').mockImplementation(() => hydration);
  mountCard();
  expect(mediationCalls()).toHaveLength(0);
  await act(async () => finishHydration(records.get(key) ?? null));
  await waitFor(() => expect(screen.getByText('Authorized enqueue events: 2')).toBeTruthy());
  const [[url, init]] = mediationCalls();
  expect(url).toBe('https://first.test/autonomy/mediation');
  expect(init).toMatchObject({ method: 'GET', body: undefined,
    headers: { 'X-User-Token': 'user-one', 'X-Admin-Token': 'owner-one' } });
  expect((fetch as ReturnType<typeof vi.fn>).mock.calls.every(([, options]) => options.method === 'GET')).toBe(true);
});

it('places the independent card immediately after Trust in the actual Status screen', async () => {
  const view = render(<ServerProvider><ScreenProbe /></ServerProvider>);
  await waitFor(() => expect(view.getByText('Task mediation')).toBeTruthy());
  const trust = view.getByText('Trust').parentElement;
  expect(trust?.nextElementSibling?.contains(view.getByText('Task mediation'))).toBe(true);
  expect(trust?.nextElementSibling?.nextElementSibling?.contains(view.getByText('System map'))).toBe(true);
  await waitFor(() => expect(view.getByText('Effective mode: enforce')).toBeTruthy());
});

it('Status pull-to-refresh clears its mediation projection before the independent re-read', async () => {
  const refreshed = deferred(); let mediationReads = 0;
  global.fetch = vi.fn((url: string) => String(url).endsWith('/autonomy/mediation')
    ? ++mediationReads === 1 ? Promise.resolve(response(valid('off'))) : refreshed.promise
    : Promise.resolve(response({}, 503))) as any;
  const view = render(<ServerProvider><ScreenProbe /></ServerProvider>);
  await waitFor(() => expect(view.getByText('Authorized enqueue events: 2')).toBeTruthy());
  fireEvent.click(view.getByText('Pull to refresh'));
  expect(view.queryByText(/Authorized enqueue events:/)).toBeNull();
  expect(view.getByText(/Loading task mediation status/)).toBeTruthy();
  await waitFor(() => expect(mediationCalls()).toHaveLength(2));
  await act(async () => refreshed.resolve(response({ mode: 'hold', valid: false, stats: null })));
  expect(view.getByText('Effective mode: hold')).toBeTruthy();
  expect(view.getByText('Evidence: unavailable or invalid')).toBeTruthy();
  expect(view.queryByText(/Authorized enqueue events:/)).toBeNull();
});

it('does not request mediation without an admin token and opens Settings', async () => {
  records.set(key, JSON.stringify({ version: 2, config: { ...config, adminToken: '  ' }, appearance: null, chatScope: 'first-scope' }));
  mountCard();
  await waitFor(() => expect(screen.getByText(/Admin token required/)).toBeTruthy());
  expect(mediationCalls()).toHaveLength(0);
  fireEvent.click(screen.getByText('Settings'));
  expect(goToSettings).toHaveBeenCalledOnce();
});

it('does not request mediation for an unconfigured hub', async () => {
  records.set(key, JSON.stringify({ version: 2, config: { ...config, baseUrl: '' }, appearance: null, chatScope: 'first-scope' }));
  mountCard();
  await waitFor(() => expect(screen.getByText(/Connect a hub in Settings/)).toBeTruthy());
  expect(mediationCalls()).toHaveLength(0);
  fireEvent.click(screen.getByText('Settings'));
  expect(goToSettings).toHaveBeenCalledOnce();
});

it.each(['off', 'hold', 'enforce'] as const)('shows %s mode apart from valid evidence and four event counts', async mode => {
  global.fetch = vi.fn(async () => response(valid(mode))) as any;
  mountCard();
  await waitFor(() => expect(screen.getByText(`Effective mode: ${mode}`)).toBeTruthy());
  expect(screen.getByText('Evidence: verified')).toBeTruthy();
  for (const label of ['Authorized enqueue events: 2', 'Governed events: 3', 'Refused unmediated events: 4', 'Ungoverned events detected: 5']) {
    expect(screen.getByText(label)).toBeTruthy();
  }
  expect(screen.getByText(/verified recorded events, not every task/i)).toBeTruthy();
});

it('clears counts during refresh, then shows invalid evidence with no counts', async () => {
  const next = deferred(); let reads = 0;
  global.fetch = vi.fn(() => ++reads === 1 ? Promise.resolve(response(valid())) : next.promise) as any;
  mountCard();
  await waitFor(() => expect(screen.getByText('Authorized enqueue events: 2')).toBeTruthy());
  fireEvent.click(screen.getByText('Refresh'));
  expect(screen.queryByText(/Authorized enqueue events:/)).toBeNull();
  expect(screen.getByText(/Loading task mediation status/)).toBeTruthy();
  await act(async () => next.resolve(response({ mode: 'hold', valid: false, stats: null })));
  expect(screen.getByText('Effective mode: hold')).toBeTruthy();
  expect(screen.getByText('Evidence: unavailable or invalid')).toBeTruthy();
  expect(screen.queryByText(/Governed events:/)).toBeNull();
});

it('clears a valid count immediately on refresh and keeps errors neutral', async () => {
  let reads = 0;
  global.fetch = vi.fn(async () => ++reads === 1 ? response(valid())
    : response({ error: 'owner-one https://first.test secret' }, 401)) as any;
  mountCard();
  await waitFor(() => expect(screen.getByText('Authorized enqueue events: 2')).toBeTruthy());
  fireEvent.click(screen.getByText('Refresh'));
  expect(screen.queryByText(/Authorized enqueue events:/)).toBeNull();
  await waitFor(() => expect(screen.getByText('Task mediation status unavailable.')).toBeTruthy());
  expect(screen.queryByText(/Effective mode:/)).toBeNull();
  expect(document.body.textContent).not.toContain('owner-one');
  expect(document.body.textContent).not.toContain('check your user token');
});

it.each([
  response({ mode: 'future', valid: true, stats: counts }),
  response({ mode: 'enforce', valid: true, stats: { ...counts, governed: true } }),
  response({ mode: 'enforce', valid: true, stats: { ...counts, governed: -1 } }),
  response({ mode: 'enforce', valid: true, stats: { authorized_enqueue: 2 } }),
  response({ error: 'owner-one https://first.test secret' }, 401),
  response({ error: 'owner-one https://first.test secret' }, 503),
])('keeps malformed and denied responses neutral without numeric or credential leakage', async reply => {
  global.fetch = vi.fn(async () => reply) as any;
  mountCard();
  await waitFor(() => expect(screen.getByText('Task mediation status unavailable.')).toBeTruthy());
  expect(screen.queryByText(/Effective mode:/)).toBeNull();
  expect(screen.queryByText(/Authorized enqueue events:/)).toBeNull();
  expect(document.body.textContent).not.toContain('owner-one');
  expect(document.body.textContent).not.toContain('https://first.test');
  expect(document.body.textContent).not.toContain('check your user token');
  fireEvent.click(screen.getByText('Retry'));
  await waitFor(() => expect(mediationCalls()).toHaveLength(2));
});

it('synchronously clears old hub output and ignores a late response from that hub', async () => {
  const first = deferred(); const second = deferred();
  global.fetch = vi.fn((url: string) => String(url).startsWith('https://first.test')
    ? first.promise : second.promise) as any;
  mountCard();
  await waitFor(() => expect(mediationCalls()).toHaveLength(1));
  await act(async () => server.updateConfig({ ...config, baseUrl: 'https://second.test' }));
  expect(screen.queryByText(/Effective mode:/)).toBeNull();
  await waitFor(() => expect(mediationCalls()).toHaveLength(2));
  await act(async () => first.resolve(response(valid('off'))));
  expect(screen.queryByText('Effective mode: off')).toBeNull();
  await act(async () => second.resolve(response(valid('hold'))));
  expect(screen.getByText('Effective mode: hold')).toBeTruthy();
});

it('synchronously clears old admin credential output and ignores its delayed response', async () => {
  const first = deferred(); const second = deferred();
  global.fetch = vi.fn((_url: string, init: RequestInit) => (init.headers as Record<string, string>)['X-Admin-Token'] === 'owner-one'
    ? first.promise : second.promise) as any;
  mountCard();
  await waitFor(() => expect(mediationCalls()).toHaveLength(1));
  await act(async () => server.updateConfig({ ...config, adminToken: 'owner-two' }));
  expect(screen.queryByText(/Effective mode:/)).toBeNull();
  await waitFor(() => expect(mediationCalls()).toHaveLength(2));
  await act(async () => first.resolve(response(valid('off'))));
  expect(screen.queryByText('Effective mode: off')).toBeNull();
  await act(async () => second.resolve(response(valid('enforce'))));
  expect(screen.getByText('Effective mode: enforce')).toBeTruthy();
});

it('removes a displayed count in the same connection-change render before the new read completes', async () => {
  const next = deferred();
  global.fetch = vi.fn((url: string) => String(url).startsWith('https://first.test')
    ? Promise.resolve(response(valid('off'))) : next.promise) as any;
  mountCard();
  await waitFor(() => expect(screen.getByText('Authorized enqueue events: 2')).toBeTruthy());
  await act(async () => server.updateConfig({ ...config, baseUrl: 'https://second.test' }));
  expect(screen.queryByText(/Authorized enqueue events:/)).toBeNull();
  expect(screen.queryByText(/Effective mode:/)).toBeNull();
  await act(async () => next.resolve(response(valid('hold'))));
  expect(screen.getByText('Effective mode: hold')).toBeTruthy();
});

it('keeps the newer refresh result when an older same-scope read arrives later', async () => {
  const old = deferred(); let reads = 0;
  global.fetch = vi.fn(() => ++reads === 1 ? old.promise : Promise.resolve(response(valid('hold')))) as any;
  mountCard();
  await waitFor(() => expect(mediationCalls()).toHaveLength(1));
  fireEvent.click(screen.getByText('Refresh'));
  await waitFor(() => expect(screen.getByText('Effective mode: hold')).toBeTruthy());
  await act(async () => old.resolve(response(valid('off'))));
  expect(screen.getByText('Effective mode: hold')).toBeTruthy();
});

it('discards a response delivered after unmount', async () => {
  const late = deferred();
  global.fetch = vi.fn(() => late.promise) as any;
  const view = mountCard();
  await waitFor(() => expect(mediationCalls()).toHaveLength(1));
  view.unmount();
  await act(async () => late.resolve(response(valid('off'))));
  expect(view.container.textContent).toBe('');
});
