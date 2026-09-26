/* H315 — the agent's plans, next to the decisions they lead to.

   The model keeps a checklist with its `todo` tool (agents/core/todo_tool.py) and
   re-reads it on every call. The owner reads the same lists here, in the Decision
   Inbox, so intent is visible before an approval card appears: "here is what I plan
   to do" instead of only "approve this command".

   Only plans with work still open are shown (a plan whose items are all completed or
   cancelled is history, readable with `nerva todo`), at most PLANS_SHOWN of them and
   ITEMS_SHOWN items each, with how long ago each was written: a plan abandoned days ago
   does not look live. Each item says who wrote its text when it was not the owner (a
   guest's, a household member's or a background turn) and whether that text came from
   an untrusted source (the H315 review: tags are per item, so a merge by the owner
   cannot relabel a guest's text). A failed read says it failed; it is never drawn as
   "no plans".

   H666 — a subtask sits indented under its parent (`parent` is another item's id), drawn
   by todoTree, the twin of the CLI's builder: a missing, self or cyclic parent draws at
   the top and no item is dropped. ITEMS_SHOWN counts rows in that order. */
import React from 'react';
import { Row, Tag, arr, mono } from '../panel-kit';
import { todoTree } from '../todo-tree';

export const PLANS_PATH = '/sessions/todo';
export const PLANS_SHOWN = 3;
export const ITEMS_SHOWN = 8;
const OPEN = new Set(['pending', 'in_progress']);
const MARKS: Record<string, string> = { pending: '○', in_progress: '▶', completed: '✓', cancelled: '–' };
const WORDS: Record<string, string> = {
  pending: 'to do', in_progress: 'in progress', completed: 'done', cancelled: 'cancelled',
};

type Item = { id?: string; content?: string; status?: string; by?: string; tainted?: boolean; parent?: string };
type Plan = { session_id?: string; agent?: string; posture?: string; updated_at?: number; todos?: Item[] };
const WRITERS: Record<string, string> = { guest: 'guest turn', system: 'background turn' };

/** What the owner should know about an item's text: whose turn wrote it when it was not
    the owner's (operator/guest is a household member) and whether it is untrusted. */
export function itemTags(item: Item): string[] {
  const [surface, principal] = String(item?.by || '').split('/');
  const tags: string[] = [];
  if (principal === 'guest' && surface === 'operator') tags.push('household turn');
  else if (principal && WRITERS[principal]) tags.push(WRITERS[principal]);
  if (item?.tainted === true) tags.push('untrusted source');
  return tags;
}

/** "just now", "12 min ago", "5 h ago", "3 d ago"; empty when the hub sent no time. */
export function planAge(updated: unknown, now: number = Date.now()): string {
  if (typeof updated !== 'number' || !Number.isFinite(updated)) return '';
  const seconds = Math.max(0, Math.round(now / 1000 - updated));
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return `${Math.floor(seconds / 86400)} d ago`;
}

/** Plans with at least one open item, most recent first, capped. */
export function openPlans(reply: any): Plan[] {
  return arr(reply, 'plans')
    .filter((plan: Plan) => arr(plan?.todos).some((item: Item) => OPEN.has(String(item?.status))))
    .slice(0, PLANS_SHOWN);
}

export function PlansInFlight({ reply, error }: { reply: any; error?: string | null }) {
  if (error) {
    return <div style={{ fontSize: 10, color: 'var(--amber)', marginTop: 6 }}>plans unavailable · {error}</div>;
  }
  const plans = openPlans(reply);
  if (!plans.length) return null;
  return (
    <section aria-label="plans in flight" data-testid="plans-in-flight" style={{ marginTop: 8 }}>
      <div style={{ ...mono, fontSize: 9.5, color: 'var(--ink-2)', letterSpacing: '.06em' }}>
        PLANS IN FLIGHT · what the agent intends, before any approval it leads to
      </div>
      {plans.map((plan, i) => {
        const items = arr(plan.todos) as Item[];
        const rows = todoTree(items, (item) => item?.id, (item) => item?.parent);
        const done = items.filter((item) => item.status === 'completed').length;
        const age = planAge(plan.updated_at);
        return (
          <div key={plan.session_id || i}>
            <Row>
              <span style={{ ...mono, color: 'var(--accent-light)' }}>{plan.session_id || 'session'}</span>
              {plan.agent && <Tag>{plan.agent}</Tag>}
              <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-2)' }}>
                {done}/{items.length} done{age ? ` · updated ${age}` : ''}
              </span>
            </Row>
            <ul style={{ listStyle: 'none', margin: '2px 0 6px 10px', padding: 0, fontSize: 11 }}>
              {rows.slice(0, ITEMS_SHOWN).map(([item, depth], k) => (
                <li key={k} data-depth={depth} style={{
                  paddingLeft: depth * 14,
                  color: item.status === 'in_progress' ? 'var(--ink)' : 'var(--ink-2)',
                  textDecoration: item.status === 'cancelled' ? 'line-through' : undefined,
                  overflowWrap: 'anywhere',
                }}>
                  <span aria-label={WORDS[String(item.status)] || 'unknown status'} role="img" style={{ ...mono, marginRight: 6 }}>
                    {MARKS[String(item.status)] || '?'}
                  </span>
                  {String(item.content ?? '')}
                  {itemTags(item).map((tag) => (
                    <React.Fragment key={tag}>{' '}<Tag c="var(--amber)">{tag}</Tag></React.Fragment>
                  ))}
                </li>
              ))}
              {items.length > ITEMS_SHOWN && <li style={{ color: 'var(--ink-2)' }}>… {items.length - ITEMS_SHOWN} more</li>}
            </ul>
          </div>
        );
      })}
    </section>
  );
}
