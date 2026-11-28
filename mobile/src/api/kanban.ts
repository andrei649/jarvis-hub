import { ApiError, normalizeBaseUrl } from './client';
import type { ServerConfig } from '../storage/settings';

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

const BOARD_SLUG_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const KANBAN_ROOT = '/api/kanban';

export function validBoardSlug(slug: string): boolean {
  return BOARD_SLUG_RE.test(slug);
}

function adminHeaders(config: ServerConfig, json: boolean): Record<string, string> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (json) headers['Content-Type'] = 'application/json';
  if (config.token.trim()) headers['X-User-Token'] = config.token.trim();
  if (config.adminToken.trim()) headers['X-Admin-Token'] = config.adminToken.trim();
  return headers;
}

async function kanbanFetch<T>(
  config: ServerConfig,
  method: 'GET' | 'POST',
  path: string,
  opts: { body?: unknown; signal?: AbortSignal } = {},
): Promise<{ status: number; ok: boolean; data: T }> {
  const base = normalizeBaseUrl(config.baseUrl);
  if (!base) throw new ApiError('No server URL configured');
  if (!config.adminToken.trim()) {
    throw new ApiError('Admin token required — add one in Settings', 403);
  }
  const controller = new AbortController();
  const forwardAbort = () => controller.abort();
  opts.signal?.addEventListener('abort', forwardAbort);
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const res = await fetch(base + path, {
      method,
      headers: adminHeaders(config, opts.body !== undefined),
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: controller.signal,
      cache: 'no-store',
    });
    let payload: unknown = null;
    try {
      payload = await res.json();
    } catch {
      payload = null;
    }
    if (res.status === 401) throw new ApiError('Unauthorized — check your user token', 401);
    if (res.status === 403) {
      const detail = isRecord(payload) && typeof payload.detail === 'string' ? payload.detail : '';
      throw new ApiError(detail || 'Admin access required or denied by kernel', 403);
    }
    return { status: res.status, ok: res.ok, data: payload as T };
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (opts.signal?.aborted) throw new ApiError('Request cancelled', 499);
    throw new ApiError(`Could not reach ${base}`);
  } finally {
    clearTimeout(timer);
    opts.signal?.removeEventListener('abort', forwardAbort);
  }
}

export type KanbanBoardSummary = {
  slug: string;
  name: string;
};

export type KanbanCardSummary = {
  id: string;
  title: string;
  status: string;
  assignee: string | null;
  priority: number | null;
  workerPid: number | null;
  warningCount: number;
};

export type KanbanColumnSummary = {
  name: string;
  tasks: KanbanCardSummary[];
};

export type KanbanBoardSnapshot = {
  board: string;
  boards: KanbanBoardSummary[];
  columns: KanbanColumnSummary[];
  activeWorkers: Array<{ taskId: string; runId: number | string | null; profile: string | null; pid: number | null }>;
};

export type KanbanDispatchOutcome = {
  ok: boolean;
  status: 'queued' | 'disabled' | 'refused' | 'idle' | string;
  reason: string | null;
  queued: Array<{ taskId: string; queueId: number | null; status: string }>;
};

function parseCard(raw: unknown): KanbanCardSummary | null {
  if (!isRecord(raw) || typeof raw.id !== 'string' || !raw.id.trim()) return null;
  const warnings = isRecord(raw.warnings) && typeof raw.warnings.count === 'number' ? raw.warnings.count : 0;
  return {
    id: raw.id.trim(),
    title: typeof raw.title === 'string' && raw.title.trim() ? raw.title.trim() : raw.id.trim(),
    status: typeof raw.status === 'string' ? raw.status : 'todo',
    assignee: typeof raw.assignee === 'string' && raw.assignee.trim() ? raw.assignee.trim() : null,
    priority: typeof raw.priority === 'number' && Number.isFinite(raw.priority) ? raw.priority : null,
    workerPid: typeof raw.worker_pid === 'number' && Number.isFinite(raw.worker_pid) ? raw.worker_pid : null,
    warningCount: warnings,
  };
}

