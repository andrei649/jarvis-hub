// @ts-nocheck
import React from 'react';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', async (orig) => ({ ...(await orig()), apiGet: vi.fn() }));

import { apiGet } from '../api/client';
import { resetPolling } from '../signals/poll';
import { Timeline } from './Timeline';
import { startOfDay } from './sources';
import { hubFixture, httpError, routeGet } from './testkit';

const get = apiGet as unknown as ReturnType<typeof vi.fn>;
const CLOCK = new Date(2026, 10, 23, 14, 30);
const DAY0 = startOfDay(CLOCK.getTime());
const HOUR = 3600_000;
const iso = (ms: number) => new Date(ms).toISOString();

function routes(over = {}) {
  routeGet(get, {
    '/api/dashboard/today': { items: [{ entry_id: 'action:1', kind: 'action', title: 'Booked Conf Room A', epoch: (DAY0 + 9 * HOUR) / 1000, agent: 'pepper' }] },
    '/autonomy/tasks?status=blocked': { tasks: [
      { id: 7, title: 'Restart four services', agent: 'stark', risk_tier: 3, created_at: iso(DAY0 - 50 * HOUR) },
      { id: 8, title: 'Move EUR 4200', agent: 'gecko', risk_tier: 3, created_at: iso(DAY0 + 8 * HOUR) },
    ] },
    '/autonomy/tasks?status=running': { tasks: [{ id: 9, title: 'Reindex', agent: 'stark', updated_at: iso(DAY0 + 13 * HOUR) }] },
    '/api/subagents': { spawns: [], stats: { active: 0, cap: 3 } },
    '/heartbeat/status': { scheduler_running: true, heartbeats: [{ agent_id: 'pepper', next_run: iso(DAY0 + 18 * HOUR) }], blocked: [] },
    '/autonomy/observer': { enabled: true, probes: 4, tracked: 4, unhealthy: [{ key: 'service.ollama', detail: 'connection refused', severity: 'CRITICAL', since: iso(DAY0 + 8 * HOUR) }] },
    '/api/security/kill-switch': { global: false, any_halted: false, halted_count: 0 },
    ...over,
  });
}
const hub = () => hubFixture({ trust: { mic: 'on', strictLocal: true, cloudAvailable: false, claudeAvailable: false } });
const ui = (props = {}) => <Timeline hub={hub()} lang="en" demo={false} clock={CLOCK} navigate={vi.fn()} turns={[]} {...props} />;
const lane = (id) => document.querySelector(`[data-lane="${id}"]`) as HTMLElement;

beforeEach(() => { resetPolling(); get.mockReset(); });
afterEach(() => { resetPolling(); cleanup(); });

describe('Timeline: start times come from the hub', () => {
  it('says since which day a run, a hold and a problem began when that was before today, and says so when no start was reported', async () => {
    routes({
      '/autonomy/tasks?status=running': { tasks: [{ id: 9, title: 'Reindex', agent: 'stark', updated_at: iso(DAY0 - 20 * HOUR) }, { id: 10, title: 'Mystery', agent: 'pepper' }] },
      '/autonomy/tasks?status=blocked': { tasks: [{ id: 8, title: 'Move EUR 4200', agent: 'gecko', risk_tier: 3 }] },
      '/autonomy/observer': { enabled: true, probes: 4, tracked: 4, unhealthy: [{ key: 'service.ollama', detail: 'down', severity: 'CRITICAL', since: iso(DAY0 - 30 * HOUR) }, { key: 'resource.ram', detail: null, severity: 'WARN' }] },
    });
    render(ui());
    await waitFor(() => expect(lane('system').querySelector('[data-ev="system"]')).not.toBeNull());
    await waitFor(() => expect(lane('stark')).not.toBeNull());
    const text = document.body.textContent;
    expect(text).not.toContain('since 00:00');
    expect(lane('stark').textContent).toMatch(/Running since \d+ \w+: Reindex/);
    expect(lane('stark').querySelector('[data-ev="run"]').getAttribute('data-stub')).toBe('true');
    expect(lane('pepper').textContent).toContain('Running start time not reported: Mystery');
    expect(lane('gecko').textContent).toContain('Waits for you start time not reported: Move EUR 4200');
    expect(lane('system').textContent).toMatch(/service\.ollama — down · since \d+ \w+/);
    expect(lane('system').textContent).toContain('resource.ram · start time not reported');
  });
});

