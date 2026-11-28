import { afterEach, describe, expect, jest, test } from '@jest/globals';
import { dispatchKanbanReady, fetchKanbanSnapshot, proposeCompanyGoal, validBoardSlug } from '../kanban';
import type { ServerConfig } from '../../storage/settings';

const adminCfg: ServerConfig = {
  baseUrl: 'https://hub.example',
  token: 'user-tok',
  adminToken: 'admin-tok',
};

const noAdminCfg: ServerConfig = {
  baseUrl: 'https://hub.example',
  token: 'user-tok',
  adminToken: '',
};

function jsonRes(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe('H18.34 Kanban board & H462 company goals native API', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  test('validates board slugs strictly and refuses calls without admin token', async () => {
    expect(validBoardSlug('default')).toBe(true);
    expect(validBoardSlug('ops_board-2')).toBe(true);
    expect(validBoardSlug('../bad')).toBe(false);
    expect(validBoardSlug('')).toBe(false);

    await expect(fetchKanbanSnapshot(noAdminCfg)).rejects.toThrow(/Admin token required/);
    await expect(dispatchKanbanReady(adminCfg, '../bad')).rejects.toThrow(/Invalid Kanban board slug/);
  });

  test('loads boards, columns, and active workers with admin headers', async () => {
    const fetchMock = jest.fn(async (url: string) => {
      if (url.endsWith('/api/kanban/boards')) {
        return jsonRes({ current: 'ops', boards: [{ slug: 'ops', name: 'Operations' }] });
      }
      if (url.includes('/api/kanban/board?board=ops')) {
        return jsonRes({
          columns: [
            { name: 'todo', tasks: [{ id: 'k_1', title: 'Audit backups', status: 'todo', assignee: 'steve' }] },
            { name: 'in_progress', tasks: [{ id: 'k_2', title: 'Sync vault', status: 'in_progress', worker_pid: 4120, warnings: { count: 1 } }] },
          ],
        });
      }
      if (url.includes('/api/kanban/workers/active?board=ops')) {
        return jsonRes({ workers: [{ task_id: 'k_2', run_id: 9, profile: 'steve', worker_pid: 4120 }] });
      }
      return jsonRes({}, 404);
    });
    (globalThis as any).fetch = fetchMock;

    const snap = await fetchKanbanSnapshot(adminCfg);
    expect(snap.board).toBe('ops');
    expect(snap.columns).toHaveLength(2);
    expect(snap.columns[1].tasks[0]).toMatchObject({
      id: 'k_2',
      workerPid: 4120,
      warningCount: 1,
    });
    expect(snap.activeWorkers).toEqual([
      { taskId: 'k_2', runId: 9, profile: 'steve', pid: 4120 },
    ]);
  });

  test('surfaces governed_worker_unavailable honestly instead of fabricating empty queues', async () => {
    (globalThis as any).fetch = jest.fn(async () =>
      jsonRes({ ok: false, status: 'refused', reason: 'governed_worker_unavailable', queued: [] }, 503),
    );

    const res = await dispatchKanbanReady(adminCfg, 'default', 3);
    expect(res).toEqual({
      ok: false,
      status: 'refused',
      reason: 'governed_worker_unavailable',
      queued: [],
    });
  });

  test('proposes approval-gated company goals and surfaces 409 company_mode_off refusals', async () => {
    const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
    mockFetch
      .mockResolvedValueOnce(jsonRes({ ok: true, task_id: 'goal_77', title: 'Ship mobile parity', card: {} }))
      .mockResolvedValueOnce(jsonRes({ ok: false, reason: 'company_mode_off', detail: 'Company mode is disabled' }, 409));
    (globalThis as any).fetch = mockFetch;

    const ok = await proposeCompanyGoal(adminCfg, '  Ship mobile parity  ');
    expect(ok).toEqual({ taskId: 'goal_77', title: 'Ship mobile parity' });

    await expect(proposeCompanyGoal(adminCfg, 'Another goal')).rejects.toThrow(/Company mode is disabled/);
    await expect(proposeCompanyGoal(adminCfg, '   ')).rejects.toThrow(/must not be blank/);
  });
});
