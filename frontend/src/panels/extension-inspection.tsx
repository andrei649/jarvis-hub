import React from 'react';
import { Card, Row, Tag, mono, useApi } from '../panel-kit';

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

type ExtensionRow = {
  id: string;
  version: string;
  reason: string;
  signature_verified: boolean;
  approval_verified: boolean;
  quarantine_state: 'not_inspected';
  execution_available: boolean;
  declared_tools: string[];
  declared_commands: string[];
  command_requires_args: string[];
  declared_events: string[];
  capabilities: string[];
  callable_tools: string[];
  callable_commands: string[];
};
type ExtensionReport = { mode: 'inspection_only'; reason: string; extensions: ExtensionRow[] };

function object(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}
function names(value: unknown, pattern: RegExp, limit = 64): string[] | null {
  if (!Array.isArray(value) || value.length > limit ||
      !value.every((item) => typeof item === 'string' && pattern.test(item))) return null;
  const result = value as string[];
  return new Set(result).size === result.length ? result : null;
}
function subset(items: string[], allowed: string[]): boolean {
  const set = new Set(allowed);
  return items.every((item) => set.has(item));
}
function normalizeReport(value: unknown): ExtensionReport | null {
  const report = object(value);
  if (!report || report.mode !== 'inspection_only' || typeof report.reason !== 'string' ||
      !REPORT_REASONS.has(report.reason) || !Array.isArray(report.extensions) || report.extensions.length > 128) return null;
  const rows: ExtensionRow[] = [];
  const ids = new Set<string>();
  for (const candidate of report.extensions) {
    const row = object(candidate);
    if (!row || typeof row.id !== 'string' || !NAME.test(row.id) ||
        typeof row.version !== 'string' || !VERSION.test(row.version) ||
        typeof row.reason !== 'string' || !ROW_REASONS.has(row.reason) ||
        typeof row.signature_verified !== 'boolean' || typeof row.approval_verified !== 'boolean' ||
        row.quarantine_state !== 'not_inspected' || typeof row.execution_available !== 'boolean' ||
        !Array.isArray(row.capabilities) || row.capabilities.length > 3 ||
        !row.capabilities.every((item) => typeof item === 'string' && CAPABILITIES.has(item)) ||
        new Set(row.capabilities).size !== row.capabilities.length ||
        !Array.isArray(row.declared_events) || row.declared_events.length > 64 ||
        !row.declared_events.every((item) => typeof item === 'string' && EVENTS.has(item)) ||
        new Set(row.declared_events).size !== row.declared_events.length || ids.has(row.id)) return null;
    ids.add(row.id);
    const declaredTools = names(row.declared_tools, TOOL);
    const callableTools = names(row.callable_tools, TOOL);
    const declaredCommands = names(row.declared_commands, NAME);
    const callableCommands = names(row.callable_commands, NAME);
    const requiresArgs = names(row.command_requires_args, NAME);
    if (!declaredTools || !callableTools || !declaredCommands || !callableCommands || !requiresArgs ||
        declaredTools.some((tool) => !tool.startsWith(`${row.id}.`)) ||
        callableTools.some((tool) => !tool.startsWith(`${row.id}.`)) ||
        !subset(callableTools, declaredTools) || !subset(callableCommands, declaredCommands) ||
        !subset(requiresArgs, declaredCommands) ||
        (declaredTools.length && !row.capabilities.includes('tools')) ||
        (declaredCommands.length && !row.capabilities.includes('commands')) ||
        (row.declared_events.length && !row.capabilities.includes('events.observe')) ||
        (!row.execution_available && (callableTools.length || callableCommands.length)) ||
        (row.execution_available && !row.signature_verified) ||
        ((callableTools.length || callableCommands.length) && row.reason !== 'activated')) return null;
    rows.push({
      id: row.id, version: row.version, reason: row.reason,
      signature_verified: row.signature_verified, approval_verified: row.approval_verified,
      quarantine_state: 'not_inspected', execution_available: row.execution_available,
      declared_tools: declaredTools, declared_commands: declaredCommands,
      command_requires_args: requiresArgs, declared_events: row.declared_events as string[],
      capabilities: row.capabilities as string[], callable_tools: callableTools,
      callable_commands: callableCommands,
    });
  }
  return { mode: 'inspection_only', reason: report.reason, extensions: rows };
}

const reportReason = (reason: string): string => ({
  acquisition_unavailable: 'Acquisition inspection is unavailable.',
  acquisition_disabled: 'Acquisition is disabled.',
  acquisition_not_composed: 'The acquisition runtime is not composed.',
  extension_capacity: 'The extension inspection capacity was reached.',
  sdk_dispatch_unavailable: 'SDK dispatch is unavailable.',
  activated: 'An activation is present; callable surfaces are listed per extension.',
  acquisition_inspection_unavailable: 'The extension inspection could not read its current state.',
}[reason] || 'Extension inspection returned an unknown status.');