describe('Timeline', () => {
  it('draws a lane for each agent with something today, from real events only', async () => {
    routes();
    render(ui());
    await waitFor(() => expect(lane('pepper')).not.toBeNull());
    await waitFor(() => expect(lane('stark')).not.toBeNull());
    expect(lane('pepper').textContent).toContain('09:00 finished: Booked Conf Room A');
    expect(lane('pepper').textContent).toContain('Next check 18:00');
    expect(lane('stark').textContent).toContain('Running since 13:00: Reindex');
    // jarvis and frigga have nothing today: no lane
    expect(lane('jarvis')).toBeNull();
    expect(lane('frigga')).toBeNull();
  });

  it('keeps a hold on the docket as a numbered pin that links to its entry, with a stub when it is older than today', async () => {
    routes();
    render(ui());
    await waitFor(() => expect(lane('stark')?.querySelector('[data-ev="hold"]')).not.toBeNull());
    const hold = lane('stark').querySelector('[data-ev="hold"]');
    expect(hold.getAttribute('data-stub')).toBe('true');
    expect(hold.querySelector('.n-lanes__stub').textContent).toMatch(/^since \d+ \w+$/);
    const pin = within(hold).getByRole('link');
    expect(pin.textContent).toBe('1');
    expect(pin.getAttribute('href')).toMatch(/#docket-entry-7$/);
    expect(pin.getAttribute('aria-label')).toBe('Decision 1: Restart four services');
    const todays = lane('gecko').querySelector('[data-ev="hold"]');
    expect(todays.getAttribute('data-stub')).toBeNull();
    expect(within(todays).getByRole('link').textContent).toBe('2');
  });

  it('puts problems on a System lane, because probes name no agent', async () => {
    routes();
    render(ui());
    await waitFor(() => expect(lane('system').querySelector('[data-ev="system"]')).not.toBeNull());
    expect(lane('system').textContent).toContain('service.ollama');
    expect(lane('system').textContent).toContain('connection refused');
    expect(document.querySelector('[data-lane="ollama"]')).toBeNull();
  });

  it('says the System lane is unknown, not clear, when the observer is refused', async () => {
    routes({ '/autonomy/observer': httpError(401) });
    render(ui());
    await waitFor(() => expect(lane('system').textContent).toContain('Problems: not known'));
    expect(lane('system').textContent).not.toContain('No problems reported');
  });

  it('says "no problems" only when the observer answered with none', async () => {
    routes({ '/autonomy/observer': { enabled: true, probes: 4, tracked: 4, unhealthy: [] } });
    render(ui());
    await waitFor(() => expect(lane('system').textContent).toContain('No problems reported.'));
  });

  it('folds agents with no activity into one named row, and draws the cloud-only agent dashed', async () => {
    routes();
    render(ui());
    const folded = await waitFor(() => { const el = document.querySelector('[data-folded]'); expect(el).not.toBeNull(); return el; });
    expect(folded.textContent).toMatch(/agents with no activity reported today: .*Jarvis/);
    expect(folded.textContent).not.toContain('Pepper');
    expect(lane('athena').className).toContain('n-lanes__row--dashed');
    expect(lane('athena').textContent).toContain('Cloud only: unavailable while no cloud model is configured.');
  });

  it('names the sources that did not answer in the foot, and draws nothing from them', async () => {
    routes({ '/autonomy/tasks?status=blocked': httpError(401), '/api/dashboard/today': new TypeError('Failed to fetch') });
    render(ui());
    await waitFor(() => expect(document.querySelector('.n-lanes__hidden')).not.toBeNull());
    expect(document.querySelector('.n-lanes__hidden').textContent).toMatch(/Not drawn because the hub did not answer: .*Finished.*Waiting/);
    expect(document.querySelector('[data-ev="hold"]')).toBeNull();
    expect(document.querySelector('[data-ev="done"]')).toBeNull();
    const foot = document.querySelector('[data-timeline-sources]');
    expect(foot.querySelectorAll('[data-source-state]').length).toBe(6);
  });

  it("shows each agent's state in the Now column", async () => {
    routes();
    render(ui());
    await waitFor(() => expect(lane('stark')?.querySelector('.n-lanes__now').textContent).toMatch(/Waiting on you · 1/));
    expect(lane('pepper').querySelector('.n-lanes__now').textContent).toMatch(/Finished today · 1/);
  });

  it('is a demo sample in demo, with no events and no request', () => {
    routes();
    render(ui({ demo: true }));
    expect(document.querySelector('[data-demo-note]')).not.toBeNull();
    expect(document.querySelector('[data-ev]')).toBeNull();
    expect(get).not.toHaveBeenCalled();
  });

  it('speaks Romanian', async () => {
    routes();
    render(ui({ lang: 'ro' }));
    expect(screen.getByRole('heading', { name: 'Ziua pe agenți' })).toBeTruthy();
    await waitFor(() => expect(lane('pepper')?.textContent).toContain('terminat: Booked Conf Room A'));
  });
});
