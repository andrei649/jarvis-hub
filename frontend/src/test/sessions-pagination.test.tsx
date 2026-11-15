// @ts-nocheck
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SessionsPanel } from '../panels/sessions';

const reply = (status, body) => ({ ok: status < 400, status,
  json: async () => body, text: async () => JSON.stringify(body) });
const makeRows = (first, count, prefix = 'Recent session') => Array.from({ length: count }, (_, i) => ({
  id: `${prefix.toLowerCase().replaceAll(' ', '-')}-${first + i}`,
  title: `${prefix} ${String(first + i).padStart(2, '0')}`,
  summary: `summary ${first + i}`,
  agent_id: i % 2 ? 'frigga' : 'ultron',
  resume_id: `${prefix.toLowerCase().replaceAll(' ', '-')}-resume-${first + i}`,
}));
const rows20 = makeRows(1, 20);
const opaqueCursor = 'next + /cursor?value';

let requests;
let fetchMock;
let onPage;
let legacyRows;
function parseRequest(url, init = {}) {
  const parsed = new URL(String(url), 'http://hud.test');
  const path = parsed.pathname;
  const row = { url: String(url), path, query: parsed.searchParams, method: init.method || 'GET', headers: init.headers || {}, body: init.body };
  requests.push(row);
  return row;
}
const pageCalls = () => requests.filter(request => request.path === '/sessions/page');
const legacyCalls = () => requests.filter(request => request.path === '/sessions' || request.path === '/sessions?archived=true');
const searchBox = () => screen.getByLabelText('Search loaded recent sessions');

beforeEach(() => {
  cleanup();
  localStorage.setItem('hud.user_token', 'user-token');
  localStorage.setItem('hud.admin_token', 'owner-token');
  requests = [];
  onPage = undefined;
  legacyRows = [{ id: 'legacy-session', title: 'Legacy session' }];
  fetchMock = vi.fn(async (url, init = {}) => {
    const call = parseRequest(url, init);
    if (call.path === '/sessions/page') {
      return onPage ? onPage(call) : reply(200, { sessions: rows20, next_cursor: null });
    }
    if (call.path === '/sessions' || call.path === '/sessions?archived=true') {
      return reply(200, { sessions: legacyRows });
    }
    if (call.path === '/sessions/chat-1/archive') return reply(200, { ok: true });
    return reply(404, { error: 'not found' });
  });
  global.fetch = fetchMock;
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.removeItem('hud.user_token');
  localStorage.removeItem('hud.admin_token');
});

