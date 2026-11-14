import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fetchDeliveries } from '../../mobile/src/api/deliveries';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { StatusScreen } from '../../mobile/src/screens/StatusScreen';
import { records } from './support/storage';

const config = { baseUrl: 'https://hub.test/', token: 'user', adminToken: 'owner' };
const key = 'jarvis.server.config.v1';
const states = ['sent', 'failed', 'partial', 'unknown', 'pending', 'attempting', 'skipped'] as const;
const row = (state: string, index: number) => ({ id: `receipt-${index}`, channel: 'telegram', target: '42', state,
  attempt: 1, error: null, chars: 12, created: 1_700_000_000, updated: 1_700_000_001, keyed: true,
  body: 'PRIVATE_BODY', key: 'PRIVATE_KEY' });
const view = { stats: { by_state: Object.fromEntries(states.map(state => [state, 1])), dead_targets: 2 },
  deliveries: states.map(row), dead_targets: ['PRIVATE_DEAD_TARGET'], dead_targets_truncated: false,
  retention: { window_seconds: 86_400, protected_limit: 700, protected_count: 23,
    retention_seconds: 604_800, ordinary_row_limit: 400 }, body: 'PRIVATE_TOP_LEVEL' };
const reply = (body: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status,
  json: async () => body }) as Response;
const calls = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('/api/channels/deliveries'));
let server: ReturnType<typeof useServer>;
function Probe() { server = useServer(); return <StatusScreen onGoToSettings={() => {}} />; }
const mount = () => render(<ServerProvider><Probe /></ServerProvider>);

