import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { KanbanView } from './KanbanView';
import { TaskDrawer } from './drawer';
import { clearActionFailures } from '../../api/client';
import type { KanbanBoard, KanbanTaskDetail } from './types';

class FakeSocket {
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(public url: string, public protocols: string[]) {}
  close() {}
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const sampleBoard: KanbanBoard = {
  columns: [
    { name: 'triage', tasks: [{ id: 't_parent', title: 'Parent spec', status: 'triage' }] },
    { name: 'todo', tasks: [] },
    { name: 'ready', tasks: [] },
    { name: 'running', tasks: [{ id: 't_run', title: 'Running job', status: 'running', assignee: 'coder', current_run_started_at: 1000 }] },
    { name: 'blocked', tasks: [] },
    { name: 'review', tasks: [] },
    { name: 'done', tasks: [] },
  ],
  assignees: ['coder'],
  tenants: [],
  latest_event_id: 9,
  now: 1000,
};

describe('Kanban advanced HUD controls (all 23 routes)', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('nerva.kanban.board', 'alpha');
    clearActionFailures();
    vi.stubGlobal('WebSocket', FakeSocket);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it('wires board telemetry, active workers, diagnostics filter, board switch, and honest 503 export/import refusals', async () => {
    const calls: Array<{ method: string; url: string; body?: unknown }> = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method || 'GET';
      const body = typeof init?.body === 'string' && init.body ? JSON.parse(init.body) : undefined;
      calls.push({ method, url, body });

      if (method === 'GET' && url === '/api/kanban/boards') {
        return jsonResponse({
          boards: [
            { slug: 'alpha', name: 'Alpha', total: 2 },
            { slug: 'beta', name: 'Beta', total: 0 },
          ],
          current: 'alpha',
        });
      }
      if (method === 'GET' && url === '/api/kanban/projects') return jsonResponse({ projects: [] });
      if (method === 'GET' && url === '/api/kanban/profiles') return jsonResponse({ profiles: [{ name: 'coder', description: 'Code worker' }] });
      if (method === 'GET' && url === '/api/kanban/orchestration') {
        return jsonResponse({
          orchestrator_profile: 'coder',
          resolved_orchestrator_profile: 'coder',
          default_assignee: 'coder',
          resolved_default_assignee: 'coder',
          auto_decompose: false,
        });
      }
      if (method === 'GET' && url === '/api/kanban/config') {
        return jsonResponse({ detail: 'Kanban config requires a Nerva adapter' }, 503);
      }
      if (method === 'GET' && url === '/api/kanban/model-options') {
        return jsonResponse({ detail: 'model options requires a Nerva adapter' }, 503);
      }
      if (method === 'GET' && url.startsWith('/api/kanban/board?')) {
        return jsonResponse(sampleBoard);
      }
      if (method === 'GET' && url.startsWith('/api/kanban/assignees?')) {
        return jsonResponse({ assignees: [{ name: 'researcher', task_count: 2 }] });
      }
      if (method === 'GET' && url.startsWith('/api/kanban/stats?')) {
        return jsonResponse({ by_status: { triage: 1, running: 1 }, oldest_ready_age_seconds: 42 });
      }
      if (method === 'GET' && url.startsWith('/api/kanban/workers/active?')) {
        return jsonResponse({
          workers: [{ run_id: 11, task_id: 't_run', task_title: 'Running job', profile: 'coder', worker_pid: 9021 }],
          count: 1,
        });
      }
      if (method === 'GET' && url === '/api/kanban/diagnostics?board=alpha&severity=error') {
        return jsonResponse({ diagnostics: [], count: 0 });
      }
      if (method === 'GET' && url.startsWith('/api/kanban/diagnostics?')) {
        return jsonResponse({
          diagnostics: [{
            task_id: 't_run',
            task_title: 'Running job',
            status: 'running',
            diagnostics: [{ kind: 'stale_heartbeat', severity: 'warning', title: 'Heartbeat stale', detail: 'No ping', actions: [] }],
          }],
          count: 1,
        });
      }
      if (method === 'POST' && url === '/api/kanban/boards/beta/switch') {
        return jsonResponse({ ok: true, current: 'beta' });
      }
      if (method === 'POST' && url.endsWith('/export')) {
        return jsonResponse({ detail: 'board export requires a Nerva adapter' }, 503);
      }
      if (method === 'POST' && url === '/api/kanban/boards/import') {
        return jsonResponse({ detail: 'board import requires a Nerva adapter' }, 503);
      }
      return jsonResponse({ detail: `unhandled ${method} ${url}` }, 500);
    }));

