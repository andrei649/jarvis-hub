import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { TaskDrawer } from './panels/kanban/drawer';
import * as api from './panels/kanban/api';
import type { KanbanTaskDetail } from './panels/kanban/types';

vi.mock('./panels/kanban/api', () => ({ fetchTask: vi.fn(), fetchLog: vi.fn(), fetchRun: vi.fn(), reclaimTask: vi.fn(), patchTask: vi.fn(), addComment: vi.fn(), uploadAttachment: vi.fn(), downloadAttachment: vi.fn(), deleteTask: vi.fn() }));
const detail: KanbanTaskDetail = {
  task: { id: 't_1', title: 'Inspect queue', status: 'triage', body: '**Goal:** diagnose', priority: 2, workspace_kind: 'dir', workspace_path: '/repo' },
  comments: [{ id: 2, author: 'owner', body: 'Existing note', created_at: 1 }], events: [{ id: 4, kind: 'status', payload: {status:'triage'}, created_at: 1 }],
  attachments: [{ id: 3, filename: 'proof.txt', size: 4 }], links: { parents: [], children: [] }, runs: [],
};
beforeEach(() => {
  vi.mocked(api.fetchTask).mockResolvedValue(detail);
});
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals(); });
const props = { slug: 'alpha', id: 't_1', columns: ['triage','ready','running'], profiles: [], onOpen: vi.fn(), onClose: vi.fn(), onChanged: vi.fn() };

