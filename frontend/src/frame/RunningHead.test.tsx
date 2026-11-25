import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { clearActionFailures } from '../api/client';
import { resetPolling } from '../signals/poll';
import { SIGNAL_IDS } from '../signals/types';
import { clockTime } from './kit';
import {
  MARKS_QUERY, RUNHEAD_FIT_STEPS, RunningHead, fitRunningHead, isLooser, modeRefusalText, runheadSpills, runheadStepApplies,
  type RunheadFitStep,
} from './RunningHead';
import { hubSnapshotFrom, initialHubSnapshot } from './types';
import { stubHub, type HubAnswer } from './test-support';

const LIVE_DATA = { demo: false, serverUp: true, llm: { state: 'ready', model: 'gemma-4-31b', residents: [] }, sources: {} } as any;

type Hub = { mode?: HubAnswer; interrupts?: HubAnswer; audit?: HubAnswer; post?: (body: any) => HubAnswer };
/** The hub's answers; `setMode` changes the mode in force behind the page's back (another tab). */
function hub({
  mode = { status: 200, body: { mode: 'ask' } }, interrupts = { status: 200, body: { used: 1, per_day: 4, remaining: 3 } },
  audit = { status: 200, body: { valid: true, first_invalid_id: null, entries: 921 } }, post,
}: Hub = {}) {
  let current: HubAnswer = mode;
  const calls = stubHub((method, path, body) => {
    if (path === '/autonomy/mode' && method === 'POST') {
      const answer = post ? post(body) : { status: 200, body: { mode: (body as any).mode, ok: true, effective: true } };
      if (answer !== 'down' && answer.status === 200) current = { status: 200, body: { mode: (body as any).mode } };
      return answer;
    }
    if (path === '/autonomy/mode') return current;
    if (path === '/autonomy/interrupts') return interrupts;
    if (path === '/api/security/audit/verify') return audit;
    if (path === '/api/admin/network/calls') return { status: 403, body: { detail: 'admin token required' } };
    return { status: 404 };
  }, vi.stubGlobal);
  return Object.assign(calls, { setMode: (next: string) => { current = { status: 200, body: { mode: next } }; } });
}
const confirmShown = () => waitFor(() => {
  const el = document.querySelector('[data-runhead="confirm"]');
  expect(el).not.toBeNull();
  return el as HTMLElement;
});
const signal = (id: string) => document.querySelector(`[data-signal="${id}"]`) as HTMLElement;
const modeGroup = () => screen.getByRole('radiogroup', { name: 'Approval mode' });
const radio = (name: string) => within(modeGroup()).getByRole('radio', { name }) as HTMLButtonElement;

beforeEach(() => { resetPolling(); clearActionFailures(); localStorage.clear(); });
afterEach(() => { resetPolling(); clearActionFailures(); vi.unstubAllGlobals(); });

