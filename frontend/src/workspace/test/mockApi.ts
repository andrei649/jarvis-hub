/* Test harness: a routed fetch mock and fixtures for the Workspace screens.

   Routes are keyed "METHOD /path" (the query string is matched separately when given as
   "METHOD /path?query"); each answers a value (sent as 200 JSON), a {status, body} reply, or a
   function of the request. Every call is recorded with its parsed JSON body and headers so
   tests can assert exactly what the UI sent. An unmatched request fails the test loudly. */
import { vi } from 'vitest';
import type { AdminDepartment, AdminUser, Department, Org, SessionInfo, WorkspaceUser } from '../api/types';

export interface RecordedCall {
  method: string;
  path: string;
  search: string;
  body: unknown;
  headers: Record<string, string>;
}

export interface Reply { status?: number; body?: unknown; headers?: Record<string, string> }
export type RouteHandler = unknown | Reply | ((call: RecordedCall) => unknown | Reply | Promise<unknown | Reply>);

/** Only `{status: number, body?, headers?}` is a reply envelope: documents, runs and approvals
    carry a string `status` of their own and are bodies. */
function isReply(value: unknown): value is Reply {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const keys = Object.keys(value);
  return keys.length > 0 && keys.every((key) => key === 'status' || key === 'body' || key === 'headers')
    && (!('status' in value) || typeof (value as Reply).status === 'number');
}

export function json(status: number, body?: unknown): Reply {
  return { status, body };
}

export function apiError(status: number, error: string, extra: Record<string, unknown> = {}): Reply {
  return { status, body: { error, message: `server says ${error}`, ...extra } };
}

function toResponse(reply: Reply): Response {
  const status = reply.status ?? 200;
  if (status === 204 || reply.body === undefined) return new Response(null, { status });
  return new Response(JSON.stringify(reply.body), {
    status, headers: { 'Content-Type': 'application/json', ...reply.headers },
  });
}

export function mockFetch(routes: Record<string, RouteHandler>) {
  const calls: RecordedCall[] = [];
  const table = new Map(Object.entries(routes));
  const fn = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), 'http://localhost');
    const method = (init.method || 'GET').toUpperCase();
    const headers = Object.fromEntries(Object.entries((init.headers as Record<string, string>) || {}));
    let body: unknown = init.body;
    if (typeof body === 'string' && headers['Content-Type'] === 'application/json') body = JSON.parse(body);
    const call: RecordedCall = { method, path: url.pathname, search: url.search, body, headers };
    calls.push(call);
    const handler = table.get(`${method} ${url.pathname}${url.search}`) ?? table.get(`${method} ${url.pathname}`);
    if (handler === undefined) throw new Error(`unmocked request: ${method} ${url.pathname}${url.search}`);
    const value = typeof handler === 'function' ? await (handler as (c: RecordedCall) => unknown)(call) : handler;
    // A ready-made Response (e.g. a server-sent event stream) is answered as it is.
    if (value instanceof Response) return value;
    return toResponse(isReply(value) ? value : { status: 200, body: value });
  });
  vi.stubGlobal('fetch', fn);
  return {
    calls,
    fn,
    /** Replace or add a route mid-test. */
    on(key: string, handler: RouteHandler) { table.set(key, handler); },
    find(method: string, path: string) { return calls.filter((c) => c.method === method && c.path === path); },
  };
}

// ---------------------------------------------------------------- fixtures

export const ORG: Org = { name: 'Acme', default_locale: 'ro', model_policy: 'local_only' };

export const DEPARTMENTS: Department[] = [
  { id: 1, slug: 'general', name: 'General', description: '', member_count: 2, document_count: 0 },
  { id: 2, slug: 'juridic', name: 'Juridic', description: 'Contracte', member_count: 1, document_count: 3 },
];

export const ADMIN_DEPARTMENTS: AdminDepartment[] = DEPARTMENTS.map((d) => ({
  ...d, assistant_instructions: '', archived: false, report_count: 0, conversation_count: 0,
}));

export function makeUser(over: Partial<WorkspaceUser> = {}): WorkspaceUser {
  return {
    id: 1, email: 'ana@acme.ro', name: 'Ana Pop', role: 'admin', status: 'active', locale: 'ro', theme: 'light',
    department_ids: [1], ...over,
  };
}

export function makeAdminUser(over: Partial<AdminUser> = {}): AdminUser {
  return { ...makeUser(), last_login_at: null, pending_invite: null, ...over };
}

export function signedIn(user: WorkspaceUser = makeUser()): SessionInfo {
  return {
    enabled: true, setup_required: false, sso_available: false, authenticated: true,
    user, org: ORG, csrf_token: 'csrf-1', departments: DEPARTMENTS,
  };
}

export const SIGNED_OUT: SessionInfo = { enabled: true, setup_required: false, sso_available: false, authenticated: false };

/** The polls and lists every signed-in shell makes on mount. */
export function shellRoutes(): Record<string, RouteHandler> {
  return {
    'GET /api/workspace/departments': { departments: DEPARTMENTS },
    'GET /api/workspace/approvals': { items: [], pending_inbox_count: 2 },
    'GET /api/workspace/notifications': { items: [], unread_count: 0 },
    'GET /api/workspace/model': {
      available: true, backend: 'lm-studio', model: 'qwen', route: 'local', locality: 'local',
      policy: 'local_only', reason: null, guardrails_mode: 'monitor',
    },
  };
}

export function setLocation(path: string): void {
  window.history.replaceState(null, '', path);
}
