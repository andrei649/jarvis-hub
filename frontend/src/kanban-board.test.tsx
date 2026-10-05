import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { KanbanView, errText } from './panels/kanban/KanbanView';
import { arcState } from './panels/kanban/board';
import type { KanbanBoard } from './panels/kanban/types';
import * as api from './panels/kanban/api';

vi.mock('./panels/kanban/api', () => ({
  fetchBoards: vi.fn(), fetchBoard: vi.fn(), fetchProjects: vi.fn(), fetchProfiles: vi.fn(), fetchOrchestration: vi.fn(),
  createKanbanSocket: vi.fn(), createTask: vi.fn(), patchTask: vi.fn(), bulkTasks: vi.fn(), deleteTask: vi.fn(),
  createBoard: vi.fn(), updateBoard: vi.fn(), deleteBoard: vi.fn(), dispatch: vi.fn(), fetchTask: vi.fn(), fetchLog: vi.fn(), addComment: vi.fn(), uploadAttachment: vi.fn(), downloadAttachment: vi.fn(),
}));
const board = (title: string, cursor = 4): KanbanBoard => ({ columns: [
  { name: 'triage', tasks: [{ id: 't_1', title, status: 'triage', priority: 2 }] },
  { name: 'ready', tasks: [] }, { name: 'running', tasks: [] }, { name: 'done', tasks: [] },
], assignees: [], tenants: [], latest_event_id: cursor, now: 1 });

