import React from 'react';
import { asLive, Card, Row, State, mono, useApi } from '../panel-kit';

type Counts = {
  runs: number; input_tokens: number; output_tokens: number;
  cost_usd: number; unpriced_calls: number;
};
type AgentRow = Counts & { agent: string; model: string; priced: boolean };
type ModelRow = Counts & { model: string; estimated_from_last_model?: boolean; legacy_unattributed?: boolean };
type Summary = {
  totals: Counts;
  by_agent: AgentRow[];
  by_model: ModelRow[];
  by_locality?: Record<'local' | 'cloud' | 'unknown', Counts>;
};

const integer = (n: number) => Number.isFinite(n) ? n.toLocaleString('en-US') : '—';
const dollars = (n: number) => Number.isFinite(n) ? `$${n.toFixed(6)}` : '—';
const tokens = (row: Counts) => integer(row.input_tokens + row.output_tokens);
const tokensNumber = (row: Counts) => row.input_tokens + row.output_tokens;
const colors = { local: 'var(--green)', cloud: 'var(--amber)', unknown: 'var(--ink-2)' };

function LocalityBar({ name, values }: { name: string; values: Record<'local' | 'cloud' | 'unknown', number> }) {
  const total = values.local + values.cloud + values.unknown;
  return <div role="meter" aria-label={name} aria-valuemin={0} aria-valuemax={100}
    aria-valuenow={total ? 100 * values.local / total : 0}
    aria-valuetext={total ? `local ${Math.round(100 * values.local / total)}%, cloud ${Math.round(100 * values.cloud / total)}%, unknown ${Math.round(100 * values.unknown / total)}%` : 'no known amount'}
    style={{ display: 'flex', height: 8, width: '100%', background: 'var(--surface)', borderRadius: 4, overflow: 'hidden', margin: '5px 0' }}>
    {(['local', 'cloud', 'unknown'] as const).map(key =>
      <span key={key} title={`${key}: ${values[key]}`} style={{ width: total ? `${100 * values[key] / total}%` : '0%', background: colors[key] }} />)}
  </div>;
}

function UsageRow({ label, row }: { label: string; row: Counts }) {
  return <Row>
    <span>{label}</span>
    <span style={{ marginLeft: 'auto', textAlign: 'right' }}>
      {integer(row.runs)} runs · {tokens(row)} tokens ({integer(row.input_tokens)} in / {integer(row.output_tokens)} out) · {dollars(row.cost_usd)} estimated
      {row.unpriced_calls > 0 && <span> · {integer(row.unpriced_calls)} unpriced call{row.unpriced_calls === 1 ? '' : 's'}</span>}
    </span>
  </Row>;
}

/** Read-only usage snapshot from the existing APM rollup; each call is classified at record time. */
export function UsagePanel() {
  const { d, e, loading, reload } = useApi('/api/admin/apm');
  const summary = d as Summary | null;
  const totals = summary?.totals;
  return <Card title="USAGE" live={asLive(d)} onReload={reload}>
    <State e={e} loading={loading} n={totals ? 1 : 0} />
    {totals && <div style={{ ...mono, fontSize: 11 }}>
      <h3>Totals</h3>
      <UsageRow label="all usage" row={totals} />
      <p style={{ color: 'var(--ink-2)' }}>Costs are token price estimates for known models. Unpriced calls are excluded from dollar amounts; totals are not an invoice.</p>
      <h3>Where it ran</h3>
      {summary.by_locality ? <>
        <div>Token locality</div>
        <LocalityBar name="Token locality" values={{
          local: tokensNumber(summary.by_locality.local),
          cloud: tokensNumber(summary.by_locality.cloud),
          unknown: tokensNumber(summary.by_locality.unknown),
        }} />
        <div>Known estimated cost locality</div>
        <LocalityBar name="Known estimated cost locality" values={{
          local: summary.by_locality.local.cost_usd,
          cloud: summary.by_locality.cloud.cost_usd,
          unknown: summary.by_locality.unknown.cost_usd,
        }} />
        <p style={{ color: 'var(--ink-2)' }}>Cost bar includes priced calls only; unpriced costs are unknown.</p>
        {(['local', 'cloud', 'unknown'] as const).map(name =>
          <UsageRow key={name} label={name} row={summary.by_locality![name]} />)}
      </> : <p>Route attribution unavailable for this rollup.</p>}
      <h3>By agent</h3>
      {summary.by_agent?.length ? summary.by_agent.map(row =>
        <UsageRow key={row.agent} label={row.agent} row={row} />) : <p>No recorded calls.</p>}
      <h3>By model</h3>
      {summary.by_model?.length ? summary.by_model.map(row =>
        <React.Fragment key={row.model}>
          <UsageRow label={row.model} row={row} />
          {row.estimated_from_last_model && <p>Legacy model attribution for {row.model} is estimated from the last recorded model.</p>}
          {row.legacy_unattributed && <p>Legacy calls have no reliable model attribution.</p>}
        </React.Fragment>) : <p>No recorded models.</p>}
    </div>}
  </Card>;
}
