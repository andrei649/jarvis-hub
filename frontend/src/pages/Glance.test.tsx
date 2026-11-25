// @ts-nocheck
import React from 'react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

let summary: any;
let verdict: any;
const kill = { state: 'live', value: { halted: false }, checkedAt: 1, lastGoodAt: Date.now(), stop: vi.fn(), refresh: vi.fn() };
vi.mock('../docket/links', async (orig) => ({ ...(await orig()), useDocketSummary: () => summary }));
vi.mock('../signals/hooks', async (orig) => ({ ...(await orig()), useVerdict: () => verdict }));
vi.mock('../frame/useKillSwitch', () => ({ useKillSwitch: () => kill }));
vi.mock('../frame/RunningHead', () => ({ RunningHead: (p) => <div data-testid="runhead" data-variant={p.variant}>marks</div> }));

import { Glance, SHIFTS, SHIFT_EVERY_MS } from './Glance';
import { hubFixture } from './testkit';

const CLOCK = new Date(2026, 10, 23, 10, 51);
const onExit = vi.fn();
const navigate = vi.fn();
const live = (entries: number) => ({ state: 'live', value: { entries, requests: entries, friction: { typed: 3, twoStep: 1, click: 2 } }, checkedAt: 1, lastGoodAt: Date.now() });
const hub = (over = {}) => hubFixture({
  locality: { local_pct: 95, local: 115, cloud: 6, unknown: 0, total: 121 },
  calendar: [{ tm: '09:30', ti: 'Standup', vw: 'Meet', state: 'past' }, { tm: '11:00', ti: '1:1 with Cosmina', vw: 'Office', state: 'next' }, { tm: '14:00', ti: 'Raiffeisen review', vw: 'Room A', state: '' }],
  weather: { city: 'București', temp: '9', desc: 'Mist' },
  ...over,
});
const ui = (props = {}) => <Glance hub={hub()} lang="en" demo={false} clock={CLOCK} turns={[]} onExit={onExit} navigate={navigate} {...props} />;
const cell = (id) => document.querySelector(`[data-cell="${id}"]`) as HTMLElement;

