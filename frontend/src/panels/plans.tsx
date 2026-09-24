/* H315 — the agent's plans, next to the decisions they lead to.

   The model keeps a checklist with its `todo` tool (agents/core/todo_tool.py) and
   re-reads it on every call. The owner reads the same lists here, in the Decision
   Inbox, so intent is visible before an approval card appears: "here is what I plan
   to do" instead of only "approve this command".

   Only plans with work still open are shown (a plan whose items are all completed or
   cancelled is history, readable with `nerva todo`), at most PLANS_SHOWN of them and
   ITEMS_SHOWN items each. A plan written during a guest's turn (a household member, a
   Telegram sender) says so: its text was steered by someone other than the owner.
   A failed read says it failed; it is never drawn as "no plans". */
import React from 'react';
import { Row, Tag, arr, mono } from '../panel-kit';

export const PLANS_PATH = '/sessions/todo';
export const PLANS_SHOWN = 3;
export const ITEMS_SHOWN = 8;
const OPEN = new Set(['pending', 'in_progress']);
const MARKS: Record<string, string> = { pending: '○', in_progress: '▶', completed: '✓', cancelled: '–' };
const WORDS: Record<string, string> = {
  pending: 'to do', in_progress: 'in progress', completed: 'done', cancelled: 'cancelled',
};

type Item = { id?: string; content?: string; status?: string };
type Plan = { session_id?: string; agent?: string; posture?: string; todos?: Item[] };

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
        const done = items.filter((item) => item.status === 'completed').length;
        const guest = String(plan.posture || '').endsWith('/guest');
        return (
          <div key={plan.session_id || i}>
            <Row>
              <span style={{ ...mono, color: 'var(--accent-light)' }}>{plan.session_id || 'session'}</span>
              {plan.agent && <Tag>{plan.agent}</Tag>}
              {guest && <Tag c="var(--amber)">guest turn</Tag>}
              <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--ink-2)' }}>{done}/{items.length} done</span>
            </Row>
            <ul style={{ listStyle: 'none', margin: '2px 0 6px 10px', padding: 0, fontSize: 11 }}>
              {items.slice(0, ITEMS_SHOWN).map((item, k) => (
                <li key={item.id ?? k} style={{
                  color: item.status === 'in_progress' ? 'var(--ink)' : 'var(--ink-2)',
                  textDecoration: item.status === 'cancelled' ? 'line-through' : undefined,
                  overflowWrap: 'anywhere',
                }}>
                  <span aria-label={WORDS[String(item.status)] || 'unknown status'} role="img" style={{ ...mono, marginRight: 6 }}>
                    {MARKS[String(item.status)] || '?'}
                  </span>
                  {String(item.content ?? '')}
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
