import type { ServerConfig } from '../storage/settings';
import { ApiError, normalizeBaseUrl } from './client';

export const EXTENSIONS_INSPECTION_PATH = '/api/plugins/extensions';

const NAME = /^[a-z][a-z0-9_]{0,63}$/;
const VERSION = /^(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})(?:[-+][A-Za-z0-9.-]{1,40})?$/;
const TOOL = /^[a-z][a-z0-9_]{0,63}\.[a-z][a-z0-9_]{0,63}$/;
const EVENTS = new Set([
  'command.started', 'command.completed', 'session.started', 'session.ended', 'tool.completed',
  'approval.smart.requested', 'approval.smart.decided',
]);
const CAPABILITIES = new Set(['tools', 'commands', 'events.observe']);
const REPORT_REASONS = new Set([
  'acquisition_unavailable', 'acquisition_disabled', 'acquisition_not_composed',
  'extension_capacity', 'sdk_dispatch_unavailable', 'activated', 'acquisition_inspection_unavailable',
]);
const ROW_REASONS = new Set([
  'sdk_dispatch_unavailable', 'acquired_inactive', 'acquired_integrity_unverified', 'activated',
]);

export type ExtensionInspectionRow = {
  id: string;
  version: string;
  reason: string;
  signatureVerified: boolean;
  approvalVerified: boolean;
  quarantineState: 'not_inspected';
  executionAvailable: boolean;
  declaredTools: string[];
  callableTools: string[];
  declaredCommands: string[];
  callableCommands: string[];
  commandRequiresArgs: string[];
  declaredEvents: string[];
  capabilities: string[];
};

export type ExtensionInspectionReport = {
  mode: 'inspection_only';
  reason: string;
  extensions: ExtensionInspectionRow[];
};

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function names(value: unknown, pattern: RegExp): string[] | null {
  if (!Array.isArray(value) || value.length > 64
    || !value.every(item => typeof item === 'string' && pattern.test(item))) return null;
  const result = value as string[];
  return new Set(result).size === result.length ? result : null;
}

function subset(items: string[], allowed: string[]): boolean {
  const set = new Set(allowed);
  return items.every(item => set.has(item));
}

/** Keep only the bounded, passive inspection contract; reject malformed or widened claims. */
export function normalizeExtensionInspection(value: unknown): ExtensionInspectionReport {
  const report = object(value) ? value : null;
  if (!report || report.mode !== 'inspection_only' || typeof report.reason !== 'string'
    || !REPORT_REASONS.has(report.reason) || !Array.isArray(report.extensions)
    || report.extensions.length > 128) {
    throw new ApiError('Invalid extension inspection');
  }

  const ids = new Set<string>();
  const extensions: ExtensionInspectionRow[] = [];
  for (const candidate of report.extensions) {
    const row = object(candidate) ? candidate : null;
    if (!row || typeof row.id !== 'string' || !NAME.test(row.id)
      || typeof row.version !== 'string' || !VERSION.test(row.version)
      || typeof row.reason !== 'string' || !ROW_REASONS.has(row.reason)
      || typeof row.signature_verified !== 'boolean' || typeof row.approval_verified !== 'boolean'
      || row.quarantine_state !== 'not_inspected' || typeof row.execution_available !== 'boolean'
      || !Array.isArray(row.capabilities) || row.capabilities.length > 3
      || !row.capabilities.every(item => typeof item === 'string' && CAPABILITIES.has(item))
      || new Set(row.capabilities).size !== row.capabilities.length
      || !Array.isArray(row.declared_events) || row.declared_events.length > 64
      || !row.declared_events.every(item => typeof item === 'string' && EVENTS.has(item))
      || new Set(row.declared_events).size !== row.declared_events.length || ids.has(row.id)) {
      throw new ApiError('Invalid extension inspection');
    }
    ids.add(row.id);

    const declaredTools = names(row.declared_tools, TOOL);
    const callableTools = names(row.callable_tools, TOOL);
    const declaredCommands = names(row.declared_commands, NAME);
    const callableCommands = names(row.callable_commands, NAME);
    const commandRequiresArgs = names(row.command_requires_args, NAME);
    if (!declaredTools || !callableTools || !declaredCommands || !callableCommands || !commandRequiresArgs
      || declaredTools.some(tool => !tool.startsWith(`${row.id}.`))
      || callableTools.some(tool => !tool.startsWith(`${row.id}.`))
      || !subset(callableTools, declaredTools) || !subset(callableCommands, declaredCommands)
      || !subset(commandRequiresArgs, declaredCommands)
      || (declaredTools.length > 0 && !row.capabilities.includes('tools'))
      || (declaredCommands.length > 0 && !row.capabilities.includes('commands'))
      || (row.declared_events.length > 0 && !row.capabilities.includes('events.observe'))
      || (!row.execution_available && (callableTools.length > 0 || callableCommands.length > 0))
      || (row.execution_available && !row.signature_verified)
      || ((callableTools.length > 0 || callableCommands.length > 0) && row.reason !== 'activated')) {
      throw new ApiError('Invalid extension inspection');
    }

    extensions.push({
      id: row.id,
      version: row.version,
      reason: row.reason,
      signatureVerified: row.signature_verified,
      approvalVerified: row.approval_verified,
      quarantineState: 'not_inspected',
      executionAvailable: row.execution_available,
      declaredTools,
      callableTools,
      declaredCommands,
      callableCommands,
      commandRequiresArgs,
      declaredEvents: row.declared_events as string[],
      capabilities: row.capabilities as string[],
    });
  }

  return { mode: 'inspection_only', reason: report.reason, extensions };
}

/** One user-authenticated, read-only snapshot. No retry or server body is exposed on failure. */
export async function fetchExtensionInspection(
  config: ServerConfig,
  signal: AbortSignal,
): Promise<ExtensionInspectionReport> {
  const base = normalizeBaseUrl(config.baseUrl);
  if (!base) throw new ApiError('No hub connected');

  const abort = new AbortController();
  const cancel = () => abort.abort();
  signal.addEventListener('abort', cancel, { once: true });
  if (signal.aborted) abort.abort();
  if (abort.signal.aborted) {
    signal.removeEventListener('abort', cancel);
    throw new ApiError('Extension inspection request cancelled or timed out');
  }

  const timer = setTimeout(cancel, 15000);
  try {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (config.token.trim()) headers['X-User-Token'] = config.token.trim();
    const response = await fetch(base + EXTENSIONS_INSPECTION_PATH, {
      method: 'GET', headers, signal: abort.signal, cache: 'no-store', redirect: 'error',
    });
    if (abort.signal.aborted) throw new ApiError('Extension inspection request cancelled or timed out');
    if (!response.ok) throw new ApiError('Extension inspection unavailable', response.status);
    const data: unknown = await response.json();
    if (abort.signal.aborted) throw new ApiError('Extension inspection request cancelled or timed out');
    return normalizeExtensionInspection(data);
  } catch (error) {
    if (abort.signal.aborted) throw new ApiError('Extension inspection request cancelled or timed out');
    if (error instanceof ApiError) throw error;
    throw new ApiError('Extension inspection unavailable');
  } finally {
    clearTimeout(timer);
    signal.removeEventListener('abort', cancel);
  }
}