describe('RunningHead', () => {
  it('draws all eight items: six signals, the approval mode and the interrupts', async () => {
    hub();
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    const head = document.querySelector('[data-frame="runhead"]') as HTMLElement;
    expect([...head.querySelectorAll('[data-signal]')].map((el) => el.getAttribute('data-signal'))).toEqual([...SIGNAL_IDS]);
    expect(head.querySelector('[data-runhead="mode"]')).not.toBeNull();
    expect(head.querySelector('[data-runhead="interrupts"]')).not.toBeNull();
    // every signal is a disclosure: the basis and the time behind a button
    expect(within(signal('data')).getByRole('button').getAttribute('aria-expanded')).toBe('false');
    await waitFor(() => expect(radio('Ask').getAttribute('aria-checked')).toBe('true'));
    expect(head.querySelector('[data-runhead="interrupts"]')?.textContent).toContain('1 of 4 used today');
  });

  it('says Checking… before the hub answers and Unknown for what did not answer, never a default or an all-clear', async () => {
    hub();
    const { rerender } = render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    for (const id of ['egress', 'localRoute', 'microphone', 'model', 'data']) {
      expect(signal(id).getAttribute('data-state')).toBe('unknown');
      expect(signal(id).querySelector('[data-mark="unknown"]')).not.toBeNull();
      expect(within(signal(id)).getByRole('button').textContent).toContain('Checking…');
    }
    // the hub answered, but not its trust status nor its locality
    rerender(<RunningHead hub={hubSnapshotFrom(LIVE_DATA, null, { now: Date.now() })} lang="en" demo={false} />);
    expect(screen.getByRole('button', { name: 'Egress: Unknown — trust status did not answer' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Sent to local runners: Unknown — locality did not answer' })).toBeTruthy();
    const text = document.querySelector('[data-frame="runhead"]')?.textContent || '';
    expect(text).not.toMatch(/Sealed — nothing can leave|\b0\b|\d%/);
    await waitFor(() => expect(signal('chain').textContent).toMatch(/Intact · 921 sealed · verified \d\d:\d\d/));
  });

  it('names the model with its backend, and links to the page that sets it up', async () => {
    hub();
    const navigate = vi.fn();
    const live = hubSnapshotFrom({ ...LIVE_DATA, llmBackend: 'ollama' }, null, { now: Date.now() });
    render(<RunningHead hub={live} lang="en" demo={false} navigate={navigate} />);
    const button = screen.getByRole('button', { name: 'Model: gemma-4-31b · ollama' });
    expect(button.querySelector('code')?.textContent).toBe('gemma-4-31b');
    fireEvent.click(button);
    const link = within(signal('model')).getByRole('link', { name: 'Model setup' });
    expect(link.getAttribute('href')).toContain('/v2/console/model-setup');
    fireEvent.click(link);
    expect(navigate).toHaveBeenCalledWith('/v2/console/model-setup');
  });

  it('says how current the data on screen is', () => {
    hub();
    const T0 = new Date(2026, 10, 23, 10, 50).getTime();
    const { rerender } = render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    expect(signal('data').textContent).toContain('Checking…');
    const live = hubSnapshotFrom(LIVE_DATA, null, { now: Date.now() });
    rerender(<RunningHead hub={live} lang="en" demo={false} />);
    expect(signal('data').getAttribute('data-state')).toBe('live');
    expect(signal('data').textContent).toContain(`Live · checked ${clockTime(live.lastGoodAt as number)}`);
    const down = hubSnapshotFrom({ ...LIVE_DATA, serverUp: false }, { ...live, lastGoodAt: T0 }, { now: Date.now() });
    rerender(<RunningHead hub={down} lang="en" demo={false} />);
    expect(signal('data').getAttribute('data-state')).toBe('offline');
    expect(signal('data').textContent).toContain('Offline · last good reading 10:50');
    rerender(<RunningHead hub={initialHubSnapshot(true)} lang="en" demo />);
    for (const id of SIGNAL_IDS) expect(signal(id).textContent).toContain('Demo sample');
  });

  it('turns stale on its own when no good answer comes for 2.5 loader intervals', () => {
    vi.useFakeTimers();
    try {
      hub();
      const live = hubSnapshotFrom(LIVE_DATA, null, { now: Date.now() });
      render(<RunningHead hub={live} lang="en" demo={false} />);
      expect(signal('data').getAttribute('data-state')).toBe('live');
      act(() => { vi.advanceTimersByTime(75_002); });
      expect(signal('data').getAttribute('data-state')).toBe('stale');
      expect(signal('data').textContent).toContain('Stale · checked');
    } finally {
      vi.useRealTimers();
    }
  });

  it('makes a stricter mode one click', async () => {
    const calls = hub();
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    await waitFor(() => expect(radio('Ask').getAttribute('aria-checked')).toBe('true'));
    fireEvent.click(radio('Off'));
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST')).toEqual([{ method: 'POST', path: '/autonomy/mode', body: { mode: 'off' } }]));
    await waitFor(() => expect(radio('Off').getAttribute('aria-checked')).toBe('true'));
    expect(document.querySelector('[data-runhead="confirm"]')).toBeNull();
  });

  it('makes a looser mode two steps, and Cancel posts nothing', async () => {
    const calls = hub();
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    await waitFor(() => expect(radio('Ask').getAttribute('aria-checked')).toBe('true'));
    fireEvent.click(radio('Auto'));
    const confirm = await confirmShown();
    expect(confirm.textContent).toContain('Auto lets reversible actions run without asking.');
    // the armed group is named in the page's own words, not confirm.tsx's English default
    expect(within(confirm).getByRole('group', { name: 'Confirm the looser approval mode' })).toBeTruthy();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
    fireEvent.click(within(confirm).getByRole('button', { name: 'Cancel' }));
    expect(document.querySelector('[data-runhead="confirm"]')).toBeNull();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);

    fireEvent.click(radio('Auto'));
    await confirmShown();
    fireEvent.click(screen.getByRole('button', { name: 'Switch to Auto' }));
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST')).toEqual([{ method: 'POST', path: '/autonomy/mode', body: { mode: 'auto' } }]));
    await waitFor(() => expect(radio('Auto').getAttribute('aria-checked')).toBe('true'));
  });

  it('decides the friction on the mode in force now, not on the last poll', async () => {
    // the page last read Auto; the hub has since been set to Off elsewhere. From Auto, Ask would be
    // stricter (one click); from Off it loosens the mode, so it takes the two steps.
    const calls = hub({ mode: { status: 200, body: { mode: 'auto' } } });
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    await waitFor(() => expect(radio('Auto').getAttribute('aria-checked')).toBe('true'));
    calls.setMode('off');
    const before = calls.length;
    fireEvent.click(radio('Ask'));
    const confirm = await confirmShown();
    expect(confirm.textContent).toContain('Ask resumes the proactive loop');
    // it asked the hub again before deciding, and wrote nothing
    expect(calls.slice(before).some((c) => c.method === 'GET' && c.path === '/autonomy/mode')).toBe(true);
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
    await waitFor(() => expect(radio('Off').getAttribute('aria-checked')).toBe('true'));
  });

  it('is disabled with its reason when the mode cannot be read, and in demo', async () => {
    hub({ mode: { status: 403, body: { detail: 'admin token required' } }, interrupts: { status: 403 } });
    const { unmount } = render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    await waitFor(() => expect(document.querySelector('[data-runhead="mode"]')?.textContent).toContain('Refused — needs the owner credential'));
    for (const name of ['Auto', 'Ask', 'Off']) expect(radio(name).disabled).toBe(true);
    expect(within(modeGroup()).queryAllByRole('radio', { checked: true })).toHaveLength(0);
    expect(document.querySelector('[data-runhead="interrupts"]')?.textContent).toContain('Refused');
    unmount();
    resetPolling();
    vi.unstubAllGlobals();
    const calls = hub();
    render(<RunningHead hub={initialHubSnapshot(true)} lang="en" demo />);
    for (const name of ['Auto', 'Ask', 'Off']) expect(radio(name).disabled).toBe(true);
    expect(document.querySelector('[data-runhead="mode"]')?.textContent).toContain('Demo sample');
    expect([...calls]).toEqual([]);
  });

  it('shows a refused write in the hub\'s terms, with the mode in force', async () => {
    hub({ post: () => ({ status: 503, body: { error: 'mode_not_saved', mode: 'ask' } }) });
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    await waitFor(() => expect(radio('Ask').getAttribute('aria-checked')).toBe('true'));
    fireEvent.click(radio('Off'));
    const note = await screen.findByRole('alert');
    expect(note.textContent).toContain('Off was not saved. Ask is in force.');
    expect(radio('Ask').getAttribute('aria-checked')).toBe('true');
  });

  it('says Unknown for an interrupt budget the hub did not report', async () => {
    hub({ interrupts: { status: 200, body: { remaining: null, per_day: null, used: null } } });
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    await waitFor(() => expect(document.querySelector('[data-runhead="interrupts"]')?.textContent).toContain('Unknown — not reported'));
  });

  it('is marks and short words in the floating window, still all eight items: the mode read there, not changed', async () => {
    const calls = hub();
    const { unmount } = render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} variant="marks" />);
    expect(within(signal('egress')).getByRole('button').textContent).toBe('Checking…');
    unmount();
    const live = hubSnapshotFrom({ ...LIVE_DATA, llmBackend: 'ollama' }, null, { now: Date.now() });
    render(<RunningHead hub={live} lang="en" demo={false} variant="marks" links={false} />);
    const head = document.querySelector('[data-frame="runhead"]') as HTMLElement;
    expect([...head.querySelectorAll('[data-signal]')].map((el) => el.getAttribute('data-signal'))).toEqual([...SIGNAL_IDS]);
    const mode = head.querySelector('[data-runhead="mode"]') as HTMLElement;
    const interrupts = head.querySelector('[data-runhead="interrupts"]') as HTMLElement;
    expect(mode).not.toBeNull();
    expect(interrupts).not.toBeNull();
    await waitFor(() => expect(mode.querySelector('[data-mode]')?.textContent).toBe('Ask'));
    expect(mode.hasAttribute('data-readonly')).toBe(true);
    expect(mode.getAttribute('title')).toContain('Anything with a side effect waits for your approval.');
    expect(within(head).queryByRole('radiogroup')).toBeNull();
    expect(within(mode).queryByRole('button')).toBeNull();
    // the marks draw the count alone; the whole reading is the button's name and its popover's
    const budget = within(interrupts).getByRole('button');
    await waitFor(() => expect(budget.textContent).toBe('1 of 4'));
    expect(budget.getAttribute('aria-label')).toBe('Interrupts: 1 of 4 used today');
    // the floating window shows no other page: a popover names no page to open
    fireEvent.click(within(signal('model')).getByRole('button'));
    expect(signal('model').textContent).toContain('gemma-4-31b');
    expect(within(signal('model')).queryByRole('link')).toBeNull();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
  });

  it('reads a refused mode as refused in the marks, never as a default', async () => {
    hub({ mode: { status: 403, body: { detail: 'admin token required' } }, interrupts: { status: 403 } });
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} variant="marks" />);
    await waitFor(() => expect(document.querySelector('[data-runhead="mode"]')?.textContent).toContain('Refused — needs the owner credential'));
    expect(document.querySelector('[data-runhead="mode"] [data-mode]')).toBeNull();
    await waitFor(() => expect(document.querySelector('[data-runhead="interrupts"]')?.textContent).toContain('Refused'));
  });

  it('speaks Romanian', async () => {
    hub();
    render(<RunningHead hub={initialHubSnapshot()} lang="ro" demo={false} />);
    expect(screen.getByRole('button', { name: 'Ieșire: Se verifică…' })).toBeTruthy();
    const group = screen.getByRole('radiogroup', { name: 'Mod de aprobare' });
    await waitFor(() => expect(within(group).getByRole('radio', { name: 'Întreabă' }).getAttribute('aria-checked')).toBe('true'));
    await waitFor(() => expect(document.querySelector('[data-runhead="interrupts"]')?.textContent).toContain('1 din 4 folosite azi'));
  });
});

/* Below 760px (§4.2 "one line of marks", §5.1, §11): every item is a mark (the approval mode its
   word, the interrupts their count), each a button named with the words it no longer draws, with
   its popover. frame.css lays the line out (frame-fit-css.test.ts); the e2e render matrix
   (e2e/ledger-shots.spec.ts) measures it at 320, 390, 600 and 740px. */
