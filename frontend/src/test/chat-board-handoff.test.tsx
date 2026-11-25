import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { InputBar } from '../cockpit';
import { openComposerMenu } from '../home/talk/test-support';

const t = { transmit: 'Transmit', placeholder: 'Message', channel: 'Chat' };
const digest = 'a'.repeat(64);
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('offers board results for a live ordinary message and leaves private boards unopened until requested', () => {
  const fetcher = vi.fn();
  vi.stubGlobal('fetch', fetcher);
  const view = render(<InputBar t={t} selectedTurn agent="frigga" sessionId="chat-one" />);
  openComposerMenu('attach');   // Board result is in the composer's Attach menu since the re-lay
  const board = screen.getByRole('button', { name: 'Attach board result' }) as HTMLButtonElement;
  expect(board.disabled).toBe(false);
  fireEvent.change(screen.getByPlaceholderText('Message'), { target: { value: '/new' } });
  expect(board.disabled).toBe(true);
  fireEvent.click(board);
  expect(fetcher.mock.calls.some(([url]) => String(url).includes('/api/kanban'))).toBe(false);
  view.rerender(<InputBar t={t} selectedTurn={false} demo />);
  expect(screen.queryByRole('button', { name: 'Attach board result' })).toBeNull();
});

it('previews staged results for Obsidian without cloud consent or changing the chat draft', async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
  const card = { id: 't_1', title: 'Finished card', status: 'done', result: 'Reviewed passage', board_source_sha256: digest };
  const fetcher = vi.fn(async (url: string, options?: RequestInit) => {
    if (url.endsWith('/api/kanban/boards')) return Response.json({ current: 'alpha', boards: [{ slug: 'alpha', name: 'Alpha' }] });
    if (url.includes('/api/kanban/board?')) return Response.json({ columns: [{ tasks: [card] }] });
    if (url.includes('/api/kanban/tasks/t_1?')) return Response.json({ task: card });
    if (url.endsWith('/api/kanban/board-note/preview')) return Response.json({ title: 'Results', content: 'Reviewed passage' });
    if (url.endsWith('/api/os/status')) return Response.json({ ok: true,
      captureTarget: { id: `v1-${'b'.repeat(64)}`, vault: 'Owner Vault', inbox: 'Inbox' } });
    throw new Error(`Unexpected request: ${url} ${options?.method}`);
  });
  vi.stubGlobal('fetch', fetcher);
  const submit = vi.fn();
  render(<InputBar t={t} selectedTurn agent="athena" sessionId="save-only" onSubmit={submit}/>);
  const input = screen.getByPlaceholderText('Message') as HTMLInputElement;
  fireEvent.change(input, { target: { value: 'Unsent owner question' } });
  openComposerMenu('attach');
  fireEvent.click(screen.getByRole('button', { name: 'Attach board result' }));
  fireEvent.change(await screen.findByRole('combobox', { name: 'Completed task' }), { target: { value: 't_1' } });
  fireEvent.click(await screen.findByRole('button', { name: 'Attach full result' }));
  expect((screen.getByRole('button', { name: 'Transmit' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Save results to Obsidian' }));
  expect((await screen.findByRole('textbox', { name: 'Note' }) as HTMLTextAreaElement).value).toBe('Reviewed passage');
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(input.value).toBe('Unsent owner question');
  expect(screen.getByText('Reviewed passage')).toBeTruthy();
  expect(submit).not.toHaveBeenCalled();
  expect(fetcher.mock.calls.filter(([url]) => String(url).endsWith('/api/kanban/board-note/preview'))).toHaveLength(1);
  expect(fetcher.mock.calls.filter(([url]) => String(url).includes('/api/os/brain/chat-note'))).toHaveLength(0);
});

it('keeps an edited message and reviewed result through an in-flight recheck, then sends once on retry', async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
  const card = { id: 't_1', title: 'Finished card', status: 'done', result: 'Exact recorded result', latest_summary: 'Older summary', board_source_sha256: digest };
  const task = () => Response.json({ task: card, comments: [], events: [], links: { parents: [], children: [] }, runs: [] });
  let resolveRecheck!: (response: Response) => void;
  let reads = 0;
  const fetcher = vi.fn((url: string, options: RequestInit) => {
    if (url.endsWith('/api/kanban/boards')) return Promise.resolve(Response.json({ current: 'alpha', boards: [{ slug: 'alpha', name: 'Alpha' }] }));
    if (url.includes('/api/kanban/board?')) return Promise.resolve(Response.json({ columns: [{ name: 'done', tasks: [card] }], tenants: [], assignees: [], latest_event_id: 0, now: 0 }));
    if (url.includes('/api/kanban/tasks/t_1?')) {
      reads++;
      return reads === 2 ? new Promise<Response>(resolve => { resolveRecheck = resolve; }) : Promise.resolve(task());
    }
    throw new Error(`Unexpected request: ${url} ${options.method}`);
  });
  vi.stubGlobal('fetch', fetcher);
  const submit = vi.fn(() => true);
  const ref = { board: 'alpha', taskId: 't_1' };
  render(<InputBar t={t} selectedTurn agent="frigga" sessionId="chat-one" boardResultForChat={ref}
    onBoardResultReviewed={vi.fn()} onSubmit={submit} />);
  const input = screen.getByPlaceholderText('Message') as HTMLInputElement;
  fireEvent.change(input, { target: { value: 'First question' } });
  expect((await screen.findByRole('textbox', { name: 'Result text to review' }) as HTMLTextAreaElement).value).toBe('Exact recorded result');
  expect(screen.getByText('Recorded task result')).toBeTruthy();
  expect(screen.getByText('Destination: the next message in this chat, to frigga.')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Attach full result' }));
  expect(submit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  await waitFor(() => expect(reads).toBe(2));
  fireEvent.change(input, { target: { value: 'Edited question' } });
  expect(input.value).toBe('Edited question');
  expect(submit).not.toHaveBeenCalled();
  resolveRecheck(task());
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('not accepted'));
  expect(input.value).toBe('Edited question');
  expect(submit).not.toHaveBeenCalled();
  expect(screen.getByText('Exact recorded result')).toBeTruthy();
  const readsBeforeRetry = reads;
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  await waitFor(() => expect(submit).toHaveBeenCalledExactlyOnceWith('Edited question', undefined,
    undefined, false, { boardReferences: [{ board: 'alpha', task_id: 't_1', source: 'result', excerpt: 'Exact recorded result', sha256: digest }], allowBoardCloud: false }));
  expect(reads).toBe(readsBeforeRetry + 1);
  await waitFor(() => expect(input.value).toBe(''));
  fireEvent.change(input, { target: { value: 'Next ordinary turn' } });
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  expect(submit).toHaveBeenCalledTimes(2);
  expect(submit.mock.calls[1]).toEqual(['Next ordinary turn']);
  expect(reads).toBe(3);
  for (const [url, options] of fetcher.mock.calls) {
    if (url.includes('/api/kanban')) expect(options).toMatchObject({ method: 'GET', cache: 'no-store', redirect: 'error', credentials: 'same-origin' });
  }
});

it('sends two reviewed worker outputs in order with one comparison question', async () => {
  const cards = [
    { id: 't_first', title: 'Plan', status: 'done', result: 'Use the south entrance.', board_source_sha256: digest },
    { id: 't_second', title: 'Plan', status: 'done', latest_summary: 'The north entrance is closed.', board_source_sha256: digest },
  ];
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/api/kanban/boards')) return Response.json({ current: 'alpha', boards: [{ slug: 'alpha', name: 'Alpha' }] });
    if (url.includes('/api/kanban/board?')) return Response.json({ columns: [{ name: 'done', tasks: cards }] });
    const task = cards.find(card => url.includes('/tasks/' + card.id + '?'));
    if (task) return Response.json({ task });
    throw new Error('Unexpected read ' + url);
  }));
  const submit = vi.fn(() => true);
  render(<InputBar t={t} selectedTurn agent="frigga" sessionId="together" onSubmit={submit}/>);
  const input = screen.getByPlaceholderText('Message');
  openComposerMenu('attach');   // stays open: the review returns focus to its trigger in the menu
  for (const card of cards) {
    fireEvent.click(screen.getByRole('button', { name: 'Attach board result' }));
    const picker = await screen.findByRole('combobox', { name: 'Completed task' });
    await waitFor(() => expect((picker as HTMLSelectElement).disabled).toBe(false));
    fireEvent.change(picker, { target: { value: card.id } });
    fireEvent.click(await screen.findByRole('button', { name: 'Attach full result' }));
  }
  expect(submit).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { value: 'Read @file:notes.md too' } });
  expect(screen.getByText(/share 128,000 bytes/)).toBeTruthy();
  fireEvent.change(input, { target: { value: '' } });
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  await waitFor(() => expect(submit).toHaveBeenCalledExactlyOnceWith(
    'Compare the task results and identify the source of each conclusion.', undefined, undefined, false,
    { boardReferences: [
      { board: 'alpha', task_id: 't_first', source: 'result', excerpt: 'Use the south entrance.', sha256: digest },
      { board: 'alpha', task_id: 't_second', source: 'latest_summary', excerpt: 'The north entrance is closed.', sha256: digest },
    ], allowBoardCloud: false }));
});