    render(<KanbanView />);
    await screen.findByRole('button', { name: 'Running job' });

    // Mount-time 503s on /config and /model-options do not trigger a false top-level alert.
    expect(screen.queryByRole('alert')).toBeNull();
    expect(calls.some(c => c.method === 'GET' && c.url === '/api/kanban/config')).toBe(true);
    expect(calls.some(c => c.method === 'GET' && c.url === '/api/kanban/model-options')).toBe(true);
    expect(calls.some(c => c.method === 'GET' && c.url === '/api/kanban/assignees?board=alpha')).toBe(true);

    // Claimed worker is visible without opening diagnostics; the panel retains stats and filtering.
    const workers = await screen.findByRole('region', { name: 'Active workers' });
    expect(within(workers).getByText('coder')).toBeTruthy();
    expect(within(workers).getByRole('button', { name: 'Running job' })).toBeTruthy();
    expect(workers.textContent).not.toContain('pid');
    await waitFor(() => expect(screen.getByRole('button', { name: /Stats & diagnostics · ⚠ 1/ })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /Stats & diagnostics/ }));
    const opsPanel = screen.getByLabelText('Stats and diagnostics');
    expect(within(opsPanel).getByText('triage: 1')).toBeTruthy();
    expect(within(opsPanel).getByText('Oldest ready wait: 42s')).toBeTruthy();
    expect(within(opsPanel).queryByText('coder')).toBeNull();
    expect(within(opsPanel).getByText(/warning: Heartbeat stale/)).toBeTruthy();

    fireEvent.change(within(opsPanel).getByLabelText('Diagnostic severity'), { target: { value: 'error' } });
    await waitFor(() => expect(calls.some(c => c.method === 'GET' && c.url === '/api/kanban/diagnostics?board=alpha&severity=error')).toBe(true));
    expect(await within(opsPanel).findByText('No active diagnostics')).toBeTruthy();

    // Export board surfaces 503 refusal honestly without closing dialog or claiming export succeeded.
    fireEvent.click(screen.getByRole('button', { name: 'More board actions' }));
    fireEvent.click(screen.getByRole('button', { name: 'Export board' }));
    const exportDialog = screen.getByRole('dialog', { name: 'Export board' });
    fireEvent.click(within(exportDialog).getByRole('button', { name: 'Export archive' }));
    await waitFor(() => expect(within(exportDialog).getByRole('alert').textContent).toContain('board export requires a Nerva adapter'));
    expect(calls.some(c => c.method === 'POST' && c.url === '/api/kanban/boards/alpha/export')).toBe(true);
    fireEvent.click(within(exportDialog).getByRole('button', { name: 'Cancel' }));

    // Import board surfaces 503 refusal honestly without closing dialog or claiming import succeeded.
    fireEvent.click(screen.getByRole('button', { name: 'More board actions' }));
    fireEvent.click(screen.getByRole('button', { name: 'Import board' }));
    const importDialog = screen.getByRole('dialog', { name: 'Import board' });
    fireEvent.change(within(importDialog).getByLabelText('Archive path'), { target: { value: '/tmp/alpha.tar.gz' } });
    fireEvent.click(within(importDialog).getByRole('button', { name: 'Import archive' }));
    await waitFor(() => expect(within(importDialog).getByRole('alert').textContent).toContain('board import requires a Nerva adapter'));
    expect(calls.find(c => c.method === 'POST' && c.url === '/api/kanban/boards/import')?.body).toEqual({
      archive: '/tmp/alpha.tar.gz',
      switch: false,
    });
    fireEvent.click(within(importDialog).getByRole('button', { name: 'Cancel' }));

    // Switching board calls POST /api/kanban/boards/{slug}/switch.
    fireEvent.change(screen.getByLabelText('Board'), { target: { value: 'beta' } });
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url === '/api/kanban/boards/beta/switch')).toBe(true));
  });

  it('wires profile description updates, auto-describe, and draft effort estimation with honest 503 refusals', async () => {
    let estimateMode: '503' | '200' = '503';
    const calls: Array<{ method: string; url: string; body?: unknown }> = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method || 'GET';
      const body = typeof init?.body === 'string' && init.body ? JSON.parse(init.body) : undefined;
      calls.push({ method, url, body });

      if (method === 'GET' && url === '/api/kanban/boards') return jsonResponse({ boards: [{ slug: 'alpha', name: 'Alpha' }], current: 'alpha' });
      if (method === 'GET' && url === '/api/kanban/projects') return jsonResponse({ projects: [] });
      if (method === 'GET' && url === '/api/kanban/profiles') return jsonResponse({ profiles: [{ name: 'researcher', description: 'Initial notes' }] });
      if (method === 'GET' && url === '/api/kanban/orchestration') return jsonResponse({ auto_decompose: false, resolved_default_assignee: 'researcher' });
      if (method === 'GET' && url === '/api/kanban/config') return jsonResponse({ detail: 'Kanban config requires a Nerva adapter' }, 503);
      if (method === 'GET' && url === '/api/kanban/model-options') return jsonResponse({ detail: 'model options requires a Nerva adapter' }, 503);
      if (method === 'GET' && url.startsWith('/api/kanban/board?')) return jsonResponse(sampleBoard);
      if (method === 'GET' && url.startsWith('/api/kanban/assignees?')) return jsonResponse({ assignees: [] });
      if (method === 'GET' && url.startsWith('/api/kanban/stats?')) return jsonResponse({ by_status: {}, oldest_ready_age_seconds: null });
      if (method === 'GET' && url.startsWith('/api/kanban/workers/active?')) return jsonResponse({ workers: [], count: 0 });
      if (method === 'GET' && url.startsWith('/api/kanban/diagnostics?')) return jsonResponse({ diagnostics: [], count: 0 });
      if (method === 'PATCH' && url === '/api/kanban/profiles/researcher') {
        return jsonResponse({ detail: 'profile updates require a Nerva adapter' }, 503);
      }
      if (method === 'POST' && url === '/api/kanban/profiles/researcher/describe-auto') {
        return jsonResponse({ detail: 'auto profile description requires a Nerva adapter' }, 503);
      }
      if (method === 'POST' && url === '/api/kanban/estimate') {
        if (estimateMode === '503') return jsonResponse({ detail: 'draft estimation requires a Nerva adapter' }, 503);
        return jsonResponse({ ok: true, complexity: 'medium', est_tokens: 1800, rationale: 'UI and parity tests' });
      }
      return jsonResponse({ detail: `unhandled ${method} ${url}` }, 500);
    }));

    render(<KanbanView />);
    await screen.findByText('Running job');

    // Orchestration panel shows config 503 note, keeps Auto decompose disabled, and surfaces profile 503s.
    fireEvent.click(screen.getByRole('button', { name: 'Orchestration' }));
    const orch = screen.getByLabelText('Orchestration settings');
    expect((within(orch).getByLabelText('Auto decompose') as HTMLInputElement).disabled).toBe(true);
    expect(within(orch).getByText(/Runtime config: Kanban config requires a Nerva adapter/)).toBeTruthy();

    fireEvent.change(within(orch).getByLabelText('Profile description researcher'), { target: { value: 'Deep web specialist' } });
    fireEvent.click(within(orch).getByRole('button', { name: 'Save profile researcher' }));
    await waitFor(() => expect(within(orch).getByRole('alert').textContent).toContain('profile updates require a Nerva adapter'));
    expect(calls.find(c => c.method === 'PATCH' && c.url === '/api/kanban/profiles/researcher')?.body).toEqual({
      description: 'Deep web specialist',
    });

    fireEvent.click(within(orch).getByRole('button', { name: 'Auto-describe researcher' }));
    await waitFor(() => expect(within(orch).getByRole('alert').textContent).toContain('auto profile description requires a Nerva adapter'));
    expect(calls.find(c => c.method === 'POST' && c.url === '/api/kanban/profiles/researcher/describe-auto')?.body).toEqual({
      overwrite: true,
    });

    // Draft effort estimation in NewTaskDialog: 503 refusal first, then 200 estimate rendering.
    fireEvent.click(screen.getByRole('button', { name: 'New task' }));
    const createDialog = screen.getByRole('dialog', { name: 'New task' });
    fireEvent.change(within(createDialog).getByLabelText('Title'), { target: { value: 'Ship parity' } });
    fireEvent.change(within(createDialog).getByLabelText('Description'), { target: { value: 'Wire all controls' } });
    fireEvent.click(within(createDialog).getByRole('button', { name: 'Estimate effort' }));
    await waitFor(() => expect(within(createDialog).getByRole('alert').textContent).toContain('draft estimation requires a Nerva adapter'));
    expect(calls.find(c => c.method === 'POST' && c.url === '/api/kanban/estimate')?.body).toEqual({
      title: 'Ship parity',
      body: 'Wire all controls',
    });

    estimateMode = '200';
    fireEvent.click(within(createDialog).getByRole('button', { name: 'Estimate effort' }));
    expect(await within(createDialog).findByText(/medium · 1800 tok — UI and parity tests/)).toBeTruthy();
  });

  it('wires drawer dependency links, durable run details, reassign, and available worker controls', async () => {
    let reassignMode: '409' | '200' = '409';
    const calls: Array<{ method: string; url: string; body?: unknown }> = [];
    const runningDetail: KanbanTaskDetail = {
      task: {
        id: 't_run',
        title: 'Running job',
        status: 'running',
        assignee: 'coder',
        worker_pid: 9021,
      },
      comments: [],
      events: [],
      attachments: [],
      links: { parents: ['t_parent'], children: [] },
      link_tasks: [{ id: 't_parent', title: 'Parent spec', status: 'triage' }],
      runs: [{ id: 11, profile: 'coder', status: 'running', summary: 'Executing slice' }],
    };

    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method || 'GET';
      const body = typeof init?.body === 'string' && init.body ? JSON.parse(init.body) : undefined;
      calls.push({ method, url, body });

      if (method === 'GET' && url === '/api/kanban/tasks/t_run?board=alpha') return jsonResponse(runningDetail);
      if (method === 'GET' && url === '/api/kanban/home-channels?board=alpha&task_id=t_run') {
        return jsonResponse({ detail: 'home channels requires a Nerva adapter' }, 503);
      }
      if (method === 'POST' && url === '/api/kanban/links?board=alpha') {
        return jsonResponse({ ok: true, gated: false });
      }
      if (method === 'DELETE' && url === '/api/kanban/links?parent_id=t_parent&child_id=t_run&board=alpha') {
        return jsonResponse({ ok: true });
      }
      if (method === 'POST' && url === '/api/kanban/tasks/t_run/reassign?board=alpha') {
        if (reassignMode === '409') {
          return jsonResponse({ detail: 'Task is actively running; pass reclaim_first=true' }, 409);
        }
        return jsonResponse({ ok: true, task_id: 't_run', assignee: 'researcher' });
      }
      if (method === 'GET' && url === '/api/kanban/runs/11?board=alpha') {
        return jsonResponse({ run: { id: 11, profile: 'coder', status: 'running', worker_pid: 9021, started_at: 1000 } });
      }
      if (method === 'POST' && url === '/api/kanban/tasks/t_run/home-subscribe/telegram?board=alpha') {
        return jsonResponse({ detail: 'channel subscription requires a Nerva adapter' }, 503);
      }
      if (method === 'DELETE' && url === '/api/kanban/tasks/t_run/home-subscribe/telegram?board=alpha') {
        return jsonResponse({ detail: 'channel unsubscribe requires a Nerva adapter' }, 503);
      }
      if (method === 'GET' && url === '/api/kanban/model-options') {
        return jsonResponse({ detail: 'model options requires a Nerva adapter' }, 503);
      }
      if (method === 'POST' && url === '/api/kanban/tasks/t_run/estimate?board=alpha') {
        return jsonResponse({ detail: 'task estimate requires a Nerva adapter' }, 503);
      }
      if (method === 'POST' && url === '/api/kanban/tasks/t_run/specify?board=alpha') {
        return jsonResponse({ detail: 'task specification requires a Nerva adapter' }, 503);
      }
      if (method === 'POST' && url === '/api/kanban/tasks/t_run/decompose?board=alpha') {
        return jsonResponse({ detail: 'task decomposition requires a Nerva adapter' }, 503);
      }
      return jsonResponse({ detail: `unhandled ${method} ${url}` }, 500);
    }));

    const onChanged = vi.fn();
    render(
      <TaskDrawer
        slug="alpha"
        id="t_run"
        columns={['triage', 'ready', 'running', 'done']}
        profiles={[
          { name: 'coder', is_default: true, description: '', description_auto: false },
          { name: 'researcher', is_default: false, description: '', description_auto: false },
        ]}
        knownAssignees={[{ name: 'reviewer', on_disk: false, counts: { triage: 1 } }]}
        allTasks={[
          { id: 't_run', title: 'Running job', status: 'running' },
          { id: 't_child', title: 'Child task', status: 'triage' },
        ]}
        onOpen={vi.fn()}
        onClose={vi.fn()}
        onChanged={onChanged}
      />,
    );

    const dialog = await screen.findByRole('dialog', { name: 'Task details' });
    await waitFor(() => expect(within(dialog).getByText('home channels requires a Nerva adapter')).toBeTruthy());

    // Add dependency link (POST /api/kanban/links) & remove dependency link (DELETE /api/kanban/links)
    fireEvent.change(within(dialog).getByLabelText('Dependency direction'), { target: { value: 'child' } });
    fireEvent.change(within(dialog).getByLabelText('Linked task ID'), { target: { value: 't_child' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add link' }));
    await waitFor(() => expect(calls.find(c => c.method === 'POST' && c.url === '/api/kanban/links?board=alpha')?.body).toEqual({
      parent_id: 't_run',
      child_id: 't_child',
    }));

    fireEvent.click(within(dialog).getByRole('button', { name: 'Unlink t_parent' }));
    await waitFor(() => expect(calls.some(c => c.method === 'DELETE' && c.url === '/api/kanban/links?parent_id=t_parent&child_id=t_run&board=alpha')).toBe(true));

    // Reassign: a running task refuses until the server permits reassignment.
    fireEvent.change(within(dialog).getByLabelText('Assign profile'), { target: { value: 'researcher' } });
    await waitFor(() => expect(within(dialog).getByRole('alert').textContent).toContain('Task is actively running; pass reclaim_first=true'));
    expect(within(dialog).queryByText(/Reassigned to/)).toBeNull();

    reassignMode = '200';
    fireEvent.change(within(dialog).getByLabelText('Worker action reason'), { target: { value: 'handoff' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Reassign' }));
    await waitFor(() => expect(within(dialog).getByRole('status').textContent).toContain('Reassigned to researcher.'));
    expect(calls.filter(c => c.method === 'POST' && c.url === '/api/kanban/tasks/t_run/reassign?board=alpha').pop()?.body).toEqual({
      profile: 'researcher',
      reason: 'handoff',
    });

    // The persisted run is readable; this legacy row has no native recovery marker.
    fireEvent.click(within(dialog).getByRole('tab', { name: 'Worker history' }));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Run details' }));
    const runDetail = await within(dialog).findByLabelText('Run 11 details');
    expect(runDetail.textContent).toContain('Run #11');
    expect(runDetail.textContent).toContain('pid 9021');

    expect(within(dialog).queryByRole('button', { name: 'Inspect process' })).toBeNull();
    expect(within(dialog).queryByRole('button', { name: 'Terminate run' })).toBeNull();
    expect(within(dialog).queryByRole('button', { name: 'Check and recover interrupted run' })).toBeNull();
    expect(calls.some(c => c.url.endsWith('/log?board=alpha'))).toBe(false);

    // Notifications subscribe / unsubscribe: honest 503 refusals
    fireEvent.click(within(dialog).getByRole('button', { name: 'Subscribe channel' }));
    await waitFor(() => expect(within(dialog).getByRole('alert').textContent).toContain('channel subscription requires a Nerva adapter'));
    expect(within(dialog).queryByText(/Subscribed telegram/)).toBeNull();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Unsubscribe channel' }));
    await waitFor(() => expect(within(dialog).getByRole('alert').textContent).toContain('channel unsubscribe requires a Nerva adapter'));
    expect(within(dialog).queryByText(/Unsubscribed telegram/)).toBeNull();

    // Load model options: honest 503 refusal
    fireEvent.click(within(dialog).getByRole('button', { name: 'Load model options' }));
    await waitFor(() => expect(within(dialog).getByRole('alert').textContent).toContain('model options requires a Nerva adapter'));

    // Other unsupported worker actions still report honest 503 refusals.
    fireEvent.click(within(dialog).getByRole('button', { name: 'Estimate' }));
    await waitFor(() => expect(within(dialog).getByRole('alert').textContent).toContain('task estimate requires a Nerva adapter'));

    fireEvent.click(within(dialog).getByRole('button', { name: 'Specify' }));
    await waitFor(() => expect(within(dialog).getByRole('alert').textContent).toContain('task specification requires a Nerva adapter'));

    fireEvent.click(within(dialog).getByRole('button', { name: 'Decompose' }));
    await waitFor(() => expect(within(dialog).getByRole('alert').textContent).toContain('task decomposition requires a Nerva adapter'));
  });

  it('posts the displayed native run ID and shows the server held outcome', async () => {
    const calls: Array<{ method: string; url: string; body?: unknown }> = [];
    const running: KanbanTaskDetail = {
      task: { id: 't_run', title: 'Recover me', status: 'running', current_run_id: 42, recoverable_run_id: 42 },
      comments: [], events: [], links: { parents: [], children: [] }, runs: [
        { id: 41, status: 'nerva_worker_interrupted', outcome: 'nerva_worker_interrupted', ended_at: 100 },
        { id: 42, status: 'running', started_at: 200, ended_at: null },
      ],
    };
    const held: KanbanTaskDetail = { ...running,
      task: { ...running.task, status: 'blocked', current_run_id: null, recoverable_run_id: null },
      runs: [running.runs[0], { id: 42, status: 'reclaimed', outcome: 'reclaimed', summary: 'Held for review', ended_at: 300 }],
    };
    let recovered = false;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input), method = init?.method || 'GET';
      const body = typeof init?.body === 'string' && init.body ? JSON.parse(init.body) : undefined;
      calls.push({ method, url, body });
      if (method === 'GET' && url === '/api/kanban/tasks/t_run?board=alpha') return jsonResponse(recovered ? held : running);
      if (method === 'POST' && url === '/api/kanban/tasks/t_run/reclaim?board=alpha') { recovered = true; return jsonResponse({ ok: true, status: 'recovered' }); }
      if (method === 'GET' && url.startsWith('/api/kanban/home-channels?')) return jsonResponse({ detail: 'unavailable' }, 503);
      return jsonResponse({ detail: `unhandled ${method} ${url}` }, 500);
    }));
    render(<TaskDrawer slug="alpha" id="t_run" columns={['running', 'blocked']} profiles={[]} onOpen={vi.fn()} onClose={vi.fn()} onChanged={vi.fn()}/>);
    const button = await screen.findByRole('button', { name: 'Check and recover interrupted run' });
    fireEvent.click(button);
    await waitFor(() => expect(calls.find(c => c.method === 'POST' && c.url === '/api/kanban/tasks/t_run/reclaim?board=alpha')?.body).toEqual({ expected_run_id: 42 }));
    expect(await screen.findByText('Held for review')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Check and recover interrupted run' })).toBeNull();
  });
});
