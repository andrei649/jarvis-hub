import { ApiError, normalizeBaseUrl } from './client';
import type { ServerConfig } from '../storage/settings';

export type ModelRole = {
  role: string;
  configured: boolean;
  provider?: string;
  model?: string;
  local?: boolean | null;
  reason?: string;
  note?: string;
  error?: boolean;
  detail?: string;
};

export type ModelRoles = { roles: ModelRole[]; reachable: null };
const ROLES_TIMEOUT_MS = 10000;
const MAX_ROLES = 24;
const MAX_FIELD = 240;
const MAX_NOTE = 500;

function invalid(): never { throw new ApiError('Invalid model roles response'); }
function optionalString(row: Record<string, unknown>, key: string, max = MAX_FIELD): string | undefined {
  const value = row[key];
  if (value === undefined || value === null) return undefined;
  if (typeof value !== 'string' || value.length > max) return invalid();
  return value;
}

function parseRoles(data: unknown): ModelRoles {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return invalid();
  const envelope = data as Record<string, unknown>;
  if (!Array.isArray(envelope.roles) || envelope.roles.length > MAX_ROLES || envelope.reachable !== null) return invalid();
  const roles = envelope.roles.map((value): ModelRole => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return invalid();
    const row = value as Record<string, unknown>;
    if (typeof row.role !== 'string' || !row.role || row.role.length > 64 || typeof row.configured !== 'boolean') return invalid();
    if (row.local !== undefined && row.local !== null && typeof row.local !== 'boolean') return invalid();
    if (row.error !== undefined && typeof row.error !== 'boolean') return invalid();
    return {
      role: row.role, configured: row.configured,
      provider: optionalString(row, 'provider'), model: optionalString(row, 'model'),
      local: row.local as boolean | null | undefined,
      reason: optionalString(row, 'reason'), note: optionalString(row, 'note', MAX_NOTE),
      error: row.error as boolean | undefined, detail: optionalString(row, 'detail', MAX_NOTE),
    };
  });
  return { roles, reachable: null };
}

/** Configuration metadata only. The endpoint does not probe a provider. */
export async function fetchModelRoles(config: ServerConfig, signal?: AbortSignal): Promise<ModelRoles> {
  const base = normalizeBaseUrl(config.baseUrl);
  if (!base) throw new ApiError('No server URL configured');
  if (signal?.aborted) throw new ApiError('Model roles request cancelled');
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  let onAbort: (() => void) | undefined;
  const deadline = new Promise<never>((_, reject) => {
    onAbort = () => { controller.abort(); reject(new ApiError('Model roles request cancelled')); };
    signal?.addEventListener('abort', onAbort, { once: true });
    timer = setTimeout(() => { controller.abort(); reject(new ApiError('Model roles request timed out')); }, ROLES_TIMEOUT_MS);
  });
  const read = async (): Promise<ModelRoles> => {
    let res: Response;
    try {
      res = await fetch(base + '/api/llm/roles', {
        method: 'GET',
        headers: {
          Accept: 'application/json',
          ...(config.token.trim() ? { 'X-User-Token': config.token.trim() } : {}),
          ...(config.adminToken.trim() ? { 'X-Admin-Token': config.adminToken.trim() } : {}),
        },
        signal: controller.signal,
      });
    } catch {
      if (controller.signal.aborted) throw new ApiError('Model roles request cancelled');
      throw new ApiError(`Could not reach ${base} — check the URL and network`);
    }
    if (controller.signal.aborted) throw new ApiError('Model roles request cancelled');
    if (!res.ok) throw new ApiError(res.status === 401 ? 'Unauthorized — check your credentials' : `Server returned HTTP ${res.status}`, res.status);
    const data: unknown = await res.json();
    if (controller.signal.aborted) throw new ApiError('Model roles request cancelled');
    return parseRoles(data);
  };
  try { return await Promise.race([read(), deadline]); }
  finally {
    if (timer) clearTimeout(timer);
    if (onAbort) signal?.removeEventListener('abort', onAbort);
  }
}
