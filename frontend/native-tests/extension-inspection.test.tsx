import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ExtensionInspection } from '../../mobile/src/components/ExtensionInspection';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { records } from './support/storage';

const config = { baseUrl: 'https://hub.test/', token: 'user', adminToken: 'owner-secret' };
const key = 'jarvis.server.config.v1';
const row = {
  id: 'boats', version: '1.0.0', reason: 'activated',
  signature_verified: true, approval_verified: false, quarantine_state: 'not_inspected',
  execution_available: true, declared_tools: ['boats.summarize'], callable_tools: ['boats.summarize'],
  declared_commands: ['boat_report'], callable_commands: ['boat_report'],
  command_requires_args: ['boat_report'], declared_events: ['session.started'],
  capabilities: ['tools', 'commands', 'events.observe'],
};
const report = { mode: 'inspection_only', reason: 'activated', extensions: [row] };
const response = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300, status, json: async () => body,
}) as Response;
const calls = () => vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('/api/plugins/extensions'));
let server: ReturnType<typeof useServer>;
function Probe() {
  server = useServer();
  return <ExtensionInspection />;
}
const mount = () => render(<ServerProvider><Probe /></ServerProvider>);

beforeEach(() => {
  records.clear();
  records.set(key, JSON.stringify({ version: 2, config, appearance: null, chatScope: 'first' }));
  vi.stubGlobal('fetch', vi.fn(async () => response(report)));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

async function readyAndOpen() {
  await screen.findByText('Extensions');
  await waitFor(() => expect(server?.ready).toBe(true));
  fireEvent.click(screen.getByLabelText('Open extension inspection'));
}

it('keeps the disclosure collapsed without a request, then reads one user-authenticated snapshot', async () => {
  mount();
  await screen.findByText('Extensions');
  await waitFor(() => expect(server?.ready).toBe(true));
  expect(calls()).toHaveLength(0);

  fireEvent.click(screen.getByLabelText('Open extension inspection'));
  await screen.findByLabelText('Extension boats');
  expect(screen.getAllByText('boats.summarize')).toHaveLength(2);
  expect(screen.getByText('Owner approval not verified')).toBeTruthy();
  expect(calls()).toHaveLength(1);
  const [url, init] = calls()[0];
  expect(url).toBe('https://hub.test/api/plugins/extensions');
  expect(init).toMatchObject({ method: 'GET', cache: 'no-store', redirect: 'error',
    headers: { Accept: 'application/json', 'X-User-Token': 'user' } });
  expect((init?.headers as Record<string, string>)['X-Admin-Token']).toBeUndefined();
});

it('hides the previous snapshot before refresh and shows only a fixed error on refusal', async () => {
  let refuse = false;
  vi.mocked(fetch).mockImplementation(async () => refuse
    ? response({ error: 'PRIVATE_BACKEND_DETAIL' }, 403) : response(report));
  mount();
  await readyAndOpen();
  await screen.findByLabelText('Extension boats');

  refuse = true;
  fireEvent.click(screen.getByLabelText('Refresh extension inspection'));
  expect(screen.queryByLabelText('Extension boats')).toBeNull();
  await screen.findByText('This account cannot inspect extensions.');
  expect(document.body.textContent).not.toContain('PRIVATE_BACKEND_DETAIL');
});

it('closes and aborts a pending read, ignoring a late reply', async () => {
  let release!: (value: Response) => void;
  vi.mocked(fetch).mockImplementation(() => new Promise(resolve => { release = resolve; }));
  mount();
  await readyAndOpen();
  await waitFor(() => expect(calls()).toHaveLength(1));
  const signal = calls()[0][1]!.signal!;

  fireEvent.click(screen.getByLabelText('Close extension inspection'));
  expect(signal.aborted).toBe(true);
  await act(async () => release(response(report)));
  expect(screen.queryByLabelText('Extension boats')).toBeNull();
  expect(screen.getByLabelText('Open extension inspection')).toBeTruthy();
});

it('aborts and fences a pending reply when the disclosure unmounts', async () => {
  let release!: (value: Response) => void;
  vi.mocked(fetch).mockImplementation(() => new Promise(resolve => { release = resolve; }));
  const mounted = mount();
  await readyAndOpen();
  await waitFor(() => expect(calls()).toHaveLength(1));
  const signal = calls()[0][1]!.signal!;

  mounted.unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => release(response(report)));
  expect(screen.queryByLabelText('Extension boats')).toBeNull();
});

it.each([
  ['host', { baseUrl: 'https://new-hub.test/' }],
  ['user token', { token: 'new-user-token' }],
])('clears the snapshot and closes on a %s change', async (_label, change) => {
  mount();
  await readyAndOpen();
  await screen.findByLabelText('Extension boats');
  await act(async () => server.updateConfig({ ...config, ...change }));

  expect(screen.queryByLabelText('Extension boats')).toBeNull();
  expect(screen.getByLabelText('Open extension inspection')).toBeTruthy();
  expect(calls()).toHaveLength(1);
  fireEvent.click(screen.getByLabelText('Open extension inspection'));
  await screen.findByLabelText('Extension boats');
  expect(calls()).toHaveLength(2);
  const [url, init] = calls()[1];
  expect(url).toBe(change.baseUrl ? 'https://new-hub.test/api/plugins/extensions' : 'https://hub.test/api/plugins/extensions');
  expect((init?.headers as Record<string, string>)['X-User-Token']).toBe(change.token || 'user');
  expect((init?.headers as Record<string, string>)['X-Admin-Token']).toBeUndefined();
});

it('aborts a stalled connection read when the hub identity changes', async () => {
  let release!: (value: Response) => void;
  vi.mocked(fetch).mockImplementationOnce(() => new Promise(resolve => { release = resolve; }))
    .mockResolvedValue(response(report));
  mount();
  await readyAndOpen();
  await waitFor(() => expect(calls()).toHaveLength(1));
  const signal = calls()[0][1]!.signal!;

  await act(async () => server.updateConfig({ ...config, baseUrl: 'https://other.test/' }));
  expect(signal.aborted).toBe(true);
  expect(screen.queryByLabelText('Extension boats')).toBeNull();
  await act(async () => release(response(report)));
  expect(screen.queryByLabelText('Extension boats')).toBeNull();
});
