import type { ServerConfig } from '../storage/settings';
import { ApiError, normalizeBaseUrl } from './client';

export type AgentOpinion = { agent: string; ok: boolean; text?: string; model?: string; route?: string; reason?: string };

const TIMEOUT_MS = 130_000; // The hub allows each comparison member up to 120 seconds.
const BODY_LIMIT = 256 * 1024;
const ID = /^[a-z0-9_-]{1,64}$/;

function invalid(): never { throw new ApiError('Invalid comparison response'); }
function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}
function validUnicode(value: string): boolean {
  try { encodeURIComponent(value); return true; } catch { return false; }
}

function parseOpinions(value: unknown, agents: [string, string]): AgentOpinion[] {
  if (!record(value) || !Array.isArray(value.opinions) || value.opinions.length !== 2) return invalid();
  const found = new Map<string, AgentOpinion>();
  for (const item of value.opinions) {
    if (!record(item) || typeof item.agent !== 'string' || !agents.includes(item.agent) ||
        found.has(item.agent) || typeof item.ok !== 'boolean') return invalid();
    const opinion: AgentOpinion = { agent: item.agent, ok: item.ok };
    for (const [key, max] of [['text', 100_000], ['model', 256], ['route', 128], ['reason', 128]] as const) {
      if (key in item) {
        const field = item[key];
        if (typeof field !== 'string' || field.length > max || !validUnicode(field)) return invalid();
        opinion[key] = field;
      }
    }
    if (opinion.ok && !opinion.text?.trim()) return invalid();
    found.set(item.agent, opinion);
  }
  if (found.size !== 2) return invalid();
  return agents.map(agent => found.get(agent)!);
}

/** Compare two active hub agents without starting a chat or retrying model calls. */
export async function compareAgents(config: ServerConfig, question: string, agents: [string, string],
  allowCloud: boolean, signal?: AbortSignal): Promise<AgentOpinion[]> {
  if (typeof question !== 'string' || !validUnicode(question) || !Array.isArray(agents) || agents.length !== 2 ||
      agents[0] === agents[1] || !agents.every(id => typeof id === 'string' && ID.test(id)) ||
      typeof allowCloud !== 'boolean') throw new ApiError('Invalid comparison request');
  const trimmed = question.trim();
  if (!trimmed || Array.from(trimmed).length > 4096) throw new ApiError('Invalid comparison request');
  if (signal?.aborted) throw new ApiError('Comparison cancelled');
  const raw = normalizeBaseUrl(config.baseUrl);
  if (!raw) throw new ApiError('No server URL configured');
  let base: string;
  try {
    if (raw.includes('\\')) throw new Error('Invalid URL');
    const url = new URL(raw);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
      throw new Error('Invalid URL');
    }
    base = url.href.replace(/\/+$/, '');
  } catch { throw new ApiError('Invalid server URL'); }

  const controller = new AbortController();
  let rejectStop!: (error: ApiError) => void;
  const stopped = new Promise<never>((_, reject) => { rejectStop = reject; });
  const onAbort = () => { controller.abort(); rejectStop(new ApiError('Comparison cancelled')); };
  signal?.addEventListener('abort', onAbort, { once: true });
  const timer = setTimeout(() => { controller.abort(); rejectStop(new ApiError('Comparison timed out')); }, TIMEOUT_MS);
  const request = async () => {
    let response: Response;
    try {
      const { fetch: nativeFetch } = await import('expo/fetch');
      if (controller.signal.aborted) throw new Error('Cancelled');
      response = await nativeFetch(base + '/api/agents/opinions', {
        method: 'POST', redirect: 'error', credentials: 'omit', signal: controller.signal,
        headers: {
          Accept: 'application/json', 'Content-Type': 'application/json', 'Cache-Control': 'no-store',
          ...(config.token.trim() ? { 'X-User-Token': config.token.trim() } : {}),
          ...(config.adminToken.trim() ? { 'X-Admin-Token': config.adminToken.trim() } : {}),
        },
        body: JSON.stringify({ question: trimmed, agents, allow_cloud: allowCloud }),
      });
    } catch { throw new ApiError('Comparison unavailable'); }
    if (controller.signal.aborted) throw new ApiError('Comparison cancelled');
    if (response.status < 200 || response.status >= 300) {
      throw new ApiError(response.status === 401 || response.status === 403 ? 'Owner authorization required'
        : response.status === 429 ? 'Comparison already running' : 'Comparison unavailable', response.status);
    }
    const length = response.headers?.get('content-length');
    if (length != null && (!/^\d+$/.test(length) || Number(length) > BODY_LIMIT)) {
      controller.abort();
      return invalid();
    }
    let body: string;
    try { body = await response.text(); } catch { return invalid(); }
    if (controller.signal.aborted) throw new ApiError('Comparison cancelled');
    if (body.length > BODY_LIMIT) return invalid();
    try { return parseOpinions(JSON.parse(body), agents); } catch (error) {
      if (error instanceof ApiError) throw error;
      return invalid();
    }
  };
  try { return await Promise.race([request(), stopped]); }
  finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }
}