describe('RunningHead below 760px', () => {
  /** A window narrower than 760px. */
  const narrowWindow = () => vi.stubGlobal('matchMedia', (query: string) => ({
    matches: query === MARKS_QUERY, media: query, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {},
  }));
  const head = () => document.querySelector('[data-frame="runhead"]') as HTMLElement;

  it('is one line of marks: each signal its mark alone, named with its words, the whole value in its popover', async () => {
    hub();
    narrowWindow();
    const live = hubSnapshotFrom({ ...LIVE_DATA, llmBackend: 'ollama' }, null, { now: Date.now() });
    render(<RunningHead hub={live} lang="en" demo={false} />);
    expect(head().classList.contains('n-runhead--compact')).toBe(true);
    expect([...head().querySelectorAll('[data-signal]')].map((el) => el.getAttribute('data-signal'))).toEqual([...SIGNAL_IDS]);
    for (const id of SIGNAL_IDS) {
      const button = within(signal(id)).getByRole('button');
      // the mark alone: a shape, hidden from assistive tech, whose words are the button's name
      expect(button.textContent).toBe('');
      expect(button.querySelector('svg[data-mark]')?.getAttribute('aria-hidden')).toBe('true');
      expect(button.getAttribute('aria-label')).toMatch(/^[^:]+: .+/);
      expect(button.getAttribute('title')).toBe(button.getAttribute('aria-label'));
      // the label is read, not drawn
      expect(signal(id).querySelector('dt')?.hasAttribute('data-visually-hidden')).toBe(true);
    }
    const model = screen.getByRole('button', { name: 'Model: gemma-4-31b · ollama' });
    fireEvent.click(model);
    expect(model.getAttribute('aria-expanded')).toBe('true');
    expect(signal('model').querySelector('.n-signals__said')?.textContent).toBe('gemma-4-31b· ollama');
    expect(within(signal('model')).getByRole('link', { name: 'Model setup' })).toBeTruthy();
    await waitFor(() => expect(screen.getByRole('button', { name: /^Audit chain: Intact · 921 sealed/ })).toBeTruthy());
  });

  it('draws the approval mode as its word and keeps it changeable in its popover, with the same friction', async () => {
    const calls = hub();
    narrowWindow();
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    const button = await screen.findByRole('button', { name: 'Approval mode: Ask' });
    expect(button.textContent).toBe('Ask');
    expect(button.getAttribute('title')).toContain('Anything with a side effect waits for your approval.');
    // the choice is in the popover, not on the line
    expect(screen.queryByRole('radiogroup')).toBeNull();
    fireEvent.click(button);
    fireEvent.click(radio('Auto'));
    const confirm = await confirmShown();
    expect(head().querySelector('[data-runhead="mode"]')?.contains(confirm)).toBe(true);
    expect(confirm.textContent).toContain('Auto lets reversible actions run without asking.');
    // closing the popover drops the looser choice that was not confirmed: nothing is written
    fireEvent.click(button);
    expect(document.querySelector('[data-runhead="confirm"]')).toBeNull();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
    // a stricter one is one click, from the popover
    fireEvent.click(button);
    fireEvent.click(radio('Off'));
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST')).toEqual([{ method: 'POST', path: '/autonomy/mode', body: { mode: 'off' } }]));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Approval mode: Off' }).textContent).toBe('Off'));
  });

  it('draws the interrupts as their count, the whole reading in the name and the popover', async () => {
    hub();
    narrowWindow();
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    const button = await screen.findByRole('button', { name: 'Interrupts: 1 of 4 used today' });
    expect(button.textContent).toBe('1 of 4');
    fireEvent.click(button);
    const item = head().querySelector('[data-runhead="interrupts"]') as HTMLElement;
    expect(item.textContent).toContain('1 of 4 used today');
    expect(item.textContent).toContain('Proactive interruptions used today, against the daily ceiling.');
  });

  it('draws what it could not read as the mark of what is known, never a default, the reason in the name', async () => {
    hub({ mode: { status: 403, body: { detail: 'admin token required' } }, interrupts: { status: 403 } });
    narrowWindow();
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    const mode = await screen.findByRole('button', { name: 'Approval mode: Refused — needs the owner credential' });
    expect(mode.textContent).toBe('');
    expect(mode.querySelector('[data-mark="blocked"]')).not.toBeNull();
    const interrupts = await screen.findByRole('button', { name: /^Interrupts: Refused/ });
    expect(interrupts.textContent).toBe('');
    expect(interrupts.querySelector('[data-mark="blocked"]')).not.toBeNull();
    // in its popover the mode cannot be changed, and says why
    fireEvent.click(mode);
    for (const name of ['Auto', 'Ask', 'Off']) expect(radio(name).disabled).toBe(true);
    expect(head().querySelector('[data-runhead="mode"]')?.textContent).toContain('Refused — needs the owner credential');
  });

  it('speaks Romanian', async () => {
    hub();
    narrowWindow();
    render(<RunningHead hub={initialHubSnapshot()} lang="ro" demo={false} />);
    expect(screen.getByRole('button', { name: 'Ieșire: Se verifică…' }).textContent).toBe('');
    expect((await screen.findByRole('button', { name: 'Mod de aprobare: Întreabă' })).textContent).toBe('Întreabă');
    expect((await screen.findByRole('button', { name: 'Întreruperi: 1 din 4 folosite azi' })).textContent).toBe('1 din 4');
  });

  it('draws the floating window\'s and Glance\'s marks as the same one line, the mode still read, not changed', async () => {
    // measured at 420px (e2e runhead-window): mark and short word per item took four lines and cut
    // the interrupts at the window's edge; §4.2 asks one line of marks there
    const calls = hub();
    narrowWindow();
    const live = hubSnapshotFrom({ ...LIVE_DATA, llmBackend: 'ollama' }, null, { now: Date.now() });
    render(<RunningHead hub={live} lang="en" demo={false} variant="marks" links={false} />);
    expect(head().classList.contains('n-runhead--compact')).toBe(true);
    for (const id of SIGNAL_IDS) {
      const button = within(signal(id)).getByRole('button');
      expect(button.textContent).toBe('');
      expect(button.getAttribute('aria-label')).toMatch(/^[^:]+: .+/);
    }
    // the mode is its word, a button whose popover says it and what it means, with no choice in it
    const mode = await screen.findByRole('button', { name: 'Approval mode: Ask' });
    expect(mode.textContent).toBe('Ask');
    fireEvent.click(mode);
    const item = head().querySelector('[data-runhead="mode"]') as HTMLElement;
    expect(item.hasAttribute('data-readonly')).toBe(true);
    expect(item.textContent).toContain('Anything with a side effect waits for your approval.');
    expect(within(head()).queryByRole('radiogroup')).toBeNull();
    expect((await screen.findByRole('button', { name: 'Interrupts: 1 of 4 used today' })).textContent).toBe('1 of 4');
    // the floating window shows no other page: a popover names no page to open
    fireEvent.click(screen.getByRole('button', { name: 'Model: gemma-4-31b · ollama' }));
    expect(within(signal('model')).queryByRole('link')).toBeNull();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
  });

  it('draws an unread mode in the marks as the mark of what is known, the reason in its name', async () => {
    hub({ mode: { status: 403, body: { detail: 'admin token required' } } });
    narrowWindow();
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} variant="marks" />);
    const mode = await screen.findByRole('button', { name: 'Approval mode: Refused — needs the owner credential' });
    expect(mode.textContent).toBe('');
    expect(mode.querySelector('[data-mark="blocked"]')).not.toBeNull();
    fireEvent.click(mode);
    expect(head().querySelector('[data-runhead="mode"]')?.textContent).toContain('Refused — needs the owner credential');
  });
});

/* Fitting the line from 1100px (RUNHEAD_FIT_STEPS; frame.css draws each step and
   frame-fit-css.test.ts pins that it does; e2e/ledger-shots.spec.ts runhead-fit measures the real
   thing). jsdom lays nothing out, so the geometry is a model: the eight items side by side, the
   line `need(steps)` px long in a head `room` px wide, and the free-length values cut (their
   scrollWidth past their box) while `cut(steps)` says so — by 50px each when it says true, or by
   the px it gives. Every read of the layout is counted. */
