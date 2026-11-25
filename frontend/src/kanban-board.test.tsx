import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { KanbanView, errText } from './panels/kanban/KanbanView';
import { arcState } from './panels/kanban/board';
import type { KanbanBoard } from './panels/kanban/types';
import * as api from './panels/kanban/api';

vi.mock('./panels/kanban/api', () => ({
  fetchBoards: vi.fn(), fetchBoard: vi.fn(), fetchProjects: vi.fn(), fetchProfiles: vi.fn(), fetchAssignees: vi.fn(), fetchOrchestration: vi.fn(),
  createKanbanSocket: vi.fn(), createTask: vi.fn(), patchTask: vi.fn(), bulkTasks: vi.fn(), deleteTask: vi.fn(),
  createBoard: vi.fn(), updateBoard: vi.fn(), deleteBoard: vi.fn(), dispatch: vi.fn(), fetchTask: vi.fn(), fetchLog: vi.fn(), addComment: vi.fn(), uploadAttachment: vi.fn(), downloadAttachment: vi.fn(), fetchActiveWorkers: vi.fn(), reassignTask: vi.fn(), updateProfileDescription: vi.fn(),
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
  vi.mocked(api.fetchAssignees).mockResolvedValue({ assignees: [] });
  vi.mocked(api.fetchOrchestration).mockRejectedValue(new Error('503 adapter unavailable'));
  vi.mocked(api.fetchActiveWorkers).mockResolvedValue({ workers: [], count: 0, checked_at: 1 });
  vi.mocked(api.createKanbanSocket).mockReturnValue({ close: vi.fn(), socket: {} as WebSocket });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('Kanban board', () => {
  it('assigns native registered profiles on new and existing tasks without offering unsupported profile edits', async () => {
    vi.mocked(api.fetchProfiles).mockResolvedValue({ profiles: [
      { name: 'frigga', is_default: true, description: '', description_auto: false },
      { name: 'ultron', is_default: false, description: 'Review code', description_auto: false },
    ], editable: false });
    vi.mocked(api.fetchAssignees).mockResolvedValue({ assignees: [{ name: 'former-worker', on_disk: false, counts: {} }] });
    vi.mocked(api.fetchTask).mockResolvedValue({ task: { id: 't_1', title: 'Alpha card', status: 'triage', assignee: 'former-worker' }, comments: [], events: [], attachments: [], links: { parents: [], children: [] }, runs: [] });
    vi.mocked(api.createTask).mockResolvedValue({ task: { id: 't_2', title: 'Native task', status: 'triage' } });
    vi.mocked(api.reassignTask).mockResolvedValue({ ok: true, task_id: 't_1', assignee: 'ultron' });
    render(<KanbanView />);
    await screen.findByText('Alpha card');
    fireEvent.click(screen.getByRole('button', { name: 'Orchestration' }));
    expect(await screen.findByText('Registered profiles')).toBeTruthy();
    expect(screen.getByText('Review code')).toBeTruthy();
    expect(screen.queryByLabelText('Profile description ultron')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Auto-describe ultron' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /new task in triage/i }));
    const dialog = screen.getByRole('dialog', { name: 'New task' });
    expect(within(dialog).getByRole('option', { name: 'former-worker' })).toBeTruthy();
    expect(within(dialog).getByRole('option', { name: 'Unassigned' })).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText('Title'), { target: { value: 'Native task' } });
    fireEvent.change(within(dialog).getByLabelText('Assignee'), { target: { value: 'ultron' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create task' }));
    await waitFor(() => expect(api.createTask).toHaveBeenCalledWith('alpha', expect.objectContaining({ assignee: 'ultron' })));
    fireEvent.click(screen.getByText('Alpha card'));
    const assign = await screen.findByLabelText('Assign profile');
    expect(within(assign).getByRole('option', { name: 'former-worker' })).toBeTruthy();
    vi.mocked(api.reassignTask).mockRejectedValueOnce(new Error('Task is already claimed'));
    fireEvent.change(assign, { target: { value: 'ultron' } });
    await screen.findByText('Task is already claimed');
    expect((assign as HTMLSelectElement).value).toBe('former-worker');
    fireEvent.change(assign, { target: { value: 'ultron' } });
    await waitFor(() => expect(api.reassignTask).toHaveBeenCalledTimes(2));
    expect(api.reassignTask).toHaveBeenLastCalledWith('alpha', 't_1', { profile: 'ultron' });
  });

  it('keeps legacy profile description controls when editable is omitted', async () => {
    vi.mocked(api.fetchProfiles).mockResolvedValue({ profiles: [{ name: 'frigga', is_default: true, description: 'Build', description_auto: false }] });
    render(<KanbanView />);
    await screen.findByText('Alpha card');
    fireEvent.click(screen.getByRole('button', { name: 'Orchestration' }));
    expect(await screen.findByLabelText('Profile description frigga')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Auto-describe frigga' })).toBeTruthy();
  });

  it('reports profile load refusal separately from orchestration while retaining task-only assignees', async () => {
    vi.mocked(api.fetchProfiles).mockRejectedValue(new Error('native roster offline'));
    vi.mocked(api.fetchAssignees).mockResolvedValue({ assignees: [{ name: 'former-worker', on_disk: false, counts: {} }] });
    render(<KanbanView />);
    await screen.findByText('Alpha card');
    expect(await screen.findByText(/Agent profiles unavailable: native roster offline/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /new task in triage/i }));
    expect(within(screen.getByRole('dialog', { name: 'New task' })).getByRole('option', { name: 'former-worker' })).toBeTruthy();
  });

  it('offers assignees already on the board when the separate assignee list is unavailable', async () => {
    vi.mocked(api.fetchBoard).mockResolvedValue({ ...board('Alpha card'), assignees: ['task-only'] });
    vi.mocked(api.fetchAssignees).mockRejectedValue(new Error('assignee endpoint unavailable'));
    render(<KanbanView />);
    await screen.findByText('Alpha card');
    fireEvent.click(screen.getByRole('button', { name: /new task in triage/i }));
    expect(within(screen.getByRole('dialog', { name: 'New task' })).getByRole('option', { name: 'task-only' })).toBeTruthy();
  });

  it('ignores an older profile response after a newer roster refresh', async () => {
    let resolveOld!: (value: Awaited<ReturnType<typeof api.fetchProfiles>>) => void;
    vi.mocked(api.fetchProfiles)
      .mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }))
      .mockResolvedValue({ profiles: [{ name: 'ultron', is_default: false, description: '', description_auto: false }], editable: false });
    vi.mocked(api.updateProfileDescription).mockResolvedValue({ ok: true });
    render(<KanbanView />);
    await screen.findByText('Alpha card');
    fireEvent.click(screen.getByRole('button', { name: 'Orchestration' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save profile default' }));
    expect(await screen.findByText('Registered profiles')).toBeTruthy();
    resolveOld({ profiles: [{ name: 'legacy', is_default: true, description: '', description_auto: false }] });
    await waitFor(() => expect(screen.queryByLabelText('Profile description legacy')).toBeNull());
    expect(screen.getByText('ultron')).toBeTruthy();
  });
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

  it('shows two claimed agents directly on the board and clears them when both tasks finish', async () => {
    let done = false;
    vi.mocked(api.fetchBoard).mockImplementation(async () => ({ ...board('Alpha card'), columns: [
      { name: 'triage', tasks: [] }, { name: 'running', tasks: done ? [] : [
        { id: 't_a', title: 'Build API', status: 'running', current_run_id: 11 },
        { id: 't_b', title: 'Check UI', status: 'running', current_run_id: 12 },
      ] }, { name: 'done', tasks: done ? [
        { id: 't_a', title: 'Build API', status: 'done', latest_summary: 'API ready' },
        { id: 't_b', title: 'Check UI', status: 'done', latest_summary: 'UI verified' },
      ] : [] },
    ] }));
    vi.mocked(api.fetchActiveWorkers).mockImplementation(async () => done
      ? { workers: [], count: 0, checked_at: 2 }
      : { workers: [
        { run_id: 11, task_id: 't_a', task_title: 'Build API', task_status: 'running', profile: 'agent-a' },
        { run_id: 12, task_id: 't_b', task_title: 'Check UI', task_status: 'running', profile: 'agent-b' },
      ], count: 2, checked_at: 1 });
    render(<KanbanView />);
    const workers = await screen.findByRole('region', { name: 'Active workers' });
    await waitFor(() => expect(within(workers).getByText('agent-a')).toBeTruthy());
    expect(within(workers).getByText('agent-b')).toBeTruthy();
    expect(within(workers).getByRole('button', { name: 'Build API' })).toBeTruthy();
    expect(workers.textContent).not.toContain('pid');
    done = true;
    const socketCalls = vi.mocked(api.createKanbanSocket).mock.calls;
    const frame = socketCalls[socketCalls.length - 1]?.[2];
    frame?.({ cursor: 5, events: [{ id: 5, task_id: 't_a' }] });
    await waitFor(() => expect(within(workers).getByText('No active running workers')).toBeTruthy());
    expect(within(workers).queryByText('agent-a')).toBeNull();
    expect(screen.getByText('API ready')).toBeTruthy();
    expect(screen.getByText('UI verified')).toBeTruthy();
  });

  it('shows each finished worker output on its own card as concurrent workers finish separately', async () => {
    let phase = 0;
    const longResult = `Agent A delivered ${'proof '.repeat(50)}`;
    vi.mocked(api.fetchBoard).mockImplementation(async () => ({ ...board('Alpha card'), columns: [
      { name: 'running', tasks: [
        ...(phase === 0 ? [{ id: 't_a', title: 'Same title', status: 'running', assignee: 'agent-a', body: 'A instructions', current_run_id: 11 }] : []),
        ...(phase < 2 ? [{ id: 't_b', title: 'Same title', status: 'running', assignee: 'agent-b', body: 'B instructions', current_run_id: 12 }] : []),
      ] },
      { name: 'done', tasks: [
        ...(phase > 0 ? [{ id: 't_a', title: 'Same title', status: 'done', assignee: 'agent-a', body: 'A instructions', result: longResult, latest_summary: 'A summary' }] : []),
        ...(phase > 1 ? [{ id: 't_b', title: 'Same title', status: 'done', assignee: 'agent-b', body: 'B instructions', latest_summary: 'B summary' }] : []),
        { id: 't_empty', title: 'No output', status: 'done', assignee: 'agent-c', body: 'C instructions' },
      ] },
    ] }));
    vi.mocked(api.fetchActiveWorkers).mockImplementation(async () => ({ workers: [
      ...(phase === 0 ? [{ run_id: 11, task_id: 't_a', task_title: 'Same title', task_status: 'running', profile: 'agent-a' }] : []),
      ...(phase < 2 ? [{ run_id: 12, task_id: 't_b', task_title: 'Same title', task_status: 'running', profile: 'agent-b' }] : []),
    ], count: phase === 0 ? 2 : phase === 1 ? 1 : 0, checked_at: phase + 1 }));
    render(<KanbanView />);
    expect((await screen.findByTestId('lane-running')).textContent).toContain('A instructions');
    expect(screen.getByTestId('lane-running').textContent).toContain('B instructions');
    const done = await screen.findByTestId('lane-done');
    expect(within(done).getByText('No result recorded')).toBeTruthy();
    expect(within(done).queryByText('C instructions')).toBeNull();
    phase = 1;
    const socketCalls = vi.mocked(api.createKanbanSocket).mock.calls;
    const frame = socketCalls[socketCalls.length - 1]?.[2];
    frame?.({ cursor: 5, events: [{ id: 5, task_id: 't_a' }] });
    await waitFor(() => expect(within(done).getAllByText('Same title')).toHaveLength(1));
    const a = within(done).getByText('Same title').closest('article')!;
    expect(a.textContent).toContain('agent-a');
    expect(a.textContent).toContain('Result');
    expect(a.textContent).toContain('Agent A delivered');
    expect(a.textContent).not.toContain('A summary');
    expect(a.textContent).not.toContain('A instructions');
    expect(a.querySelector('.kb-card-summary')?.textContent?.length).toBeLessThanOrEqual(201);
    phase = 2;
    frame?.({ cursor: 6, events: [{ id: 6, task_id: 't_b' }] });
    await waitFor(() => expect(within(done).getAllByText('Same title')).toHaveLength(2));
    const cards = within(done).getAllByText('Same title').map(title => title.closest('article')!);
    const b = cards.find(card => card.textContent?.includes('agent-b'))!;
    expect(b.textContent).toContain('Latest summary');
    expect(b.textContent).toContain('B summary');
    expect(b.textContent).not.toContain('B instructions');
    expect(a.textContent).toContain('Agent A delivered');
  });

  it('ignores an older worker response and clears active rows on the latest refusal', async () => {
    let releaseOld!: (value: any) => void;
    let workerCalls = 0;
    vi.mocked(api.fetchActiveWorkers).mockImplementation(() => {
      workerCalls++;
      if (workerCalls === 1) return new Promise(resolve => { releaseOld = resolve; });
      return Promise.reject(new Error('workers unavailable'));
    });
    render(<KanbanView />);
    await screen.findByText('Alpha card');
    const workers = screen.getByRole('region', { name: 'Active workers' });
    expect(within(workers).getByText('Loading active workers…')).toBeTruthy();
    const socketCalls = vi.mocked(api.createKanbanSocket).mock.calls;
    const frame = socketCalls[socketCalls.length - 1]?.[2];
    frame?.({ cursor: 6, events: [{ id: 6, task_id: 't_1' }] });
    await waitFor(() => expect(within(workers).getByText('Active workers unavailable.')).toBeTruthy());
    releaseOld({ workers: [{ run_id: 99, task_id: 't_1', task_title: 'Old worker', task_status: 'running', profile: 'stale-agent' }], count: 1, checked_at: 1 });
    await waitFor(() => expect(within(workers).queryByText('stale-agent')).toBeNull());
  });

  it('keeps claimed workers visible during a same-board refresh, then clears them on refusal', async () => {
    let rejectRefresh!: (reason: Error) => void;
    let workerCalls = 0;
    vi.mocked(api.fetchActiveWorkers).mockImplementation(() => ++workerCalls === 1
      ? Promise.resolve({ workers: [{ run_id: 11, task_id: 't_1', task_title: 'Alpha card', task_status: 'running', profile: 'agent-a' }], count: 1, checked_at: 1 })
      : new Promise((_, reject) => { rejectRefresh = reject; }));
    vi.mocked(api.fetchBoard).mockResolvedValue({ ...board('Alpha card'), columns: [
      { name: 'running', tasks: [{ id: 't_1', title: 'Alpha card', status: 'running', current_run_id: 11 }] },
    ] });
    render(<KanbanView />);
    const workers = await screen.findByRole('region', { name: 'Active workers' });
    await waitFor(() => expect(within(workers).getByText('agent-a')).toBeTruthy());
    const socketCalls = vi.mocked(api.createKanbanSocket).mock.calls;
    socketCalls[socketCalls.length - 1]?.[2]({ cursor: 6, events: [{ id: 6, task_id: 't_1' }] });
    await waitFor(() => expect(api.fetchActiveWorkers).toHaveBeenCalledTimes(2));
    expect(within(workers).getByText('agent-a')).toBeTruthy();
    rejectRefresh(new Error('unavailable'));
    await waitFor(() => expect(within(workers).getByText('Active workers unavailable.')).toBeTruthy());
    expect(within(workers).queryByText('agent-a')).toBeNull();
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

  it('shows unsupported orchestration controls and preserves returned queue item status and IDs', async () => {
    vi.mocked(api.dispatch).mockResolvedValue({ ok: true, status: 'queued', queued: [
      { task_id: 't_1', queue_id: 7, status: 'proposed' },
      { task_id: 't_2', queue_id: 8, status: 'running' },
    ] });
    render(<KanbanView />);
    await screen.findByText('Alpha card');
    fireEvent.click(screen.getByRole('button', { name: 'Orchestration' }));
    expect((screen.getByLabelText('Auto decompose') as HTMLInputElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Request dispatch' }));
    const notice = (await screen.findByText(/2 signed queue items returned/)).textContent;
    expect(notice).toContain('card t_1 · queue 7 (proposed)');
    expect(notice).toContain('card t_2 · queue 8 (running)');
    expect(notice).toContain('Approved or running items may have advanced earlier');
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
    expect(await screen.findByText(/No queue items returned/)).toBeTruthy();
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
