// @ts-nocheck
/* H315 — the Decision Inbox shows the plans the agent keeps with its `todo` tool
   (GET /sessions/todo), under the decisions they lead to. fetch is routed by URL. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { DecisionInboxPanel } from '../gap';
import { ITEMS_SHOWN, PLANS_SHOWN, itemTags, openPlans, planAge } from '../panels/plans';

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

  it('tags each item with whose turn wrote its text and whether that text is untrusted', async () => {
    const by = (id, content, writer, extra = {}) => ({ ...item(id, content, 'pending'), by: writer, ...extra });
    route([plan('telegram-42', [
      by(1, 'from a guest', 'inbound/guest'),
      by(2, 'from the household', 'operator/guest'),
      by(3, 'from a job', 'internal/system'),
      by(4, 'from a page', 'operator/owner', { tainted: true, status: 'in_progress' }),
      by(5, 'mine at the hud', 'operator/owner'),
      by(6, 'mine on telegram', 'inbound/owner'),
    ], { posture: 'inbound/owner' })]);
    render(<DecisionInboxPanel />);
    const line = async (text) => (await screen.findByText(text, { exact: false })).closest('li').textContent;
    expect(await line('from a guest')).toContain('guest turn');
    expect(await line('from the household')).toContain('household turn');
    expect(await line('from the household')).not.toContain('guest turn');
    expect(await line('from a job')).toContain('background turn');
    expect(await line('from a page')).toContain('untrusted source');
    for (const mine of ['mine at the hud', 'mine on telegram']) {
      const text = await line(mine);
      expect(text).not.toMatch(/turn|untrusted/);
    }
    expect(itemTags({ by: 'inbound/guest', tainted: true })).toEqual(['guest turn', 'untrusted source']);
    expect(itemTags({ by: 'operator/owner', tainted: 'yes' })).toEqual([]);   // only a real true
  });

  it('says how long ago each plan was written', async () => {
    const now = Date.now() / 1000;
    route([plan('old', [item(1, 'stale step', 'pending')], { updated_at: now - 3 * 86400 }),
      plan('new', [item(1, 'fresh step', 'pending')], { updated_at: now - 5 })]);
    render(<DecisionInboxPanel />);
    await screen.findByText('stale step');
    const text = screen.getByTestId('plans-in-flight').textContent;
    expect(text).toContain('0/1 done · updated 3 d ago');
    expect(text).toContain('0/1 done · updated just now');
    expect(planAge(undefined)).toBe('');
    expect(planAge(1000, 1000 * 1000 + 600 * 1000)).toBe('10 min ago');
    expect(planAge(0, 5 * 3600 * 1000)).toBe('5 h ago');
  });

  it('shows every tag an item carries, not only the first', async () => {
    route([plan('telegram-42', [{ ...item(1, 'from a guest page', 'pending'), by: 'inbound/guest', tainted: true }])]);
    render(<DecisionInboxPanel />);
    const line = (await screen.findByText('from a guest page', { exact: false })).closest('li').textContent;
    expect(line).toContain('guest turn');
    expect(line).toContain('untrusted source');
  });

  it('draws the age boundaries where they are', () => {
    expect(planAge(0, 59_400)).toBe('just now');        // 59 s
    expect(planAge(0, 59_600)).toBe('1 min ago');       // rounds to 60 s
    expect(planAge(0, 60_000)).toBe('1 min ago');
    expect(planAge(0, 3_599_000)).toBe('59 min ago');
    expect(planAge(0, 3_600_000)).toBe('1 h ago');
    expect(planAge(0, 86_399_000)).toBe('23 h ago');
    expect(planAge(0, 86_400_000)).toBe('1 d ago');
    expect(planAge(0, 129_600_000)).toBe('1 d ago');    // a day and a half is still one day
    expect(planAge(0, 172_800_000)).toBe('2 d ago');
    expect(planAge(10, 0)).toBe('just now');            // a clock behind the hub's is not negative time
  });

  it('strikes cancelled items through, names the agent and labels the section', async () => {
    route([plan('web-1', [item(1, 'dropped step', 'cancelled'), item(2, 'open step', 'pending')], { agent: 'friday' })]);
    render(<DecisionInboxPanel />);
    const dropped = await screen.findByText('dropped step');
    expect(dropped.closest('li').style.textDecoration).toBe('line-through');
    expect(screen.getByText('open step').closest('li').style.textDecoration).toBe('');
    expect(screen.getByText('friday')).toBeTruthy();
    expect(screen.getByRole('region', { name: 'plans in flight' })).toBeTruthy();
  });

  it('draws nothing at all when no plan has open work', async () => {
    route([plan('finished', [item(1, 'all done', 'completed')])]);
    render(<DecisionInboxPanel />);
    await waitFor(() => expect(calls.some((c) => c.url.includes('/sessions/todo'))).toBe(true));
    await waitFor(() => expect(screen.queryByText(/PLANS IN FLIGHT/)).toBeNull());
    expect(screen.queryByTestId('plans-in-flight')).toBeNull();
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

  it('says a failed read failed, and why, instead of drawing no plans', async () => {
    route([], { plansStatus: 503 });
    render(<DecisionInboxPanel />);
    const note = await screen.findByText(/plans unavailable/);
    expect(note.textContent).toMatch(/plans unavailable · .*503/);
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

  it('indents a subtask under its parent and keeps dangling, self and cyclic parents in view (H666)', async () => {
    const sub = (id, content, status, parent) => ({ ...item(id, content, status), parent });
    route([plan('web-1', [
      sub('b', 'loop b', 'pending', 'a'), sub('a', 'loop a', 'pending', 'b'),
      item('1', 'ship it', 'in_progress'), sub('1a', 'write tests', 'pending', '1'),
      sub('1a1', 'edge cases', 'pending', '1a'), sub('me', 'self parent', 'pending', 'me'),
      sub('o', 'orphan', 'pending', 'gone'),
    ])]);
    render(<DecisionInboxPanel />);
    await screen.findByText('ship it');
    const rows = Array.from(screen.getByTestId('plans-in-flight').querySelectorAll('li'))
      .map((li) => [li.textContent.slice(1), li.getAttribute('data-depth'), li.style.paddingLeft]);
    expect(rows).toEqual([
      ['ship it', '0', '0px'], ['write tests', '1', '14px'], ['edge cases', '2', '28px'],
      ['self parent', '0', '0px'], ['orphan', '0', '0px'], ['loop b', '0', '0px'], ['loop a', '0', '0px'],
    ]);
  });
});