type LineModel = { room: number; need: (steps: string[]) => number; cut?: (steps: string[]) => boolean | number; past?: (el: Element) => number };
const ITEM_SELECTOR = '[data-signal], [data-runhead="mode"], [data-runhead="interrupts"]';
const layout = { reads: 0 };
function stubLine(model: LineModel) {
  const stepsAt = (el: Element) => (el.closest('[data-frame="runhead"]')?.getAttribute('data-fit') || '').split(' ').filter(Boolean);
  const rect = (left: number, right: number) => ({ left, right, top: 0, bottom: 34, width: right - left, height: 34, x: left, y: 0, toJSON() { return this; } }) as DOMRect;
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
    layout.reads += 1;
    const head = this.closest('[data-frame="runhead"]');
    if (!head) return rect(0, 0);
    if (this === head) return rect(0, model.room);
    const items = Array.from(head.querySelectorAll(ITEM_SELECTOR));
    const item = this.matches(ITEM_SELECTOR) ? this : this.closest(ITEM_SELECTOR);
    const at = item ? items.indexOf(item) : -1;
    if (at < 0) return rect(0, 0);
    const w = model.need(stepsAt(head)) / items.length;
    // a part drawn `past(el)` px beyond its item's right edge (an item narrower than what it draws)
    return rect(at * w, (at + 1) * w + (this === item ? 0 : model.past?.(this) ?? 0));
  });
  const width = (el: Element, scroll: boolean) => {
    layout.reads += 1;
    if (!el.matches('.n-signals__ident, .n-signals__text')) return 0;
    const cut = scroll ? model.cut?.(stepsAt(el)) : 0;
    return 50 + (typeof cut === 'number' ? Math.max(0, cut) : cut ? 50 : 0);
  };
  Object.defineProperty(HTMLElement.prototype, 'scrollWidth', { configurable: true, get() { return width(this, true); } });
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get() { return width(this, false); } });
}
/** A window whose width matches the media queries from `px` (the running head's forms). */
const windowOf = (px: number) => vi.stubGlobal('matchMedia', (query: string) => {
  const min = /min-width:\s*(\d+)px/.exec(query);
  const max = /max-width:\s*(\d+)px/.exec(query);
  const matches = (!min || px >= Number(min[1])) && (!max || px <= Number(max[1]));
  return { matches, media: query, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {} };
});
function bareHead(): HTMLElement {
  const head = document.createElement('div');
  head.setAttribute('data-frame', 'runhead');
  head.className = 'n-runhead n-runhead--full';
  head.innerHTML = ['egress', 'localRoute', 'microphone', 'model', 'data', 'chain'].map((id) =>
    `<div data-signal="${id}"><dt>${id}</dt><dd><button class="n-signals__button"><span class="n-signals__text">${id}</span></button></dd></div>`).join('')
    + '<div data-runhead="mode"></div><div data-runhead="interrupts"></div>';
  document.body.appendChild(head);
  return head;
}

describe('RunningHead — fitting its line from 1100px', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete (HTMLElement.prototype as any).scrollWidth;
    delete (HTMLElement.prototype as any).clientWidth;
    document.querySelectorAll('body > [data-frame="runhead"]').forEach((el) => el.remove());
  });

  it('takes its steps in the measured order, each only where it changes something', () => {
    expect(RUNHEAD_FIT_STEPS).toEqual(['source', 'short', 'egress', 'values', 'tight', 'labels', 'mode', 'cut', 'lines']);
    const at = (form: 'xl' | 'l' | 'm' | 's', variant: 'full' | 'marks' = 'full') => RUNHEAD_FIT_STEPS.filter((step) => runheadStepApplies(step, form, variant));
    expect(at('xl')).toEqual([...RUNHEAD_FIT_STEPS]);
    // below 2200px the values are short already; below 1680px the labels too, and the sources'
    // reasons read; below 1340px the labels are read, not drawn
    expect(at('l')).toEqual(['source', 'short', 'tight', 'labels', 'mode', 'cut', 'lines']);
    expect(at('m')).toEqual(['tight', 'labels', 'mode', 'cut', 'lines']);
    expect(at('s')).toEqual(['tight', 'mode', 'cut', 'lines']);
    // the marks (Glance, the floating window) draw no label, no long value and no choice
    expect(at('xl', 'marks')).toEqual(['source', 'tight', 'cut', 'lines']);
    expect(at('m', 'marks')).toEqual(['tight', 'cut', 'lines']);
  });

  it('measures its way through the steps until nothing spills; below 1100px it takes none', () => {
    const model: LineModel = { room: 1500, need: (steps) => 2000 - 100 * steps.length };
    stubLine(model);
    const head = bareHead();
    fitRunningHead(head, { form: 'xl' });
    expect(head.getAttribute('data-fit')).toBe('source short egress values tight');
    // 1340–1679px: the steps that change nothing there are passed over
    fitRunningHead(head, { form: 'm' });
    expect(head.getAttribute('data-fit')).toBe('tight labels mode cut lines');
    model.need = (steps) => 1700 - 100 * steps.length;
    fitRunningHead(head, { form: 'm' });
    expect(head.getAttribute('data-fit')).toBe('tight labels');
    // a line tighter spacing alone fits keeps its labels drawn
    model.need = (steps) => 1560 - 100 * steps.length;
    fitRunningHead(head, { form: 'm' });
    expect(head.getAttribute('data-fit')).toBe('tight');
    // nothing changed: going on from the steps taken finds nothing to do
    fitRunningHead(head, { form: 'm', fresh: false });
    expect(head.getAttribute('data-fit')).toBe('tight');
    // a line that fits takes no step; below 1100px none is ever written
    model.need = () => 1400;
    fitRunningHead(head, { form: 's' });
    expect(head.hasAttribute('data-fit')).toBe(false);
    model.need = () => 4000;
    fitRunningHead(head, { form: null });
    expect(head.hasAttribute('data-fit')).toBe(false);
  });

  it('counts a value cut with an ellipsis as a spill until the "cut" step, and only then accepts it', () => {
    // the line fits, but only because the free-length values are cut: every step before "cut" is
    // tried; folding the mode gives them room ("tight", which gave them none, is taken back)
    const model: LineModel = { room: 1500, need: () => 1400, cut: (steps) => !steps.includes('mode') };
    stubLine(model);
    const head = bareHead();
    fitRunningHead(head, { form: 's' });
    expect(head.getAttribute('data-fit')).toBe('mode');
    expect(runheadSpills(head)).toBe(false);
    // values cut whatever is folded: "cut" is taken, and nothing the cut would deepen comes back
    model.cut = (steps) => 100 - (steps.includes('mode') ? 60 : 0) - (steps.includes('tight') ? 20 : 0);
    fitRunningHead(head, { form: 's' });
    expect(head.getAttribute('data-fit')).toBe('tight mode cut');
    expect(runheadSpills(head)).toBe(false);
    head.setAttribute('data-fit', 'tight mode');
    expect(runheadSpills(head)).toBe(true);
  });

  it('takes back, the lossiest first, a step a later one made unneeded, never deepening a cut', () => {
    // 2560px with the widest values: the source labels' reasons (~160px) and the long labels (~300px)
    // went before the egress statement's short form freed ~640px; with it, the long labels come back
    const frees: Record<string, number> = { source: 160, short: 300, egress: 640, values: 120, tight: 60 };
    const model: LineModel = { room: 2400, need: (steps) => 3000 - steps.reduce((sum, step) => sum + (frees[step] ?? 0), 0) };
    stubLine(model);
    const head = bareHead();
    fitRunningHead(head, { form: 'xl' });
    // the walk ended on "source short egress" (1900px in 2400); with the egress statement short,
    // the long labels come back (2200px), and so does the source labels' reason (2360px)
    expect(head.getAttribute('data-fit')).toBe('egress');
    // with less room the reason stays read (2360px would spill), the labels still come back
    model.room = 2300;
    fitRunningHead(head, { form: 'xl' });
    expect(head.getAttribute('data-fit')).toBe('source egress');
    // nothing a cut would deepen comes back: at 1180px the walk needs the cut, and taking the closer
    // spacing back would leave the line whole only by cutting the values further (the cut grows
    // with what the line needs, as the free-length values give way)
    model.room = 1100;
    model.need = (steps) => 1400 - (steps.includes('tight') ? 60 : 0) - (steps.includes('mode') ? 300 : 0);
    model.cut = (steps) => (model.need(steps) - 900) / 6;
    fitRunningHead(head, { form: 's' });
    expect(head.getAttribute('data-fit')).toBe('tight mode cut');
  });

  /* Review, fourth round: "Model cloud configur…" and the model id were drawn cut before the "cut"
     step (Console Romanian at 1536px, Threshold light Romanian at 2200px): 0.11–1.41px wider than
     their boxes, which whole pixels read as equal or as one pixel over — not a spill — while
     Chromium draws the ellipsis for any overflow of a layout unit. */
  it('counts a value cut by less than a pixel as a spill before the "cut" step, as Chromium draws the ellipsis', () => {
    stubLine({ room: 1500, need: () => 1400 });
    const head = bareHead();
    const text = head.querySelector('[data-signal="model"] .n-signals__text') as HTMLElement;
    expect(runheadSpills(head)).toBe(false);
    const box = (left: number, right: number) => ({ left, right, top: 8, bottom: 26, width: right - left, height: 18, x: left, y: 8, toJSON() { return this; } }) as DOMRect;
    const spy = vi.mocked(Element.prototype.getBoundingClientRect);
    const line = spy.getMockImplementation() as (this: Element) => DOMRect;
    spy.mockImplementation(function (this: Element) { return this === text ? box(600, 700) : line.call(this); });
    // the model's text 0.33px wider than its box: scrollWidth and clientWidth read equal
    vi.spyOn(document, 'createRange').mockImplementation(() => {
      let node: Node | null = null;
      return { selectNodeContents: (n: Node) => { node = n; }, getClientRects: () => (node === text ? [box(600, 700.33)] : []) } as unknown as Range;
    });
    expect(text.scrollWidth).toBe(text.clientWidth);
    expect(runheadSpills(head)).toBe(true);
    // from the "cut" step a cut value is accepted (its name, title and popover keep it whole)
    head.setAttribute('data-fit', 'cut');
    expect(runheadSpills(head)).toBe(false);
  });

  it('counts an item past the line, or a part past its item, as a spill', () => {
    stubLine({ room: 1500, need: () => 1400 });
    const head = bareHead();
    expect(runheadSpills(head)).toBe(false);
    vi.restoreAllMocks();
    stubLine({ room: 1500, need: () => 1600 });
    expect(runheadSpills(head)).toBe(true);
    // a value drawn past its own item (an item narrower than what it draws) is a spill too
    vi.restoreAllMocks();
    const button = head.querySelector('[data-signal="model"] .n-signals__button') as HTMLElement;
    stubLine({ room: 1500, need: () => 1400, past: (el) => (el === button ? 40 : 0) });
    expect(runheadSpills(head)).toBe(true);
  });

  it('fits itself when it renders and when its words change, and reads no layout on a render that changes nothing', async () => {
    hub();
    windowOf(1280);
    // Romanian is longer: it needs the mode folded too
    const model: LineModel = { room: 1240, need: (steps) => (document.querySelector('[data-frame="runhead"] [lang="ro"], [data-frame="runhead"][data-lang="ro"]') ? 1500 : 1300) - 100 * steps.length };
    stubLine(model);
    model.need = (steps) => (document.querySelector('[data-frame="runhead"]')?.getAttribute('aria-label') === 'Antet de pagină' ? 1500 : 1300) - 100 * steps.length;
    const live = hubSnapshotFrom(LIVE_DATA, null, { now: Date.now() });
    const { rerender } = render(<RunningHead hub={live} lang="en" demo={false} />);
    const head = document.querySelector('[data-frame="runhead"]') as HTMLElement;
    expect(head.getAttribute('data-fit')).toBe('tight');
    await act(async () => { rerender(<RunningHead hub={live} lang="ro" demo={false} />); });
    expect(head.getAttribute('data-fit')).toBe('tight mode cut');
    await act(async () => { rerender(<RunningHead hub={live} lang="en" demo={false} />); });
    expect(head.getAttribute('data-fit')).toBe('tight');
    layout.reads = 0;
    for (let i = 0; i < 5; i += 1) await act(async () => { rerender(<RunningHead hub={live} lang="en" demo={false} navigate={vi.fn()} />); });
    expect(layout.reads).toBe(0);
  });
});

