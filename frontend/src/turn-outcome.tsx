import React from 'react';

export type TurnOutcome = {
  latency_ms?: number;
  completion?: { kind: string; explanation: string; severity: 'info' | 'warning'; unanswered_tool_results: number };
  tools?: { proposed: number; queued: number; executed: number | null; failures: number | null; basis: 'observed' | 'unknown' };
  output?: { tokens: number | null; basis: 'provider_complete' | 'visible_estimate' | 'unknown' };
  file_mutations?: Array<{ attempt: number; operation: 'write' | 'delete'; outcome: 'refused' | 'unknown' | 'applied_unverified' }>;
  file_mutation_attribution?: 'unknown';
};

const count = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const object = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value);

/** Parse an untrusted SSE projection field by field; partial progress is useful. */
export function turnOutcome(value: unknown): TurnOutcome | null {
  if (!object(value)) return null;
  const result: TurnOutcome = {};
  if (typeof value.latency_ms === 'number' && Number.isFinite(value.latency_ms) && value.latency_ms >= 0)
    result.latency_ms = value.latency_ms;
  if (object(value.completion) && typeof value.completion.kind === 'string'
      && typeof value.completion.explanation === 'string'
      && (value.completion.severity === 'info' || value.completion.severity === 'warning')
      && count(value.completion.unanswered_tool_results)) {
    result.completion = value.completion as TurnOutcome['completion'];
  }
  if (object(value.tools) && count(value.tools.proposed) && count(value.tools.queued)
      && (value.tools.executed === null || count(value.tools.executed))
      && (value.tools.failures === null || count(value.tools.failures))
      && (value.tools.basis === 'observed' || value.tools.basis === 'unknown')) {
    result.tools = value.tools as TurnOutcome['tools'];
  }
  if (object(value.output) && (value.output.tokens === null || count(value.output.tokens))
      && ['provider_complete', 'visible_estimate', 'unknown'].includes(String(value.output.basis))) {
    result.output = value.output as TurnOutcome['output'];
  }
  if (Array.isArray(value.file_mutations)) {
    const items = value.file_mutations.filter((item): item is NonNullable<TurnOutcome['file_mutations']>[number] =>
      object(item) && count(item.attempt) && item.attempt > 0
      && (item.operation === 'write' || item.operation === 'delete')
      && ['refused', 'unknown', 'applied_unverified'].includes(String(item.outcome)));
    // The trusted queue caps one origin at 256 signed attempts.
    if (items.length && items.length === value.file_mutations.length && items.length <= 256)
      result.file_mutations = items;
  }
  if (value.file_mutation_attribution === 'unknown') result.file_mutation_attribution = 'unknown';
  return Object.keys(result).length ? result : null;
}

function durationText(ms: number): string {
  if (ms === 0) return '0 ms';
  if (ms < 1000) return `${Math.max(1, Math.round(ms))} ms`;
  return `${(ms / 1000).toFixed(2).replace(/\.?0+$/, '')} s`;
}

function outputText(output: NonNullable<TurnOutcome['output']>): string {
  if (output.tokens === null) return 'Output tokens: unknown';
  if (output.basis === 'provider_complete') return `Output tokens: ${output.tokens} (provider reported)`;
  return `Visible output: ~${output.tokens} tokens (text estimate)`;
}

/** Whole-turn result and live output flow; no objective-success claim. */
export function StatusStrip({ outcome }: { outcome?: TurnOutcome | null }) {
  if (!outcome) return null;
  return <section aria-label="Turn outcome" style={{ display: 'block', padding: '4px 8px',
    color: 'var(--ink-2)', fontFamily: 'var(--font-mono)', fontSize: 10 }}>
    {outcome.latency_ms !== undefined && <output aria-label="Turn duration">
      Turn duration: {durationText(outcome.latency_ms)}
    </output>}
    {outcome.output && <output aria-label="Output token flow" style={{ display: 'block' }}>
      {outputText(outcome.output)}
    </output>}
    {outcome.tools && <div aria-label="Tool call accounting">
      Tools proposed {outcome.tools.proposed}, queued {outcome.tools.queued}; executed{' '}
      {outcome.tools.executed ?? 'unknown'}, failed {outcome.tools.failures ?? 'unknown'} ({outcome.tools.basis})
    </div>}
    {outcome.completion && <div role="status" aria-label="Turn completion"
      style={{ color: outcome.completion.severity === 'warning' ? 'var(--amber)' : 'var(--ink-2)' }}>
      {outcome.completion.severity === 'warning' ? 'Warning' : 'Info'}: {outcome.completion.explanation}
      {outcome.completion.unanswered_tool_results > 0
        ? ` ${outcome.completion.unanswered_tool_results} accepted tool result(s) were not covered by a later model answer.` : ''}
    </div>}
    {!!outcome.file_mutations?.length && <aside aria-label="File mutation notes">
      {outcome.file_mutations.map((item) => <div key={item.attempt}>
        File {item.operation} attempt {item.attempt}: {item.outcome === 'refused' ? 'refused before effect'
          : item.outcome === 'unknown' ? 'effect uncertain' : 'effect not verified'}.
      </div>)}
    </aside>}
    {outcome.file_mutation_attribution === 'unknown' && <div aria-label="File mutation attribution">
      A file mutation result could not be linked to this turn.
    </div>}
  </section>;
}