beforeEach(() => {
  localStorage.clear();
  vi.mocked(api.fetchBoards).mockResolvedValue({ current: 'alpha', boards: [
    { slug: 'alpha', name: 'Alpha', project_id: null, default_workspace_kind: 'scratch' },
    { slug: 'beta', name: 'Beta', project_id: null, default_workspace_kind: 'scratch' },
  ] });
  vi.mocked(api.fetchBoard).mockImplementation(async (slug) => board(slug === 'beta' ? 'Beta card' : 'Alpha card'));
  vi.mocked(api.fetchProjects).mockResolvedValue({ projects: [{ id: 'p1', slug: 'repo', name: 'Repo', primary_path: '/repo' }] });
  vi.mocked(api.fetchProfiles).mockResolvedValue({ profiles: [] });
  vi.mocked(api.fetchOrchestration).mockRejectedValue(new Error('503 adapter unavailable'));
  vi.mocked(api.createKanbanSocket).mockReturnValue({ close: vi.fn(), socket: {} as WebSocket });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('Kanban board', () => {
  it('uses the donor heartbeat threshold and queued Triage state', () => {
    const now = Date.now() / 1000;
    expect(arcState({ id: 'a', title: 'A', status: 'running', last_heartbeat_at: now - 100 })).toBe('running');
    expect(arcState({ id: 'a', title: 'A', status: 'running', last_heartbeat_at: now - 130 })).toBe('stale');
    expect(arcState({ id: 'b', title: 'B', status: 'triage' })).toBe('queued');
  });

  it('renders structured validation refusals as text', () => {
    const refusal = Object.assign(new Error('PATCH -> 422'), { body: { detail: [{ msg: 'project is required' }] } });
    expect(errText(refusal)).toContain('project is required');
  });

  it('renders donor lanes and creates a triage card with explicit workspace and task fields', async () => {
    vi.mocked(api.createTask).mockResolvedValue({ task: { id: 't_2', title: 'Investigate', status: 'triage' } });
    render(<KanbanView />);
    expect(await screen.findByText('Alpha card')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /new task in triage/i }));
    const dialog = screen.getByRole('dialog', { name: /new task/i });
    fireEvent.change(within(dialog).getByLabelText('Title'), { target: { value: 'Investigate' } });
    fireEvent.change(within(dialog).getByLabelText('Description'), { target: { value: 'Fix case' } });
    fireEvent.change(within(dialog).getByLabelText('Priority'), { target: { value: '3' } });
    fireEvent.change(within(dialog).getByLabelText('Workspace'), { target: { value: 'dir' } });
    fireEvent.change(within(dialog).getByLabelText('Workspace override'), { target: { value: '/repo' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create task' }));
    await waitFor(() => expect(api.createTask).toHaveBeenCalledWith('alpha', expect.objectContaining({
      title: 'Investigate', body: 'Fix case', priority: 3, triage: true, workspace_kind: 'dir', workspace_path: '/repo',
    })));
  });

  it('switches board scope, closes old socket and ignores late old-board response', async () => {
    let resolveOld!: (value: KanbanBoard) => void;
    vi.mocked(api.fetchBoard).mockImplementation((slug) => slug === 'alpha' ? new Promise(resolve => { resolveOld = resolve; }) : Promise.resolve(board('Beta card', 17)));
    render(<KanbanView />);
    fireEvent.change(await screen.findByLabelText('Board'), { target: { value: 'beta' } });
    expect(await screen.findByText('Beta card')).toBeTruthy();
    resolveOld(board('Stale alpha'));
    await waitFor(() => expect(screen.queryByText('Stale alpha')).toBeNull());
    expect(api.createKanbanSocket).toHaveBeenCalledWith('beta', 17, expect.any(Function), expect.any(Function));
  });

  it('persists project selection only after successful board metadata PATCH', async () => {
    vi.mocked(api.updateBoard).mockResolvedValue({ board: { slug: 'alpha', name: 'Alpha', project_id: 'p1' } });
    render(<KanbanView />);
    await screen.findByText('Alpha card');
    fireEvent.click(screen.getByRole('button', { name: 'Board settings' }));
    fireEvent.change(screen.getByLabelText('Project'), { target: { value: 'p1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save board' }));
    await waitFor(() => expect(api.updateBoard).toHaveBeenCalledWith('alpha', expect.objectContaining({ project_id: 'p1' })));
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('shows unsupported orchestration controls and reports dispatch as queued only', async () => {
    vi.mocked(api.dispatch).mockResolvedValue({ ok: true, status: 'queued', queued: [{ task_id: 't_1', queue_id: 7, status: 'proposed' }] });
    render(<KanbanView />);
    await screen.findByText('Alpha card');
    fireEvent.click(screen.getByRole('button', { name: 'Orchestration' }));
    expect((screen.getByLabelText('Auto decompose') as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Request dispatch' }));
    expect((await screen.findByText(/1 signed request queued/)).textContent).toContain('queue 7');
    expect(screen.queryByText(/worker started/i)).toBeNull();
  });

  it('reports busy, empty, and refused dispatch outcomes without claiming a queue', async () => {
    const view = render(<KanbanView />);
    await screen.findByText('Alpha card');
    vi.mocked(api.dispatch).mockResolvedValueOnce({ ok: true, status: 'busy', queued: [] });
    fireEvent.click(screen.getByRole('button', { name: 'Request dispatch' }));
    expect(await screen.findByText(/Dispatch is busy; no new request was queued/)).toBeTruthy();
    vi.mocked(api.dispatch).mockResolvedValueOnce({ ok: true, status: 'queued', queued: [] });
    fireEvent.click(screen.getByRole('button', { name: 'Request dispatch' }));
    expect(await screen.findByText(/No eligible tasks were queued/)).toBeTruthy();
    vi.mocked(api.dispatch).mockResolvedValueOnce({ ok: false, status: 'refused', reason: 'owner_required', queued: [] });
    fireEvent.click(screen.getByRole('button', { name: 'Request dispatch' }));
    expect((await screen.findByRole('alert')).textContent).toContain('owner_required');
    view.unmount();
  });

  it('closes an old-board creation form on switch and ignores its late completion', async () => {
    let resolveCreate!: (value: {task: {id: string; title: string; status: string}}) => void;
    vi.mocked(api.createTask).mockImplementation(() => new Promise(resolve => { resolveCreate = resolve; }));
    render(<KanbanView />);
    await screen.findByText('Alpha card');
    fireEvent.click(screen.getByRole('button', { name: /new task in triage/i }));
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Old alpha task' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create task' }));
    fireEvent.change(screen.getByLabelText('Board'), { target: { value: 'beta' } });
    await waitFor(() => expect(within(screen.getByTestId('lane-triage')).getByText('Beta card')).toBeTruthy());
    expect(screen.queryByRole('dialog', { name: 'New task' })).toBeNull();
    resolveCreate({ task: { id: 't_old', title: 'Old alpha task', status: 'triage' } });
    await waitFor(() => expect(screen.queryByText('Alpha card')).toBeNull());
    expect(screen.getByText('Beta card')).toBeTruthy();
  });

  it('does not repaint a new board when an old-board mutation rejects late', async () => {
    let rejectOld!: (reason: Error) => void;
    vi.mocked(api.patchTask).mockImplementation(() => new Promise((_resolve, reject) => { rejectOld = reject; }));
    render(<KanbanView />);
    const card = await screen.findByText('Alpha card');
    const dataTransfer = { data: '', setData(_t: string, v: string) { this.data = v; }, getData() { return this.data; }, effectAllowed: '', dropEffect: '' };
    fireEvent.dragStart(card.closest('[draggable]')!, { dataTransfer });
    fireEvent.dragOver(screen.getByTestId('lane-ready'), { dataTransfer });
    fireEvent.drop(screen.getByTestId('lane-ready'), { dataTransfer });
    fireEvent.change(screen.getByLabelText('Board'), { target: { value: 'beta' } });
    expect(await screen.findByText('Beta card')).toBeTruthy();
    rejectOld(new Error('late alpha refusal'));
    await waitFor(() => expect(screen.queryByText('Alpha card')).toBeNull());
    expect(screen.queryByText('late alpha refusal')).toBeNull();
  });

  it('keeps only failed IDs selected after donor-style bulk delete', async () => {
    vi.mocked(api.fetchBoard).mockResolvedValue({ ...board('Alpha card'), columns: [
      { name: 'triage', tasks: [{id:'t_1', title:'Alpha card', status:'triage'}, {id:'t_2', title:'Second card', status:'triage'}] },
      {name:'ready',tasks:[]}, {name:'running',tasks:[]}, {name:'done',tasks:[]},
    ] });
    vi.mocked(api.deleteTask).mockImplementation(async (_slug, id) => { if (id === 't_2') throw new Error('protected'); return {deleted:true}; });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<KanbanView />);
    await screen.findByText('Second card');
    fireEvent.click(screen.getByText('Alpha card').closest('[draggable]')!, { metaKey: true });
    fireEvent.click(screen.getByText('Second card').closest('[draggable]')!, { metaKey: true });
    fireEvent.click(screen.getByRole('button', { name: 'Delete selected' }));
    await waitFor(() => expect(api.deleteTask).toHaveBeenCalledTimes(2));
    expect((await screen.findByRole('alert')).textContent).toContain('protected');
    expect(screen.getByRole('toolbar', { name: 'Selected tasks' }).textContent).toContain('1 selected');
  });

  it('rolls back a refused drag move and surfaces the server error', async () => {
    vi.mocked(api.patchTask).mockRejectedValue(new Error('workflow refused'));
    render(<KanbanView />);
    const card = await screen.findByText('Alpha card');
    const dataTransfer = { data: '', setData(_t: string, v: string) { this.data = v; }, getData() { return this.data; }, effectAllowed: '', dropEffect: '' };
    fireEvent.dragStart(card.closest('[draggable]')!, { dataTransfer });
    fireEvent.dragOver(screen.getByTestId('lane-ready'), { dataTransfer });
    fireEvent.drop(screen.getByTestId('lane-ready'), { dataTransfer });
    expect((await screen.findByRole('alert')).textContent).toContain('workflow refused');
    expect(within(screen.getByTestId('lane-triage')).getByText('Alpha card')).toBeTruthy();
  });
});