/** A line at 1180px that needs the closer spacing and the mode folded ("tight mode"): 1400px, the
 *  spacing frees 60 and the fold 300, in 1080px. */
const foldLine = (): LineModel => ({ room: 1080, need: (steps) => 1400 - (steps.includes('tight') ? 60 : 0) - (steps.includes('mode') ? 300 : 0) });

/* The approval mode folded into its word (the "mode" step): the same choice, source and friction,
   in a popover. The fit is modelled so that it folds the mode at this width. */
describe('RunningHead — the approval mode folded into its word', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete (HTMLElement.prototype as any).scrollWidth;
    delete (HTMLElement.prototype as any).clientWidth;
  });
  const folded = () => {
    windowOf(1180);
    stubLine(foldLine());
  };

  it('is a button named with the mode in force, the choice in its popover, a looser mode still two steps', async () => {
    const calls = hub();
    folded();
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    const head = document.querySelector('[data-frame="runhead"]') as HTMLElement;
    const fold = await screen.findByRole('button', { name: 'Approval mode: Ask' });
    expect(head.getAttribute('data-fit')).toBe('tight mode');
    expect(fold.textContent).toBe('Ask');
    expect(fold.getAttribute('title')).toContain('Anything with a side effect waits for your approval.');
    expect(fold.getAttribute('aria-expanded')).toBe('false');
    const mode = head.querySelector('[data-runhead="mode"]') as HTMLElement;
    expect(document.getElementById(fold.getAttribute('aria-controls') as string)?.contains(modeGroup())).toBe(true);
    fireEvent.click(fold);
    expect(fold.getAttribute('aria-expanded')).toBe('true');
    expect(mode.hasAttribute('data-open')).toBe(true);
    // a looser choice in the popover takes the confirmation, as in the line
    fireEvent.click(radio('Auto'));
    const confirm = await confirmShown();
    expect(mode.contains(confirm)).toBe(true);
    expect(confirm.textContent).toContain('Auto lets reversible actions run without asking.');
    // the armed confirmation takes the focus (confirm.tsx); Escape there closes the popover, drops
    // the unconfirmed choice and returns to the button: nothing written
    const switchTo = within(confirm).getByRole('button', { name: 'Switch to Auto' });
    await waitFor(() => expect(document.activeElement).toBe(switchTo));
    fireEvent.keyDown(switchTo, { key: 'Escape' });
    expect(fold.getAttribute('aria-expanded')).toBe('false');
    expect(document.querySelector('[data-runhead="confirm"]')).toBeNull();
    expect(document.activeElement).toBe(fold);
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
    // a press outside closes it too
    fireEvent.click(fold);
    fireEvent.mouseDown(document.body);
    expect(fold.getAttribute('aria-expanded')).toBe('false');
    // a stricter one is one click, from the popover
    fireEvent.click(fold);
    fireEvent.click(radio('Off'));
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST')).toEqual([{ method: 'POST', path: '/autonomy/mode', body: { mode: 'off' } }]));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Approval mode: Off' }).textContent).toBe('Off'));
  });

  it('draws what it could not read as the mark of what is known, with the reason in its name', async () => {
    hub({ mode: { status: 403, body: { detail: 'admin token required' } } });
    folded();
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    const fold = await screen.findByRole('button', { name: 'Approval mode: Refused — needs the owner credential' });
    expect(fold.textContent).toBe('');
    expect(fold.querySelector('[data-mark="blocked"]')).not.toBeNull();
    fireEvent.click(fold);
    for (const name of ['Auto', 'Ask', 'Off']) expect(radio(name).disabled).toBe(true);
  });

  it('opens its popover on a refusal that lands while it is folded, so the refusal is seen', async () => {
    hub({ post: () => ({ status: 503, body: { error: 'mode_not_saved', mode: 'ask' } }) });
    folded();
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    const fold = await screen.findByRole('button', { name: 'Approval mode: Ask' });
    fireEvent.click(fold);
    fireEvent.click(radio('Off'));
    const note = await screen.findByRole('alert');
    expect(note.textContent).toContain('Off was not saved. Ask is in force.');
    expect(fold.getAttribute('aria-expanded')).toBe('true');
  });
});

