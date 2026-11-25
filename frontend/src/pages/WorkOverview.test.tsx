// @ts-nocheck
import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', async (orig) => ({ ...(await orig()), apiGet: vi.fn() }));
let summary: any;
vi.mock('../docket/links', async (orig) => ({ ...(await orig()), useDocketSummary: () => summary }));

import { apiGet } from '../api/client';
import { resetPolling } from '../signals/poll';
import { WorkOverview } from './WorkOverview';
import { hubFixture, httpError, isoAgo, routeGet, secondsAgo } from './testkit';

const get = apiGet as unknown as ReturnType<typeof vi.fn>;
const navigate = vi.fn();
const liveSummary = (entries: number, requests = entries) => ({ state: 'live', value: { entries, requests, friction: { typed: 2, twoStep: 1, click: 0 } }, checkedAt: 1, lastGoodAt: Date.now() });
const blocked = (id: number, tier: number, over = {}) => ({ id, title: `Request ${id}`, agent: 'stark', risk_tier: tier, kind: 'x', created_at: isoAgo(id), ...over });
const startOfToday = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime() / 1000; };
const action = (n: number, agent = 'pepper') => ({ entry_id: `action:${n}`, kind: 'action', title: `Finished ${n}`, ts: new Date().toISOString(), epoch: Math.max(startOfToday() + 1, secondsAgo(n)), agent });

function routes(over = {}) {
  routeGet(get, {
    '/autonomy/tasks?status=blocked': { tasks: [blocked(1, 0), blocked(2, 3), blocked(3, 2), blocked(4, 3)] },
    '/api/payments': { payments: [{ id: 'p', payee: 'Gecko', amount: 5, currency: 'EUR', status: 'pending' }, { id: 'q', payee: 'Pepper', amount: 3, currency: 'EUR', status: 'settled' }] },
    '/api/skills/proposals': { proposals: [], count: 3, more: 0, cards: [] },
    '/api/status/slots': { slots: { turns: { running: 2, per_session: 1, cap: 4 }, lanes: [], subagents: { running: 0, cap: 3 } }, holders: [{ surface: 'web', age_s: 200 }, { surface: 'unknown', age_s: 30 }], holders_total: 2 },
    '/autonomy/tasks?status=running': { tasks: [{ id: 9, title: 'Index the vault', agent: 'stark', risk_tier: 0, updated_at: isoAgo(5) }] },
    '/api/subagents': { spawns: [{ id: 's1', agent: 'scout', parent: 'jarvis', status: 'running', stalled: true, created_at: isoAgo(3) }], stats: { active: 1, cap: 3 } },
    '/heartbeat/status': { scheduler_running: true, heartbeats: [{ agent_id: 'stark', next_run: new Date(Date.now() + 7200_000).toISOString() }, { agent_id: 'pepper', next_run: new Date(Date.now() + 3600_000).toISOString() }], blocked: [] },
    '/api/jobs': { jobs: [{ id: 'j1', name: 'Nightly backup', schedule_text: 'every day at 03:00', cron: '0 3 * * *', enabled: true, runnable: true, paused_reason: null, one_shot: false, run_at: null, last_run_at: new Date(Date.now() - 3600_000).toISOString(), last_status: 'ok' }, { id: 'j2', name: 'Once', cron: 'at 2099-01-01', one_shot: true, run_at: new Date(Date.now() + 7200_000).toISOString(), enabled: true, runnable: false, paused_reason: 'quota' }] },
    '/api/dashboard/today': { items: [action(1), action(2, 'stark'), { entry_id: 'l:1', kind: 'learning', title: 'Learned a thing', epoch: secondsAgo(1), agent: 'jarvis' }] },
    ...over,
  });
}
const hubWithSlots = () => hubFixture({ slots: { turns: { running: 2, per_session: 1, cap: 4 }, lanes: [], subagents: { running: 0, cap: 3 } } });
const ui = (props = {}) => <WorkOverview hub={hubWithSlots()} lang="en" demo={false} navigate={navigate} turns={[]} question={null} {...props} />;
const line = (id) => document.querySelector(`[data-line="${id}"]`) as HTMLElement;

beforeEach(() => { resetPolling(); get.mockReset(); navigate.mockReset(); summary = liveSummary(4, 6); });
afterEach(() => { resetPolling(); cleanup(); });

