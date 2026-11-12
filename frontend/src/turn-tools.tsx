/* H137 — what the agent ran during a turn, and what it queued for the owner, inline with
   the reply.

   - Tool cards: the HUD asks /chat/stream for `tool_events`; each `tool` frame carries only
     the trail's live fields (event, tool, call id, status — never arguments or results,
     agents/core/observability/tool_events.py LIVE_FIELDS). One card per call, updated in
     place as the call moves from requested to running to done or failed.
   - Approvals: the end frame's `pending_approvals` are the ids of the cards this turn put
     in the decision inbox. Each is listed under the reply as a link that opens the inbox on
     that card (`?card=<id>`); the decision itself is only ever made there. */
import React from 'react';
import { appUrl } from './base-path';

export type ToolCard = { key: string; tool: string; state: 'requested' | 'running' | 'done' | 'failed' | 'stopped'; event: string };

const MAX_CARDS = 24;

function stateOf(event: string, status: unknown, prior?: ToolCard['state']): ToolCard['state'] {
  if (event === 'tool_failed' || status === 'failed' || status === 'error') return 'failed';
  if (event === 'tool_result' || event === 'tool_result_untrusted' || status === 'done' || status === 'ok' || status === 'completed') return 'done';
  if (event === 'tool_loop_repeated' || event === 'tool_loop_failing' || event === 'tool_cap_reached') return 'stopped';
  if (event === 'tool_started' || event === 'tool_heartbeat' || status === 'running') return 'running';
  return prior || 'requested';
}

/** Fold one `tool` stream frame into the turn's cards (new list; bounded). */
export function mergeToolEvent(cards: ToolCard[] | undefined, row: any): ToolCard[] {
  const list = Array.isArray(cards) ? cards : [];
  if (!row || typeof row !== 'object') return list;
  const event = typeof row.event === 'string' ? row.event.slice(0, 64) : '';
  const tool = typeof row.tool === 'string' ? row.tool.slice(0, 128) : '';
  if (!tool) return list;                         // profile/loop rows without a tool: no card
  const key = typeof row.call_id === 'string' && row.call_id ? row.call_id.slice(0, 128) : `${tool}#${list.length}`;
  const at = list.findIndex((c) => c.key === key);
  if (at >= 0) {
    const next = list.slice();
    const prior = next[at];
    // A finished call does not go back to running on a late heartbeat.
    const state = prior.state === 'done' || prior.state === 'failed' ? prior.state : stateOf(event, row.status, prior.state);
    next[at] = { ...prior, state, event: event || prior.event };
    return next;
  }
  if (list.length >= MAX_CARDS) return list;
  return [...list, { key, tool, state: stateOf(event, row.status), event }];
}

const COLOUR: Record<ToolCard['state'], string> = {
  requested: 'var(--ink-2)', running: 'var(--accent-light)', done: 'var(--green)', failed: 'var(--red)', stopped: 'var(--amber)',
};
const LABEL: Record<ToolCard['state'], string> = {
  requested: 'requested', running: 'running…', done: 'done', failed: 'failed', stopped: 'stopped by the loop guard',
};

export function TurnTools({ tools }: { tools?: ToolCard[] }) {
  if (!Array.isArray(tools) || !tools.length) return null;
  return (
    <div className="turn-tools" role="list" aria-label="tools this turn ran" style={{ display: 'flex', flexWrap: 'wrap', gap: 4, margin: '4px 0' }}>
      {tools.map((c) => (
        <span role="listitem" key={c.key} data-state={c.state} className="turn-tool"
          style={{ fontFamily: 'var(--font-mono)', fontSize: 10, border: '1px solid var(--panel-line)', borderRadius: 4, padding: '2px 6px', color: COLOUR[c.state] }}>
          ⚙ {c.tool} · {LABEL[c.state]}
        </span>
      ))}
    </div>
  );
}

/** The approval cards a turn queued, as ids; only well-formed positive integers are shown. */
export function approvalIds(raw: unknown): number[] {
  if (!Array.isArray(raw)) return [];
  return raw.filter((x) => Number.isInteger(x) && (x as number) > 0).slice(0, 20) as number[];
}

export function TurnApprovals({ ids }: { ids?: number[] }) {
  if (!Array.isArray(ids) || !ids.length) return null;
  return (
    <div className="turn-approvals" role="note" style={{ fontSize: 11, color: 'var(--amber)', margin: '4px 0' }}>
      {ids.length === 1 ? '1 action waits' : `${ids.length} actions wait`} for your decision:{' '}
      {ids.map((id, i) => <span key={id}>{i ? ', ' : ''}<a href={appUrl(`/v2/console/decision-inbox?card=${id}`)}
        style={{ color: 'var(--accent-light)' }}>card #{id}</a></span>)}
      {' · decided only in the Decision Inbox'}
    </div>
  );
}