beforeEach(() => {
  onExit.mockReset(); navigate.mockReset(); kill.stop.mockReset(); kill.stop.mockResolvedValue({ ok: true });
  kill.state = 'live'; kill.value = { halted: false };
  summary = live(9);
  verdict = { state: 'degraded', rule: 8, mark: 'attn', headline: '4 services down', causes: [], checkedAt: new Date(2026, 10, 23, 10, 50).getTime(), since: new Date(2026, 10, 23, 8, 14).getTime() };
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('Glance: the four cells', () => {
  it('says how many need the owner, as a count, and that signing is on the page', () => {
    render(ui());
    expect(cell('need').querySelector('.n-glance__fig').textContent).toBe('9');
    expect(cell('need').textContent).toContain('await your signature');
    expect(cell('need').textContent).toContain('3 typed · 1 two-step · 2 one click.');
    expect(cell('need').textContent).toContain('Signing happens on the page, never from here.');
  });

  it('is unknown, never 0, when the docket did not answer', () => {
    summary = { state: 'refused', value: null, checkedAt: 1, lastGoodAt: null, reason: 'credential' };
    render(ui());
    expect(cell('need').querySelector('.n-glance__fig').textContent).toBe('—');
    expect(cell('need').textContent).toMatch(/Unknown/);
    expect(cell('need').textContent).toMatch(/Refused/);
    expect(cell('need').textContent).not.toContain('Nothing waits');
    expect(cell('need').querySelector('.n-glance__fig').textContent).not.toBe('0');
  });

  it('says nothing waits only for a docket that answered empty', () => {
    summary = { state: 'empty', value: { entries: 0, requests: 0, friction: { typed: 0, twoStep: 0, click: 0 } }, checkedAt: 1, lastGoodAt: Date.now() };
    render(ui());
    expect(cell('need').textContent).toContain('Nothing waits');
  });

  it('shows the verdict exactly as the day register computes it: its state word, headline and time', () => {
    render(ui());
    const health = cell('health');
    expect(health.getAttribute('data-verdict-state')).toBe('degraded');
    expect(health.querySelector('.n-glance__fig').textContent).toBe('Degraded');
    expect(health.textContent).toContain('4 services down');
    expect(health.textContent).toContain('Health · since 08:14');
    expect(health.textContent).toContain('Checked 10:50.');
  });

  it('counts where work ran, with its basis, and draws no percentage anywhere', () => {
    render(ui());
    const where = cell('where');
    expect(where.querySelector('.n-glance__fig').textContent).toBe('115 of 121');
    expect(where.textContent).toContain('runs sent to local runners');
    expect(where.textContent).toContain('By route');
    expect(document.body.textContent).not.toMatch(/\d\s?%/);
  });

  it('labels the last good figure Offline, not as current, while the hub is out of reach', () => {
    render(ui({ hub: hub({ state: 'offline', lastGoodAt: Date.now() - 10 * 60_000 }) }));
    const where = cell('where');
    expect(where.querySelector('.n-glance__fig').textContent).toBe('115 of 121');
    expect(where.textContent).toMatch(/Offline/);
  });

  it('is unknown, never 0 or 100, when the hub did not report where work ran', () => {
    render(ui({ hub: hub({ locality: null }) }));
    const where = cell('where');
    expect(where.querySelector('.n-glance__fig').textContent).toBe('Unknown');
    expect(where.textContent).toContain('did not report');
    expect(where.textContent).not.toMatch(/\b(0|100)\b/);
  });

  it('says none counted yet, not 0 of 0, for a hub that answered with no runs', () => {
    render(ui({ hub: hub({ locality: { local_pct: null, local: 0, cloud: 0, unknown: 0, total: 0 } }) }));
    expect(cell('where').querySelector('.n-glance__fig').textContent).toBe('None yet');
  });

  it('names the next calendar event, in minutes, and the one after it', () => {
    render(ui());
    const next = cell('next');
    expect(next.textContent).toContain('Next · in 9 min');
    expect(next.querySelector('.n-glance__fig').textContent).toBe('11:00');
    expect(next.textContent).toContain('1:1 with Cosmina');
    expect(next.textContent).toContain('Office · 14:00 Raiffeisen review');
  });

  it('says no event was reported, without claiming the calendar is empty', () => {
    render(ui({ hub: hub({ calendar: [] }) }));
    expect(cell('next').textContent).toContain('No event reported');
    expect(cell('next').textContent).toContain('empty or not connected');
  });

  it('draws the clock, the date and the weather the hub reported', () => {
    render(ui());
    expect(document.querySelector('.n-glance__clock time').textContent).toBe('10:51');
    expect(document.querySelector('.n-glance__clock').textContent).toContain('Monday');
    expect(document.querySelector('.n-glance__clock').textContent).toContain('București · 9° · Mist');
    cleanup();
    render(ui({ hub: hub({ weather: null }) }));
    expect(document.querySelector('.n-glance__clock').textContent).not.toContain('°');
  });

  it("shows this tab's working reply by the agent that was asked", () => {
    const askedAt = CLOCK.getTime() - 3 * 60_000;
    render(ui({ turns: [{ turnId: 1, agent: 'jarvis', askedAt, startedAt: null, firstTokenAt: null }] }));
    const now = screen.getByRole('status');
    expect(now.textContent).toContain('Jarvis is working on your question');
    expect(now.textContent).toContain('asked 10:48 · 3 min so far');
  });

  it('draws the running head as marks', () => {
    render(ui());
    expect(screen.getByTestId('runhead').getAttribute('data-variant')).toBe('marks');
  });
});

describe('Glance is read only', () => {
  it('has no sign, approve, confirm, resume or verdict control: its only buttons return and stop', () => {
    render(ui());
    const names = screen.getAllByRole('button').map((b) => b.textContent.replace(/\s+/g, ' ').trim());
    expect(names).toEqual(['Return to the page Esc', 'Stop all agents']);
    expect(names.join(' ')).not.toMatch(/sign|approve|confirm|resume|disengage|verify|reject|defer/i);
    expect(document.querySelector('input, textarea, select, [role="textbox"]')).toBeNull();
  });

  it('only stops: one click engages the stop, and a refusal is said', async () => {
    kill.stop.mockResolvedValueOnce({ ok: false, reason: 'owner credential required' });
    render(ui());
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Stop all agents' })); });
    expect(kill.stop).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('alert').textContent).toContain('The stop was not confirmed: owner credential required');
  });

  it('offers no resume while halted: it says so and points at the Trust page', () => {
    kill.value = { halted: true };
    render(ui());
    expect(screen.queryByRole('button', { name: 'Stop all agents' })).toBeNull();
    expect(screen.queryByRole('button', { name: /resume|disengage/i })).toBeNull();
    fireEvent.click(screen.getByRole('link', { name: 'Open Trust' }));
    expect(navigate).toHaveBeenCalledWith('/v2/trust');
  });

  // the stop acts on the real hub whatever the page shows, and stopping is the safe direction (§4.1):
  // it stays live in demo, as the masthead's and Trust's do; no resume is drawn here at all
  it('keeps the stop live in demo, offers no resume, and draws no figure for where work ran', () => {
    render(ui({ demo: true }));
    expect(screen.getByRole('button', { name: 'Stop all agents' }).disabled).toBe(false);
    expect(screen.queryByRole('button', { name: /resume|disengage/i })).toBeNull();
    expect(cell('where').querySelector('.n-glance__fig').textContent).toBe('—');
  });
});

describe('Glance returns to the page', () => {
  it('on Escape, and on the return control, but not on other keys or chords', () => {
    render(ui());
    fireEvent.keyDown(window, { key: 'a' });
    fireEvent.keyDown(window, { key: 'Escape', ctrlKey: true });
    expect(onExit).not.toHaveBeenCalled();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onExit).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: /Return to the page/ }));
    expect(onExit).toHaveBeenCalledTimes(2);
  });

  it('leaves Escape to an open disclosure, which closes first', () => {
    const { container } = render(ui());
    const main = container.querySelector('main');
    const open = document.createElement('button');
    open.setAttribute('aria-expanded', 'true');
    main.appendChild(open);
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onExit).not.toHaveBeenCalled();
    open.setAttribute('aria-expanded', 'false');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onExit).toHaveBeenCalledTimes(1);
  });

  it('stops listening once it is gone', () => {
    const { unmount } = render(ui());
    unmount();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onExit).not.toHaveBeenCalled();
  });
});

