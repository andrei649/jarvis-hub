import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { BoardResultReview, useBoardResult, type BoardReference, type BoardResultRef } from '../composer-board-result';
import * as api from '../panels/kanban/api';

vi.mock('../panels/kanban/api', () => ({ fetchBoards: vi.fn(), fetchBoard: vi.fn(), fetchTask: vi.fn() }));

const digest = 'a'.repeat(64);
const task = (result = 'Recorded evidence', more = {}) => ({ id: 't_1', title: 'Finish report', status: 'done', result, latest_summary: 'Fallback summary', board_source_sha256: digest, ...more });
const detail = (result = 'Recorded evidence', more = {}) => ({ task: task(result, more), comments: [], events: [], links: { parents: [], children: [] }, runs: [] });
const send = vi.fn(() => true);
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
});
const target = { id: `v1-${'b'.repeat(64)}`, vault: 'Owner Vault', inbox: 'Inbox' };

function Harness({ agent = 'jarvis', session = 's1', enabled = true, lang = 'en', refTask, onSend }: {
  agent?: string; session?: string; enabled?: boolean; lang?: string; refTask?: BoardResultRef;
  onSend?: (references: BoardReference[]) => boolean | Promise<boolean>;
}) {
  const draft = useBoardResult(agent, session, enabled, lang);
  return <>
    <button ref={draft.trigger} onClick={() => void draft.open(refTask)}>Attach task result</button>
    <button onClick={() => void draft.send(onSend || send)}>Transmit</button>
    <span data-testid="active">{String(draft.active)}</span>
    <span data-testid="count">{draft.count}</span>
    <span data-testid="busy">{String(draft.busy)}</span>
    <BoardResultReview draft={draft}/>
  </>;
}

beforeEach(() => {
  vi.clearAllMocks();
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
  vi.mocked(api.fetchBoards).mockResolvedValue({ current: 'alpha', boards: [{ slug: 'alpha', name: 'Alpha' }] });
  vi.mocked(api.fetchBoard).mockResolvedValue({ columns: [{ name: 'done', tasks: [task()] }], tenants: [], assignees: [], latest_event_id: 0, now: 0 });
  vi.mocked(api.fetchTask).mockResolvedValue(detail());
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.removeItem('hud.user_token'); localStorage.removeItem('hud.admin_token'); });

it('previews only reviewed results for an editable Obsidian note without sending chat or changing the selection', async () => {
  localStorage.setItem('hud.user_token', 'chat-user');
  localStorage.setItem('hud.admin_token', 'board-admin');
  const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => url.endsWith('/api/kanban/board-note/preview')
    ? json({ title: 'Reviewed results', content: '## alpha/t_1\nRecorded evidence' })
    : json({ ok: true, captureTarget: target }));
  vi.stubGlobal('fetch', fetchMock);
  render(<Harness refTask={{ board: 'alpha', taskId: 't_1' }}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  await screen.findByRole('textbox', { name: 'Result text to review' });
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save results to Obsidian' }));
  expect((await screen.findByRole('textbox', { name: 'Note' }) as HTMLTextAreaElement).value)
    .toBe('## alpha/t_1\nRecorded evidence');
  const preview = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/kanban/board-note/preview'))!;
  expect(JSON.parse(String(preview[1]?.body))).toEqual({ references: [
    { board: 'alpha', task_id: 't_1', source: 'result', excerpt: 'Recorded evidence', sha256: digest },
  ] });
  expect(preview[1]?.headers).toMatchObject({ 'X-User-Token': 'chat-user' });
  expect(preview[1]?.headers).not.toHaveProperty('X-Admin-Token');
  expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([
    expect.stringContaining('/api/kanban/board-note/preview'), expect.stringContaining('/api/os/status'),
  ]);
  expect(api.fetchTask).toHaveBeenCalledTimes(1);
  expect(screen.getByTestId('count').textContent).toBe('1');
  expect(send).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(screen.getByTestId('count').textContent).toBe('1');
  expect(send).not.toHaveBeenCalled();
});

