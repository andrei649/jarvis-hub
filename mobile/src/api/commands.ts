import type { ServerConfig } from '../storage/settings';
import { ApiError, normalizeBaseUrl } from './client';

export type CommandSummary = {
  name: string;
  command: string;
  description: string;
  tier: 'user' | 'admin';
  usage: string;
};

export type ShortcutSummary = Omit<CommandSummary, 'tier'> & {
  kind: 'quick' | 'skill' | 'bundle';
  tier: 'admin';
};

export type CommandCatalog =
  | { status: 'available'; commands: CommandSummary[]; shortcuts: ShortcutSummary[];
      truncated: boolean; shortcutsUnavailable: boolean }
  | { status: 'unavailable'; commands: [] };

function validCommand(value: unknown): value is CommandSummary {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const command = value as Record<string, unknown>;
  return typeof command.name === 'string' && /^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(command.name)
    && command.command === `/${command.name}`
    && typeof command.description === 'string' && command.description.length <= 1000
    && typeof command.usage === 'string' && command.usage.length <= 1000
    && (command.tier === 'user' || command.tier === 'admin');
}

function validShortcut(value: unknown): value is ShortcutSummary {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const row = value as Record<string, unknown>;
  if (typeof row.name !== 'string' || row.name.length > 64 || row.tier !== 'admin'
    || typeof row.description !== 'string' || row.description.length > 1000
    || typeof row.usage !== 'string' || row.usage.length > 1000) return false;
  if (row.kind === 'quick') return /^[a-z][a-z0-9_]{0,63}$/.test(row.name)
    && row.command === `/${row.name}`;
  if (row.kind === 'skill') return /^[a-z][a-z0-9_-]{0,63}$/.test(row.name)
    && row.command === `/${row.name}`;
  if (row.kind === 'bundle') return /^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$/.test(row.name)
    && row.command === `/bundle ${row.name}`;
  return false;
}

/** Read the current chat principal's catalog without invoking any command. */
export async function fetchCommands(config: ServerConfig, signal: AbortSignal): Promise<CommandCatalog> {
  const base = normalizeBaseUrl(config.baseUrl);
  if (!base) throw new ApiError('No server URL configured');
  const abort = new AbortController();
  const cancel = () => abort.abort();
  signal.addEventListener('abort', cancel, { once: true });
  if (signal.aborted) abort.abort();
  if (abort.signal.aborted) {
    signal.removeEventListener('abort', cancel);
    throw new ApiError('Command request cancelled or timed out');
  }
  const timer = setTimeout(cancel, 15000);
  try {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (config.token.trim()) headers['X-User-Token'] = config.token.trim();
    if (config.adminToken.trim()) headers['X-Admin-Token'] = config.adminToken.trim();
    const response = await fetch(base + '/api/commands', {
      method: 'GET', headers, signal: abort.signal, cache: 'no-store', redirect: 'error',
    });
    if (abort.signal.aborted) throw new ApiError('Command request cancelled or timed out');
    if (!response.ok && response.status !== 503) {
      throw new ApiError(`Server returned HTTP ${response.status}`, response.status);
    }
    const data = await response.json();
    if (abort.signal.aborted) throw new ApiError('Command request cancelled or timed out');
    if (response.status === 503 && data?.ok === false && data?.reason === 'commands_unavailable'
      && Array.isArray(data.commands) && data.commands.length === 0) {
      return { status: 'unavailable', commands: [] };
    }
    if (!response.ok) throw new ApiError(`Server returned HTTP ${response.status}`, response.status);
    const shortcuts = data?.shortcuts === undefined ? [] : data.shortcuts;
    if (data?.ok !== true || !Array.isArray(data.commands) || !Array.isArray(shortcuts)
      || data.commands.length + shortcuts.length > 256
      || !data.commands.every(validCommand) || !shortcuts.every(validShortcut)
      || (data.truncated !== undefined && typeof data.truncated !== 'boolean')
      || (data.shortcuts_unavailable !== undefined && typeof data.shortcuts_unavailable !== 'boolean')) {
      throw new ApiError('Invalid command catalog');
    }
    return { status: 'available', commands: data.commands, shortcuts,
      truncated: data.truncated === true, shortcutsUnavailable: data.shortcuts_unavailable === true };
  } catch (error) {
    if (abort.signal.aborted) throw new ApiError('Command request cancelled or timed out');
    if (error instanceof ApiError) throw error;
    throw new ApiError(`Could not reach ${base} — check the URL and network`);
  } finally {
    clearTimeout(timer);
    signal.removeEventListener('abort', cancel);
  }
}