function rowStatus(reason: string): string {
  return ({
    activated: 'Activated',
    acquired_inactive: 'Inactive',
    acquired_integrity_unverified: 'Integrity not verified',
    sdk_dispatch_unavailable: 'No callable surface',
  }[reason] || 'Status unavailable');
}

function readFailure(status: number): string {
  if (status === 401) return 'Sign in to inspect extensions.';
  if (status === 403) return 'This account cannot inspect extensions.';
  if (status === 503) return 'The extension inspection service is unavailable.';
  if (!status) return 'Extension inspection is offline.';
  return 'The extension inspection request failed.';
}

function Values({ label, items, requiresArgs = [], emptyLabel = 'none declared' }: {
  label: string; items: string[]; requiresArgs?: string[]; emptyLabel?: string;
}) {
  return <section aria-label={label} style={{ marginTop: 8 }}>
    <div style={{ ...mono, color: 'var(--ink-2)', fontSize: 10, marginBottom: 3 }}>{label.toUpperCase()}</div>
    {items.length ? <ul style={{ margin: '2px 0 0', paddingLeft: 18 }}>
      {items.map((item) => <li key={item} style={{ ...mono, fontSize: 10.5, padding: '2px 0' }}>
        {item}{requiresArgs.includes(item) && <Tag>requires arguments</Tag>}
      </li>)}
    </ul> : <div style={{ ...mono, color: 'var(--ink-2)', fontSize: 10 }}>{emptyLabel}</div>}
  </section>;
}

function ExtensionCard({ row }: { row: ExtensionRow }) {
  return <section aria-label={`Extension ${row.id}`} style={{ borderTop: '1px solid var(--panel-line)', paddingTop: 8, marginTop: 9 }}>
    <Row>
      <strong style={{ ...mono, color: 'var(--accent-light)' }}>{row.id}</strong>
      <Tag>{row.version}</Tag>
      <Tag>{rowStatus(row.reason)}</Tag>
    </Row>
    <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 6 }} aria-label={`${row.id} trust facts`}>
      <Tag>signature {row.signature_verified ? 'verified' : 'not verified'}</Tag>
      <Tag>owner approval {row.approval_verified ? 'verified' : 'not verified'}</Tag>
      <Tag>Quarantine not checked</Tag>
      <Tag>execution {row.execution_available ? 'available' : 'unavailable'}</Tag>
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 8 }}>
      <Values label="Declared tools" items={row.declared_tools} />
      <Values label="Currently callable tools" items={row.callable_tools} emptyLabel="none currently callable" />
      <Values label="Declared commands" items={row.declared_commands} requiresArgs={row.command_requires_args} />
      <Values label="Currently callable commands" items={row.callable_commands}
        requiresArgs={row.command_requires_args} emptyLabel="none currently callable" />
      <Values label="Declared events" items={row.declared_events} />
    </div>
  </section>;
}

export function ExtensionInspectionPanel() {
  const { d, e, status, loading, reload } = useApi(EXTENSIONS_INSPECTION_PATH);
  // useApi intentionally retains its last successful payload on failure. Hide it while
  // refreshing and whenever the refresh failed; this panel never presents stale state.
  const report = !loading && !e ? normalizeReport(d) : null;
  const failed = !loading && !!e;
  const malformed = !loading && !failed && d !== null && report === null;
  return <Card title="EXTENSION INSPECTION" sub="read-only · current snapshot" onReload={reload}>
    <div style={{ ...mono, color: 'var(--ink-2)', fontSize: 10, marginBottom: 7 }}>
      Inspect declared and currently available tools and commands.
    </div>
    {loading && <div role="status" style={{ color: 'var(--ink-2)', fontSize: 12 }}>Checking extension state…</div>}
    {failed && <div role="alert" style={{ color: 'var(--amber)', fontSize: 12 }}>{readFailure(status)}</div>}
    {malformed && <div role="alert" style={{ color: 'var(--amber)', fontSize: 12 }}>Extension inspection returned invalid data.</div>}
    {report && <>
      <div role="status" style={{ color: 'var(--ink-2)', fontSize: 11 }}>{reportReason(report.reason)}</div>
      {report.extensions.length > 0 && <p style={{ color: 'var(--ink-2)', fontSize: 10, margin: '5px 0' }}>
        Signature verification, owner approval, and current callability are separate facts.
      </p>}
      {report.extensions.length ? report.extensions.map((row) => <ExtensionCard key={row.id} row={row} />)
        : <div style={{ ...mono, color: 'var(--ink-2)', fontSize: 10, marginTop: 8 }}>No extensions reported in this inspection.</div>}
    </>}
  </Card>;
}

export { normalizeReport as normalizeExtensionInspection };