it('reopens an unconfirmed write with the exact request ID and reviewed body', async () => {
  let saves = 0;
  const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url.endsWith('/api/kanban/board-note/preview')) return json({ title: 'Results', content: 'Reviewed evidence only' });
    if (url.endsWith('/api/os/status')) return json({ ok: true, captureTarget: target });
    if (url.endsWith('/api/os/brain/chat-note')) return ++saves === 1 ? json({ ok: false }, 503)
      : json({ ok: true, relPath: 'Inbox/Results.md', source: null });
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal('fetch', fetchMock);
  render(<Harness refTask={{ board: 'alpha', taskId: 't_1' }}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  await screen.findByRole('textbox', { name: 'Result text to review' });
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save results to Obsidian' }));
  const note = await screen.findByRole('textbox', { name: 'Note' });
  fireEvent.change(note, { target: { value: 'Edited reviewed evidence' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
  await screen.findByText('Save could not be confirmed. Retry the same request.');
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save results to Obsidian' }));
  expect((await screen.findByRole('textbox', { name: 'Note' }) as HTMLTextAreaElement).value)
    .toBe('Edited reviewed evidence');
  fireEvent.click(screen.getByRole('button', { name: 'Retry save' }));
  await screen.findByText(/Saved to Obsidian: Inbox\/Results.md/);
  const posts = fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/api/os/brain/chat-note'));
  expect(posts).toHaveLength(2);
  expect(JSON.parse(String(posts[0]?.[1]?.body))).toEqual(JSON.parse(String(posts[1]?.[1]?.body)));
  expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/api/kanban/board-note/preview'))).toHaveLength(1);
  expect(screen.getByTestId('count').textContent).toBe('1');
  expect(send).not.toHaveBeenCalled();
});

it('requires re-review on a changed source and ignores a late preview after a session switch', async () => {
  const fetchMock = vi.fn(async () => json({ detail: 'board_source_changed' }, 409));
  vi.stubGlobal('fetch', fetchMock);
  const view = render(<Harness refTask={{ board: 'alpha', taskId: 't_1' }}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  await screen.findByRole('textbox', { name: 'Result text to review' });
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save results to Obsidian' }));
  await screen.findByText('One or more sources changed. Review the staged results again before saving.');
  expect(screen.queryByText('Changed or missing; review again or remove before sending.')).toBeNull();
  expect(screen.getByRole('button', { name: 'Save results to Obsidian' }).hasAttribute('disabled')).toBe(true);
  expect(screen.getByRole('button', { name: 'Review this task again: alpha/t_1' })).toBeTruthy();
  expect(send).not.toHaveBeenCalled();

  let finish!: (value: Response) => void;
  fetchMock.mockImplementationOnce(() => new Promise(done => { finish = done; }));
  fireEvent.click(screen.getByRole('button', { name: 'Review this task again: alpha/t_1' }));
  await screen.findByRole('textbox', { name: 'Result text to review' });
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save results to Obsidian' }));
  view.rerender(<Harness session="s2" refTask={{ board: 'alpha', taskId: 't_1' }}/>);
  finish(json({ title: 'Late', content: 'private old-session result' }));
  await waitFor(() => expect(screen.getByTestId('count').textContent).toBe('0'));
  expect(screen.queryByText('private old-session result')).toBeNull();
});

it('clears private staged text on preview auth expiry and rejects an invalid preview without saving', async () => {
  const fetchMock = vi.fn(async () => json({ title: 'Invalid', content: '' }));
  vi.stubGlobal('fetch', fetchMock);
  render(<Harness refTask={{ board: 'alpha', taskId: 't_1' }}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  await screen.findByRole('textbox', { name: 'Result text to review' });
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save results to Obsidian' }));
  await screen.findByText('The note preview was invalid. Nothing was saved.');
  expect(screen.getByTestId('count').textContent).toBe('1');
  expect(screen.queryByRole('textbox', { name: 'Note' })).toBeNull();
  fetchMock.mockResolvedValueOnce(json({ detail: 'expired' }, 403));
  fireEvent.click(screen.getByRole('button', { name: 'Save results to Obsidian' }));
  await screen.findByText('Board access expired. Sign in and review task results again.');
  expect(screen.getByTestId('count').textContent).toBe('0');
  expect(screen.queryByText('Recorded evidence')).toBeNull();
  expect(send).not.toHaveBeenCalled();
});

it('lets the owner pick and review one recorded result, then rechecks before one accepted dispatch', async () => {
  render(<Harness/>);
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  const selector = await screen.findByRole('combobox', { name: 'Completed task' });
  fireEvent.change(selector, { target: { value: 't_1' } });
  expect((await screen.findByRole('textbox', { name: 'Result text to review' }) as HTMLTextAreaElement).value).toBe('Recorded evidence');
  expect(screen.getByText('Recorded task result')).toBeTruthy();
  expect(send).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  expect(screen.getByText('Destination: the next message in this chat, to jarvis.')).toBeTruthy();
  expect(screen.getByTestId('active').textContent).toBe('true');
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  await waitFor(() => expect(send).toHaveBeenCalledExactlyOnceWith([{ board: 'alpha', task_id: 't_1', source: 'result', excerpt: 'Recorded evidence', sha256: digest }]));
  expect(api.fetchTask).toHaveBeenCalledTimes(2);
  await waitFor(() => expect(screen.getByTestId('active').textContent).toBe('false'));
});

it('labels summary fallback and requires a chosen bounded passage for oversized text', async () => {
  const long = 'A'.repeat(64_000) + 'B';
  vi.mocked(api.fetchTask).mockResolvedValue(detail('', { latest_summary: long }));
  render(<Harness refTask={{ board: 'alpha', taskId: 't_1' }} lang="ro"/>);
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  const area = await screen.findByRole('textbox', { name: 'Textul rezultatului de revizuit' }) as HTMLTextAreaElement;
  expect(screen.getByText(/Ultimul rezumat \(alternativă/)).toBeTruthy();
  area.setSelectionRange(0, 0);
  fireEvent.click(screen.getByRole('button', { name: 'Atașează pasajul selectat' }));
  expect(screen.getByRole('alert').textContent).toBe('Selectează întâi un pasaj din rezultat.');
  expect(screen.queryByRole('button', { name: 'Reîncearcă' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Atașează rezultatul complet' }).hasAttribute('disabled')).toBe(true);
  area.setSelectionRange(63995, 64001);
  fireEvent.click(screen.getByRole('button', { name: 'Atașează pasajul selectat' }));
  expect(screen.getByText('AAAAAB', { exact: true })).toBeTruthy();
  expect(send).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  await waitFor(() => expect(send).toHaveBeenCalledExactlyOnceWith([{ board: 'alpha', task_id: 't_1', source: 'latest_summary', excerpt: 'AAAAAB', sha256: digest }]));
});

it('never dispatches a changed task and requires fresh review', async () => {
  vi.mocked(api.fetchTask).mockResolvedValueOnce(detail()).mockResolvedValueOnce(detail('Changed result'));
  render(<Harness refTask={{ board: 'alpha', taskId: 't_1' }}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  await screen.findByRole('textbox', { name: 'Result text to review' });
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  await waitFor(() => expect(screen.getAllByRole('alert')[0].textContent).toContain('The task changed'));
  expect(send).not.toHaveBeenCalled();
  expect(screen.getByTestId('active').textContent).toBe('true');
  expect(screen.getByRole('button', { name: 'Review this task again: alpha/t_1' })).toBeTruthy();
});

it('retains the reviewed attachment when recheck fails or dispatch is refused', async () => {
  vi.mocked(api.fetchTask).mockResolvedValueOnce(detail()).mockRejectedValueOnce(new Error('offline')).mockResolvedValue(detail());
  send.mockReturnValueOnce(false).mockReturnValue(true);
  render(<Harness refTask={{ board: 'alpha', taskId: 't_1' }}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  await screen.findByRole('textbox', { name: 'Result text to review' });
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Could not recheck'));
  expect(screen.getByTestId('active').textContent).toBe('true');
  expect(send).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
  expect(screen.getByTestId('active').textContent).toBe('true');
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
  expect(screen.getByTestId('active').textContent).toBe('false');
});

it('ignores a stale task read after session change', async () => {
  let resolve!: (value: ReturnType<typeof detail>) => void;
  vi.mocked(api.fetchTask).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  const view = render(<Harness session="first" refTask={{ board: 'alpha', taskId: 't_1' }}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  await waitFor(() => expect(api.fetchTask).toHaveBeenCalledTimes(1));
  view.rerender(<Harness session="second" refTask={{ board: 'alpha', taskId: 't_1' }}/>);
  resolve(detail());
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(screen.getByTestId('active').textContent).toBe('false');
  expect(send).not.toHaveBeenCalled();
});

it('accepts the same recorded source despite changing task age and unrelated metadata', async () => {
  vi.mocked(api.fetchTask).mockResolvedValueOnce(detail('Same result', { task_age: 1, body: 'private body' }))
    .mockResolvedValueOnce(detail('Same result', { task_age: 2, body: 'changed body', diagnostics: [{ secret: 'not attached' }] }));
  render(<Harness refTask={{ board: 'alpha', taskId: 't_1' }}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  await screen.findByRole('textbox', { name: 'Result text to review' });
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  await waitFor(() => expect(send).toHaveBeenCalledExactlyOnceWith([{ board: 'alpha', task_id: 't_1', source: 'result', excerpt: 'Same result', sha256: digest }]));
  expect(JSON.stringify(send.mock.calls)).not.toContain('private body');
  expect(JSON.stringify(send.mock.calls)).not.toContain('not attached');
});

it('keeps original CRLF bytes when selecting through a normalized textarea', async () => {
  vi.mocked(api.fetchTask).mockResolvedValue(detail('first\r\nsecond\r\nthird'));
  render(<Harness refTask={{ board: 'alpha', taskId: 't_1' }}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  const area = await screen.findByRole('textbox', { name: 'Result text to review' }) as HTMLTextAreaElement;
  area.setSelectionRange(0, 12);
  fireEvent.click(screen.getByRole('button', { name: 'Attach selected passage' }));
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  await waitFor(() => expect(send).toHaveBeenCalledExactlyOnceWith([{ board: 'alpha', task_id: 't_1', source: 'result', excerpt: 'first\r\nsecond', sha256: digest }]));
});

it('discards a completed read if credentials change before it resolves', async () => {
  let resolve!: (value: ReturnType<typeof detail>) => void;
  vi.mocked(api.fetchTask).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  render(<Harness refTask={{ board: 'alpha', taskId: 't_1' }}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  await waitFor(() => expect(api.fetchTask).toHaveBeenCalledTimes(1));
  localStorage.setItem('hud.admin_token', 'different-owner');
  resolve(detail('old credential data'));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(screen.queryByText('old credential data')).toBeNull();
  expect(screen.getByTestId('active').textContent).toBe('false');
});

it('stages two same-title tasks in order without sending during review and removes one independently', async () => {
  const second = task('Second evidence', { id: 't_2' });
  vi.mocked(api.fetchBoard).mockResolvedValue({ columns: [{ name: 'done', tasks: [task(), second] }], tenants: [], assignees: [], latest_event_id: 0, now: 0 });
  vi.mocked(api.fetchTask).mockImplementation(async (_board, id) => id === 't_2' ? detail('Second evidence', { id }) : detail());
  render(<Harness/>);
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  fireEvent.change(await screen.findByRole('combobox', { name: 'Completed task' }), { target: { value: 't_1' } });
  await screen.findByRole('textbox', { name: 'Result text to review' });
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  fireEvent.change(await screen.findByRole('combobox', { name: 'Completed task' }), { target: { value: 't_2' } });
  await waitFor(() => expect((screen.getByRole('textbox', { name: 'Result text to review' }) as HTMLTextAreaElement).value).toBe('Second evidence'));
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  expect(screen.getByTestId('count').textContent).toBe('2');
  expect(send).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  await waitFor(() => expect(send).toHaveBeenCalledExactlyOnceWith([
    { board: 'alpha', task_id: 't_1', source: 'result', excerpt: 'Recorded evidence', sha256: digest },
    { board: 'alpha', task_id: 't_2', source: 'result', excerpt: 'Second evidence', sha256: digest },
  ]));
});

it('keeps staged results when the picker is cancelled and replaces one task by ID', async () => {
  vi.mocked(api.fetchTask).mockResolvedValueOnce(detail()).mockResolvedValueOnce(detail('New evidence'));
  render(<Harness refTask={{ board: 'alpha', taskId: 't_1' }}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  await screen.findByRole('textbox', { name: 'Result text to review' });
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  expect(screen.getByTestId('count').textContent).toBe('1');
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  await waitFor(() => expect((screen.getByRole('textbox', { name: 'Result text to review' }) as HTMLTextAreaElement).value).toBe('New evidence'));
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  expect(screen.getByTestId('count').textContent).toBe('1');
  expect(screen.getByText('New evidence')).toBeTruthy();
});

it('blocks the entire group when one member changes and retains the other member', async () => {
  const second = task('Second evidence', { id: 't_2' });
  vi.mocked(api.fetchBoard).mockResolvedValue({ columns: [{ name: 'done', tasks: [task(), second] }], tenants: [], assignees: [], latest_event_id: 0, now: 0 });
  vi.mocked(api.fetchTask).mockImplementation(async (_board, id) => id === 't_2' ? detail('Second evidence', { id }) : detail());
  render(<Harness/>);
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  fireEvent.change(await screen.findByRole('combobox', { name: 'Completed task' }), { target: { value: 't_1' } });
  await screen.findByRole('textbox', { name: 'Result text to review' });
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  fireEvent.change(await screen.findByRole('combobox', { name: 'Completed task' }), { target: { value: 't_2' } });
  await waitFor(() => expect((screen.getByRole('textbox', { name: 'Result text to review' }) as HTMLTextAreaElement).value).toBe('Second evidence'));
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  vi.mocked(api.fetchTask).mockImplementation(async (_board, id) => id === 't_2' ? detail('Changed', { id }) : detail());
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  await waitFor(() => expect(screen.getAllByRole('alert')[0].textContent).toContain('t_2'));
  expect(send).not.toHaveBeenCalled();
  expect(screen.getByTestId('count').textContent).toBe('2');
});

it('marks a missing task, blocks a second send, then permits explicit removal', async () => {
  vi.mocked(api.fetchTask).mockResolvedValueOnce(detail()).mockRejectedValueOnce(Object.assign(new Error('missing'), { status: 404 }));
  render(<Harness refTask={{ board: 'alpha', taskId: 't_1' }}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  await screen.findByRole('textbox', { name: 'Result text to review' });
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  await waitFor(() => expect(screen.getAllByRole('alert')[0].textContent).toContain('alpha/t_1'));
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  expect(api.fetchTask).toHaveBeenCalledTimes(2);
  expect(send).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Remove: alpha/t_1' }));
  expect(screen.getByTestId('count').textContent).toBe('0');
});

it('locks staged removal during recheck and dispatches only once', async () => {
  let resolve!: (value: ReturnType<typeof detail>) => void;
  vi.mocked(api.fetchTask).mockResolvedValueOnce(detail()).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
  render(<Harness refTask={{ board: 'alpha', taskId: 't_1' }}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  await screen.findByRole('textbox', { name: 'Result text to review' });
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  const remove = screen.getByRole('button', { name: 'Remove: alpha/t_1' }) as HTMLButtonElement;
  expect(remove.disabled).toBe(true);
  fireEvent.click(remove);
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  resolve(detail());
  await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
  expect(api.fetchTask).toHaveBeenCalledTimes(2);
});

it('retains staged passages until an asynchronous dispatch is accepted', async () => {
  let resolve!: (accepted: boolean) => void;
  const onSend = vi.fn(() => new Promise<boolean>(done => { resolve = done; }));
  render(<Harness refTask={{ board: 'alpha', taskId: 't_1' }} onSend={onSend}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  await screen.findByRole('textbox', { name: 'Result text to review' });
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
  expect(screen.getByTestId('count').textContent).toBe('1');
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  expect(onSend).toHaveBeenCalledTimes(1);
  resolve(false);
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('not accepted'));
  expect(screen.getByTestId('count').textContent).toBe('1');
});

it('clears staged private text on credential and session changes', async () => {
  const view = render(<Harness refTask={{ board: 'alpha', taskId: 't_1' }}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  await screen.findByRole('textbox', { name: 'Result text to review' });
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  localStorage.setItem('hud.admin_token', 'new-owner');
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  expect(send).not.toHaveBeenCalled();
  expect(screen.getByTestId('count').textContent).toBe('0');
  localStorage.removeItem('hud.admin_token');
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  await screen.findByRole('textbox', { name: 'Result text to review' });
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  view.rerender(<Harness session="s2" refTask={{ board: 'alpha', taskId: 't_1' }}/>);
  expect(screen.getByTestId('count').textContent).toBe('0');
});

it('clears staged private text on an explicit 403 recheck and shows a sign-in notice', async () => {
  vi.mocked(api.fetchTask).mockResolvedValueOnce(detail()).mockRejectedValueOnce(Object.assign(new Error('forbidden'), { status: 403 }));
  render(<Harness refTask={{ board: 'alpha', taskId: 't_1' }}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
  await screen.findByRole('textbox', { name: 'Result text to review' });
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Sign in'));
  expect(screen.getByTestId('count').textContent).toBe('0');
  expect(screen.queryByText('Recorded evidence')).toBeNull();
  expect(send).not.toHaveBeenCalled();
});

it('refuses a ninth item before staging', async () => {
  const ids = Array.from({ length: 9 }, (_, index) => `t_${index + 1}`);
  vi.mocked(api.fetchBoard).mockResolvedValue({ columns: [{ name: 'done', tasks: ids.map(id => task('A', { id })) }], tenants: [], assignees: [], latest_event_id: 0, now: 0 });
  vi.mocked(api.fetchTask).mockImplementation(async (_board, id) => detail('A', { id }));
  render(<Harness/>);
  for (const id of ids) {
    fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
    fireEvent.change(await screen.findByRole('combobox', { name: 'Completed task' }), { target: { value: id } });
    await screen.findByRole('textbox', { name: 'Result text to review' });
    fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
    if (id === 't_9') break;
  }
  expect(screen.getByTestId('count').textContent).toBe('8');
  expect(screen.getByRole('alert').textContent).toContain('group is full');
});

it('refuses text that would exceed the 128,000-byte aggregate', async () => {
  const ids = ['t_1', 't_2', 't_3'];
  const body = 'A'.repeat(50_000);
  vi.mocked(api.fetchBoard).mockResolvedValue({ columns: [{ name: 'done', tasks: ids.map(id => task(body, { id })) }], tenants: [], assignees: [], latest_event_id: 0, now: 0 });
  vi.mocked(api.fetchTask).mockImplementation(async (_board, id) => detail(body, { id }));
  render(<Harness/>);
  for (const id of ids) {
    fireEvent.click(screen.getByRole('button', { name: 'Attach task result' }));
    fireEvent.change(await screen.findByRole('combobox', { name: 'Completed task' }), { target: { value: id } });
    await screen.findByRole('textbox', { name: 'Result text to review' });
    fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  }
  expect(screen.getByTestId('count').textContent).toBe('2');
  expect(screen.getByRole('alert').textContent).toContain('128,000');
  expect(send).not.toHaveBeenCalled();
});