describe('Work overview: Needs you', () => {
  it('counts the docket with its friction mix, and lists the strictest three, oldest first, as links to their entries', async () => {
    routes();
    render(ui());
    expect(line('docket').textContent).toContain('4 decisions await your signature');
    expect(line('docket').textContent).toContain('6 requests behind them');
    expect(line('docket').textContent).toContain('2 typed · 1 two-step · 0 one click');
    const top = await waitFor(() => { const el = document.querySelector('[data-top-entries]'); expect(el).not.toBeNull(); return el; });
    const links = within(top).getAllByRole('link');
    expect(links.map((a) => a.textContent)).toEqual(['Request 4', 'Request 2', 'Request 3']);
    expect(links[0].getAttribute('href')).toMatch(/#docket-entry-4$/);
  });

  it('counts payments waiting and skill changes pending, from their own sources', async () => {
    routes();
    render(ui());
    await waitFor(() => expect(line('payments').textContent).toContain('1 payment waits for your approval'));
    expect(line('skills').textContent).toContain('3 skill changes are pending review');
  });

  it('says "nothing waits" only for sources that answered empty', async () => {
    routes({ '/api/payments': { payments: [] }, '/api/skills/proposals': { proposals: [], count: 0, more: 0, cards: [] } });
    summary = { state: 'empty', value: { entries: 0, requests: 0, friction: { typed: 0, twoStep: 0, click: 0 } }, checkedAt: 1, lastGoodAt: Date.now() };
    render(ui());
    expect(line('docket').textContent).toContain('Nothing waits on the docket.');
    await waitFor(() => expect(line('payments').textContent).toContain('No payment waits for approval.'));
    await waitFor(() => expect(line('skills').textContent).toContain('No skill change is pending.'));
  });

  it('is Refused, never "0", when the owner credential is missing', async () => {
    routes({ '/api/payments': httpError(401), '/api/skills/proposals': httpError(403), '/autonomy/tasks?status=blocked': httpError(401) });
    summary = { state: 'refused', value: null, checkedAt: 1, lastGoodAt: null, reason: 'credential' };
    render(ui());
    await waitFor(() => expect(line('payments').querySelector('[data-source-state="refused"]')).not.toBeNull());
    await waitFor(() => expect(line('skills').querySelector('[data-source-state="refused"]')).not.toBeNull());
    for (const id of ['docket', 'payments', 'skills']) {
      expect(line(id).textContent, id).toMatch(/Refused/);
      expect(line(id).textContent, id).not.toMatch(/(^|\D)0(\D|$)/);
      expect(line(id).textContent, id).not.toMatch(/Nothing waits|No payment waits|No skill change/);
    }
    expect(document.querySelector('[data-top-entries]')).toBeNull();
  });

  it('is Unknown, never "0", while a source is unreachable or the summary is not reported', async () => {
    routes({ '/api/payments': new TypeError('Failed to fetch') });
    summary = { state: 'unknown', value: null, checkedAt: null, lastGoodAt: null, reason: 'not-reported' };
    render(ui());
    expect(line('docket').textContent).toMatch(/Decisions: not known\./);
    expect(line('docket').textContent).not.toMatch(/(^|\D)0(\D|$)/);
    await waitFor(() => expect(line('payments').querySelector('[data-source-state="offline"]')).not.toBeNull());
    expect(line('payments').textContent).not.toMatch(/(^|\D)0(\D|$)/);
  });

  it('shows an open question of this tab as plain text, with a way back to the conversation', () => {
    routes();
    render(ui({ question: { id: 'q1', question: 'Which <b>file</b>?', choices: [], multi_select: false } }));
    expect(line('question').textContent).toContain('Which <b>file</b>?');
    expect(line('question').querySelector('b')).toBeNull();
    fireEvent.click(within(line('question')).getByRole('link', { name: 'Answer it in the conversation' }));
    expect(navigate).toHaveBeenCalledWith('/v2/cockpit');
  });
});

describe('Work overview: Running now', () => {
  it('counts the turn slots from the hub, shows where they run (never an agent), and names running work from named sources', async () => {
    routes();
    render(ui());
    expect(line('turns').textContent).toContain('2 turns are running now');
    expect(line('turns').textContent).toContain('of 4 allowed');
    const holders = await waitFor(() => { const el = document.querySelector('[data-slot-holders]'); expect(el).not.toBeNull(); return el; });
    expect(holders.textContent).toContain('web · 3 min');
    expect(holders.textContent).toContain('unknown · under a minute');
    expect(holders.textContent).not.toMatch(/Jarvis|Stark|Pepper/);
    await waitFor(() => expect(document.querySelector('[data-running-tasks]')?.textContent).toContain('Stark Index the vault'));
    const subs = await waitFor(() => { const el = document.querySelector('[data-subagents]'); expect(el).not.toBeNull(); return el; });
    expect(subs.textContent).toContain('for Jarvis');
    expect(subs.textContent).toContain('stalled');
  });

  it('does not say "no turn is running" when the hub did not report its slots', () => {
    routes();
    render(ui({ hub: hubFixture({ slots: null }) }));
    expect(line('turns').textContent).toContain('Turns running: not reported');
    expect(line('turns').textContent).not.toContain('No turn is running');
  });

  it('lists this tab\'s own turns by the agent that was asked', () => {
    routes();
    render(ui({ turns: [{ turnId: 1, agent: 'jarvis', askedAt: new Date(2026, 10, 23, 10, 48).getTime(), startedAt: null, firstTokenAt: null }] }));
    expect(line('this-tab').textContent).toContain('This tab · Asked Jarvis at 10:48');
  });

  it('refuses to call a running list empty when running work is refused', async () => {
    routes({ '/autonomy/tasks?status=running': httpError(401) });
    render(ui());
    await waitFor(() => expect(document.querySelectorAll('[data-reading-state="refused"]').length).toBeGreaterThan(0));
    expect(screen.queryByText('No task is running.')).toBeNull();
  });
});

describe('Work overview: Scheduled and Done today', () => {
  it('lists the next checks soonest first, with the honest note that last results are not recorded', async () => {
    routes();
    render(ui());
    const list = await waitFor(() => { const el = document.querySelector('[data-heartbeats]'); expect(el).not.toBeNull(); return el; });
    expect([...list.querySelectorAll('li')].map((li) => li.querySelector('b').textContent)).toEqual(['Pepper', 'Stark']);
    expect(screen.getByText('The last check is not recorded.')).toBeTruthy();
    await waitFor(() => expect(document.querySelector('[data-jobs]')?.textContent).toContain('Nightly backup'));
    const jobs = document.querySelector('[data-jobs]')?.textContent ?? '';
    expect(jobs).toContain('every day at 03:00');
    expect(jobs).toContain('next run not reported');
    expect(jobs).toContain('last run');
    expect(jobs).toContain('paused: quota');
    expect(jobs).toContain('runs ');
  });

  it('says jobs are refused, not absent, without the owner credential', async () => {
    routes({ '/api/jobs': httpError(401) });
    render(ui());
    await waitFor(() => expect(screen.getAllByText(/Refused/).length).toBeGreaterThan(0));
    expect(screen.queryByText('No job is set up.')).toBeNull();
  });

  it('lists what finished today, actions only, with a count', async () => {
    routes();
    render(ui());
    const list = await waitFor(() => { const el = document.querySelector('[data-done-today]'); expect(el).not.toBeNull(); return el; });
    expect(list.textContent).toContain('Finished 1');
    expect(list.textContent).not.toContain('Learned a thing');
    expect(screen.getByText('2 actions finished today')).toBeTruthy();
  });

  it('links to missions and sessions instead of merging them in', () => {
    routes();
    render(ui());
    fireEvent.click(screen.getByRole('link', { name: 'Missions' }));
    expect(navigate).toHaveBeenCalledWith('/v2/console/missions');
    fireEvent.click(screen.getByRole('link', { name: 'Sessions' }));
    expect(navigate).toHaveBeenCalledWith('/v2/console/sessions');
  });
});

describe('Work overview: sources and demo', () => {
  it('puts a source label in every section head', async () => {
    routes();
    render(ui());
    await waitFor(() => expect(document.querySelectorAll('[data-register^="work-"]').length).toBe(4));
    for (const reg of document.querySelectorAll('[data-register^="work-"]')) {
      expect(reg.querySelector('.n-register__meta [data-source-state]'), reg.getAttribute('data-register')).not.toBeNull();
    }
  });

  it('draws nothing live in demo, labels it, and asks the hub for nothing', () => {
    routes();
    render(ui({ demo: true }));
    expect(document.querySelectorAll('[data-demo-note]').length).toBe(4);
    expect(document.querySelectorAll('[data-source-state="demo"]').length).toBe(4);
    expect(get).not.toHaveBeenCalled();
  });

  it('speaks Romanian', async () => {
    routes();
    render(ui({ lang: 'ro' }));
    expect(screen.getByRole('heading', { name: 'Te așteaptă' })).toBeTruthy();
    expect(line('docket').textContent).toContain('4 decizii așteaptă semnătura ta');
  });
});
