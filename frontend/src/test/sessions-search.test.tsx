// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SessionsPanel, RESUME_PATH, deletePath } from '../panels/sessions';

const reply = (status, body) => ({ ok: status < 400, status,
  json: async () => body, text: async () => JSON.stringify(body) });
const chats = [
  { id: 'root-title', title: 'Project Phoenix', summary: 'Quarterly launch R2+ literal', agent_id: 'Ultron',
    resume_id: 'newest-title', continuations: 2 },
  { id: 'summary-row', summary: 'Neighborhood rollout', agent_id: 'Frigga', resume_id: 'newest-summary' },
  { id: 'literal-regex', title: 'Literal marker', summary: 'R22 literal token', agent_id: 'howard' },
  ...Array.from({ length: 15 }, (_, index) => ({ id: `filler-${index + 4}`, title: `Earlier row ${index + 4}`, agent_id: 'nerva' })),
  'legacy session string row',
  { id: 'needle-session-20', title: 'Newest appended session', summary: 'Tail search marker', agent_id: 'fRiGgA',
    resume_id: 'continuation-20', continuations: 3 },
];
const archived = [
  { id: 'archive-root', title: 'Archived original', summary: 'Lineage record', continuations: 2,
    resume_id: 'archive-newest' },
  { id: 'archive-other', title: 'Archived other', summary: 'Different notes' },
];

let requests;
let sessionRows;
let archivedRows;
let deleteReply;

function pathOf(url) { return String(url).replace(/^.*?(\/sessions)/, '$1'); }
function calls(method, path) { return requests.filter(request => request.method === method && (!path || request.path === path)); }

beforeEach(() => {
  cleanup();
  requests = [];
  sessionRows = chats;
  archivedRows = archived;
  deleteReply = () => reply(200, { ok: true, deleted: ['archive-newest', 'archive-root'], backups: ['/b/1', '/b/2'] });
  global.fetch = vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET';
    const path = pathOf(url);
    const body = init.body ? JSON.parse(init.body) : undefined;
    requests.push({ url: String(url), path, method, body });
    if (path === RESUME_PATH) return reply(200, { ok: true, session: body.session_id, turns: [], recap: null });
    if (path.endsWith('/title')) return reply(200, { ok: true, title: body.title });
    if (method === 'DELETE') return deleteReply();
    if (path === '/sessions?archived=true') return reply(200, { sessions: archivedRows });
    if (path === '/sessions') return reply(200, { sessions: sessionRows });
    return reply(404, {});
  });
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const searchBox = () => screen.getByLabelText('Search loaded recent sessions') as HTMLInputElement;

