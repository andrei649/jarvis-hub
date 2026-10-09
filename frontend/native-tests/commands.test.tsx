import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fetchCommands } from '../../mobile/src/api/commands';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { ChatScreen } from '../../mobile/src/screens/ChatScreen';
import { records } from './support/storage';

const KEY = 'jarvis.server.config.v1';
const config = { baseUrl: 'https://hub.test/', token: 'user', adminToken: 'owner' };
const items = [{ name: 'status', command: '/status', usage: '/status', description: 'Show hub status', tier: 'user' },
  { name: 'restart', command: '/restart', usage: '/restart <service>', description: 'Restart a service', tier: 'admin' }];
const reply = (data: unknown, status = 200) => ({ ok: status < 400, status, json: async () => data });
let server: ReturnType<typeof useServer>;
function Probe() { server = useServer(); return <ChatScreen onGoToSettings={() => {}} />; }
const mount = () => render(<ServerProvider><Probe /></ServerProvider>);

class ChatXHR {
  static latest: ChatXHR;
  body: any;
  headers: Record<string, string> = {};
  constructor() { ChatXHR.latest = this; }
  open() {}
  setRequestHeader(name: string, value: string) { this.headers[name] = value; }
  send(body: string) { this.body = JSON.parse(body); }
  abort() {}
}

beforeEach(() => {
  records.clear();
  records.set(KEY, JSON.stringify({ version: 2, config, appearance: null, chatScope: 'scope-one' }));
  vi.stubGlobal('XMLHttpRequest', ChatXHR);
  (ChatXHR as typeof ChatXHR & { latest?: ChatXHR }).latest = undefined;
  vi.stubGlobal('fetch', vi.fn(async (url: string) => reply(url.endsWith('/api/commands')
    ? { ok: true, commands: items } : { agents: [] })));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('uses both configured chat credentials and returns the live catalog', async () => {
  const result = await fetchCommands(config, new AbortController().signal);
  expect(result).toEqual({ status: 'available', commands: items });
  expect(fetch).toHaveBeenCalledWith('https://hub.test/api/commands', expect.objectContaining({
    method: 'GET', headers: expect.objectContaining({ 'X-User-Token': 'user', 'X-Admin-Token': 'owner' }),
  }));
});

it('uses admin-only credentials and distinguishes the hub unavailable response', async () => {
  vi.mocked(fetch).mockResolvedValue(reply({ ok: false, reason: 'commands_unavailable', commands: [] }, 503) as Response);
  expect(await fetchCommands({ ...config, token: '' }, new AbortController().signal))
    .toEqual({ status: 'unavailable', commands: [] });
  const headers = vi.mocked(fetch).mock.calls[0][1]?.headers as Record<string, string>;
  expect(headers['X-Admin-Token']).toBe('owner');
  expect(headers['X-User-Token']).toBeUndefined();
});

it('rejects malformed catalog payloads and HTTP errors', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(reply({ ok: true, commands: [{ ...items[0], tier: 'root' }] }) as Response)
    .mockResolvedValueOnce(reply({ ok: false }, 401) as Response);
  await expect(fetchCommands(config, new AbortController().signal)).rejects.toThrow('Invalid command catalog');
  await expect(fetchCommands(config, new AbortController().signal)).rejects.toThrow(/401|Unauthorized/);
});

it('refuses non-command entries and oversized catalogs', async () => {
  vi.mocked(fetch).mockResolvedValueOnce(reply({ ok: true, commands: [{ ...items[0], command: 'status' }] }) as Response)
    .mockResolvedValueOnce(reply({ ok: true, commands: Array(257).fill(items[0]) }) as Response);
  await expect(fetchCommands(config, new AbortController().signal)).rejects.toThrow('Invalid command catalog');
  await expect(fetchCommands(config, new AbortController().signal)).rejects.toThrow('Invalid command catalog');
});

it('does not send a pre-aborted request and reports a bodyless auth failure', async () => {
  const abort = new AbortController(); abort.abort();
  await expect(fetchCommands(config, abort.signal)).rejects.toThrow(/cancelled/);
  expect(fetch).not.toHaveBeenCalled();
  vi.mocked(fetch).mockResolvedValue({ ok: false, status: 401, json: async () => { throw new Error('no JSON'); } } as Response);
  await expect(fetchCommands(config, new AbortController().signal)).rejects.toMatchObject({ status: 401 });
});

it('ends a stalled catalog read after fifteen seconds', async () => {
  vi.useFakeTimers();
  try {
    vi.mocked(fetch).mockImplementation((_url, options) => new Promise((_resolve, reject) => {
      options?.signal?.addEventListener('abort', () => reject(new Error('aborted')));
    }));
    const pending = fetchCommands(config, new AbortController().signal);
    const assertion = expect(pending).rejects.toThrow(/timed out/);
    await vi.advanceTimersByTimeAsync(15000);
    await assertion;
    expect(vi.mocked(fetch).mock.calls[0][1]?.signal?.aborted).toBe(true);
  } finally { vi.useRealTimers(); }
});

it('shows the live catalog and inserts a choice without sending it', async () => {
  records.set('jarvis.chat.conversation.v2', JSON.stringify({ version: 2, scope: 'scope-one',
    sessionId: 'saved-session', messages: [{ id: 'previous', role: 'user', text: 'Earlier topic' }] }));
  mount();
  await screen.findByPlaceholderText('Message Jarvis…');
  fireEvent.click(screen.getByText('Commands'));
  await screen.findByText('/restart');
  expect(screen.getByText('/restart <service>')).toBeTruthy();
  expect(screen.getByText('Restart a service')).toBeTruthy();
  expect(screen.getByText('Owner')).toBeTruthy();
  fireEvent.click(screen.getByText('/restart'));
  expect((screen.getByPlaceholderText('Message Jarvis…') as HTMLInputElement).value).toBe('/restart');
  expect(ChatXHR.latest).toBeUndefined();
  fireEvent.click(screen.getByText('Send'));
  expect(ChatXHR.latest.body.message).toBe('/restart');
  expect(ChatXHR.latest.body.session_id).toBe('saved-session');
  expect(ChatXHR.latest.headers['X-Admin-Token']).toBe('owner');
});

it('preserves a newer typed draft when a command is chosen', async () => {
  mount(); await screen.findByPlaceholderText('Message Jarvis…');
  fireEvent.click(screen.getByText('Commands'));
  await screen.findByLabelText('Insert /status in message');
  fireEvent.change(screen.getByPlaceholderText('Message Jarvis…'), { target: { value: 'My unsent question' } });
  fireEvent.click(screen.getByLabelText('Insert /status in message'));
  expect((screen.getByPlaceholderText('Message Jarvis…') as HTMLInputElement).value).toBe('My unsent question');
});

it('shows unavailable and retry states distinctly from an empty catalog', async () => {
  vi.mocked(fetch).mockImplementation(async url => reply(String(url).endsWith('/api/commands')
    ? { ok: false, reason: 'commands_unavailable', commands: [] } : { agents: [] },
  String(url).endsWith('/api/commands') ? 503 : 200) as Response);
  mount(); await screen.findByPlaceholderText('Message Jarvis…');
  fireEvent.click(screen.getByText('Commands'));
  await screen.findByText(/Commands unavailable/);
  vi.mocked(fetch).mockImplementation(async url => reply(String(url).endsWith('/api/commands')
    ? { ok: true, commands: [] } : { agents: [] }) as Response);
  fireEvent.click(screen.getByText('Retry'));
  await screen.findByText(/No commands available/);
});

it('shows a transport error with a retry action', async () => {
  vi.mocked(fetch).mockImplementation(async url => {
    if (String(url).endsWith('/api/commands')) throw new Error('offline');
    return reply({ agents: [] }) as Response;
  });
  mount(); await screen.findByPlaceholderText('Message Jarvis…');
  fireEvent.click(screen.getByText('Commands'));
  await screen.findByText(/Could not load commands/);
  expect(screen.getByText('Retry')).toBeTruthy();
});

it('aborts a pending read on close and ignores its late response', async () => {
  let release!: (value: any) => void;
  vi.mocked(fetch).mockImplementation(async url => String(url).endsWith('/api/commands')
    ? new Promise(resolve => { release = resolve; }) : reply({ agents: [] }) as Response);
  mount(); await screen.findByPlaceholderText('Message Jarvis…');
  fireEvent.click(screen.getByText('Commands'));
  await waitFor(() => expect(release).toBeDefined());
  const signal = vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith('/api/commands'))![1]!.signal!;
  fireEvent.click(screen.getByText('Close commands'));
  expect(signal.aborted).toBe(true);
  await act(async () => release(reply({ ok: true, commands: items })));
  fireEvent.click(screen.getByText('Commands'));
  expect(screen.queryByText('/restart')).toBeNull();
});

