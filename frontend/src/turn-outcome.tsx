import React from 'react';
import type { PowerState } from './power-chip';

export type TurnOutcome = {
  latency_ms?: number;
  duration_ms?: number;
  prompt_elapsed_ms?: number;
  model?: string;
  context_detail?: { prompt_tokens: number; window_tokens: number };
  context_pct?: number;
  cache_hit?: number;
  tps?: number;
  compressions?: number;
  total_tokens?: number;
  title?: string;
  battery?: true;
  completion?: { kind: string; explanation: string; severity: 'info' | 'warning'; unanswered_tool_results: number };
  tools?: { proposed: number; queued: number; executed: number | null; failures: number | null; basis: 'observed' | 'unknown' };
  output?: { tokens: number | null; basis: 'provider_complete' | 'visible_estimate' | 'unknown' };
  file_mutations?: Array<{ attempt: number; operation: 'write' | 'delete'; outcome: 'refused' | 'unknown' | 'applied_unverified' }>;
  file_mutation_attribution?: 'unknown';
  recall?: TurnRecall;
};

/** H430: what the turn's last memory prefetch put in the prompt — counts and closed words. */
export type TurnRecall = {
  schema: 'nerva.recall-status.v1';
  provider: 'long_term_memory';
  basis: 'this_turn' | 'previous_recall' | 'unavailable';
  recalled: number | null;
  withheld: Partial<Record<WithheldReason, number>>;
  untrusted: number;
};

// The closed vocabulary of agents/core/memory/recall_admission.py, in its order.
const WITHHELD_REASONS = ['rejected_taint', 'rejected_privacy', 'rejected_stale',
  'rejected_contradiction', 'abstained'] as const;
type WithheldReason = typeof WITHHELD_REASONS[number];
const RECALL_PROVIDERS: Record<TurnRecall['provider'], string> = { long_term_memory: 'Long-term memory' };
const MAX_RECALL_COUNT = 10_000;
const recallCount = (value: unknown): value is number => count(value) && value <= MAX_RECALL_COUNT;

/** Mirror of recall_admission.valid_recall_status: a status or nothing, never a partial one. */
export function turnRecall(value: unknown): TurnRecall | null {
  if (!object(value)) return null;
  const keys = Object.keys(value).sort().join(',');
  if (keys !== 'basis,provider,recalled,schema,untrusted,withheld') return null;
  if (value.schema !== 'nerva.recall-status.v1' || value.provider !== 'long_term_memory') return null;
  if (!['this_turn', 'previous_recall', 'unavailable'].includes(String(value.basis))) return null;
  const { recalled, untrusted, withheld } = value;
  if (!(recalled === null || recallCount(recalled)) || !recallCount(untrusted) || !object(withheld)) return null;
  if (!Object.entries(withheld).every(([name, n]) =>
    (WITHHELD_REASONS as readonly string[]).includes(name) && recallCount(n) && n > 0)) return null;
  const reasons = Object.keys(withheld).length;
  const used = recalled as number | null;   // checked just above
  if (used === null) {
    if (reasons || untrusted) return null;
  } else if (untrusted > used || (value.basis === 'unavailable' && (used || reasons))) return null;
  return value as TurnRecall;
}

/** Mirror of recall_admission.describe_recall — the shared cases in
 *  test/recall-line-cases.json pin the two to the same line for the same status. */
export function recallLine(recall: TurnRecall): string {
  const label = RECALL_PROVIDERS[recall.provider];
  if (recall.basis === 'unavailable') return `🧠 ${label} — unavailable this turn, no memory used`;
  const parts: string[] = [];
  if (recall.recalled === null) parts.push('recalled relevant memory');
  else if (recall.recalled) parts.push(recall.recalled === 1 ? 'recalled 1 memory' : `recalled ${recall.recalled} memories`);
  if (parts.length && recall.basis === 'previous_recall') parts[0] += " from this session's previous recall";
  if (parts.length && recall.untrusted) parts[0] += ` (${recall.untrusted} from an untrusted source)`;
  const reasons = WITHHELD_REASONS.filter(name => recall.withheld[name]);
  const total = reasons.reduce((sum, name) => sum + (recall.withheld[name] ?? 0), 0);
  if (total) parts.push(`${total} withheld (${reasons.map(name =>
    `${name.replace(/^rejected_/, '')}: ${recall.withheld[name]}`).join(', ')})`);
  return parts.length ? `🧠 ${label} — ${parts.join(', ')}` : '';
}

const count = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
const object = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value);
const percent = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100;
const finitePositive = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0;

