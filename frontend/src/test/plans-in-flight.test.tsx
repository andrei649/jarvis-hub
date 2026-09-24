// @ts-nocheck
/* H315 — the Decision Inbox shows the plans the agent keeps with its `todo` tool
   (GET /sessions/todo), under the decisions they lead to. fetch is routed by URL. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { DecisionInboxPanel } from '../gap';
import { ITEMS_SHOWN, PLANS_SHOWN, openPlans } from '../panels/plans';

const item = (id, content, status) => ({ id: String(id), content, status });
const plan = (session_id, todos, extra = {}) => ({ session_id, todos, agent: 'nerva', posture: 'operator/owner', ...extra });

let calls;
function route(plans, { plansStatus = 200 } = {}) {
  calls = [];
  global.fetch = vi.fn((url, init = {}) => {
    const u = String(url);
    calls.push({ url: u, admin: (init.headers || {})['X-Admin-Token'] });
    const reply = (status, body) => ({ ok: status < 400, status, json: async () => body });
    if (u.includes('/sessions/todo')) return Promise.resolve(reply(plansStatus, { plans }));
    if (u.includes('/autonomy/tasks')) return Promise.resolve(reply(200, { tasks: [], total: 0 }));
    return Promise.resolve(reply(200, {}));
  });
}

beforeEach(() => {
  try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'admin-secret'); } catch { /* ignore */ }
});

describe('Decision Inbox — plans in flight (H315)', () => {
  it('reads the plans with the admin credential and shows each open one with its items', async () => {
    route([plan('web-1', [item(1, 'find flights', 'completed'), item(2, 'book the flight', 'in_progress'),
      item(3, 'tell Ana', 'pending'), item(4, 'ask about the hotel', 'cancelled')])]);
    render(<DecisionInboxPanel />);
    await screen.findByText('book the flight');
    expect(calls.find((c) => c.url.includes('/sessions/todo')).admin).toBe('admin-secret');
    const section = screen.getByTestId('plans-in-flight');
    expect(section.textContent).toContain('web-1');
    expect(section.textContent).toContain('1/4 done');
    expect(screen.getByText('tell Ana')).toBeTruthy();
    expect(screen.getByRole('img', { name: 'in progress' })).toBeTruthy();
    expect(screen.getByRole('img', { name: 'cancelled' })).toBeTruthy();
    expect(screen.queryByText('guest turn')).toBeNull();
  });

  it('says when a plan was written during a guest turn', async () => {
    route([plan('telegram-42', [item(1, 'reply to the question', 'in_progress')], { posture: 'inbound/guest' })]);
    render(<DecisionInboxPanel />);
    await screen.findByText('reply to the question');
    expect(screen.getByText('guest turn')).toBeTruthy();
  });

  it('shows only plans with open work, a few of them, and a few items each', async () => {
    const long = Array.from({ length: ITEMS_SHOWN + 3 }, (_, i) => item(i + 1, `step ${i + 1}`, 'pending'));
    const plans = [
      plan('finished', [item(1, 'all done here', 'completed'), item(2, 'dropped', 'cancelled')]),
      plan('long', long),
      ...Array.from({ length: PLANS_SHOWN + 1 }, (_, i) => plan(`s-${i}`, [item(1, `open ${i}`, 'pending')])),
    ];
    expect(openPlans({ plans }).map((p) => p.session_id)).toEqual(['long', 's-0', 's-1']);
    route(plans);
    render(<DecisionInboxPanel />);
    await screen.findByText('step 1');
    expect(screen.queryByText('all done here')).toBeNull();
    expect(screen.queryByText(`step ${ITEMS_SHOWN + 1}`)).toBeNull();
    expect(screen.getByText('… 3 more')).toBeTruthy();
    expect(screen.queryByText('open 2')).toBeNull();
  });

  it('says a failed read failed instead of drawing no plans', async () => {
    route([], { plansStatus: 503 });
    render(<DecisionInboxPanel />);
    await screen.findByText(/plans unavailable/);
    expect(screen.queryByTestId('plans-in-flight')).toBeNull();
  });

  it('reloads the plans with the rest of the inbox', async () => {
    route([plan('web-1', [item(1, 'first read', 'in_progress')])]);
    render(<DecisionInboxPanel />);
    await screen.findByText('first read');
    const before = calls.filter((c) => c.url.includes('/sessions/todo')).length;
    fireEvent.click(screen.getByLabelText('Reload'));
    await waitFor(() => expect(calls.filter((c) => c.url.includes('/sessions/todo')).length).toBe(before + 1));
  });
});