it('keeps a new question typed while a reviewed send awaits stream admission', async () => {
  const card = { id: 't_one', title: 'North', status: 'done', result: 'Dock one', board_source_sha256: digest };
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/boards')) return Response.json({ current: 'a', boards: [{ slug: 'a' }] });
    if (url.includes('/board?')) return Response.json({ columns: [{ tasks: [card] }] });
    return Response.json({ task: card });
  }));
  let acknowledge!: (ok: boolean) => void;
  const submit = vi.fn(() => new Promise<boolean>(resolve => { acknowledge = resolve; }));
  render(<InputBar t={t} selectedTurn agent="frigga" sessionId="s" onSubmit={submit}
    boardResultForChat={{ board: 'a', taskId: 't_one' }} onBoardResultReviewed={() => {}}/>);
  fireEvent.click(await screen.findByRole('button', { name: 'Attach full result' }));
  const input = screen.getByPlaceholderText('Message') as HTMLInputElement;
  fireEvent.change(input, { target: { value: 'First question' } });
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  fireEvent.change(input, { target: { value: 'Next question' } });
  acknowledge(true);
  await waitFor(() => expect(screen.queryByText('Dock one')).toBeNull());
  expect(input.value).toBe('Next question');
});

it('requires fresh affirmative consent for a cloud-capable recipient and each staged selection', async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
  const cards = [
    { id: 't_one', title: 'One', status: 'done', result: 'First', board_source_sha256: digest },
    { id: 't_two', title: 'Two', status: 'done', result: 'Second', board_source_sha256: digest },
  ];
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/boards')) return Response.json({ current: 'alpha', boards: [{ slug: 'alpha' }] });
    if (url.includes('/board?')) return Response.json({ columns: [{ tasks: cards }] });
    return Response.json({ task: cards.find(card => url.includes('/tasks/' + card.id + '?')) });
  }));
  const submit = vi.fn(() => true);
  render(<InputBar t={t} selectedTurn agent="athena" sessionId="cloud" onSubmit={submit}/>);
  openComposerMenu('attach');
  fireEvent.click(screen.getByRole('button', { name: 'Attach board result' }));
  fireEvent.change(await screen.findByRole('combobox', { name: 'Completed task' }), { target: { value: 't_one' } });
  fireEvent.click(await screen.findByRole('button', { name: 'Attach full result' }));
  const consent = screen.getByRole('checkbox', { name: /Allow these reviewed passages/ }) as HTMLInputElement;
  expect((screen.getByRole('button', { name: 'Transmit' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(consent);
  expect(consent.checked).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Attach board result' }));
  fireEvent.change(await screen.findByRole('combobox', { name: 'Completed task' }), { target: { value: 't_two' } });
  fireEvent.click(await screen.findByRole('button', { name: 'Attach full result' }));
  expect(consent.checked).toBe(false);
  expect(submit).not.toHaveBeenCalled();
  fireEvent.click(consent);
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  expect((submit.mock.calls[0] as unknown[])[4]).toMatchObject({ allowBoardCloud: true, boardReferences: [
    { task_id: 't_one' }, { task_id: 't_two' },
  ] });
});
