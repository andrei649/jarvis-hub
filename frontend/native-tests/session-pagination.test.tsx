import React, { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { SessionsModal } from '../../mobile/src/components/SessionsModal';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import * as client from '../../mobile/src/api/client';
import { records } from './support/storage';
const config = { baseUrl: 'https://hub.test', token: 'user', adminToken: 'owner' };
const other = { ...config, baseUrl: 'https://other.test', token: 'other-user' };
const recent = { id: 'root', title: 'Recent Phoenix', resume_id: 'latest', continuations: 1 };
const older = { id: 'older', title: 'Older Phoenix', agent_id: 'frigga' };
const response = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) });
const deferred = () => { let resolve!: (value: any) => void; const promise = new Promise<any>(r => { resolve = r; }); return { promise, resolve }; };
let fetchMock: ReturnType<typeof vi.fn>;
let onResumed: ReturnType<typeof vi.fn>;
let onClose: ReturnType<typeof vi.fn>;
let server: ReturnType<typeof useServer>;
const pages = () => fetchMock.mock.calls.filter(([url]) => String(url).includes('/sessions/page?'));
const legacy = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/sessions'));
const search = () => screen.getByLabelText('Search loaded recent sessions') as HTMLInputElement;
const loadOlder = () => screen.getByLabelText('Load older sessions');
function Probe() {
  server = useServer(); const [visible, setVisible] = useState(true);
  return <><button onClick={() => setVisible(false)}>Close from test</button><button onClick={() => setVisible(true)}>Reopen from test</button>
    {server.ready && <SessionsModal visible={visible} onClose={() => { onClose(); setVisible(false); }} onResumed={onResumed} />}</>;
}
const mount = () => render(<ServerProvider><Probe /></ServerProvider>);
beforeEach(() => {
  records.clear(); records.set('jarvis.server.config.v1', JSON.stringify({ version: 2, config, appearance: null, chatScope: 'paging' }));
  onResumed = vi.fn(); onClose = vi.fn();
  fetchMock = vi.fn(async (url: string) => url.includes('cursor=') ? response({ sessions: [recent, older], next_cursor: null }) : response({ sessions: [recent], next_cursor: 'next_cursor' }));
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it('starts with an admin bounded page and explicitly loads deduplicated older rows', async () => {
  mount(); await screen.findByText('Recent Phoenix'); expect(pages()).toHaveLength(1);
  const [url, init] = pages()[0]; const parsed = new URL(String(url));
  expect(parsed.pathname).toBe('/sessions/page'); expect(parsed.searchParams.get('archived')).toBe('false');
  expect(parsed.searchParams.get('limit')).toBe('20'); expect(parsed.searchParams.has('cursor')).toBe(false);
  expect(new Headers(init?.headers).get('X-Admin-Token')).toBe('owner'); expect(legacy()).toHaveLength(0);
  expect(screen.queryByText('Older Phoenix')).toBeNull(); fireEvent.click(loadOlder()); await screen.findByText('Older Phoenix');
  expect(screen.getAllByText('Recent Phoenix')).toHaveLength(1);
  expect(new URL(String(pages()[1][0])).searchParams.get('cursor')).toBe('next_cursor');
  expect(screen.queryByLabelText('Load older sessions')).toBeNull();
});
it('searches all loaded pages locally without requests or automatic resume', async () => {
  mount(); await screen.findByText('Recent Phoenix'); fireEvent.change(search(), { target: { value: '  OLDER PHOENIX ' } });
  expect(screen.getByText('No recent sessions match this search')).toBeTruthy(); fireEvent.click(loadOlder()); await screen.findByText('Older Phoenix');
  expect(screen.queryByText('Recent Phoenix')).toBeNull(); const count = fetchMock.mock.calls.length;
  fireEvent.change(search(), { target: { value: 'frigga' } }); expect(screen.getByText('Older Phoenix')).toBeTruthy();
  expect(fetchMock).toHaveBeenCalledTimes(count); expect(onResumed).not.toHaveBeenCalled();
});
it.each([401, 403, 404, 405])('falls back only on initial page status %s', async status => {
  fetchMock.mockImplementation(async (url: string) => url.includes('/sessions/page?') ? response({ detail: 'unsupported' }, status) : response({ sessions: [recent] }));
  mount(); await screen.findByText('Recent Phoenix'); expect(pages()).toHaveLength(1); expect(legacy()).toHaveLength(1);
  expect(screen.queryByLabelText('Load older sessions')).toBeNull(); expect(screen.getByText(/recent.*only|only.*recent/i)).toBeTruthy();
});
it('does not fallback on an initial server error', async () => {
  fetchMock.mockImplementation(async () => response({ detail: 'Unavailable' }, 500)); mount();
  await screen.findByText(/Unavailable|Failed|500/i); expect(legacy()).toHaveLength(0); expect(pages()).toHaveLength(1);
});
it('retains rows and cursor after a later error and retries without fallback', async () => {
  let attempts = 0;
  fetchMock.mockImplementation(async (url: string) => !url.includes('cursor=') ? response({ sessions: [recent], next_cursor: 'retry' })
    : ++attempts === 1 ? response({ detail: 'Denied later' }, 403) : response({ sessions: [older], next_cursor: null }));
  mount(); await screen.findByText('Recent Phoenix'); fireEvent.click(loadOlder());
  await waitFor(() => expect((loadOlder() as HTMLButtonElement).disabled).toBe(false));
  expect(screen.getByText('Recent Phoenix')).toBeTruthy(); expect(legacy()).toHaveLength(0);
  fireEvent.click(loadOlder()); await screen.findByText('Older Phoenix'); expect(pages()).toHaveLength(3); expect(pages()[1][0]).toBe(pages()[2][0]);
});
it('rejects a repeated cursor without accepting rows and leaves retry available', async () => {
  fetchMock.mockImplementation(async (url: string) => url.includes('cursor=') ? response({ sessions: [older], next_cursor: 'next_cursor' }) : response({ sessions: [recent], next_cursor: 'next_cursor' }));
  mount(); await screen.findByText('Recent Phoenix'); fireEvent.click(loadOlder());
  await waitFor(() => expect((loadOlder() as HTMLButtonElement).disabled).toBe(false));
  expect(screen.queryByText('Older Phoenix')).toBeNull(); expect(screen.getByText('Recent Phoenix')).toBeTruthy(); expect(legacy()).toHaveLength(0);
});
it('synchronously blocks concurrent older clicks before React commits the disabled state', async () => {
  const delayed = deferred(); fetchMock.mockImplementation(async (url: string) => url.includes('cursor=') ? delayed.promise : response({ sessions: [recent], next_cursor: 'next' }));
  mount(); await screen.findByText('Recent Phoenix'); const button = loadOlder();
  act(() => { button.dispatchEvent(new MouseEvent('click', { bubbles: true })); button.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
  expect(pages()).toHaveLength(2); await act(async () => delayed.resolve(response({ sessions: [older], next_cursor: null }))); await screen.findByText('Older Phoenix');
});
it('refresh resets to page one, preserves query, and fences the pending older page', async () => {
  const delayed = deferred(); let initial = 0;
  fetchMock.mockImplementation(async (url: string) => url.includes('cursor=') ? delayed.promise
    : response({ sessions: [++initial === 1 ? recent : { id: 'fresh', title: 'Fresh Phoenix' }], next_cursor: 'fresh_cursor' }));
  mount(); await screen.findByText('Recent Phoenix'); fireEvent.change(search(), { target: { value: 'phoenix' } }); fireEvent.click(loadOlder());
  fireEvent.click(screen.getByLabelText('Refresh recent sessions')); await screen.findByText('Fresh Phoenix');
  await act(async () => delayed.resolve(response({ sessions: [older], next_cursor: null })));
  expect(search().value).toBe('phoenix'); expect(screen.queryByText('Older Phoenix')).toBeNull(); expect(screen.queryByText('Recent Phoenix')).toBeNull(); expect(loadOlder()).toBeTruthy();
});
it.each(['close', 'connection'])('clears query and rows and drops a private delayed older page after %s', async mode => {
  const delayed = deferred(); let first = true;
  fetchMock.mockImplementation(async (url: string) => url.includes('cursor=') ? delayed.promise : response({ sessions: [first ? recent : { id: 'new', title: 'New scope history' }], next_cursor: first ? 'next' : null }));
  mount(); await screen.findByText('Recent Phoenix'); fireEvent.change(search(), { target: { value: 'phoenix' } }); fireEvent.click(loadOlder()); first = false;
  if (mode === 'close') { fireEvent.click(screen.getByText('Close from test')); fireEvent.click(screen.getByText('Reopen from test')); }
  else await act(async () => server.updateConfig(other));
  await screen.findByText('New scope history');
  await act(async () => delayed.resolve(response({ sessions: [{ id: 'private', title: 'Private old history' }], next_cursor: 'private_cursor' })));
  expect(search().value).toBe(''); expect(screen.queryByText('Recent Phoenix')).toBeNull(); expect(screen.queryByText('Private old history')).toBeNull(); expect(screen.queryByLabelText('Load older sessions')).toBeNull();
});
it('explicit lineage resume supersedes a pending older load', async () => {
  const delayedPage = deferred(); const delayedResume = deferred();
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/sessions/resume')) { expect(JSON.parse(String(init?.body)).session_id).toBe('latest'); return delayedResume.promise; }
    return url.includes('cursor=') ? delayedPage.promise : response({ sessions: [recent], next_cursor: 'next' });
  });
  mount(); await screen.findByText('Recent Phoenix'); fireEvent.click(loadOlder()); fireEvent.click(screen.getByText('Recent Phoenix'));
  await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/sessions/resume'))).toBe(true));
  await act(async () => delayedPage.resolve(response({ sessions: [older], next_cursor: null }))); expect(screen.queryByText('Older Phoenix')).toBeNull();
  await act(async () => delayedResume.resolve(response({ ok: true, session: 'latest', turns: [] })));
  expect(onResumed).toHaveBeenCalledWith('latest', []); expect(onClose).toHaveBeenCalledOnce();
});
it.each([
  { sessions: [{ id: '../unsafe' }], next_cursor: null },
  { sessions: [{ id: 'x'.repeat(129) }], next_cursor: null },
  { sessions: [{ id: 'valid', resume_id: '../unsafe' }], next_cursor: null },
  { sessions: [{ id: 'valid', title: {} }], next_cursor: null },
  { sessions: Array.from({ length: 21 }, (_, i) => ({ id: `row-${i}` })), next_cursor: null },
  { sessions: [], next_cursor: 'x'.repeat(513) }, { sessions: [], next_cursor: 12 },
  { sessions: 'invalid', next_cursor: null }, { sessions: [] },
])('rejects malformed bounded page payload %# using the real client', async body => {
  fetchMock.mockResolvedValue(response(body)); await expect(client.fetchSessionsPage(config)).rejects.toThrow();
});
it('rejects oversized request cursor before HTTP', async () => {
  await expect(client.fetchSessionsPage(config, 'x'.repeat(513))).rejects.toThrow(); expect(fetchMock).not.toHaveBeenCalled();
});
it('an explicit same-config save resets query and fences pending older history using the connection epoch', async () => {
  const delayed = deferred(); let refreshed = false;
  fetchMock.mockImplementation(async (url: string) => url.includes('cursor=') ? delayed.promise : response({ sessions: [refreshed ? { id: 'new', title: 'Reconnected history' } : recent], next_cursor: refreshed ? null : 'next' }));
  mount(); await screen.findByText('Recent Phoenix'); fireEvent.change(search(), { target: { value: 'phoenix' } }); fireEvent.click(loadOlder()); refreshed = true;
  const previousEpoch = server.connectionEpoch; await act(async () => server.updateConfig(config));
  await screen.findByText('Reconnected history'); expect(server.connectionEpoch).toBeGreaterThan(previousEpoch);
  await act(async () => delayed.resolve(response({ sessions: [older], next_cursor: 'private_cursor' })));
  expect(search().value).toBe(''); expect(screen.queryByText('Older Phoenix')).toBeNull(); expect(screen.queryByLabelText('Load older sessions')).toBeNull();
});
it('malformed later rows preserve the loaded list and exact retry cursor', async () => {
  let attempts = 0;
  fetchMock.mockImplementation(async (url: string) => !url.includes('cursor=') ? response({ sessions: [recent], next_cursor: 'retry' })
    : ++attempts === 1 ? response({ sessions: [older, { id: '../unsafe' }], next_cursor: null }) : response({ sessions: [older], next_cursor: null }));
  mount(); await screen.findByText('Recent Phoenix'); fireEvent.click(loadOlder()); await screen.findByText('Invalid session page received from the hub');
  expect(screen.queryByText('Older Phoenix')).toBeNull(); expect(screen.getByText('Recent Phoenix')).toBeTruthy(); expect(legacy()).toHaveLength(0);
  fireEvent.click(loadOlder()); await screen.findByText('Older Phoenix'); expect(pages()[1][0]).toBe(pages()[2][0]);
});
it('rejects a longer cursor cycle without accepting the cycling page rows', async () => {
  let calls = 0;
  fetchMock.mockImplementation(async () => response(++calls === 1 ? { sessions: [recent], next_cursor: 'cursor_a' }
    : calls === 2 ? { sessions: [older], next_cursor: 'cursor_b' } : { sessions: [{ id: 'bad', title: 'Cycling page' }], next_cursor: 'cursor_a' }));
  mount(); await screen.findByText('Recent Phoenix'); fireEvent.click(loadOlder()); await screen.findByText('Older Phoenix'); fireEvent.click(loadOlder());
  await screen.findByText(/repeated session cursor/i); expect(screen.queryByText('Cycling page')).toBeNull(); expect(screen.getByText('Older Phoenix')).toBeTruthy();
});
it('accepts maximum safe ID and cursor boundaries, preserving lineage and omitting null optional fields', async () => {
  const id = 's'.repeat(128); const cursor = 'c'.repeat(512);
  fetchMock.mockResolvedValue(response({ sessions: [{ id, resume_id: id, title: 'Boundary', summary: null, turn_count: 0, continuations: 0 }], next_cursor: cursor }));
  await expect(client.fetchSessionsPage(config, cursor)).resolves.toEqual({ sessions: [{ id, resume_id: id, title: 'Boundary', turn_count: 0, continuations: 0 }], next_cursor: cursor });
  expect(new URL(String(fetchMock.mock.calls[0][0])).searchParams.get('cursor')).toBe(cursor);
});
it.each(['', 'x.y', 'x/y', 'x=y', 'x\n'])('rejects malformed cursor %j before HTTP', async cursor => {
  await expect(client.fetchSessionsPage(config, cursor)).rejects.toThrow(); expect(fetchMock).not.toHaveBeenCalled();
});
it.each([12, {}, true])('rejects non-string request cursors before HTTP %#', async cursor => {
  await expect(client.fetchSessionsPage(config, cursor as any)).rejects.toThrow(); expect(fetchMock).not.toHaveBeenCalled();
});
it.each([
  { sessions: [{ id: 'safe\n' }], next_cursor: null },
  { sessions: [{ id: 'safe', resume_id: 'safe\n' }], next_cursor: null },
  { sessions: [{ id: 'safe' }], next_cursor: 'cursor\n' },
])('rejects trailing-newline page identifiers %#', async body => {
  fetchMock.mockResolvedValue(response(body)); await expect(client.fetchSessionsPage(config)).rejects.toThrow();
});
it('never falls back after a successful HTTP response containing a malformed initial page', async () => {
  fetchMock.mockResolvedValue(response({ sessions: [{ id: '../unsafe' }], next_cursor: null }));
  mount(); await screen.findByText('Invalid session page received from the hub'); expect(legacy()).toHaveLength(0); expect(pages()).toHaveLength(1);
  expect(screen.queryByLabelText('Load older sessions')).toBeNull();
});
it('reports an initial transport failure without falling back or resuming', async () => {
  fetchMock.mockRejectedValue(new Error('offline')); mount(); await screen.findByText(/Could not reach/);
  expect(legacy()).toHaveLength(0); expect(pages()).toHaveLength(1); expect(onResumed).not.toHaveBeenCalled();
});
it('retains loaded rows and query on a failed refresh while resetting the older cursor', async () => {
  mount(); await screen.findByText('Recent Phoenix'); fireEvent.click(loadOlder()); await screen.findByText('Older Phoenix');
  fireEvent.change(search(), { target: { value: 'phoenix' } });
  fetchMock.mockResolvedValue(response({ detail: 'Unavailable' }, 503));
  fireEvent.click(screen.getByLabelText('Refresh recent sessions')); await screen.findByText(/503/);
  expect(search().value).toBe('phoenix'); expect(screen.getByText('Recent Phoenix')).toBeTruthy(); expect(screen.getByText('Older Phoenix')).toBeTruthy();
  expect(screen.queryByLabelText('Load older sessions')).toBeNull(); expect(legacy()).toHaveLength(0);
});