it('aborts and fences old-hub results after a connection change', async () => {
  let release!: (value: any) => void;
  vi.mocked(fetch).mockImplementation(async url => String(url).endsWith('/api/commands')
    ? new Promise(resolve => { release = resolve; }) : reply({ agents: [] }) as Response);
  mount(); await screen.findByPlaceholderText('Message Jarvis…');
  fireEvent.click(screen.getByText('Commands'));
  await waitFor(() => expect(release).toBeDefined());
  const signal = vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith('/api/commands'))![1]!.signal!;
  await act(async () => server.updateConfig({ ...config, baseUrl: 'https://other.test' }));
  expect(signal.aborted).toBe(true);
  await act(async () => release(reply({ ok: true, commands: items })));
  expect(screen.queryByText('/restart')).toBeNull();
});

it('aborts a pending catalog read when the chat screen unmounts', async () => {
  vi.mocked(fetch).mockImplementation(async url => String(url).endsWith('/api/commands')
    ? new Promise(() => {}) : reply({ agents: [] }) as Response);
  const view = mount(); await screen.findByPlaceholderText('Message Jarvis…');
  fireEvent.click(screen.getByText('Commands'));
  await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/api/commands'))).toBe(true));
  const signal = vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith('/api/commands'))![1]!.signal!;
  view.unmount();
  expect(signal.aborted).toBe(true);
});