describe('Kanban task drawer', () => {
  it('renders task markdown through the shared safe renderer', async () => {
    render(<TaskDrawer {...props} />);
    expect(await screen.findByText('Goal:')).toBeTruthy();
    expect(screen.queryByText('**Goal:** diagnose')).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Child results' })).toBeNull();
  });

  it('shows full child outputs and opens the matching task', async () => {
    const fullSummary = 'Inspected every line of the ledger. '.repeat(8) + 'Final quantity 147.';
    vi.mocked(api.fetchTask).mockResolvedValue({ ...detail, child_results: [
      { id: 'alpha', title: 'Check receipts', status: 'done', result: 'Balance **325**.', latest_summary: 'Reconciled' },
      { id: 'beta', title: 'Count stock', status: 'done', assignee: 'Ultron', result: null, latest_summary: fullSummary },
      { id: 'gamma', title: 'Draft report', status: 'running' },
    ] });
    render(<TaskDrawer {...props} />);
    const receipts = within(await screen.findByRole('article', { name: 'Check receipts' }));
    expect(receipts.getByText('325').tagName).toBe('STRONG');
    expect(receipts.queryByText('Reconciled')).toBeNull();
    const stock = within(screen.getByRole('article', { name: 'Count stock' }));
    expect(stock.getByText(/Assigned to Ultron/)).toBeTruthy();
    expect(stock.getByText(fullSummary)).toBeTruthy();
    expect(stock.getByText('Latest run summary')).toBeTruthy();
    fireEvent.click(stock.getByRole('button', { name: 'Count stock' }));
    expect(props.onOpen).toHaveBeenCalledWith('beta');
    const pending = screen.getByRole('article', { name: 'Draft report' });
    expect(pending.textContent).toMatch(/running/i);
    expect(pending.textContent).not.toContain('147');
  });

  it('posts a body-only comment and refreshes the detail', async () => {
    vi.mocked(api.addComment).mockResolvedValue({ok:true});
    render(<TaskDrawer {...props} />);
    const dialog = await screen.findByRole('dialog', { name: 'Task details' });
    fireEvent.click(within(dialog).getByRole('tab', { name: 'Comments' }));
    expect(within(dialog).getByText('Existing note')).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText('Comment'), { target: { value: 'New note' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Post comment' }));
    await waitFor(() => expect(api.addComment).toHaveBeenCalledWith('alpha', 't_1', 'New note'));
    await waitFor(() => expect(api.fetchTask).toHaveBeenCalledTimes(2));
  });

  it('uploads a file and downloads by attachment ID, never stored_path', async () => {
    vi.mocked(api.uploadAttachment).mockResolvedValue({attachment:{id:5}});
    vi.mocked(api.downloadAttachment).mockResolvedValue(new Blob(['proof']));
    vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn(() => 'blob:test'), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    render(<TaskDrawer {...props} />);
    await screen.findByText('proof.txt');
    fireEvent.change(screen.getByLabelText('Upload attachment'), { target: { files: [new File(['new'], 'new.txt')] } });
    await waitFor(() => expect(api.uploadAttachment).toHaveBeenCalledWith('alpha', 't_1', expect.any(File)));
    fireEvent.click(screen.getByRole('button', { name: 'Download proof.txt' }));
    await waitFor(() => expect(api.downloadAttachment).toHaveBeenCalledWith('alpha', 3));
  });

  it('prepares a project comment on its chosen board and posts only after review', async () => {
    const ref = {path:'Inbox/Model (2).md',title:'Model',view:'robot'};
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(Response.json({ok:true,projects:[ref]}))
      .mockResolvedValueOnce(Response.json({ok:true,...ref,summary:'Blue shell.',project:{version:1,view:'robot'}})));
    vi.mocked(api.addComment).mockResolvedValue({ok:true});
    const view = render(<TaskDrawer {...props}/>);
    fireEvent.click(await screen.findByRole('tab',{name:'Comments'}));
    const field = await screen.findByLabelText('Comment') as HTMLTextAreaElement;
    fireEvent.change(field, {target:{value:'Please review.'}});
    fireEvent.click(screen.getByRole('button',{name:'Link a saved 3D project'}));
    fireEvent.click(await screen.findByRole('button',{name:'Add to comment'}));
    await waitFor(() => expect(field.value).toContain('Please review.\n\n[Open saved 3D project](/os/?project=Inbox%2FModel%20%282%29.md)\nBlue shell.'));
    const draft = field.value;
    expect(api.addComment).not.toHaveBeenCalled();
    view.rerender(<TaskDrawer {...props} slug="second-board"/>);
    fireEvent.click(await screen.findByRole('tab',{name:'Comments'}));
    expect((await screen.findByLabelText('Comment') as HTMLTextAreaElement).value).toBe('');
    view.rerender(<TaskDrawer {...props}/>);
    fireEvent.click(await screen.findByRole('tab',{name:'Comments'}));
    expect((await screen.findByLabelText('Comment') as HTMLTextAreaElement).value).toBe(draft);
    fireEvent.click(screen.getByRole('button',{name:'Post comment'}));
    await waitFor(() => expect(api.addComment).toHaveBeenCalledWith('alpha','t_1',draft));
  });

  it('rolls back a refused status edit and shows the server refusal', async () => {
    vi.mocked(api.patchTask).mockRejectedValue(new Error('workflow refused'));
    render(<TaskDrawer {...props} />);
    const status = await screen.findByLabelText('Status');
    fireEvent.change(status, { target: { value: 'ready' } });
    expect((await screen.findByRole('alert')).textContent).toContain('workflow refused');
    expect((screen.getByLabelText('Status') as HTMLSelectElement).value).toBe('triage');
  });

  it('labels unavailable worker controls instead of claiming success', async () => {
    render(<TaskDrawer {...props} />);
    expect(await screen.findByText('Inspect queue')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /recover interrupted run/i })).toBeNull();
    expect(screen.queryByRole('tab', { name: 'Log' })).toBeNull();
    expect(api.fetchLog).not.toHaveBeenCalled();
  });

  it('shows durable interruption followed by a completed retry and no raw log request', async () => {
    vi.mocked(api.fetchTask).mockResolvedValue({ ...detail, task: { ...detail.task, status: 'done' }, runs: [
      { id: 11, profile: 'frigga', status: 'nerva_worker_interrupted', outcome: 'nerva_worker_interrupted', error: 'queue execution ended', metadata: { retry_status: 'ready' }, started_at: 100, ended_at: 110 },
      { id: 12, profile: 'frigga', status: 'done', outcome: 'completed', summary: 'Calculation finished', started_at: 120, ended_at: 130 },
    ] });
    render(<TaskDrawer {...props} />);
    const history = await screen.findByRole('tab', { name: 'Worker history' });
    expect(history.getAttribute('aria-selected')).toBe('true');
    expect(screen.getByText(/Attempt 1.*frigga/)).toBeTruthy();
    expect(screen.getByText(/Status: Interrupted/)).toBeTruthy();
    expect(screen.getByText('queue execution ended')).toBeTruthy();
    expect(screen.getByText('Interrupted; next state: ready.')).toBeTruthy();
    expect(screen.getByText(/Attempt 2.*Latest.*frigga/)).toBeTruthy();
    expect(screen.getByText('Status: done · Outcome: Completed')).toBeTruthy();
    expect(screen.getByText('Calculation finished')).toBeTruthy();
    expect(screen.getAllByText(/Started .* · Ended /)).toHaveLength(2);
    expect(api.fetchLog).not.toHaveBeenCalled();
  });

  it('sends exact native run identity and shows the held review result', async () => {
    const running = { ...detail, task: { ...detail.task, status: 'running', current_run_id: 22, recoverable_run_id: 22 }, runs: [
      { id: 21, status: 'nerva_worker_interrupted', outcome: 'nerva_worker_interrupted', ended_at: 100 },
      { id: 22, status: 'running', outcome: null, started_at: 200, ended_at: null },
    ] } satisfies KanbanTaskDetail;
    const held = { ...running, task: { ...running.task, status: 'blocked', current_run_id: null, recoverable_run_id: null }, runs: [
      running.runs[0], { ...running.runs[1], status: 'reclaimed', outcome: 'reclaimed', ended_at: 300, summary: 'Held for review' },
    ] } satisfies KanbanTaskDetail;
    vi.mocked(api.fetchTask).mockResolvedValueOnce(running).mockResolvedValue(held);
    vi.mocked(api.reclaimTask).mockResolvedValue({ok:true, status:'recovered'});
    render(<TaskDrawer {...props} />);
    const button = await screen.findByRole('button', { name: 'Check and recover interrupted run' });
    fireEvent.change(screen.getByLabelText('Worker action reason'), { target: { value: 'owner review' } });
    fireEvent.click(button);
    await waitFor(() => expect(api.reclaimTask).toHaveBeenCalledWith('alpha', 't_1', 22, 'owner review'));
    expect(await screen.findByText('Interrupted run recovered; task held for review.')).toBeTruthy();
    expect(screen.getByText('Held for review')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Check and recover interrupted run' })).toBeNull();
  });

  it('keeps legacy and stale run records read only', async () => {
    vi.mocked(api.fetchTask).mockResolvedValue({ ...detail, task: { ...detail.task, status: 'running', current_run_id: 31, recoverable_run_id: 30,
      diagnostics: [{ kind: 'stale_worker', severity: 'warning', title: 'Worker stale', detail: 'No heartbeat', count: 1, last_seen_at: 100, data: {}, actions: [{ kind: 'reclaim', label: 'Reclaim worker' }] }],
    }, runs: [
      { id: 30, status: 'running', started_at: 100, ended_at: null },
      { id: 31, status: 'running', started_at: 200, ended_at: null },
    ] });
    render(<TaskDrawer {...props} />);
    expect(await screen.findByText(/Attempt 2.*Latest/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Check and recover interrupted run' })).toBeNull();
    expect((screen.getByRole('button', { name: 'Reclaim worker · unavailable' }) as HTMLButtonElement).disabled).toBe(true);
    expect(api.reclaimTask).not.toHaveBeenCalled();
  });

  it('does not claim a held task when the worker result was already saved', async () => {
    const running = { ...detail, task: { ...detail.task, status: 'running', current_run_id: 50, recoverable_run_id: 50 }, runs: [
      { id: 50, status: 'running', started_at: 100, ended_at: null },
    ] } satisfies KanbanTaskDetail;
    const done = { ...running, task: { ...running.task, status: 'done', current_run_id: null, recoverable_run_id: null }, runs: [
      { id: 50, status: 'done', outcome: 'completed', summary: 'Saved result', started_at: 100, ended_at: 200 },
    ] } satisfies KanbanTaskDetail;
    vi.mocked(api.fetchTask).mockResolvedValueOnce(running).mockResolvedValue(done);
    vi.mocked(api.reclaimTask).mockResolvedValue({ok:true, status:'board_effect_preserved'});
    render(<TaskDrawer {...props}/>);
    fireEvent.click(await screen.findByRole('button',{name:'Check and recover interrupted run'}));
    expect(await screen.findByText('Worker result was already saved; history refreshed.')).toBeTruthy();
    expect(screen.getByText('Saved result')).toBeTruthy();
    expect(screen.queryByText(/task held for review/i)).toBeNull();
  });
});