/** Parse an untrusted SSE projection field by field; partial progress is useful. */
export function turnOutcome(value: unknown): TurnOutcome | null {
  if (!object(value)) return null;
  const result: TurnOutcome = {};
  if (typeof value.latency_ms === 'number' && Number.isFinite(value.latency_ms) && value.latency_ms >= 0)
    result.latency_ms = value.latency_ms;
  if (count(value.duration_ms)) result.duration_ms = value.duration_ms;
  if (count(value.prompt_elapsed_ms)) result.prompt_elapsed_ms = value.prompt_elapsed_ms;
  if (typeof value.model === 'string' && value.model.length <= 120
      && /^[A-Za-z0-9][A-Za-z0-9._:/+\-]*$/.test(value.model)) result.model = value.model;
  if (object(value.context_detail) && count(value.context_detail.prompt_tokens)
      && count(value.context_detail.window_tokens) && value.context_detail.window_tokens > 0
      && value.context_detail.prompt_tokens <= value.context_detail.window_tokens)
    result.context_detail = value.context_detail as TurnOutcome['context_detail'];
  if (percent(value.context_pct)) {
    if (!result.context_detail || Math.abs(value.context_pct
      - 100 * result.context_detail.prompt_tokens / result.context_detail.window_tokens) < 1e-6)
      result.context_pct = value.context_pct;
  }
  if (percent(value.cache_hit)) result.cache_hit = value.cache_hit;
  if (finitePositive(value.tps)) result.tps = value.tps;
  if (count(value.compressions)) result.compressions = value.compressions;
  if (count(value.total_tokens)) result.total_tokens = value.total_tokens;
  if (typeof value.title === 'string' && value.title.trim() && value.title.length <= 200)
    result.title = value.title;
  if (value.battery === true) result.battery = true;
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
  const recall = turnRecall(value.recall);
  if (recall) result.recall = recall;
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
export function StatusStrip({ outcome, power }: { outcome?: TurnOutcome | null; power?: PowerState }) {
  if (!outcome) return null;
  const recall = outcome.recall ? recallLine(outcome.recall) : '';
  return <section aria-label="Turn outcome" style={{ display: 'block', padding: '4px 8px',
    color: 'var(--ink-2)', fontFamily: 'var(--font-mono)', fontSize: 10,
    width: '100%', maxWidth: '100%', minWidth: 0, minHeight: 0, flexShrink: 1, boxSizing: 'border-box',
    maxHeight: '35vh', overflowX: 'auto', overflowY: 'auto', overflowWrap: 'anywhere',
    lineHeight: 1.4 }}>
    {outcome.latency_ms !== undefined && <output aria-label="Turn duration" style={{ display: 'block' }}>
      Turn duration: {durationText(outcome.latency_ms)}
    </output>}
    {outcome.model && <output aria-label="Request model" style={{ display: 'block' }}>Model: {outcome.model}</output>}
    {outcome.context_detail && <output aria-label="Prompt context" style={{ display: 'block' }}>
      Prompt context: {outcome.context_detail.prompt_tokens} / {outcome.context_detail.window_tokens}
    </output>}
    {outcome.context_pct !== undefined && <output aria-label="Prompt context percent" style={{ display: 'block' }}>
      Context: {outcome.context_pct.toFixed(1)}%
    </output>}
    {outcome.cache_hit !== undefined && <output aria-label="Prompt cache hit"
      data-band={outcome.cache_hit >= 70 ? 'high' : outcome.cache_hit >= 40 ? 'medium' : 'low'}
      style={{ display: 'block', color: outcome.cache_hit >= 70 ? 'var(--accent)' : outcome.cache_hit >= 40 ? 'var(--amber)' : 'var(--red, #ef4444)' }}>
      Cache hit since invalidation: {outcome.cache_hit.toFixed(1)}%
    </output>}
    {outcome.tps !== undefined && <output aria-label="Request output tokens per second" style={{ display: 'block' }}>
      Request output tokens/s: {outcome.tps.toFixed(1)}
    </output>}
    {outcome.compressions !== undefined && <output aria-label="Accepted compressions" style={{ display: 'block' }}>
      Accepted compressions: {outcome.compressions}
    </output>}
    {outcome.duration_ms !== undefined && <output aria-label="Turn generation and settlement" style={{ display: 'block' }}>
      Generation and settlement: {durationText(outcome.duration_ms)}
    </output>}
    {outcome.prompt_elapsed_ms !== undefined && <output aria-label="Prompt elapsed to first visible chunk" style={{ display: 'block' }}>
      First visible chunk: {durationText(outcome.prompt_elapsed_ms)}
    </output>}
    {outcome.total_tokens !== undefined && <output aria-label="Total provider tokens" style={{ display: 'block' }}>
      Total provider tokens: {outcome.total_tokens}
    </output>}
    {outcome.title && <output aria-label="Session title" style={{ display: 'block' }}>Session: {outcome.title}</output>}
    {outcome.battery && power?.onBattery && <output aria-label="Battery" style={{ display: 'block' }}>
      Battery: {power.percent === null ? 'on battery' : `${power.percent}%`}
    </output>}
    {outcome.output && <output aria-label="Output token flow" style={{ display: 'block' }}>
      {outputText(outcome.output)}
    </output>}
    {recall && <output aria-label="Memory recall" style={{ display: 'block' }}>{recall}</output>}
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
