import { normalizeAppearance, type Appearance } from '../appearance';
import type { ServerConfig } from '../storage/settings';
import { ApiError, normalizeBaseUrl } from './client';

/** One cancellable, bounded-time GET. No server preference mutation or auth retry. */
export async function fetchAppearance(config: ServerConfig, signal: AbortSignal): Promise<Appearance> {
  const base = normalizeBaseUrl(config.baseUrl);
  if (!base) throw new ApiError('No server URL configured');
  const abort = new AbortController();
  const cancel = () => abort.abort();
  signal.addEventListener('abort', cancel, { once: true });
  if (signal.aborted) abort.abort();
  const timer = setTimeout(cancel, 15000);
  try {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (config.token.trim()) headers['X-User-Token'] = config.token.trim();
    const response = await fetch(base + '/api/preferences/appearance', { method: 'GET', headers,
      signal: abort.signal, cache: 'no-store', redirect: 'error' });
    if (abort.signal.aborted) throw new ApiError('Appearance request cancelled or timed out');
    if (!response.ok) throw new ApiError('Appearance request failed', response.status);
    const data = await response.json();
    if (abort.signal.aborted) throw new ApiError('Appearance request cancelled or timed out');
    if (!data || typeof data.configured !== 'boolean' || !data.preferences || typeof data.preferences !== 'object' || Array.isArray(data.preferences)) {
      throw new ApiError('Invalid appearance response');
    }
    return normalizeAppearance(data.preferences);
  } finally {
    clearTimeout(timer); signal.removeEventListener('abort', cancel);
  }
}
