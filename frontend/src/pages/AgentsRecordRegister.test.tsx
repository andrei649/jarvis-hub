// @ts-nocheck
import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', async (orig) => ({ ...(await orig()), apiGet: vi.fn() }));

import { apiGet } from '../api/client';
import { resetPolling } from '../signals/poll';
import { AgentsRecordRegister } from './AgentsRecordRegister';
import { hubFixture, httpError, isoAgo, routeGet, secondsAgo } from './testkit';

const get = apiGet as unknown as ReturnType<typeof vi.fn>;
const navigate = vi.fn();
const entry = (seq: number, over = {}) => ({ seq, ts: secondsAgo(seq), actor: 'jarvis', action: 'route', why: `Routed question ${seq}`, metadata: {}, entry_hash: `abcd${seq}000000000000ef${seq}`, ...over });
const startOfToday = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime() / 1000; };

function routes(over = {}) {
  routeGet(get, {
    '/autonomy/tasks?status=blocked': { tasks: [{ id: 1, title: 'Move money', agent: 'gecko', risk_tier: 3, created_at: isoAgo(5) }, { id: 2, title: 'Restart', agent: 'gecko', risk_tier: 3, created_at: isoAgo(4) }] },
    '/autonomy/tasks?status=running': { tasks: [{ id: 9, title: 'Index the vault', agent: 'stark' }] },
    '/api/subagents': { spawns: [], stats: { active: 0, cap: 3 } },
    '/api/dashboard/today': { items: [{ entry_id: 'action:1', kind: 'action', title: 'Booked', epoch: startOfToday() + 5, ts: new Date().toISOString(), agent: 'pepper' }] },
    '/heartbeat/status': { scheduler_running: true, heartbeats: [{ agent_id: 'frigga', next_run: new Date(Date.now() + 3600_000).toISOString() }], blocked: [] },
    '/api/security/kill-switch': { global: false, any_halted: false, halted_count: 0 },
    '/api/security/audit/verify': { valid: true, first_invalid_id: null, entries: 921, tamper_evident: true },
    '/api/security/audit/intent': { verify: { ok: true, n: 7 }, entries: [7, 6, 5, 4, 3, 2, 1].map((n) => entry(n)) },
    ...over,
  });
}
const hub = (over = {}) => hubFixture({
  agents: [{ id: 'jarvis', name: 'Jarvis' }, { id: 'pepper', name: 'Pepper' }, { id: 'stark', name: 'Stark' }, { id: 'gecko', name: 'Gecko' }, { id: 'athena', name: 'Athena' }, { id: 'frigga', name: 'Frigga' }],
  trust: { mic: 'on', strictLocal: true, cloudAvailable: false, claudeAvailable: false },
  slots: { turns: { running: 3, per_session: 1, cap: 4 }, lanes: [], subagents: { running: 0, cap: 3 } },
  ...over,
});
const ui = (props = {}) => <AgentsRecordRegister hub={hub()} lang="en" demo={false} navigate={navigate} turns={[]} {...props} />;
const group = (activity) => document.querySelector(`[data-activity="${activity}"]`) as HTMLElement;

beforeEach(() => { resetPolling(); get.mockReset(); navigate.mockReset(); });
afterEach(() => { resetPolling(); cleanup(); });

