/** Local Kanban transport. All ordinary mutations pass through the HUD failure sink. */
import { apiGet, apiPost, apiPatch, apiDelete, getAdminToken, getToken } from '../../api/client';
import { appUrl } from '../../base-path';
import type { BoardMeta, BoardsResponse, KanbanBoard, KanbanProfile, KanbanProject, KanbanTask, KanbanTaskDetail, OrchestrationSettings } from './types';

const root = '/api/kanban';
export function scopedPath(path: string, slug: string): string {
  const query = new URLSearchParams();
  if (slug) query.set('board', slug);
  return root + path + (query.size ? '?' + query : '');
}
export const boardPath = (slug: string, archived = false) => {
  const query = new URLSearchParams();
  if (slug) query.set('board', slug);
  if (archived) query.set('include_archived', 'true');
  return root + '/board' + (query.size ? '?' + query : '');
};
export const fetchBoard = (slug: string, archived = false) => apiGet<KanbanBoard>(boardPath(slug, archived), { admin: true });
export const fetchBoards = () => apiGet<BoardsResponse>(root + '/boards', { admin: true });
export const fetchTask = (slug: string, id: string) => apiGet<KanbanTaskDetail>(scopedPath(`/tasks/${encodeURIComponent(id)}`, slug), { admin: true });
export const fetchProjects = () => apiGet<{projects: KanbanProject[]}>(root + '/projects', { admin: true });
export const fetchProfiles = () => apiGet<{profiles: KanbanProfile[]}>(root + '/profiles', { admin: true });
export const fetchOrchestration = () => apiGet<OrchestrationSettings>(root + '/orchestration', { admin: true });
export const fetchLog = (slug: string, id: string) => apiGet<{exists: boolean; content: string}>(scopedPath(`/tasks/${encodeURIComponent(id)}/log`, slug), { admin: true });
export const createTask = (slug: string, body: Record<string, unknown>) => apiPost<{task: KanbanTask; warning?: string}>(scopedPath('/tasks', slug), body, { admin: true });
export const patchTask = (slug: string, id: string, body: Record<string, unknown>) => apiPatch(scopedPath(`/tasks/${encodeURIComponent(id)}`, slug), body, { admin: true });
export const bulkTasks = (slug: string, ids: string[], body: Record<string, unknown>) => apiPost<{results: Array<{id: string; ok: boolean; error?: string}>}>(scopedPath('/tasks/bulk', slug), { ids, ...body }, { admin: true });
export const deleteTask = (slug: string, id: string) => apiDelete(scopedPath(`/tasks/${encodeURIComponent(id)}`, slug), { admin: true });
export const addComment = (slug: string, id: string, body: string) => apiPost(scopedPath(`/tasks/${encodeURIComponent(id)}/comments`, slug), { body }, { admin: true });
export const createBoard = (slug: string, name: string, project_id?: string) => apiPost<{board: BoardMeta}>(root + '/boards', { slug, name, ...(project_id ? {project_id} : {}) }, { admin: true });
export const updateBoard = (slug: string, body: Record<string, unknown>) => apiPatch<{board: BoardMeta}>(`${root}/boards/${encodeURIComponent(slug)}`, body, { admin: true });
export const deleteBoard = (slug: string) => apiDelete(`${root}/boards/${encodeURIComponent(slug)}`, { admin: true });
export interface DispatchResult {
  ok: boolean;
  status: string;
  reason?: string;
  queued: Array<{ task_id: string; queue_id: number; status: string }>;
}
export const dispatch = (slug: string) => apiPost<DispatchResult>(scopedPath('/dispatch', slug), {}, { admin: true });

export function kanbanEventsUrl(slug: string, since: number): string {
  const url = new URL(appUrl(root + '/events'), window.location.href);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  const query = new URLSearchParams();
  if (slug) query.set('board', slug);
  query.set('since', String(since));
  url.search = query.toString();
  return url.toString();
}
export type KanbanEventsFrame = { cursor?: number; events?: Array<{id: number; task_id?: string}> };
export function createKanbanSocket(slug: string, since: number, onFrame: (frame: KanbanEventsFrame) => void, onDisconnect?: () => void) {
  const token = getAdminToken();
  const protocols = ['nerva-kanban', ...(token ? [`nerva-admin.${token}`] : [])];
  const ws = new WebSocket(kanbanEventsUrl(slug, since), protocols);
  let active = true;
  ws.onclose = () => { if (active) onDisconnect?.(); };
  ws.onmessage = event => {
    if (!active) return;
    try { const frame = JSON.parse(event.data) as KanbanEventsFrame; if (frame && Array.isArray(frame.events)) onFrame(frame); } catch { /* ignore malformed frame */ }
  };
  return { close: () => { active = false; ws.close(); }, socket: ws };
}

function adminHeaders(): Record<string, string> {
  const h: Record<string, string> = {};
  if (getAdminToken()) h['X-Admin-Token'] = getAdminToken();
  if (getToken()) h['X-User-Token'] = getToken();
  return h;
}
async function checkedFetch(path: string, init: RequestInit): Promise<Response> {
  const response = await fetch(appUrl(path), { ...init, credentials: 'same-origin', redirect: 'error', cache: 'no-store' });
  if (!response.ok) {
    let detail = '';
    try { const body = await response.json() as {detail?: string}; detail = body.detail || ''; } catch { /* non-JSON refusal */ }
    throw Object.assign(new Error(detail || `${init.method || 'GET'} ${path} -> ${response.status}`), { status: response.status });
  }
  return response;
}
export async function uploadAttachment(slug: string, id: string, file: File) {
  const body = new FormData();
  body.append('file', file, file.name);
  const response = await checkedFetch(scopedPath(`/tasks/${encodeURIComponent(id)}/attachments`, slug), { method: 'POST', headers: adminHeaders(), body });
  return response.json() as Promise<{attachment: {id: number}}>;
}
export async function downloadAttachment(slug: string, id: number): Promise<Blob> {
  if (!Number.isSafeInteger(id) || id < 1) throw new Error('integer attachment ID required');
  const response = await checkedFetch(scopedPath(`/attachments/${id}`, slug), { method: 'GET', headers: adminHeaders() });
  return response.blob();
}
