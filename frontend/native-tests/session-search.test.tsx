import React, { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { SessionsModal } from '../../mobile/src/components/SessionsModal';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { records } from './support/storage';

const SERVER_KEY = 'jarvis.server.config.v1';
const config = { baseUrl: 'https://hub.test', token: 'user', adminToken: 'owner' };
const otherConfig = { ...config, baseUrl: 'https://other.test', token: 'other-user' };
const rows = [
  { id: 'root-title', title: 'Project Phoenix', summary: 'Quarterly launch plan', agent_id: 'ultron',
    resume_id: 'newest-title', continuations: 2 },
  { id: 'summary-row', summary: 'Neighborhood rollout', agent_id: 'frigga', resume_id: 'newest-summary' },
  { id: 'id-match-73', summary: 'Archive row', agent_id: 'howard' },
  { id: 'agent-row', title: 'Operations report', agent_id: 'athena' },
];
const response = (body: unknown) => ({ ok: true, status: 200, json: async () => (body && typeof body === 'object' && 'sessions' in body ? { ...body, next_cursor: null } : body) });
let server: ReturnType<typeof useServer>;
let fetchMock: ReturnType<typeof vi.fn>;
let onResumed: ReturnType<typeof vi.fn>;
let onClose: ReturnType<typeof vi.fn>;

function Probe() {
  server = useServer();
  const [visible, setVisible] = useState(true);
  return <>
    <button onClick={() => setVisible(false)}>Close sessions from test</button>
    <button onClick={() => setVisible(true)}>Reopen sessions from test</button>
    <button onClick={() => void server.updateConfig(otherConfig)}>Switch hub from test</button>
    {server.ready ? <SessionsModal visible={visible} onClose={() => { onClose(); setVisible(false); }} onResumed={onResumed} /> : null}
  </>;
}
const mount = () => render(<ServerProvider><Probe /></ServerProvider>);
const searchBox = () => screen.getByLabelText('Search loaded recent sessions') as HTMLInputElement;
const sessionCalls = () => fetchMock.mock.calls.filter(([url]) => (String(url).endsWith('/sessions') || String(url).includes('/sessions/page?')));
const resumeCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/sessions/resume'));

beforeEach(() => {
  records.clear();
  records.set(SERVER_KEY, JSON.stringify({ version: 2, config, appearance: null, chatScope: 'search-scope' }));
  onResumed = vi.fn();
  onClose = vi.fn();
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/sessions/resume')) {
      const sessionId = JSON.parse(String(init?.body)).session_id;
      return response({ ok: true, session: sessionId, turns: [{ role: 'user', content: 'Selected history' }] });
    }
    return response({ sessions: rows });
  });
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('filters loaded recent rows by trimmed case-insensitive title, summary, id, and agent without fetching or resuming', async () => {
  mount();
  await screen.findByText('Project Phoenix');
  const searchesBefore = sessionCalls().length;
  const resumesBefore = resumeCalls().length;

  fireEvent.change(searchBox(), { target: { value: '  PROJECT PHOENIX  ' } });
  expect(screen.getByText('Project Phoenix')).toBeTruthy();
  expect(screen.queryByText('Neighborhood rollout')).toBeNull();

  fireEvent.change(searchBox(), { target: { value: '  NEIGHBORHOOD ROLLOUT  ' } });
  expect(screen.getByText('Neighborhood rollout')).toBeTruthy();
  expect(screen.queryByText('Project Phoenix')).toBeNull();

  fireEvent.change(searchBox(), { target: { value: '  ID-MATCH-73  ' } });
  expect(screen.getByText('Archive row')).toBeTruthy();
  expect(screen.queryByText('Operations report')).toBeNull();

  fireEvent.change(searchBox(), { target: { value: '  FRIGGA  ' } });
  expect(screen.getByText('Neighborhood rollout')).toBeTruthy();
  expect(screen.queryByText('Archive row')).toBeNull();
  expect(sessionCalls()).toHaveLength(searchesBefore);
  expect(resumeCalls()).toHaveLength(resumesBefore);
  expect(onResumed).not.toHaveBeenCalled();

  fireEvent.click(screen.getByLabelText('Clear session search'));
  expect(searchBox().value).toBe('');
  expect(screen.getByText('Project Phoenix')).toBeTruthy();
  expect(screen.getByText('Neighborhood rollout')).toBeTruthy();
});

it('distinguishes a local no-match result from an actually empty saved-session list', async () => {
  mount();
  await screen.findByText('Project Phoenix');
  fireEvent.change(searchBox(), { target: { value: 'no row has this phrase' } });
  expect(screen.getByText('No recent sessions match this search')).toBeTruthy();
  expect(screen.queryByText('No saved sessions')).toBeNull();

  cleanup();
  fetchMock.mockImplementation(async () => response({ sessions: [] }));
  mount();
  await screen.findByText('No saved sessions');
  expect(screen.queryByText('No recent sessions match this search')).toBeNull();
  fireEvent.change(searchBox(), { target: { value: 'still no sessions' } });
  expect(screen.getByText('No saved sessions')).toBeTruthy();
  expect(screen.queryByText('No recent sessions match this search')).toBeNull();
});