/* A key held down, as a browser delivers it: the first keydown, then its auto-repeats (repeat: true),
   each to whatever has the focus by then. Enter on a button clicks it unless the keydown's default
   was prevented (the browser's activation behaviour; jsdom does not do that part itself). The page's
   answers (the mode asked again) land between two repeats, as they do ~33 ms apart in a browser.
   Returns the buttons a press was held back on, by name. */
async function holdEnter(presses: number): Promise<string[]> {
  const held: string[] = [];
  for (let i = 0; i < presses; i += 1) {
    const target = document.activeElement as HTMLElement | null;
    if (!target || target === document.body) break;
    const down = new KeyboardEvent('keydown', { key: 'Enter', repeat: i > 0, bubbles: true, cancelable: true });
    await act(async () => {
      target.dispatchEvent(down);
      if (!down.defaultPrevented && target instanceof HTMLButtonElement) target.click();
    });
    if (down.defaultPrevented) held.push(target.getAttribute('aria-label') || target.textContent || '');
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  }
  return held;
}

/* Loosening the mode is two steps in every form: the press that chooses Auto moves the focus onto
   "Switch to Auto" (confirm.tsx), so the confirming button takes only a fresh press
   (repeatConfirms={false}). Otherwise holding Enter on the Auto radio would choose it on the first
   keydown and press "Switch to Auto" with an auto-repeat: one gesture, and POST /autonomy/mode. */
describe('RunningHead — a key held down never loosens the mode', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete (HTMLElement.prototype as any).scrollWidth;
    delete (HTMLElement.prototype as any).clientWidth;
  });
  const posts = (calls: Array<{ method: string }>) => calls.filter((c) => c.method === 'POST');

  /** Hold Enter on the focused Auto radio; then the second click of a double-click; then a fresh press. */
  async function holdOnAuto(calls: Array<{ method: string; path: string; body: unknown }>) {
    const auto = radio('Auto');
    auto.focus();
    expect(document.activeElement).toBe(auto);
    const held = await holdEnter(8);
    // nothing was written: the first press chose Auto and armed the confirmation, which took the
    // focus, and every repeat that reached it was held back
    expect(posts(calls)).toEqual([]);
    const confirm = await confirmShown();
    const switchTo = within(confirm).getByRole('button', { name: 'Switch to Auto' });
    expect(document.activeElement).toBe(switchTo);
    expect(held.filter((name) => name === 'Switch to Auto').length).toBeGreaterThan(0);
    // nor is the second click of a double-click a press
    fireEvent.click(switchTo, { detail: 2 });
    expect(posts(calls)).toEqual([]);
    // a fresh press confirms: the second step is still one press away, never zero
    expect(await holdEnter(1)).toEqual([]);
    await waitFor(() => expect(posts(calls)).toEqual([{ method: 'POST', path: '/autonomy/mode', body: { mode: 'auto' } }]));
  }

  it('in the line', async () => {
    const calls = hub();
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    await waitFor(() => expect(radio('Ask').getAttribute('aria-checked')).toBe('true'));
    await holdOnAuto(calls);
  });

  it('folded into its word (the "mode" fit step), in its popover', async () => {
    const calls = hub();
    windowOf(1180);
    stubLine(foldLine());
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    const fold = await screen.findByRole('button', { name: 'Approval mode: Ask' });
    expect(document.querySelector('[data-frame="runhead"]')?.getAttribute('data-fit')).toBe('tight mode');
    fireEvent.click(fold);
    expect(fold.getAttribute('aria-expanded')).toBe('true');
    await holdOnAuto(calls);
  });

  it('below 760px, in its popover', async () => {
    const calls = hub();
    vi.stubGlobal('matchMedia', (query: string) => ({
      matches: query === MARKS_QUERY, media: query, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {},
    }));
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Approval mode: Ask' }));
    await holdOnAuto(calls);
  });

  it('a stricter mode is still one press, held or not, and is written once', async () => {
    const calls = hub();
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    await waitFor(() => expect(radio('Ask').getAttribute('aria-checked')).toBe('true'));
    radio('Off').focus();
    await holdEnter(4);
    await waitFor(() => expect(posts(calls)).toEqual([{ method: 'POST', path: '/autonomy/mode', body: { mode: 'off' } }]));
    expect(document.querySelector('[data-runhead="confirm"]')).toBeNull();
  });
});

/** A window that can be resized: matchMedia answers for its width and tells its listeners, then
 *  the window says it was resized (both rows refit on that). */
function resizableWindow(px: number) {
  let width = px;
  const listeners = new Set<() => void>();
  vi.stubGlobal('matchMedia', (query: string) => {
    const min = /min-width:\s*(\d+)px/.exec(query);
    const max = /max-width:\s*(\d+)px/.exec(query);
    return {
      get matches() { return (!min || width >= Number(min[1])) && (!max || width <= Number(max[1])); },
      media: query,
      addEventListener: (_: string, fn: () => void) => listeners.add(fn), removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
      addListener: (fn: () => void) => listeners.add(fn), removeListener: (fn: () => void) => listeners.delete(fn),
    };
  });
  return {
    set: (next: number) => act(() => {
      width = next;
      listeners.forEach((fn) => fn());
      window.dispatchEvent(new Event('resize'));
    }),
  };
}
/** The line's room changed (the window, a font, a reading elsewhere on the line): the head refits. */
const refit = (line: LineModel, room: number) => act(() => { line.room = room; window.dispatchEvent(new Event('resize')); });
const runhead = () => document.querySelector('[data-frame="runhead"]') as HTMLElement;
const modeRoot = () => document.querySelector('[data-frame="runhead"] [data-runhead="mode"]') as HTMLElement;
const foldButton = () => document.querySelector('[data-runhead="mode"] .n-runhead__fold') as HTMLButtonElement;
const steps = () => runhead().getAttribute('data-fit') || '';
/** jsdom lays nothing out: here an element counts as drawn (it has client rects) unless it is in a
 *  hidden subtree, as the approval mode's closed popover below 760px is. */
const drawnUnlessHidden = () => vi.spyOn(Element.prototype, 'getClientRects').mockImplementation(function (this: Element) {
  return (this.closest('[hidden]') ? [] : [{ left: 0, top: 0, right: 10, bottom: 10, width: 10, height: 10 }]) as unknown as DOMRectList;
});

/* The folded approval mode and the fit (review, third polish round): the popover goes with the fold,
   a press outside never drops what waits in the line, a fit never moves the mode while its looser
   choice waits for the second step, and a focus in the mode follows it into its new form. */