beforeEach(() => {
  records.clear();
  records.set(key, JSON.stringify({ version: 2, config, appearance: null, chatScope: 'first' }));
  vi.stubGlobal('fetch', vi.fn(async (url: string) => reply(String(url).includes('/api/channels/deliveries') ? view : {},
    String(url).includes('/api/channels/deliveries') ? 200 : 503)));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('requests only after deliberate opening, with configured credentials and read-only options', async () => {
  mount();
  await screen.findByText('Delivery receipts');
  expect(calls()).toHaveLength(0);
  fireEvent.click(screen.getByLabelText('Open delivery receipts'));
  await screen.findByText(/Platform acknowledged all parts/);
  expect(calls()).toHaveLength(1);
  const [url, init] = calls()[0];
  expect(url).toBe('https://hub.test/api/channels/deliveries?limit=50');
  expect(init).toMatchObject({ method: 'GET', cache: 'no-store', redirect: 'error',
    headers: { Accept: 'application/json', 'X-User-Token': 'user', 'X-Admin-Token': 'owner' } });
  expect(vi.mocked(fetch).mock.calls.every(([, options]) => options.method === 'GET')).toBe(true);
});

it('shows bounded receipt semantics and ignores extra private body fields', async () => {
  mount(); await screen.findByText('Delivery receipts');
  fireEvent.click(screen.getByLabelText('Open delivery receipts'));
  await screen.findByText(/May have arrived; automatic resend is off/);
  expect(screen.getByText(/Some parts may have been accepted/)).toBeTruthy();
  expect(screen.getByText(/23 of 700 occupied/)).toBeTruthy();
  expect(screen.getByText(/counts describe retained rows/i)).toBeTruthy();
  expect(document.body.textContent).not.toContain('PRIVATE_BODY');
  expect(document.body.textContent).not.toContain('PRIVATE_KEY');
  expect(document.body.textContent).not.toContain('PRIVATE_DEAD_TARGET');
  expect(document.body.textContent).not.toContain('PRIVATE_TOP_LEVEL');
  expect(screen.queryByRole('button', { name: /Resend|Clear dead target/i })).toBeNull();
});

it('rejects malformed, duplicate and oversized snapshots', async () => {
  for (const invalid of [
    { ...view, deliveries: Array(51).fill(row('sent', 1)) },
    { ...view, deliveries: [row('sent', 1), row('sent', 1)] },
    { ...view, deliveries: [row('sent', 1), { ...row('sent', 2), attempt: -1 }] },
    { ...view, deliveries: [row('future', 1)] },
    { ...view, retention: { ...view.retention, window_seconds: 0 } },
  ]) {
    vi.mocked(fetch).mockResolvedValueOnce(reply(invalid));
    await expect(fetchDeliveries(config, new AbortController().signal)).rejects.toThrow(/Invalid delivery receipts/);
  }
});

it('shows generic access and ledger failures, clearing rows before a refused refresh', async () => {
  let allowed = true;
  vi.mocked(fetch).mockImplementation(async url => String(url).includes('/api/channels/deliveries')
    ? allowed ? reply(view) : reply({ error: 'SECRET_SERVER_MESSAGE' }, 403) : reply({}, 503));
  mount(); await screen.findByText('Delivery receipts');
  fireEvent.click(screen.getByLabelText('Open delivery receipts'));
  await screen.findByText(/receipt-0 · telegram/);
  allowed = false;
  fireEvent.click(screen.getByLabelText('Refresh delivery receipts'));
  expect(screen.queryByText(/receipt-0 · telegram/)).toBeNull();
  await screen.findByText('Owner access required.');
  expect(document.body.textContent).not.toContain('SECRET_SERVER_MESSAGE');
  vi.mocked(fetch).mockImplementation(async url => String(url).includes('/api/channels/deliveries')
    ? reply({ error: 'SECRET_SERVER_MESSAGE' }, 503) : reply({}, 503));
  fireEvent.click(screen.getByLabelText('Refresh delivery receipts'));
  await screen.findByText('Delivery ledger unavailable.');
});

it('closes and aborts a pending read, ignoring its late reply', async () => {
  let release!: (value: Response) => void;
  vi.mocked(fetch).mockImplementation((url: string) => String(url).includes('/api/channels/deliveries')
    ? new Promise(resolve => { release = resolve; }) : Promise.resolve(reply({}, 503)));
  mount(); await screen.findByText('Delivery receipts');
  fireEvent.click(screen.getByLabelText('Open delivery receipts'));
  await waitFor(() => expect(calls()).toHaveLength(1));
  const signal = calls()[0][1]!.signal!;
  fireEvent.click(screen.getByLabelText('Close delivery receipts'));
  expect(signal.aborted).toBe(true);
  await act(async () => release(reply(view)));
  expect(screen.queryByText(/receipt-0 · telegram/)).toBeNull();
});

it('clears loaded rows on credential change and fences the old reply', async () => {
  let release!: (value: Response) => void;
  vi.mocked(fetch).mockImplementation((url: string, init: RequestInit) => String(url).includes('/api/channels/deliveries')
    ? (init.headers as Record<string, string>)['X-Admin-Token'] === 'owner'
      ? new Promise(resolve => { release = resolve; }) : Promise.resolve(reply(view))
    : Promise.resolve(reply({}, 503)));
  mount(); await screen.findByText('Delivery receipts');
  fireEvent.click(screen.getByLabelText('Open delivery receipts'));
  await waitFor(() => expect(calls()).toHaveLength(1));
  await act(async () => server.updateConfig({ ...config, adminToken: 'new-owner' }));
  expect(calls()[0][1]!.signal!.aborted).toBe(true);
  expect(screen.queryByText(/receipt-0 · telegram/)).toBeNull();
  expect(calls()).toHaveLength(1);
  await act(async () => release(reply(view)));
  expect(screen.queryByText(/receipt-0 · telegram/)).toBeNull();
});

it('remounts closed and removes already-loaded private rows on a scope change', async () => {
  mount(); await screen.findByText('Delivery receipts');
  fireEvent.click(screen.getByLabelText('Open delivery receipts'));
  await screen.findByText(/receipt-0 · telegram/);
  await act(async () => server.updateConfig({ ...config, token: 'new-user' }));
  expect(screen.queryByText(/receipt-0 · telegram/)).toBeNull();
  expect(screen.getByLabelText('Open delivery receipts')).toBeTruthy();
  expect(calls()).toHaveLength(1);
});

it('aborts a pending request when Status unmounts', async () => {
  vi.mocked(fetch).mockImplementation((url: string) => String(url).includes('/api/channels/deliveries')
    ? new Promise(() => {}) : Promise.resolve(reply({}, 503)));
  const mounted = mount(); await screen.findByText('Delivery receipts');
  fireEvent.click(screen.getByLabelText('Open delivery receipts'));
  await waitFor(() => expect(calls()).toHaveLength(1));
  const signal = calls()[0][1]!.signal!;
  mounted.unmount();
  expect(signal.aborted).toBe(true);
});

it('aborts a stalled read after fifteen seconds without retrying', async () => {
  vi.useFakeTimers();
  try {
    vi.mocked(fetch).mockImplementation((_url, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new Error('aborted')));
    }));
    const pending = fetchDeliveries(config, new AbortController().signal);
    const assertion = expect(pending).rejects.toThrow(/timed out/);
    await vi.advanceTimersByTimeAsync(15000);
    await assertion;
    expect(calls()).toHaveLength(1);
  } finally { vi.useRealTimers(); }
});