it('resets the query after close and reopen while preserving local-only search behavior', async () => {
  mount();
  await screen.findByText('Project Phoenix');
  fireEvent.change(searchBox(), { target: { value: 'phoenix' } });
  expect(screen.queryByText('Neighborhood rollout')).toBeNull();

  fireEvent.click(screen.getByText('Close sessions from test'));
  expect(screen.queryByLabelText('Search loaded recent sessions')).toBeNull();
  fireEvent.click(screen.getByText('Reopen sessions from test'));
  await screen.findByText('Project Phoenix');
  expect(searchBox().value).toBe('');
  expect(screen.getByText('Neighborhood rollout')).toBeTruthy();
});

it('keeps the query while refreshing and filters the newly fetched rows locally', async () => {
  mount();
  await screen.findByText('Project Phoenix');
  fireEvent.change(searchBox(), { target: { value: 'phoenix' } });
  fetchMock.mockImplementation(async (url: string) => (url.endsWith('/sessions') || url.includes('/sessions/page?'))
    ? response({ sessions: [{ id: 'updated-row', title: 'Phoenix follow-up', agent_id: 'frigga' },
      { id: 'unrelated-row', title: 'Archive notes', agent_id: 'howard' }] })
    : response({ ok: true, session: 'updated-row', turns: [] }));

  fireEvent.click(screen.getByLabelText('Refresh recent sessions'));
  await screen.findByText('Phoenix follow-up');
  expect(searchBox().value).toBe('phoenix');
  expect(screen.queryByText('Archive notes')).toBeNull();
  expect(resumeCalls()).toHaveLength(0);
});

it('uses the lineage resume target only after a row is explicitly selected', async () => {
  mount();
  await screen.findByText('Project Phoenix');
  fireEvent.change(searchBox(), { target: { value: 'phoenix' } });
  expect(resumeCalls()).toHaveLength(0);
  expect(onResumed).not.toHaveBeenCalled();

  fireEvent.click(screen.getByText('Project Phoenix'));
  await waitFor(() => expect(onResumed).toHaveBeenCalledWith('newest-title', expect.any(Array)));
  const posted = JSON.parse(String(resumeCalls()[0][1]?.body));
  expect(posted.session_id).toBe('newest-title');
  expect(onClose).toHaveBeenCalledOnce();
});

it('drops a delayed old-scope session list after the hub identity changes', async () => {
  let releaseOld!: (value: unknown) => void;
  fetchMock.mockImplementation(async (url: string) => {
    if (url.startsWith('https://hub.test/') && (url.endsWith('/sessions') || url.includes('/sessions/page?'))) {
      return new Promise(resolve => { releaseOld = resolve; });
    }
    if (url.startsWith('https://other.test/') && (url.endsWith('/sessions') || url.includes('/sessions/page?'))) {
      return response({ sessions: [{ id: 'other-secret', title: 'Other hub history', agent_id: 'frigga' }] });
    }
    return response({ ok: true, session: 'other-secret', turns: [] });
  });
  mount();
  await waitFor(() => expect(releaseOld).toBeDefined());
  const query = searchBox();
  fireEvent.change(query, { target: { value: 'stale query' } });

  await act(async () => server.updateConfig(otherConfig));
  await screen.findByText('Other hub history');
  expect(searchBox().value).toBe('');
  await act(async () => releaseOld(response({ sessions: [{ id: 'private-old', title: 'Old hub private history' }] })));
  expect(screen.queryByText('Old hub private history')).toBeNull();
  expect(screen.getByText('Other hub history')).toBeTruthy();
});

it('ignores a delayed resume after the hub identity changes, even with a query active', async () => {
  let releaseResume!: (value: unknown) => void;
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/sessions/resume')) {
      expect(JSON.parse(String(init?.body)).session_id).toBe('newest-title');
      return new Promise(resolve => { releaseResume = resolve; });
    }
    if (url.startsWith('https://other.test/') && (url.endsWith('/sessions') || url.includes('/sessions/page?'))) {
      return response({ sessions: [{ id: 'other-secret', title: 'Other hub history' }] });
    }
    return response({ sessions: rows });
  });
  mount();
  await screen.findByText('Project Phoenix');
  fireEvent.change(searchBox(), { target: { value: 'phoenix' } });
  fireEvent.click(screen.getByText('Project Phoenix'));
  await waitFor(() => expect(releaseResume).toBeDefined());

  await act(async () => server.updateConfig(otherConfig));
  await screen.findByText('Other hub history');
  await act(async () => releaseResume(response({ ok: true, session: 'newest-title',
    turns: [{ role: 'user', content: 'Old hub private transcript' }] })));
  expect(onResumed).not.toHaveBeenCalled();
  expect(onClose).not.toHaveBeenCalled();
  expect(screen.queryByText('Old hub private transcript')).toBeNull();
  expect(searchBox().value).toBe('');
});
