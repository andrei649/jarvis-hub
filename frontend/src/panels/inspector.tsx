/* H227 — "what can it do right now": the Inspector panel.

   One read of the admin-only GET /api/admin/inspector — the payload `nerva inspect`
   renders — for an agent as a chosen principal sees it: the owner or a guest on the HUD,
   the owner or a stranger on an external channel, or no human (a job). The status line
   says what serves the agent; the sections below it fold open: the tools its profile
   offers (gated and untrusted-output marked, the withheld ones counted), the skills its
   prompt names, the MCP servers with their liveness, and the resolved prompt for an empty
   user message, secrets masked by the hub and capped at 64 KB. Read-only. */
import React, { useMemo, useState } from 'react';
import { Card, Row, State, Tag, inpS, mono, useApi } from '../panel-kit';

export const INSPECTOR_VIEWS = ['owner', 'guest', 'inbound-owner', 'inbound', 'internal'];
export const VIEW_LABELS: Record<string, string> = {
  owner: 'owner · HUD',
  guest: 'guest · HUD',
  'inbound-owner': 'owner · channel',
  inbound: 'stranger · channel',
  internal: 'no human',
};

export function inspectorPath(agent: string, view: string): string {
  const q = new URLSearchParams({ agent: agent.trim() || 'jarvis', view });
  return `/api/admin/inspector?${q.toString()}`;
}

/** The status line: what serves the agent right now. */
export function statusLine(s: any): string {
  if (!s) return '';
  const parts = [`backend ${s.backend || 'none'}`, `model ${s.model || '?'}`,
    `${s.model_state || 'unknown'}${s.loaded_model ? ` (${s.loaded_model})` : ''}`,
    `context budget ${s.context_tokens ? s.context_tokens : '75% of the model window'}`,
    `tool loop ${s.tool_loop ? 'on' : 'off'}`];
  if (s.safe_mode) parts.push('SAFE MODE');
  return parts.join(' · ');
}

function Section({ title, sub, children }: { title: string; sub?: string; children?: any }) {
  return (
    <details style={{ marginTop: 6 }}>
      <summary style={{ cursor: 'pointer', ...mono }}>{title}{sub ? <span style={{ color: 'var(--ink-3)' }}> · {sub}</span> : null}</summary>
      <div style={{ paddingLeft: 8 }}>{children}</div>
    </details>
  );
}

const pre = { ...mono, fontSize: 10, whiteSpace: 'pre-wrap' as const, wordBreak: 'break-word' as const, margin: '4px 0', maxHeight: 360, overflow: 'auto' };

export function InspectorPanel() {
  const [agent, setAgent] = useState('jarvis');
  const [draft, setDraft] = useState('jarvis');
  const [view, setView] = useState('owner');
  const path = useMemo(() => inspectorPath(agent, view), [agent, view]);
  const { d, e, status, loading, reload } = useApi(path, true, true);
  const p = e ? null : d;
  const tools = p?.tools; const skills = p?.skills; const mcp = p?.mcp; const prompt = p?.system_prompt;
  const missing = status === 404;
  return (
    <Card title="INSPECTOR" sub={p ? `${p.agent} · ${p.posture}` : undefined} onReload={reload}>
      <form onSubmit={(ev) => { ev.preventDefault(); setAgent(draft); }} style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        <input aria-label="Agent" value={draft} onChange={(ev) => setDraft(ev.target.value)} style={{ ...inpS, width: 110 }} />
        <div role="group" aria-label="As" style={{ display: 'flex', gap: 2 }}>
          {INSPECTOR_VIEWS.map((v) => (
            <button key={v} type="button" className="tool-btn" aria-pressed={v === view} onClick={() => setView(v)}
              style={{ padding: '2px 6px', opacity: v === view ? 1 : 0.55 }}>{VIEW_LABELS[v]}</button>
          ))}
        </div>
      </form>
      {missing ? <div style={{ color: 'var(--amber)', fontSize: 12 }}>no agent named {agent}</div>
        : <State e={e} loading={loading && !p} n={p ? 1 : undefined} />}
      {p?.status ? <div style={{ ...mono, fontSize: 10.5, margin: '6px 0' }}>{statusLine(p.status)}</div> : null}
      {tools ? (
        <Section title="Tools" sub={`${(tools.offered || []).length} offered of ${tools.registry || 0}`}>
          {!tools.wired ? <div style={{ fontSize: 10, color: 'var(--amber)' }}>the tool runtime is not wired</div>
            : tools.error ? <div style={{ fontSize: 10, color: 'var(--amber)' }}>the offer could not be resolved, so nothing is offered</div>
            : !tools.loop_enabled ? <div style={{ fontSize: 10, color: 'var(--amber)' }}>the tool loop is off: none of these reach the model until llm.tool_loop_enabled is on</div>
            : null}
          {(tools.offered || []).map((t: any) => (
            <Row key={t.name}>
              <span style={{ ...mono, minWidth: 130 }}>{t.name}</span>
              {t.gated ? <Tag c="var(--amber)">gated</Tag> : null}
              {t.untrusted_output ? <Tag c="var(--red)">untrusted output</Tag> : null}
              <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>{t.description}</span>
            </Row>
          ))}
          {(tools.withheld || []).length ? (
            <div style={{ fontSize: 10, color: 'var(--ink-3)', marginTop: 4 }}>withheld ({tools.withheld.length}): {tools.withheld.join(', ')}</div>
          ) : null}
        </Section>
      ) : null}
      {skills ? (
        <Section title="Skills" sub={skills.in_prompt ? `${skills.count} in the prompt` : 'none in the prompt (llm.skills_in_prompt is off)'}>
          {(skills.rows || []).map((r: any) => (
            <Row key={`${r.skill}:${r.command}`}><span style={{ ...mono, minWidth: 130 }}>{r.command}</span><span style={{ fontSize: 10, color: 'var(--ink-3)' }}>{r.description}</span></Row>
          ))}
        </Section>
      ) : null}
      {mcp ? (
        <Section title="MCP servers" sub={`${(mcp.servers || []).length} · ${mcp.connected || 0} connected`}>
          {(mcp.servers || []).map((s: any) => (
            <Row key={s.name}>
              <span style={{ ...mono, minWidth: 100 }}>{s.name}</span>
              <Tag>{s.transport}</Tag><Tag>{s.trust}</Tag>
              <Tag c={s.connected ? 'var(--green)' : 'var(--amber)'}>{s.connected ? 'connected' : 'down'}</Tag>
              <span style={{ fontSize: 10, color: 'var(--ink-3)' }}>{s.tools} tools{(s.tool_names || []).length ? `: ${s.tool_names.join(', ')}` : ''}</span>
            </Row>
          ))}
        </Section>
      ) : null}
      {prompt ? (
        <Section title="System prompt" sub={prompt.withheld ? 'withheld' : `about ${prompt.tokens} tokens before any history · ${prompt.bytes} bytes${prompt.truncated ? `, shown to ${prompt.cap}` : ''}`}>
          {prompt.withheld ? <div style={{ fontSize: 10, color: 'var(--amber)' }}>withheld: the secret redactor could not be loaded</div> : (
            <>
              <div style={{ fontSize: 10, color: 'var(--ink-3)' }}>system</div>
              <pre aria-label="System part" style={pre}>{prompt.system}</pre>
              <div style={{ fontSize: 10, color: 'var(--ink-3)' }}>turn (an empty user message)</div>
              <pre aria-label="Turn part" style={pre}>{prompt.turn}</pre>
            </>
          )}
        </Section>
      ) : null}
    </Card>
  );
}