describe('Glance steps the sheet every ten minutes', () => {
  it('moves it a few pixels, instantly', () => {
    vi.useFakeTimers();
    window.matchMedia = vi.fn().mockReturnValue({ matches: false });
    const { container } = render(ui());
    const main = container.querySelector('main') as HTMLElement;
    expect(main.style.getPropertyValue('--n-glance-shift-x')).toBe('');
    act(() => { vi.advanceTimersByTime(SHIFT_EVERY_MS); });
    expect(main.style.getPropertyValue('--n-glance-shift-x')).toBe(`${SHIFTS[1][0]}px`);
    expect(main.style.getPropertyValue('--n-glance-shift-y')).toBe(`${SHIFTS[1][1]}px`);
    act(() => { vi.advanceTimersByTime(SHIFT_EVERY_MS); });
    expect(main.style.getPropertyValue('--n-glance-shift-x')).toBe(`${SHIFTS[2][0]}px`);
  });

  it('does not move at all when the viewer prefers reduced motion', () => {
    vi.useFakeTimers();
    window.matchMedia = vi.fn().mockReturnValue({ matches: true });
    const { container } = render(ui());
    act(() => { vi.advanceTimersByTime(SHIFT_EVERY_MS * 3); });
    expect((container.querySelector('main') as HTMLElement).style.getPropertyValue('--n-glance-shift-x')).toBe('');
  });
});

/* Glance in a short window (pages.css; e2e/ledger-shots.spec.ts runhead-window measures what is
   drawn at 420×800, 1280×560 and 1920×600): the sheet scrolls from its top, and its middle is
   centred only where it fits. A middle allowed to shrink (flex 1 1 auto, min-height 0) centred an
   overflow: the clock rose above the sheet's top, past the reach of scrolling, the date ran over
   the head, and the cells ran under the foot. */
describe('Glance in a short window', () => {
  const css = readFileSync(join(process.cwd(), 'src', 'pages', 'pages.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  const rule = (selector: string) => new RegExp(`(?:^|\\n)\\s*${selector.replace(/[.$]/g, '\\$&')}\\s*\\{([^}]*)\\}`).exec(css)?.[1] ?? '';

  it('never shrinks its middle below what it holds; the sheet scrolls instead, and the middle is centred where it fits', () => {
    const main = rule('.n-glance__main');
    expect(main).toMatch(/flex:\s*1 0 auto/);
    expect(main).not.toMatch(/min-height:\s*0/);
    expect(main).toMatch(/justify-content:\s*center/);
    expect(rule('.n-glance')).toMatch(/overflow:\s*auto/);
  });
});

describe('Glance speaks both languages', () => {
  it('in Romanian', () => {
    render(ui({ lang: 'ro' }));
    expect(cell('need').textContent).toContain('așteaptă semnătura ta');
    expect(cell('need').textContent).toContain('Semnarea se face pe pagină, niciodată de aici.');
    expect(screen.getByRole('button', { name: 'Oprește toți agenții' })).toBeTruthy();
  });
});