export async function fetchKanbanSnapshot(
  config: ServerConfig,
  requestedBoard = '',
  signal?: AbortSignal,
): Promise<KanbanBoardSnapshot> {
  const boardsRes = await kanbanFetch<unknown>(config, 'GET', KANBAN_ROOT + '/boards', { signal });
  if (!boardsRes.ok || !isRecord(boardsRes.data) || !Array.isArray(boardsRes.data.boards)) {
    const errMsg = isRecord(boardsRes.data) && typeof boardsRes.data.detail === 'string'
      ? boardsRes.data.detail
      : `Kanban boards unavailable (HTTP ${boardsRes.status})`;
    throw new ApiError(errMsg, boardsRes.status);
  }
  const boards: KanbanBoardSummary[] = boardsRes.data.boards
    .filter(isRecord)
    .filter(b => typeof b.slug === 'string' && validBoardSlug(b.slug))
    .map(b => ({
      slug: String(b.slug),
      name: typeof b.name === 'string' && b.name.trim() ? b.name.trim() : String(b.slug),
    }));

  const currentSlug = typeof boardsRes.data.current === 'string' && validBoardSlug(boardsRes.data.current)
    ? boardsRes.data.current
    : boards[0]?.slug ?? 'default';
  const slug = requestedBoard && validBoardSlug(requestedBoard) ? requestedBoard : currentSlug;

  const query = `?board=${encodeURIComponent(slug)}`;
  const [boardRes, workersRes] = await Promise.all([
    kanbanFetch<unknown>(config, 'GET', KANBAN_ROOT + '/board' + query, { signal }),
    kanbanFetch<unknown>(config, 'GET', KANBAN_ROOT + '/workers/active' + query, { signal }).catch(() => ({
      status: 200,
      ok: true,
      data: { workers: [] } as unknown,
    })),
  ]);

  if (!boardRes.ok || !isRecord(boardRes.data) || !Array.isArray(boardRes.data.columns)) {
    const errMsg = isRecord(boardRes.data) && typeof boardRes.data.detail === 'string'
      ? boardRes.data.detail
      : `Kanban board unavailable (HTTP ${boardRes.status})`;
    throw new ApiError(errMsg, boardRes.status);
  }

  const columns: KanbanColumnSummary[] = boardRes.data.columns
    .filter(isRecord)
    .filter(c => typeof c.name === 'string' && Array.isArray(c.tasks))
    .map(c => ({
      name: String(c.name),
      tasks: (c.tasks as unknown[]).map(parseCard).filter((t): t is KanbanCardSummary => t !== null),
    }));

  const rawWorkers = isRecord(workersRes.data) && Array.isArray(workersRes.data.workers)
    ? workersRes.data.workers
    : [];
  const activeWorkers = rawWorkers.filter(isRecord).map(w => ({
    taskId: typeof w.task_id === 'string' ? w.task_id : typeof w.id === 'string' ? w.id : 'unknown',
    runId: typeof w.run_id === 'number' || typeof w.run_id === 'string' ? w.run_id : null,
    profile: typeof w.profile === 'string' ? w.profile : typeof w.assignee === 'string' ? w.assignee : null,
    pid: typeof w.worker_pid === 'number' ? w.worker_pid : typeof w.pid === 'number' ? w.pid : null,
  }));

  return { board: slug, boards, columns, activeWorkers };
}

export async function dispatchKanbanReady(
  config: ServerConfig,
  board = 'default',
  limit = 4,
): Promise<KanbanDispatchOutcome> {
  if (!validBoardSlug(board)) {
    throw new ApiError('Invalid Kanban board slug', 422);
  }
  const boundedLimit = Math.max(1, Math.min(16, Math.trunc(limit)));
  const res = await kanbanFetch<unknown>(config, 'POST', '/api/autonomy/kanban/dispatch', {
    body: { board, limit: boundedLimit },
  });
  const raw = isRecord(res.data) ? res.data : {};
  const queued = Array.isArray(raw.queued)
    ? raw.queued.filter(isRecord).map(q => ({
        taskId: typeof q.task_id === 'string' ? q.task_id : '',
        queueId: typeof q.queue_id === 'number' ? q.queue_id : null,
        status: typeof q.status === 'string' ? q.status : 'pending',
      })).filter(q => q.taskId)
    : [];

  if (!res.ok) {
    const reason = typeof raw.reason === 'string' && raw.reason
      ? raw.reason
      : res.status === 503
        ? 'governed_worker_unavailable'
        : `http_${res.status}`;
    return {
      ok: false,
      status: typeof raw.status === 'string' ? raw.status : 'refused',
      reason,
      queued,
    };
  }

  return {
    ok: raw.ok !== false,
    status: typeof raw.status === 'string' ? raw.status : queued.length ? 'queued' : 'idle',
    reason: typeof raw.reason === 'string' ? raw.reason : null,
    queued,
  };
}

// ── H462 / H18.35: Company Goal Proposal (/api/company/goals) ──

export type CompanyGoalReceipt = {
  taskId: string;
  title: string;
};

export async function proposeCompanyGoal(
  config: ServerConfig,
  text: string,
): Promise<CompanyGoalReceipt> {
  const trimmed = text.trim();
  if (!trimmed) throw new ApiError('Goal text must not be blank', 400);
  const res = await kanbanFetch<unknown>(config, 'POST', '/api/company/goals', {
    body: { text: trimmed },
  });
  const raw = isRecord(res.data) ? res.data : {};
  if (!res.ok || raw.ok === false) {
    const detail = typeof raw.detail === 'string' && raw.detail.trim()
      ? raw.detail
      : typeof raw.reason === 'string' && raw.reason.trim()
        ? raw.reason
        : `Goal proposal refused (HTTP ${res.status})`;
    throw new ApiError(detail, res.status);
  }
  if (typeof raw.task_id !== 'string' || !raw.task_id.trim()) {
    throw new ApiError('Invalid company goal response');
  }
  return {
    taskId: raw.task_id.trim(),
    title: typeof raw.title === 'string' && raw.title.trim() ? raw.title.trim() : trimmed.slice(0, 80),
  };
}