describe('SessionsPanel loaded-session search', () => {
  it('renders and searches all 20 loaded rows, including row 20', async () => {
    render(<SessionsPanel />);
    await screen.findByText('Project Phoenix');
    expect(await screen.findByText('Newest appended session')).toBeTruthy();
    const reads = calls('GET').length;
    const writes = requests.filter(request => request.method !== 'GET').length;

    fireEvent.change(searchBox(), { target: { value: '  NEWEST APPENDED  ' } });
    expect(screen.getByText('Newest appended session')).toBeTruthy();
    expect(screen.queryByText('Project Phoenix')).toBeNull();
    fireEvent.change(searchBox(), { target: { value: '  TAIL SEARCH MARKER  ' } });
    expect(screen.getByText('Newest appended session')).toBeTruthy();
    fireEvent.change(searchBox(), { target: { value: '  NEIGHBORHOOD ROLLOUT  ' } });
    expect(screen.getByRole('button', { name: 'resume summary-row' })).toBeTruthy();
    expect(screen.queryByText('Project Phoenix')).toBeNull();
    fireEvent.change(searchBox(), { target: { value: '  NEEDLE-SESSION-20  ' } });
    expect(screen.getByText('Newest appended session')).toBeTruthy();
    fireEvent.change(searchBox(), { target: { value: '  FRIGGA  ' } });
    expect(screen.getByRole('button', { name: 'resume summary-row' })).toBeTruthy();
    expect(screen.getByText('Newest appended session')).toBeTruthy();
    expect(calls('GET')).toHaveLength(reads);
    expect(requests.filter(request => request.method !== 'GET')).toHaveLength(writes);
  });

  it('matches legacy string rows and treats search text as a literal substring', async () => {
    render(<SessionsPanel />);
    await screen.findByText('Project Phoenix');
    fireEvent.change(searchBox(), { target: { value: '  LEGACY SESSION STRING  ' } });
    expect(screen.getByText('legacy session string row')).toBeTruthy();
    expect(screen.queryByText('Project Phoenix')).toBeNull();

    fireEvent.change(searchBox(), { target: { value: 'R2+' } });
    expect(screen.getByText('Project Phoenix')).toBeTruthy();
    expect(screen.queryByText('Literal marker')).toBeNull();
  });

  it('shows no-match separately from empty data and clears the query', async () => {
    render(<SessionsPanel />);
    await screen.findByText('Project Phoenix');
    fireEvent.change(searchBox(), { target: { value: 'not in these sessions' } });
    expect(screen.getByText('No recent sessions match this search')).toBeTruthy();
    expect(screen.queryByText('nothing yet')).toBeNull();

    fireEvent.click(screen.getByLabelText('Clear session search'));
    expect(searchBox().value).toBe('');
    expect(screen.getByText('Project Phoenix')).toBeTruthy();

    cleanup();
    sessionRows = [];
    render(<SessionsPanel />);
    await screen.findByText('nothing yet');
    fireEvent.change(searchBox(), { target: { value: 'still empty' } });
    expect(screen.getByText('nothing yet')).toBeTruthy();
    expect(screen.queryByText('No recent sessions match this search')).toBeNull();
  });

  it('resets the query on tab changes and preserves it on refresh', async () => {
    render(<SessionsPanel />);
    await screen.findByText('Project Phoenix');
    fireEvent.change(searchBox(), { target: { value: 'phoenix' } });
    fireEvent.click(screen.getByRole('tab', { name: 'archived' }));
    expect(searchBox().value).toBe('');
    expect(await screen.findByText('Archived original')).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: 'chats' }));
    await screen.findByText('Project Phoenix');
    fireEvent.change(searchBox(), { target: { value: 'phoenix' } });

    sessionRows = [
      { id: 'new-phoenix', title: 'Phoenix follow-up' },
      { id: 'unrelated', title: 'Archive notes' },
    ];
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }));
    expect(await screen.findByText('Phoenix follow-up')).toBeTruthy();
    expect(searchBox().value).toBe('phoenix');
    expect(screen.queryByText('Archive notes')).toBeNull();
  });

  it('hides stale no-match status while refreshing and after a refresh refusal', async () => {
    render(<SessionsPanel />);
    await screen.findByText('Project Phoenix');
    fireEvent.change(searchBox(), { target: { value: 'no result in cached rows' } });
    expect(screen.getByText('No recent sessions match this search')).toBeTruthy();

    let releaseRefresh!: (value: unknown) => void;
    global.fetch = vi.fn(async (url, init = {}) => {
      requests.push({ url: String(url), path: pathOf(url), method: init.method || 'GET', body: undefined });
      return new Promise(resolve => { releaseRefresh = resolve; });
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }));
    await waitFor(() => expect(releaseRefresh).toBeDefined());
    expect(screen.queryByText('No recent sessions match this search')).toBeNull();

    await act(async () => releaseRefresh(reply(503, { error: 'temporarily unavailable' })));
    expect(await screen.findByText(/offline ·/)).toBeTruthy();
    expect(screen.queryByText('No recent sessions match this search')).toBeNull();
    expect(searchBox().value).toBe('no result in cached rows');
  });

  it('resumes a selected row through its lineage target, never while typing', async () => {
    render(<SessionsPanel />);
    await screen.findByText('Project Phoenix');
    fireEvent.change(searchBox(), { target: { value: 'newest appended' } });
    expect(calls('POST', RESUME_PATH)).toHaveLength(0);
    expect(requests.filter(request => request.method !== 'GET')).toHaveLength(0);

    fireEvent.click(screen.getByRole('button', { name: 'resume needle-session-20' }));
    await waitFor(() => expect(calls('POST', RESUME_PATH)).toHaveLength(1));
    expect(calls('POST', RESUME_PATH)[0].body).toEqual({ session_id: 'continuation-20' });
  });

  it('clears pending delete confirmation and rename editor when the query changes', async () => {
    render(<SessionsPanel />);
    await screen.findByText('Project Phoenix');
    fireEvent.click(screen.getByRole('tab', { name: 'archived' }));
    await screen.findByText('Archived original');
    fireEvent.click(screen.getByRole('button', { name: 'delete archive-root permanently' }));
    expect(screen.getByRole('button', { name: 'confirm delete archive-root' })).toBeTruthy();

    fireEvent.change(searchBox(), { target: { value: 'Archived other' } });
    expect(screen.queryByRole('button', { name: 'confirm delete archive-root' })).toBeNull();
    fireEvent.change(searchBox(), { target: { value: 'Archived original' } });
    expect(screen.getByRole('button', { name: 'delete archive-root permanently' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'confirm delete archive-root' })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'rename archive-root' }));
    expect(screen.getByRole('textbox', { name: 'title for archive-root' })).toBeTruthy();
    fireEvent.change(searchBox(), { target: { value: 'Archived other' } });
    expect(screen.queryByRole('textbox', { name: 'title for archive-root' })).toBeNull();
    expect(calls('PATCH')).toHaveLength(0);
  });

  it('keeps whole-lineage deletion explicit after searching', async () => {
    render(<SessionsPanel />);
    await screen.findByText('Project Phoenix');
    fireEvent.click(screen.getByRole('tab', { name: 'archived' }));
    await screen.findByText('Archived original');
    fireEvent.change(searchBox(), { target: { value: 'lineage record' } });
    fireEvent.click(screen.getByRole('button', { name: 'delete archive-root permanently' }));
    expect(screen.getByRole('button', { name: 'confirm delete archive-root' }).textContent)
      .toContain('whole conversation');
    expect(calls('DELETE')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'confirm delete archive-root' }));
    await waitFor(() => expect(calls('DELETE')).toHaveLength(1));
    expect(calls('DELETE')[0].path).toBe(deletePath('archive-root', true));
  });
});