describe('RunningHead — the approval mode as the fit moves it', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete (HTMLElement.prototype as any).scrollWidth;
    delete (HTMLElement.prototype as any).clientWidth;
  });
  /** At 1180px: a line that fits as it is in 1500px, and needs "tight mode" in 1080px. */
  async function atWidth(room: number) {
    const calls = hub();
    windowOf(1180);
    const line = { ...foldLine(), room };
    stubLine(line);
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    await waitFor(() => expect(within(modeGroup()).getByRole('radio', { name: 'Ask' }).getAttribute('aria-checked')).toBe('true'));
    return { calls, line };
  }

  it('closes its popover when a fit unfolds it, so the next fold does not come back open', async () => {
    const { line } = await atWidth(1080);
    expect(steps()).toBe('tight mode');
    fireEvent.click(foldButton());
    expect(foldButton().getAttribute('aria-expanded')).toBe('true');
    refit(line, 1500);
    expect(steps()).toBe('');
    expect(foldButton().getAttribute('aria-expanded')).toBe('false');
    expect(document.querySelector('[data-runhead="mode"]')?.hasAttribute('data-open')).toBe(false);
    refit(line, 1080);
    expect(steps()).toBe('tight mode');
    expect(foldButton().getAttribute('aria-expanded')).toBe('false');
  });

  it('never drops a confirmation or the hub\'s answer drawn in the line on a press outside', async () => {
    const { calls, line } = await atWidth(1080);
    // opened while folded, then unfolded by a fit: the line's choice, not a popover
    fireEvent.click(foldButton());
    refit(line, 1500);
    fireEvent.click(radio('Auto'));
    const confirm = await confirmShown();
    fireEvent.mouseDown(document.body);
    expect(document.querySelector('[data-runhead="confirm"]')).toBe(confirm);
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
    fireEvent.click(within(confirm).getByRole('button', { name: 'Cancel' }));
    expect(document.querySelector('[data-runhead="confirm"]')).toBeNull();
  });

  it('keeps a refusal drawn in the line until it is closed there', async () => {
    resetPolling();
    vi.unstubAllGlobals();
    hub({ post: () => ({ status: 503, body: { error: 'mode_not_saved', mode: 'ask' } }) });
    windowOf(1180);
    const line = { ...foldLine(), room: 1080 };
    stubLine(line);
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    await waitFor(() => expect(foldButton().getAttribute('aria-label')).toBe('Approval mode: Ask'));
    fireEvent.click(foldButton());
    refit(line, 1500);
    fireEvent.click(radio('Off'));
    const note = await screen.findByRole('alert');
    fireEvent.mouseDown(document.body);
    expect(screen.getByRole('alert')).toBe(note);
    expect(note.textContent).toContain('Off was not saved. Ask is in force.');
  });

  it('is never folded while its looser choice waits for the second step, and folds once it is answered', async () => {
    const { calls, line } = await atWidth(1500);
    expect(steps()).toBe('');
    fireEvent.click(radio('Auto'));
    const confirm = await confirmShown();
    const switchTo = within(confirm).getByRole('button', { name: 'Switch to Auto' });
    await waitFor(() => expect(document.activeElement).toBe(switchTo));
    // the line narrows: the mode holds, the line gives up something else instead
    refit(line, 1080);
    expect(steps().split(' ')).not.toContain('mode');
    expect(document.querySelector('[data-runhead="mode"]')?.hasAttribute('data-hold')).toBe(true);
    expect(document.querySelector('[data-runhead="confirm"]')).toBe(confirm);
    expect(document.activeElement).toBe(switchTo);
    // answered: the hold goes, and the head refits at once
    fireEvent.click(within(confirm).getByRole('button', { name: 'Cancel' }));
    await act(async () => {});
    expect(steps()).toBe('tight mode');
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
  });

  it('is never unfolded while its looser choice waits in the popover, and unfolds once it is answered', async () => {
    const { calls, line } = await atWidth(1080);
    fireEvent.click(foldButton());
    fireEvent.click(radio('Auto'));
    const confirm = await confirmShown();
    refit(line, 1500);
    expect(steps()).toContain('mode');
    expect(foldButton().getAttribute('aria-expanded')).toBe('true');
    expect(document.querySelector('[data-runhead="confirm"]')).toBe(confirm);
    // the second step, a fresh press: written, and then the head unfolds
    fireEvent.click(within(confirm).getByRole('button', { name: 'Switch to Auto' }));
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST')).toEqual([{ method: 'POST', path: '/autonomy/mode', body: { mode: 'auto' } }]));
    await waitFor(() => expect(steps()).toBe(''));
  });

  it('keeps the fold and its waiting confirmation when the window narrows below 1100px, where no other step is drawn', async () => {
    const calls = hub();
    const win = resizableWindow(1180);
    stubLine(foldLine());
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    await waitFor(() => expect(foldButton().getAttribute('aria-label')).toBe('Approval mode: Ask'));
    expect(steps()).toBe('tight mode');
    fireEvent.click(foldButton());
    fireEvent.click(radio('Auto'));
    const confirm = await confirmShown();
    const switchTo = within(confirm).getByRole('button', { name: 'Switch to Auto' });
    await waitFor(() => expect(document.activeElement).toBe(switchTo));
    win.set(1000);
    expect(steps()).toBe('mode');
    expect(foldButton().getAttribute('aria-expanded')).toBe('true');
    expect(document.querySelector('[data-runhead="confirm"]')).toBe(confirm);
    expect(document.activeElement).toBe(switchTo);
    // answered: the head refits at its width, where no step is drawn, and the focus stays in the mode
    fireEvent.click(within(confirm).getByRole('button', { name: 'Cancel' }));
    await act(async () => {});
    expect(steps()).toBe('');
    expect(document.activeElement).toBe(radio('Ask'));
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
  });

  it('moves a focus that was in the mode to the control that stands for it when a fit moves it', async () => {
    const { line } = await atWidth(1500);
    radio('Ask').focus();
    refit(line, 1080);
    expect(steps()).toBe('tight mode');
    expect(document.activeElement).toBe(foldButton());
    refit(line, 1500);
    expect(steps()).toBe('');
    expect(document.activeElement).toBe(radio('Ask'));
    // a focus elsewhere stays where it is
    const elsewhere = within(signal('data')).getByRole('button');
    elsewhere.focus();
    refit(line, 1080);
    expect(document.activeElement).toBe(elsewhere);
  });

  it('gives the focus to the mode written once its confirmation leaves the screen', async () => {
    const { calls } = await atWidth(1500);
    fireEvent.click(radio('Auto'));
    const confirm = await confirmShown();
    fireEvent.click(within(confirm).getByRole('button', { name: 'Switch to Auto' }));
    await waitFor(() => expect(calls.filter((c) => c.method === 'POST')).toHaveLength(1));
    await waitFor(() => expect(document.activeElement).toBe(radio('Auto')));
  });

  /* Review, fourth round: holding the head's whole form across 760px drew the line past a phone's
     window (the model item to 405px in 390, the confirmation from -47px), and a refusal held it there
     until it was closed. The head now always follows the window; what waits goes with the mode. */
  it('follows the window across 760px while its looser choice waits: the same confirmation, in the marks\' popover, the focus kept', async () => {
    const calls = hub();
    const win = resizableWindow(1180);
    stubLine({ ...foldLine(), room: 1500 });
    drawnUnlessHidden();
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    await waitFor(() => expect(radio('Ask').getAttribute('aria-checked')).toBe('true'));
    fireEvent.click(radio('Auto'));
    const confirm = await confirmShown();
    const switchTo = within(confirm).getByRole('button', { name: 'Switch to Auto' });
    await waitFor(() => expect(document.activeElement).toBe(switchTo));
    expect(modeRoot().getAttribute('data-hold')).toBe('line');
    // below 760px the head is the marks, whatever waits (§4.2); the confirmation goes with the mode,
    // the very same controls (never drawn again), into its mark's popover, open, the focus kept
    win.set(600);
    await act(async () => {});
    expect(runhead().classList.contains('n-runhead--compact')).toBe(true);
    expect(document.querySelector('[data-runhead="confirm"]')).toBe(confirm);
    expect(foldButton().getAttribute('aria-expanded')).toBe('true');
    expect(confirm.closest('[hidden]')).toBeNull();
    expect(document.activeElement).toBe(switchTo);
    // back from 760px: in the line, where it was asked (the fit keeps it unfolded while it waits)
    win.set(1180);
    await act(async () => {});
    expect(runhead().classList.contains('n-runhead--compact')).toBe(false);
    expect(steps().split(' ')).not.toContain('mode');
    expect(document.querySelector('[data-runhead="confirm"]')).toBe(confirm);
    expect(document.activeElement).toBe(switchTo);
    fireEvent.click(within(confirm).getByRole('button', { name: 'Cancel' }));
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
  });

  it('keeps a choice asked below 760px in its popover when the window widens: folded until it is answered', async () => {
    const calls = hub();
    const win = resizableWindow(600);
    // from 1100px this line would fit with the mode in the line
    stubLine({ ...foldLine(), room: 1500 });
    drawnUnlessHidden();
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Approval mode: Ask' }));
    fireEvent.click(radio('Auto'));
    const confirm = await confirmShown();
    const switchTo = within(confirm).getByRole('button', { name: 'Switch to Auto' });
    await waitFor(() => expect(document.activeElement).toBe(switchTo));
    expect(modeRoot().getAttribute('data-hold')).toBe('fold');
    // 760–1099px: no other step is drawn, but the choice keeps its popover (the fold, open)
    win.set(900);
    await act(async () => {});
    expect(runhead().classList.contains('n-runhead--compact')).toBe(false);
    expect(steps()).toBe('mode');
    expect(foldButton().getAttribute('aria-expanded')).toBe('true');
    expect(document.querySelector('[data-runhead="confirm"]')).toBe(confirm);
    expect(document.activeElement).toBe(switchTo);
    // from 1100px the line would fit unfolded: the waiting choice holds the fold
    win.set(1180);
    await act(async () => {});
    expect(steps().split(' ')).toContain('mode');
    expect(foldButton().getAttribute('aria-expanded')).toBe('true');
    expect(document.activeElement).toBe(switchTo);
    // answered: the hold goes, the line refits with the mode in it, and the popover closes with the fold
    fireEvent.click(within(confirm).getByRole('button', { name: 'Cancel' }));
    await act(async () => {});
    expect(steps()).toBe('');
    expect(foldButton().getAttribute('aria-expanded')).toBe('false');
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
  });

  it('is held by nothing but a waiting choice: the hub\'s refusal goes with the mode, a fold opening on it', async () => {
    hub({ post: () => ({ status: 503, body: { error: 'mode_not_saved', mode: 'ask' } }) });
    const win = resizableWindow(1180);
    const line = { ...foldLine(), room: 1500 };
    stubLine(line);
    drawnUnlessHidden();
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    await waitFor(() => expect(radio('Ask').getAttribute('aria-checked')).toBe('true'));
    fireEvent.click(radio('Off'));
    const note = await screen.findByRole('alert');
    expect(modeRoot().hasAttribute('data-hold')).toBe(false);
    // a fit that folds the mode while the refusal is on screen opens the popover on it
    refit(line, 1080);
    expect(steps()).toBe('tight mode');
    expect(foldButton().getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByRole('alert')).toBe(note);
    // below 760px the head is the marks; the refusal is in the mark's popover, open
    win.set(600);
    await act(async () => {});
    expect(runhead().classList.contains('n-runhead--compact')).toBe(true);
    expect(foldButton().getAttribute('aria-expanded')).toBe('true');
    expect(note.closest('[hidden]')).toBeNull();
    expect(screen.getByRole('alert')).toBe(note);
  });

  it('keeps its popover inside the window, moved in from the edge it would cross', async () => {
    hub();
    windowOf(1180);
    stubLine(foldLine());
    // the fold's popover where its stylesheet puts it (right: 0 under the fold) starts 47px left of
    // a 600px window
    vi.spyOn(document.documentElement, 'clientWidth', 'get').mockReturnValue(600);
    vi.spyOn(document.documentElement, 'clientHeight', 'get').mockReturnValue(800);
    const spy = vi.mocked(Element.prototype.getBoundingClientRect);
    const line = spy.getMockImplementation() as (this: Element) => DOMRect;
    spy.mockImplementation(function (this: Element) {
      if (!this.classList.contains('n-runhead__box')) return line.call(this);
      const shift = parseFloat((this as HTMLElement).style.getPropertyValue('--n-disclosure-shift')) || 0;
      const left = -47 + shift;
      return { left, right: left + 300, top: 40, bottom: 240, width: 300, height: 200, x: left, y: 40, toJSON() { return this; } } as DOMRect;
    });
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    await waitFor(() => expect(foldButton().getAttribute('aria-label')).toBe('Approval mode: Ask'));
    fireEvent.click(foldButton());
    const box = document.getElementById(foldButton().getAttribute('aria-controls') as string) as HTMLElement;
    expect(box.hasAttribute('data-shift')).toBe(true);
    expect(box.style.getPropertyValue('--n-disclosure-shift')).toBe(`${4 + 47}px`);
    // closed, it is placed afresh the next time it opens
    fireEvent.keyDown(within(box).getByRole('radio', { name: 'Ask' }), { key: 'Escape' });
    expect(foldButton().getAttribute('aria-expanded')).toBe('false');
    expect(box.hasAttribute('data-shift')).toBe(false);
  });

  it('below 760px closes its popover on Escape (back to its button) and on a press outside, dropping a choice not confirmed', async () => {
    const calls = hub();
    resizableWindow(600);
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    const button = await screen.findByRole('button', { name: 'Approval mode: Ask' });
    // closed, its popover is out of the reading order
    expect(screen.queryByRole('radiogroup')).toBeNull();
    fireEvent.click(button);
    fireEvent.click(radio('Auto'));
    const confirm = await confirmShown();
    fireEvent.keyDown(within(confirm).getByRole('button', { name: 'Switch to Auto' }), { key: 'Escape' });
    expect(button.getAttribute('aria-expanded')).toBe('false');
    expect(document.querySelector('[data-runhead="confirm"]')).toBeNull();
    expect(document.activeElement).toBe(button);
    fireEvent.click(button);
    fireEvent.click(radio('Auto'));
    await confirmShown();
    fireEvent.mouseDown(document.body);
    expect(button.getAttribute('aria-expanded')).toBe('false');
    expect(document.querySelector('[data-runhead="confirm"]')).toBeNull();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
  });
});