describe('Agents by exception', () => {
  it('gives each agent one state from a named source, and the rest one line of names', async () => {
    routes();
    render(ui());
    await waitFor(() => expect(group('waitingOnYou')).not.toBeNull());
    expect(group('waitingOnYou').textContent).toContain('Waiting on you · 2');
    expect(group('waitingOnYou').querySelector('[data-agent="gecko"]').getAttribute('data-source')).toBe('docket');
    await waitFor(() => expect(group('working')).not.toBeNull());
    expect(group('working').querySelector('[data-agent="stark"]').getAttribute('data-source')).toBe('running-task');
    await waitFor(() => expect(group('finishedToday')).not.toBeNull());
    expect(group('finishedToday').textContent).toContain('Pepper');
    await waitFor(() => expect(group('unavailable')).not.toBeNull());
    expect(group('unavailable').textContent).toContain('Athena');
    expect(group('unavailable').querySelector('li').getAttribute('data-source')).toBe('cloud-policy');
    // a heartbeat is a schedule, not activity: Frigga and Jarvis are in the quiet line
    expect(group('noActivity').textContent).toMatch(/2 agents with no activity reported: .*Frigga.*Jarvis|.*Jarvis.*Frigga/);
  });

  it('never says idle, ready or active', async () => {
    routes();
    render(ui());
    await waitFor(() => expect(group('working')).not.toBeNull());
    expect(document.body.textContent).not.toMatch(/\b(idle|ready|active)\b/i);
  });

  it('counts replies running elsewhere without naming anyone, from the hub slots minus this tab', async () => {
    routes();
    render(ui({ turns: [{ turnId: 1, agent: 'jarvis', askedAt: Date.now() - 60_000, startedAt: null, firstTokenAt: null }] }));
    expect(document.querySelector('[data-elsewhere]').textContent).toBe('2 replies running elsewhere');
    await waitFor(() => expect(group('working')?.querySelector('[data-agent="jarvis"]')?.getAttribute('data-source')).toBe('this-tab'));
  });

  it('says one reply, singular, and nothing when no reply runs elsewhere', async () => {
    routes();
    const a = render(ui({ hub: hub({ slots: { turns: { running: 1, per_session: 1, cap: 4 }, lanes: [], subagents: null } }) }));
    expect(document.querySelector('[data-elsewhere]').textContent).toBe('1 reply running elsewhere');
    a.unmount();
    render(ui({ hub: hub({ slots: { turns: { running: 0, per_session: 1, cap: 4 }, lanes: [], subagents: null } }) }));
    expect(document.querySelector('[data-elsewhere]')).toBeNull();
  });

  it('says it is not reported, rather than none, when the hub did not report its slots', () => {
    routes();
    render(ui({ hub: hub({ slots: null }) }));
    expect(document.querySelector('[data-elsewhere]').textContent).toBe('Replies running elsewhere: not reported');
  });

  it('names the sources that did not answer, instead of treating them as "no activity"', async () => {
    routes({ '/autonomy/tasks?status=blocked': httpError(401), '/autonomy/tasks?status=running': httpError(401) });
    render(ui());
    await waitFor(() => expect(document.querySelector('[data-unknown-sources]')).not.toBeNull());
    expect(document.querySelector('[data-unknown-sources]').textContent).toBe('Not known: decisions, running tasks.');
    expect(group('waitingOnYou')).toBeNull();
  });

  it('halts everyone when the stop is engaged', async () => {
    routes({ '/api/security/kill-switch': { global: true, any_halted: true, halted_count: 1 } });
    render(ui());
    await waitFor(() => expect(group('halted')).not.toBeNull());
    expect(group('halted').querySelectorAll('li').length).toBe(6);
  });
});

describe('The record\'s tail', () => {
  it('shows the newest five entries, plain, sealed only because the chain verified', async () => {
    routes();
    render(ui());
    const tail = await waitFor(() => { const el = document.querySelector('[data-record-tail]'); expect(el).not.toBeNull(); return el; });
    expect(tail.querySelectorAll('li').length).toBe(5);
    expect(tail.textContent).toContain('Routed question 7');
    expect(tail.textContent).not.toContain('Routed question 2');
    expect(within(tail).getAllByRole('img', { name: 'Sealed' }).length).toBe(5);
    expect(tail.textContent).toContain('by jarvis');
  });

  it('ends with the chain\'s verdict and a way to the record', async () => {
    routes();
    render(ui());
    await waitFor(() => expect(screen.getByText('Chain intact')).toBeTruthy());
    fireEvent.click(screen.getByRole('link', { name: 'Open the record' }));
    expect(navigate).toHaveBeenCalledWith('/v2/trust');
  });

  it('does not say intact when the chain could not be verified, and does not draw a refused record', async () => {
    routes({ '/api/security/audit/verify': httpError(401), '/api/security/audit/intent': httpError(401) });
    render(ui());
    await waitFor(() => expect(document.querySelector('[data-reading-state="refused"]')).not.toBeNull());
    expect(screen.getByText('Chain not verified')).toBeTruthy();
    expect(screen.queryByText('Chain intact')).toBeNull();
    expect(document.querySelector('[data-record-tail]')).toBeNull();
  });
});

describe('demo and language', () => {
  it('draws no live state in demo, labelled, with no request', () => {
    routes();
    render(ui({ demo: true }));
    expect(document.querySelector('[data-demo-note]')).not.toBeNull();
    expect(document.querySelector('[data-source-state="demo"]')).not.toBeNull();
    expect(document.querySelector('[data-agents-by-exception]')).toBeNull();
    expect(get).not.toHaveBeenCalled();
  });

  it('is a register named record', () => {
    routes();
    render(ui());
    expect(document.querySelector('[data-register="record"]')).not.toBeNull();
  });

  it('speaks Romanian', async () => {
    routes();
    render(ui({ lang: 'ro' }));
    await waitFor(() => expect(group('waitingOnYou')?.textContent).toContain('Te așteaptă · 2'));
    expect(screen.getByText('Deschide registrul')).toBeTruthy();
  });
});