describe('SessionsPanel explicit pagination', () => {
  it('uses the admin page contract, appends and deduplicates rows, and searches loaded pages locally', async () => {
    onPage = (call) => call.query.has('cursor')
      ? reply(200, { sessions: [rows20[19], { id: 'session-21', title: 'Older-only marker', summary: 'older data', agent_id: 'frigga' }], next_cursor: null })
      : reply(200, { sessions: rows20, next_cursor: opaqueCursor });
    render(<SessionsPanel />);
    await screen.findByText('Recent session 20');
    expect(screen.getByText('Recent session 01')).toBeTruthy();
    const first = pageCalls()[0];
    expect(first.query.get('archived')).toBe('false');
    expect(first.query.get('limit')).toBe('20');
    expect(first.query.has('cursor')).toBe(false);
    expect(first.headers['X-Admin-Token']).toBe('owner-token');

    const requestsBeforeTyping = requests.length;
    fireEvent.change(searchBox(), { target: { value: 'older-only marker' } });
    expect(screen.getByText('No recent sessions match this search')).toBeTruthy();
    expect(requests).toHaveLength(requestsBeforeTyping);

    fireEvent.click(screen.getByLabelText('Load older sessions'));
    expect(await screen.findByText('Older-only marker')).toBeTruthy();
    expect(screen.queryByText('Recent session 01')).toBeNull();
    fireEvent.click(screen.getByLabelText('Clear session search'));
    expect(screen.getAllByText('Recent session 20')).toHaveLength(1);
    expect(pageCalls()[1].query.get('cursor')).toBe(opaqueCursor);
    expect(screen.queryByLabelText('Load older sessions')).toBeNull();
  });

  it('blocks repeated load clicks while one page request is pending', async () => {
    let releasePage!: (value: unknown) => void;
    onPage = (call) => call.query.has('cursor')
      ? new Promise(resolve => { releasePage = resolve; })
      : reply(200, { sessions: rows20, next_cursor: 'cursor-1' });
    render(<SessionsPanel />);
    await screen.findByText('Recent session 20');
    const load = screen.getByLabelText('Load older sessions');
    fireEvent.click(load);
    await waitFor(() => expect(releasePage).toBeDefined());
    fireEvent.click(load);
    fireEvent.click(load);
    expect(pageCalls()).toHaveLength(2);

    await act(async () => releasePage(reply(200, { sessions: [{ id: 'session-21', title: 'Older row' }], next_cursor: null })));
    expect(await screen.findByText('Older row')).toBeTruthy();
  });

  it('keeps loaded rows and cursor retryable after a later-page refusal without legacy fallback', async () => {
    let rejectNext = true;
    onPage = (call) => {
      if (!call.query.has('cursor')) return reply(200, { sessions: rows20, next_cursor: 'cursor-1' });
      if (rejectNext) return reply(403, { error: 'owner access required' });
      return reply(200, { sessions: [{ id: 'session-21', title: 'Recovered older row' }], next_cursor: null });
    };
    render(<SessionsPanel />);
    await screen.findByText('Recent session 01');
    fireEvent.click(screen.getByLabelText('Load older sessions'));
    expect((await screen.findByRole('alert')).textContent).toContain('Could not load older sessions');
    expect(screen.getByText('Recent session 20')).toBeTruthy();
    expect(screen.getByLabelText('Retry loading older sessions')).toBeTruthy();
    expect(legacyCalls()).toHaveLength(0);

    rejectNext = false;
    fireEvent.click(screen.getByLabelText('Retry loading older sessions'));
    expect(await screen.findByText('Recovered older row')).toBeTruthy();
    expect(legacyCalls()).toHaveLength(0);
  });

  it('rejects repeated page cursors without appending malformed rows', async () => {
    onPage = (call) => call.query.has('cursor')
      ? reply(200, { sessions: [{ id: 'session-21', title: 'Must not append' }], next_cursor: 'cursor-1' })
      : reply(200, { sessions: rows20, next_cursor: 'cursor-1' });
    render(<SessionsPanel />);
    await screen.findByText('Recent session 20');
    fireEvent.click(screen.getByLabelText('Load older sessions'));
    expect((await screen.findByRole('alert')).textContent).toContain('invalid session page cursor');
    expect(screen.queryByText('Must not append')).toBeNull();
    expect(screen.getByText('Recent session 01')).toBeTruthy();
    expect(screen.getByLabelText('Retry loading older sessions')).toBeTruthy();
  });

  it('rejects rows without a valid bounded session id on a later page', async () => {
    onPage = (call) => call.query.has('cursor')
      ? reply(200, { sessions: [{ title: 'ID-less row' }], next_cursor: null })
      : reply(200, { sessions: rows20, next_cursor: 'cursor-1' });
    render(<SessionsPanel />);
    await screen.findByText('Recent session 20');
    fireEvent.click(screen.getByLabelText('Load older sessions'));
    expect((await screen.findByRole('alert')).textContent).toContain('invalid session page cursor');
    expect(screen.queryByText('ID-less row')).toBeNull();
    expect(screen.getByText('Recent session 20')).toBeTruthy();
    expect(screen.getByLabelText('Retry loading older sessions')).toBeTruthy();
  });

  it.each([401, 403, 404, 405])('falls back to the legacy user list only for initial page status %i', async (status) => {
    onPage = () => reply(status, { error: 'pagination unavailable' });
    render(<SessionsPanel />);
    expect(await screen.findByText('Legacy session')).toBeTruthy();
    expect(screen.getByText(/Showing the latest 20 sessions/)).toBeTruthy();
    expect(pageCalls().length).toBeGreaterThanOrEqual(1);
    expect(legacyCalls()).toHaveLength(1);
    expect(legacyCalls()[0].headers['X-Admin-Token']).toBeUndefined();
  });

  it('preserves the current list on an initial transient refresh error and clears stale pagination', async () => {
    let failRefresh = false;
    onPage = () => failRefresh
      ? reply(503, { error: 'temporary outage' })
      : reply(200, { sessions: rows20, next_cursor: 'cursor-1' });
    render(<SessionsPanel />);
    await screen.findByText('Recent session 01');
    failRefresh = true;
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }));
    expect(await screen.findByText(/offline · GET \/sessions\/page/)).toBeTruthy();
    expect(screen.getByText('Recent session 20')).toBeTruthy();
    expect(screen.queryByLabelText('Load older sessions')).toBeNull();
    expect(legacyCalls()).toHaveLength(0);
  });

  it('ignores an older page that resolves after a reload replaces the first page', async () => {
    let releaseOldPage!: (value: unknown) => void;
    let refresh = false;
    onPage = (call) => {
      if (call.query.has('cursor')) return new Promise(resolve => { releaseOldPage = resolve; });
      if (refresh) return reply(200, { sessions: [{ id: 'fresh-session', title: 'Refreshed first page' }], next_cursor: null });
      return reply(200, { sessions: rows20, next_cursor: 'cursor-1' });
    };
    render(<SessionsPanel />);
    await screen.findByText('Recent session 20');
    fireEvent.click(screen.getByLabelText('Load older sessions'));
    await waitFor(() => expect(releaseOldPage).toBeDefined());

    refresh = true;
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }));
    expect(await screen.findByText('Refreshed first page')).toBeTruthy();
    await act(async () => releaseOldPage(reply(200, { sessions: [{ id: 'stale-session', title: 'Stale older row' }], next_cursor: null })));
    expect(screen.queryByText('Stale older row')).toBeNull();
    expect(screen.getByText('Refreshed first page')).toBeTruthy();
  });

  it('ignores a pending chats page after switching to the archived tab', async () => {
    let releaseChatsPage!: (value: unknown) => void;
    onPage = (call) => {
      if (call.query.get('archived') === 'true') return reply(200, { sessions: [{ id: 'archive-1', title: 'Archived history' }], next_cursor: null });
      if (call.query.has('cursor')) return new Promise(resolve => { releaseChatsPage = resolve; });
      return reply(200, { sessions: rows20, next_cursor: 'cursor-1' });
    };
    render(<SessionsPanel />);
    await screen.findByText('Recent session 20');
    fireEvent.click(screen.getByLabelText('Load older sessions'));
    await waitFor(() => expect(releaseChatsPage).toBeDefined());
    fireEvent.change(searchBox(), { target: { value: 'stale filter' } });
    fireEvent.click(screen.getByRole('tab', { name: 'archived' }));
    expect(await screen.findByText('Archived history')).toBeTruthy();
    expect(searchBox().value).toBe('');
    await act(async () => releaseChatsPage(reply(200, { sessions: [{ id: 'stale-chat', title: 'Stale chat row' }], next_cursor: null })));
    expect(screen.queryByText('Stale chat row')).toBeNull();
    expect(screen.getByText('Archived history')).toBeTruthy();
  });

  it('does not show the previous tab rows when the new tab fetch fails', async () => {
    onPage = (call) => call.query.get('archived') === 'true'
      ? reply(503, { error: 'temporary outage' })
      : reply(200, { sessions: [{ id: 'chat-only', title: 'Chats only row' }], next_cursor: null });
    render(<SessionsPanel />);
    await screen.findByText('Chats only row');
    fireEvent.click(screen.getByRole('tab', { name: 'archived' }));
    expect(await screen.findByText(/offline · GET \/sessions\/page/)).toBeTruthy();
    expect(screen.queryByText('Chats only row')).toBeNull();
    expect(screen.queryByLabelText('resume chat-only')).toBeNull();
  });

  it('does not invalidate the active request when the selected tab is clicked again', async () => {
    let releaseInitial!: (value: unknown) => void;
    onPage = () => new Promise(resolve => { releaseInitial = resolve; });
    render(<SessionsPanel />);
    await waitFor(() => expect(releaseInitial).toBeDefined());
    fireEvent.click(screen.getByRole('tab', { name: 'chats' }));
    await act(async () => releaseInitial(reply(200, { sessions: [{ id: 'active-row', title: 'Loaded after same-tab click' }], next_cursor: null })));
    expect(await screen.findByText('Loaded after same-tab click')).toBeTruthy();
  });

  it('does not apply a pending page result after the panel unmounts', async () => {
    let releasePage!: (value: unknown) => void;
    onPage = (call) => call.query.has('cursor')
      ? new Promise(resolve => { releasePage = resolve; })
      : reply(200, { sessions: rows20, next_cursor: 'cursor-1' });
    const view = render(<SessionsPanel />);
    await screen.findByText('Recent session 20');
    fireEvent.click(screen.getByLabelText('Load older sessions'));
    await waitFor(() => expect(releasePage).toBeDefined());
    view.unmount();
    await act(async () => releasePage(reply(200, { sessions: [{ id: 'late', title: 'Late page after unmount' }], next_cursor: null })));
    expect(screen.queryByText('Late page after unmount')).toBeNull();
  });

  it('fences a pending mutation from reloading the old tab after a tab switch', async () => {
    let releaseArchive!: (value: unknown) => void;
    onPage = (call) => call.query.get('archived') === 'true'
      ? reply(200, { sessions: [{ id: 'archive-2', title: 'Current archived row' }], next_cursor: null })
      : reply(200, { sessions: [{ id: 'chat-1', title: 'Current chat row' }], next_cursor: null });
    fetchMock.mockImplementation(async (url, init = {}) => {
      const call = parseRequest(url, init);
      if (call.path === '/sessions/page') return onPage(call);
      if (call.path === '/sessions/chat-1/archive') return new Promise(resolve => { releaseArchive = resolve; });
      return reply(404, { error: 'not found' });
    });
    render(<SessionsPanel />);
    await screen.findByText('Current chat row');
    fireEvent.click(screen.getByRole('button', { name: 'archive chat-1' }));
    await waitFor(() => expect(releaseArchive).toBeDefined());
    fireEvent.click(screen.getByRole('tab', { name: 'archived' }));
    expect(await screen.findByText('Current archived row')).toBeTruthy();
    await act(async () => releaseArchive(reply(200, { ok: true })));
    expect(screen.getByText('Current archived row')).toBeTruthy();
    expect(screen.queryByText('archived chat-1')).toBeNull();
    expect((screen.getByRole('button', { name: 'resume archive-2' }) as HTMLButtonElement).disabled).toBe(false);
  });
});