describe('RunningHead — the interrupts, reachable like every signal', () => {
  it('is a button named with the whole reading, whose popover says what the budget is', async () => {
    hub({ interrupts: { status: 200, body: { used: 12, per_day: 24, remaining: 12 } } });
    windowOf(1440);
    render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    // 1340–1679px: "used today" is not drawn, but it is in the name, the title and the popover
    const button = await screen.findByRole('button', { name: 'Interrupts: 12 of 24 used today' });
    expect(button.getAttribute('title')).toBe('Interrupts: 12 of 24 used today');
    expect(button.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(button);
    expect(button.getAttribute('aria-expanded')).toBe('true');
    const panel = document.getElementById(button.getAttribute('aria-controls') as string) as HTMLElement;
    expect(panel.hidden).toBe(false);
    expect(panel.textContent).toContain('12 of 24 used today');
    expect(panel.textContent).toContain('Proactive interruptions used today, against the daily ceiling.');
    // the key stays drawn beside it, and Escape closes it, back to the button
    expect(document.querySelector('[data-runhead="interrupts"] .n-runhead__key')?.textContent).toBe('Interrupts');
    fireEvent.keyDown(button, { key: 'Escape' });
    expect(button.getAttribute('aria-expanded')).toBe('false');
    expect(document.activeElement).toBe(button);
  });

  it('names what it could not read the same way, in both languages', async () => {
    hub({ interrupts: { status: 403, body: { detail: 'admin token required' } } });
    const { unmount } = render(<RunningHead hub={initialHubSnapshot()} lang="en" demo={false} />);
    const refused = await screen.findByRole('button', { name: 'Interrupts: Refused — needs the owner credential' });
    expect(refused.textContent).toContain('Refused');
    unmount();
    resetPolling();
    vi.unstubAllGlobals();
    hub();
    render(<RunningHead hub={initialHubSnapshot()} lang="ro" demo={false} variant="marks" />);
    expect((await screen.findByRole('button', { name: 'Întreruperi: 1 din 4 folosite azi' })).textContent).toBe('1 din 4');
  });
});

/* The approval mode and the interrupt budget are read with the signals engineer's hooks and
   parsers (signals/hooks.ts useApprovalMode / useInterrupts, signals/wire.ts), tested there. */
describe('the running head\'s rules', () => {
  it('rank looser and stricter as the hub does', () => {
    expect(isLooser('ask', 'auto')).toBe(true);
    expect(isLooser('off', 'ask')).toBe(true);
    expect(isLooser('auto', 'off')).toBe(false);
    expect(isLooser('ask', 'off')).toBe(false);
  });

  it('word the hub\'s refusals', () => {
    expect(modeRefusalText('auto', { ok: true, mode: 'auto' }, 'en')).toBeNull();
    expect(modeRefusalText('auto', { error: 'mode_not_effective', live: 'ask' }, 'en'))
      .toBe('Auto did not take effect: the settings store holds another mode. Ask is in force.');
    expect(modeRefusalText('off', { error: 'managed', mode: 'ask' }, 'ro'))
      .toBe('Oprit a fost refuzat: setarea este gestionată de administrator. Întreabă este în vigoare.');
  });
});
