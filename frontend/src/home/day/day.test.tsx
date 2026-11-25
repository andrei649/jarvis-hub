import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../api/client', () => ({ apiGet: vi.fn() }));
vi.mock('../../docket/links', async (importOriginal) => ({ ...(await importOriginal<typeof import('../../docket/links')>()), openDocketEntry: vi.fn() }));
import { apiGet } from '../../api/client';
import { openDocketEntry } from '../../docket/links';
import { stringProblems } from '../../frame/strings';
import { initialHubSnapshot, hubReading } from '../../frame/types';
import { awayEntries, awaySince, awayWords } from '../../signals/away';
import { machineReadings } from '../../signals/machine';
import { resetPolling } from '../../signals/poll';
import {
  NO_PRESSURE, T0, at, calmObserver, checking, empty, healthyInput, hubOf, intactChain, live, refused,
} from '../../signals/test-support';
import { demoReading } from '../../signals/types';
import { verdict as deriveVerdict } from '../../signals/verdict';
import { AwayList } from './AwayList';
import { DayBand } from './DayBand';
import { DayRegister, dayTitle } from './DayRegister';
import { ThisMachine } from './ThisMachine';
import { TodayList } from './TodayList';
import { Verdict } from './Verdict';
import { scheduleOf, untilWords, weatherLine } from './schedule';
import { DAY_STRINGS } from './strings';

const get = apiGet as unknown as ReturnType<typeof vi.fn>;
const CLOCK = new Date(T0);
const navigate = vi.fn();

const CAL = [
  { tm: '09:30', ti: 'Standup — Digitaholic', vw: 'Google Meet', state: 'past' },
  { tm: '11:00', ti: '1:1 with Cosmina', vw: 'Office', state: 'next' },
  { tm: '14:00', ti: 'Raiffeisen quarterly review', vw: 'Conf Room A · prep 13:15', state: '' },
  { tm: '16:30', ti: 'Vision research sync', vw: 'Async', state: '' },
];

describe('the day strings', () => {
  it('are complete in English and Romanian', () => expect(stringProblems(DAY_STRINGS)).toEqual([]));
});

describe('the schedule', () => {
  it('classifies each event against the minute clock, not the row\'s own state', () => {
    const items = scheduleOf(CAL, CLOCK);
    expect(items.map((i) => i.phase)).toEqual(['past', 'next', 'later', 'later']);
    expect(items[1]).toMatchObject({ time: '11:00', minutes: 660, title: '1:1 with Cosmina', where: 'Office' });
    expect(scheduleOf(CAL, new Date(at(11, 0))).map((i) => i.phase)).toEqual(['past', 'next', 'later', 'later']);
    expect(scheduleOf(CAL, new Date(at(11, 1))).map((i) => i.phase)).toEqual(['past', 'past', 'next', 'later']);
    expect(scheduleOf(CAL, new Date(at(23, 0))).map((i) => i.phase)).toEqual(['past', 'past', 'past', 'past']);
  });
  it('lists a row whose time cannot be read as it came, and never calls it next', () => {
    const items = scheduleOf([{ tm: 'all day', ti: 'Conference', vw: '' }, { tm: '', ti: 'Reminder' }, { tm: '25:61', ti: 'Broken clock' }, { tm: '12:00', ti: 'Lunch' }], CLOCK);
    expect(items.map((i) => [i.title, i.phase, i.where])).toEqual([['Conference', 'unknown', null], ['Reminder', 'unknown', null], ['Broken clock', 'unknown', null], ['Lunch', 'next', null]]);
  });
  it('drops rows without a title and tolerates a missing calendar', () => {
    expect(scheduleOf([{ tm: '10:00' }, null, { ti: '  ' }], CLOCK)).toEqual([]);
    expect(scheduleOf(undefined, CLOCK)).toEqual([]);
  });
  it('says "in 9 min", "in 2 h", "in 1 h 15 min", and nothing for an event that has started', () => {
    expect(untilWords(660, new Date(at(10, 51)))).toBe('in 9 min');
    expect(untilWords(840, new Date(at(12, 0)))).toBe('in 2 h');
    expect(untilWords(840, new Date(at(12, 45)))).toBe('in 1 h 15 min');
    expect(untilWords(660, new Date(at(11, 1)))).toBeNull();
    expect(untilWords(null, CLOCK)).toBeNull();
    expect(untilWords(660, new Date(at(10, 51)), 'ro')).toBe('în 9 min');
  });
  it('writes the weather line from the parts the hub sent', () => {
    expect(weatherLine({ city: 'București', temp: '9°', desc: 'Mist' })).toBe('București · 9° · Mist');
    expect(weatherLine({ city: 'București', temp: '—', desc: '—' })).toBe('București');
    expect(weatherLine(null)).toBeNull();
    expect(weatherLine({ temp: '' })).toBeNull();
  });
});

/* The hub rows from /dashboard (google_calendar.py) carry ts, title, location and state, with no clock tm;
   after the loader's normCal: tm is ''. */
const HUB_CAL = [
  { tm: '', ti: 'Standup', vw: 'Google Meet', state: 'past', ts: new Date(at(9, 30)).toISOString() },
  { tm: '', ti: 'Raiffeisen quarterly review', vw: 'Conf Room A', state: 'upcoming', ts: new Date(at(14, 0)).toISOString() },
];

describe('the schedule, from the hub real rows (ts only)', () => {
  it('reads the start from ts: time, phase and "in N min"', () => {
    const items = scheduleOf(HUB_CAL, new Date(at(10, 50)));
    expect(items.map((i) => [i.time, i.phase, i.minutes])).toEqual([['09:30', 'past', 570], ['14:00', 'next', 840]]);
    expect(untilWords(items[1].minutes, new Date(at(13, 50)))).toBe('in 10 min');
  });
  it('an all-day row (a bare date) has no start time and is never past or next', () => {
    const items = scheduleOf([{ tm: '', ti: 'Holiday', ts: '2026-11-23' }, ...HUB_CAL], new Date(at(10, 50)));
    expect(items[0]).toMatchObject({ allDay: true, time: '', at: null, phase: 'unknown' });
    expect(items[2].phase).toBe('next');
  });
  it('an event on another day is listed but gives no "in N min"', () => {
    const tomorrow = new Date(at(9, 0)); tomorrow.setDate(tomorrow.getDate() + 1);
    const [item] = scheduleOf([{ tm: '', ti: 'Tomorrow', ts: tomorrow.toISOString() }], new Date(at(10, 50)));
    expect([item.phase, item.minutes]).toEqual(['next', null]);
  });
});

describe('Verdict', () => {
  const draw = (input = healthyInput(), lang: 'en' | 'ro' = 'en') => {
    const v = deriveVerdict(input, lang);
    const view = render(<Verdict verdict={v} lang={lang} navigate={navigate} />);
    return { v, ...view, root: view.container.querySelector('.n-verdict') as HTMLElement };
  };

  it('normal: the state word, the sentence, when it was checked — and no causes', () => {
    const { root } = draw();
    expect(root.getAttribute('data-verdict-state')).toBe('normal');
    expect(root.getAttribute('data-verdict-rule')).toBe('12');
    expect(root.querySelector('[data-mark="ok"]')).not.toBeNull();
    expect(screen.getByRole('heading', { level: 3 }).textContent).toBe('Working normally');
    expect(root.textContent).toContain('Normal');
    expect(root.textContent).toContain('checked 10:50');
    expect(root.querySelector('.n-causes')).toBeNull();
  });

  it('degraded: the causes in the probes\' own words, a consequence only where code supports it, since, and the remedy', () => {
    const observer = live({ enabled: true, probes: 2, tracked: 7, unhealthy: [
      { key: 'service.lmstudio', detail: 'lmstudio not responding on 127.0.0.1:1234', severity: 'CRITICAL' as const, since: at(8, 14) },
      { key: 'service.qdrant', detail: 'qdrant not responding on 127.0.0.1:6333', severity: 'CRITICAL' as const, since: at(8, 14) },
    ] });
    const blocked = live([{ id: 12, kind: 'restart_service', title: 'Restart qdrant?', agent: 'steve', createdAt: at(8, 15), service: 'qdrant' }]);
    const { root } = draw(healthyInput({ observer, blocked }));
    expect(root.getAttribute('data-verdict-state')).toBe('degraded');
    expect(screen.getByRole('heading', { level: 3 }).textContent).toBe('Working, with 2 local services not responding');
    expect(root.textContent).toContain('Degraded since 08:14');
    const causes = within(root).getByRole('list', { name: 'Causes — since 08:14' });
    const items = within(causes).getAllByRole('listitem');
    expect(items.map((li) => li.querySelector('code')?.textContent)).toEqual(['lmstudio', 'qdrant']);
    expect(items[0].textContent).toContain('lmstudio not responding on 127.0.0.1:1234');
    expect(items[0].textContent).toContain('Not blocking: replies are served by ollama.');
    expect(items[1].textContent).not.toContain('Not blocking');
    const link = within(root).getByRole('link', { name: 'its entry on the docket' });
    expect(link.getAttribute('href')).toBe('/v2/cockpit#docket-entry-12');
    expect(root.textContent).toContain('Restarting them waits for your signature —');
    fireEvent.click(link);
    expect(openDocketEntry).toHaveBeenCalledWith(12);
  });

  it('problem, halted, offline, checking, unknown and demo each draw their word and mark', () => {
    const cases: [string, ReturnType<typeof healthyInput>, string, string, string][] = [
      ['problem', healthyInput({ audit: live({ ...intactChain, valid: false, firstInvalidId: 412 }) }), 'Problem', 'problem', 'The record is broken at entry 412'],
      ['halted', healthyInput({ killSwitch: live({ halted: true }) }), 'Halted', 'held', 'All agents are stopped'],
      ['offline', healthyInput({ hub: hubOf({ state: 'offline', serverUp: false, lastGoodAt: at(10, 44) }) }), 'Offline', 'unknown', 'The hub is not answering · last good reading 10:44'],
      ['checking', healthyInput({ hub: initialHubSnapshot(false) }), 'Checking', 'unknown', 'Checking…'],
      ['unknown', healthyInput({ audit: refused() }), 'Unknown', 'unknown', 'Unknown — the audit chain did not answer'],
      ['demo', healthyInput({ demo: true }), 'Demo sample', 'attn', 'Working, with 4 local services not responding'],
    ];
    for (const [state, input, word, mark, headline] of cases) {
      const { root, unmount } = draw(input);
      expect(root.getAttribute('data-verdict-state'), state).toBe(state);
      expect(root.querySelector(`[data-mark="${mark}"]`), `${state} mark`).not.toBeNull();
      expect(root.querySelector('.n-verdict__state')?.textContent, state).toContain(word);
      expect(screen.getByRole('heading', { level: 3 }).textContent, state).toBe(headline);
      unmount();
    }
  });

  it('draws no "checked" time when the verdict has none (demo)', () => {
    const { root } = draw(healthyInput({ demo: true }));
    expect(root.querySelector('.n-verdict__asof')).toBeNull();
    expect(root.textContent).not.toContain('since');
  });

  it('links a halted verdict to Trust, and says what else did not answer beside a problem', () => {
    const halted = draw(healthyInput({ killSwitch: live({ halted: true }), audit: refused() }));
    const link = within(halted.root).getByRole('link', { name: 'Resume in Trust › Emergency stop' });
    expect(link.getAttribute('href')).toContain('/v2/console/kill-switch');
    fireEvent.click(link);
    expect(navigate).toHaveBeenCalledWith('/v2/console/kill-switch');
    expect(halted.root.querySelector('.n-verdict__missing')?.textContent).toBe('Not answering: the audit chain.');
  });

  it('keeps a cause\'s text as plain text', () => {
    const observer = live({ enabled: true, probes: 1, tracked: 1, unhealthy: [{ key: 'service.x', detail: '<b>bold</b> [x](http://e) **y**', severity: 'WARN' as const, since: null }] });
    const { root } = draw(healthyInput({ observer }));
    expect(root.querySelector('.n-causes b, .n-causes a')).toBeNull();
    expect(root.querySelector('.n-causes')?.textContent).toContain('<b>bold</b> [x](http://e) **y**');
  });

  it('speaks Romanian', () => {
    const { root } = draw(healthyInput(), 'ro');
    expect(screen.getByRole('heading', { level: 3 }).textContent).toBe('Funcționează normal');
    expect(root.textContent).toContain('Normal');
    expect(root.textContent).toContain('actualizat la 10:50');
  });
});

describe('ThisMachine', () => {
  const sys = { host: 'h', cpu: 'c', ram_used: 36, ram_total: 192, gpu: 'RTX', vram_used: 23, vram_total: 24, gpu_load: 3, backend: 'ollama', model: 'm', latency: 0, uptime: '', sessions: 0 };
  const draw = (readings: ReturnType<typeof machineReadings>, hub = hubOf()) =>
    render(<ThisMachine readings={readings} hubState={hubReading(hub, T0)} lang="en" />);

  it('draws each figure with its meter, and latency as unknown — not measured', () => {
    const { container } = draw(machineReadings({ sys, hubState: 'live' }, 'en'));
    const rows = [...container.querySelectorAll('[data-machine]')];
    expect(rows.map((r) => r.getAttribute('data-machine'))).toEqual(['ram', 'vram', 'gpu', 'latency']);
    expect(rows[0].querySelector('.n-machine__num')?.textContent).toBe('19%');
    expect((rows[0].querySelector('.n-meter__fill') as HTMLElement).style.width).toBe('19%');
    expect(rows[0].querySelector('.n-machine__detail')?.textContent).toBe('36 of 192 GB');
    expect(rows[3].querySelector('.n-meter')).toBeNull();
    expect(rows[3].querySelector('[data-mark="unknown"]')).not.toBeNull();
    expect(rows[3].textContent).toContain('Unknown — not measured');
    expect(container.querySelector('[data-source-state="live"]')).not.toBeNull();
  });

  it('a figure with no total is unknown, never 0%', () => {
    const { container } = draw(machineReadings({ sys: { ...sys, ram_total: 0, ram_used: 0 }, hubState: 'live' }, 'en'));
    const ram = container.querySelector('[data-machine="ram"]') as HTMLElement;
    expect(ram.querySelector('.n-meter')).toBeNull();
    expect(ram.textContent).not.toContain('0%');
    expect(ram.textContent).toContain('Unknown — not reported');
  });

  it('without /status it says so: checking, offline, demo', () => {
    for (const [hub, word] of [[initialHubSnapshot(false), 'Checking…'], [hubOf({ state: 'offline', serverUp: false, sys: null }), 'Unknown — the hub is not answering'], [hubOf({ demo: true, state: 'demo' }), 'Demo sample']] as const) {
      const { container, unmount } = draw(machineReadings({ sys: null, hubState: hubReading(hub, T0).state, hubReason: hubReading(hub, T0).reason }, 'en'), hub);
      expect(container.querySelector('[data-machine="ram"]')?.textContent, word).toContain(word);
      expect(container.querySelector('.n-meter')).toBeNull();
      unmount();
    }
  });
});

describe('TodayList', () => {
  const draw = (hub = hubOf({ calendar: CAL, weather: { city: 'București', temp: '9°', desc: 'Mist' } })) =>
    render(<TodayList hub={hub} hubState={hubReading(hub, T0)} clock={CLOCK} lang="en" />);

  it('lists the events, marks past and next, and says "in 10 min" on the next one only', () => {
    const { container } = draw();
    const rows = [...container.querySelectorAll('.n-schedule__row')];
    expect(rows.map((r) => r.getAttribute('data-phase'))).toEqual(['past', 'next', 'later', 'later']);
    expect(rows[1].querySelector('[role="img"]')?.getAttribute('aria-label')).toBe('Next');
    expect(rows[1].querySelector('.n-schedule__where')?.textContent).toBe('Office · in 10 min');
    expect(rows[2].querySelector('.n-schedule__where')?.textContent).toBe('Conf Room A · prep 13:15');
    expect(container.textContent).toContain('București · 9° · Mist');
    expect(container.querySelector('[data-source-state="live"]')).not.toBeNull();
  });

  it('an empty calendar says it may not be connected, labelled Empty', () => {
    const { container } = draw(hubOf());
    expect(container.querySelector('.n-schedule')).toBeNull();
    expect(container.textContent).toContain('Nothing on the calendar today, or the calendar is not connected.');
    expect(container.querySelector('[data-source-state="empty"]')).not.toBeNull();
  });

  it('a hub that has not answered says the calendar is unknown, never an empty day', () => {
    const { container } = draw(initialHubSnapshot(false));
    expect(container.textContent).toContain('Unknown — the calendar could not be read.');
    expect(container.textContent).not.toContain('Nothing on the calendar');
    expect(container.querySelector('[data-source-state="unknown"]')).not.toBeNull();
  });

  it('draws the hub real rows with their times, and "All day" for a bare date', () => {
    const hub = hubOf({ calendar: [{ tm: '', ti: 'Holiday', vw: '', ts: '2026-11-23' }, ...HUB_CAL] });
    const { container } = draw(hub);
    const rows = [...container.querySelectorAll('.n-schedule__row')];
    expect(rows.map((r) => r.querySelector('time')?.textContent)).toEqual(['All day', '09:30', '14:00']);
    expect(rows.map((r) => r.getAttribute('data-phase'))).toEqual(['unknown', 'past', 'next']);
  });

  it('two mounted lists keep their headings apart (unique ids for aria-labelledby)', () => {
    const hub = hubOf({ calendar: CAL });
    const { container } = render(<><TodayList hub={hub} hubState={hubReading(hub, T0)} clock={CLOCK} lang="en" /><TodayList hub={hub} hubState={hubReading(hub, T0)} clock={CLOCK} lang="en" /></>);
    const ids = [...container.querySelectorAll('section')].map((s) => s.getAttribute('aria-labelledby'));
    expect(new Set(ids).size).toBe(2);
    ids.forEach((id) => expect(container.querySelectorAll('[id="' + id + '"]')).toHaveLength(1));
  });

  it('keeps event titles as plain text', () => {
    const hub = hubOf({ calendar: [{ tm: '12:00', ti: '<script>x</script> **hi**', vw: '' }] });
    const { container } = draw(hub);
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('.n-schedule__what')?.textContent).toBe('<script>x</script> **hi**');
  });
});

describe('AwayList', () => {
  const draw = (over: { today?: any; entries?: any; causes?: any; blocked?: any; demo?: boolean } = {}) => {
    const today = over.today ?? live({ items: [
      { id: 'a1', at: at(7, 14), kind: 'action', title: 'Calendar synced · 1 conflict auto-resolved', agent: 'pepper' },
      { id: 'a2', at: at(9, 40), kind: 'action', title: 'Indexed 17 sources', agent: 'vision' }] });
    const summary = awayEntries({
      today, blocked: over.blocked ?? live([{ id: 7, kind: 'send_email', title: 'Send the redacted report', agent: 'ultron', createdAt: at(7, 48), service: null }]),
      causes: over.causes ?? [{ key: 'service.qdrant', detail: 'qdrant not responding', mark: 'problem', consequence: null, since: at(8, 14), source: 'observer' }],
      checkedAt: T0, since: awaySince(at(6), T0), now: T0, docketHref: (id) => `/v2/cockpit#docket-entry-${id}`,
    });
    return render(<AwayList summary={summary} words={awayWords(summary, 'en', T0)} today={today} lang="en" demo={!!over.demo}
      names={{ pepper: 'Pepper' }} recordPath="/v2/console/today" navigate={navigate} />);
  };

  it('lists entries oldest first with a mark, a time, who and what; exceptions in semibold', () => {
    const { container } = draw();
    const rows = [...container.querySelectorAll('.n-away__row')];
    expect(rows.map((r) => r.querySelector('time')?.textContent)).toEqual(['07:14', '07:48', '08:14', '09:40']);
    expect(rows.map((r) => r.getAttribute('data-away-kind'))).toEqual(['done', 'raised', 'problem', 'done']);
    expect(rows.map((r) => r.classList.contains('is-exception'))).toEqual([false, true, true, false]);
    expect(rows[0].querySelector('.n-away__who')?.textContent).toBe('Pepper');
    expect(rows[3].querySelector('.n-away__who')?.textContent).toBe('Vision');
    expect(rows[0].querySelector('[role="img"]')?.getAttribute('aria-label')).toBe('Done');
    expect(rows[2].querySelector('[role="img"]')?.getAttribute('aria-label')).toBe('Problem');
    expect(container.textContent).toContain('since 06:00 (this browser)');
  });

  it('writes the total line and the way to the record', () => {
    const { container } = draw();
    const total = container.querySelector('[data-total]') as HTMLElement;
    expect(total.textContent).toContain('4 entries');
    expect(total.textContent).toContain('2 done');
    expect(total.textContent).toContain('1 held or blocked');
    expect(total.textContent).toContain('1 problem');
    const link = within(total).getByRole('link', { name: 'Open the day\'s record' });
    fireEvent.click(link);
    expect(navigate).toHaveBeenCalledWith('/v2/console/today');
  });

  it('a raised docket entry links to the entry', () => {
    const { container } = draw();
    const link = within(container.querySelector('[data-away-kind="raised"]') as HTMLElement).getByRole('link', { name: 'Send the redacted report' });
    expect(link.getAttribute('href')).toBe('/v2/cockpit#docket-entry-7');
    fireEvent.click(link);
    expect(openDocketEntry).toHaveBeenCalledWith('7');
  });

  it('a problem whose start was not reported says it was checked, not when it began', () => {
    const { container } = draw({ causes: [{ key: 'service.n8n', detail: 'n8n not responding', mark: 'problem', consequence: null, since: null, source: 'observer' }] });
    const row = container.querySelector('[data-away-kind="problem"]') as HTMLElement;
    expect(row.getAttribute('data-at-kind')).toBe('checked');
    expect(row.textContent).toContain('checked 10:50');
  });

  it('nothing happened: a sentence and the way to the record, not a total of zeros', () => {
    const { container } = draw({ today: empty({ items: [] }), blocked: empty([]), causes: [] });
    expect(container.querySelector('.n-away')).toBeNull();
    expect(container.textContent).toContain('Nothing recorded since 06:00.');
    expect(container.querySelector('[data-total]')).toBeNull();
    expect(screen.getByRole('link', { name: 'Open the day\'s record' })).toBeTruthy();
  });

  it('a record that did not answer is unknown, never "nothing happened"', () => {
    for (const today of [refused(), checking()]) {
      const { container, unmount } = draw({ today, blocked: refused(), causes: [] });
      expect(container.textContent).toContain('Unknown — the day\'s record could not be read.');
      expect(container.textContent).not.toContain('Nothing recorded');
      expect(container.querySelector('[data-total]')).toBeNull();
      unmount();
    }
  });

  it('in demo it says the record is not read, labelled Demo sample', () => {
    const { container } = draw({ today: demoReading(null), blocked: demoReading(null), causes: [], demo: true });
    expect(container.textContent).toContain('Demo sample: the day\'s record is not read in demo mode.');
    expect(container.querySelector('[data-source-state="demo"]')).not.toBeNull();
    expect(container.querySelector('[data-total]')).toBeNull();
  });

  it('keeps titles as plain text', () => {
    const today = live({ items: [{ id: 'x', at: at(8), kind: 'action', title: '<img src=x onerror=alert(1)> **b**', agent: null }] });
    const { container } = draw({ today, blocked: empty([]), causes: [] });
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('.n-away__what')?.textContent).toBe('<img src=x onerror=alert(1)> **b**');
  });
});

function healthyHub(path: string): unknown {
  if (path === '/autonomy/observer') return { enabled: true, probes: 2, tracked: 7, unhealthy: [] };
  if (path === '/api/security/kill-switch') return { global: false, any_halted: false, halted_count: 0 };
  if (path === '/api/security/audit/verify') return { valid: true, first_invalid_id: null, entries: 921, tamper_evident: true };
  if (path === '/api/health/components') return { components: {}, failed: [], summary: '' };
  if (path === '/api/system/pressure') return { boot_id: 'b', conditions: [], worst: null };
  if (path.startsWith('/autonomy/tasks')) return { tasks: [{ id: 7, kind: 'send_email', title: 'Send the redacted report', agent: 'ultron', created_at: new Date(at(8, 1)).toISOString() }], total: 1 };
  if (path.startsWith('/api/dashboard/today')) return { items: [{ entry_id: 'action:1', ts: new Date(at(9, 40)).toISOString(), kind: 'action', title: 'Indexed 17 sources', agent: 'vision' }], counts: {} };
  throw Object.assign(new Error('404'), { status: 404 });
}

describe('DayRegister and DayBand', () => {
  beforeEach(() => {
    resetPolling();
    get.mockReset();
    get.mockImplementation(async (path: string) => healthyHub(path));
    localStorage.clear();
    localStorage.setItem('nerva.home.lastSeenAt', String(at(6)));
    navigate.mockReset();
  });
  afterEach(() => resetPolling());

  const hub = () => hubOf({
    checkedAt: Date.now(), lastGoodAt: Date.now(), calendar: CAL, weather: { city: 'București', temp: '9°', desc: 'Mist' },
    sys: { host: 'h', cpu: 'c', ram_used: 36, ram_total: 192, gpu: 'RTX', vram_used: 23, vram_total: 24, gpu_load: 3, backend: 'ollama', model: 'm', latency: 0, uptime: '', sessions: 0 },
    agents: [{ id: 'vision', name: 'Vision' }],
  });
  const clock = () => new Date(at(10, 50));

  it('the register: the date, the minute, the verdict, This machine (xl only), Today and While you were away', async () => {
    const { container } = render(<DayRegister hub={hub()} clock={clock()} lang="en" demo={false} navigate={navigate} />);
    const root = container.querySelector('[data-register="day"]') as HTMLElement;
    expect(root.querySelector('h2')?.textContent).toBe(dayTitle(clock(), 'en'));
    expect(dayTitle(clock(), 'en')).toMatch(/Monday.*23.*November/);
    expect(root.querySelector('time')?.textContent).toBe('10:50');
    expect(root.querySelector('[data-day-block="machine"]')?.closest('[data-show-from="xl"]')).not.toBeNull();
    expect(root.querySelector('[data-day-block="today"]')).not.toBeNull();
    await waitFor(() => expect(root.querySelector('.n-verdict')?.getAttribute('data-verdict-state')).toBe('normal'));
    await waitFor(() => expect(root.querySelectorAll('.n-away__row').length).toBe(2));
    const kinds = [...root.querySelectorAll('.n-away__row')].map((r) => r.getAttribute('data-away-kind'));
    expect(kinds).toEqual(['raised', 'done']);
    expect(root.querySelector('[data-away-kind="done"] .n-away__who')?.textContent).toBe('Vision');
  });

  it('the register says what it does not know while the hub has not answered: no all-clear', () => {
    get.mockImplementation(() => new Promise(() => {}));
    const { container } = render(<DayRegister hub={initialHubSnapshot(false)} clock={clock()} lang="en" demo={false} navigate={navigate} />);
    expect(container.querySelector('.n-verdict')?.getAttribute('data-verdict-state')).toBe('checking');
    expect(container.textContent).not.toContain('Working normally');
    expect(container.textContent).toContain('Checking…');
    expect(container.querySelector('[data-day-block="today"]')?.textContent).toContain('Unknown — the calendar could not be read.');
    expect(container.querySelector('[data-day-block="away"]')?.textContent).not.toContain('Nothing recorded');
  });

  it('the register in demo: labelled Demo sample, asks for nothing, draws no invented record', () => {
    const { container } = render(<DayRegister hub={hubOf({ demo: true, state: 'demo', calendar: CAL })} clock={clock()} lang="en" demo navigate={navigate} />);
    expect(container.querySelector('.n-register__meta [data-source-state="demo"]')).not.toBeNull();
    expect(container.querySelector('.n-verdict')?.getAttribute('data-verdict-state')).toBe('demo');
    expect(container.querySelector('[data-day-block="away"]')?.textContent).toContain('Demo sample: the day\'s record is not read in demo mode.');
    expect(get).not.toHaveBeenCalled();
  });

  it('the register in Romanian', async () => {
    const { container } = render(<DayRegister hub={hub()} clock={clock()} lang="ro" demo={false} navigate={navigate} />);
    expect(container.querySelector('h2')?.textContent).toMatch(/luni/i);
    await waitFor(() => expect(container.querySelector('.n-verdict h3')?.textContent).toBe('Funcționează normal'));
    expect(container.querySelector('[data-day-block="today"] h3')?.textContent).toBe('Azi');
  });

  it('the band: three cells with the verdict, the next event and the away summary, each opening its list', async () => {
    const { container } = render(<DayBand hub={hub()} clock={clock()} lang="en" demo={false} navigate={navigate} />);
    const band = container.querySelector('[data-frame="dayband"]') as HTMLElement;
    const cells = [...band.querySelectorAll('.n-dayband__button')] as HTMLButtonElement[];
    expect(cells).toHaveLength(3);
    await waitFor(() => expect(cells[0].textContent).toContain('Working normally'));
    expect(cells[0].textContent).toContain('Normal');   // the state word is read even where the mark is not
    expect(cells[0].textContent).toContain('checked');
    expect(cells[1].textContent).toContain('11:00 · 1:1 with Cosmina');
    expect(cells[1].textContent).toContain('in 10 min');
    expect(cells[1].textContent).toContain('then 14:00 Raiffeisen quarterly review');
    await waitFor(() => expect(cells[2].textContent).toContain('1 done · 1 held or blocked · 0 problems'));
    expect(cells.map((c) => c.getAttribute('aria-expanded'))).toEqual(['false', 'false', 'false']);
    fireEvent.click(cells[2]);
    expect(cells[2].getAttribute('aria-expanded')).toBe('true');
    const panel = document.getElementById(cells[2].getAttribute('aria-controls') as string) as HTMLElement;
    expect(panel.hidden).toBe(false);
    expect(within(panel).getAllByText(/Send the redacted report/).length).toBeGreaterThan(0);
    fireEvent.keyDown(panel, { key: 'Escape' });
    expect(cells[2].getAttribute('aria-expanded')).toBe('false');
    expect(document.activeElement).toBe(cells[2]);
    fireEvent.click(cells[0]);
    const verdictPanel = document.getElementById(cells[0].getAttribute('aria-controls') as string) as HTMLElement;
    expect(verdictPanel.querySelector('.n-verdict')?.getAttribute('data-verdict-state')).toBe('normal');
  });

  it('the band and the register give the same verdict', async () => {
    const h = hub();
    const both = render(<><DayBand hub={h} clock={clock()} lang="en" demo={false} navigate={navigate} /><DayRegister hub={h} clock={clock()} lang="en" demo={false} navigate={navigate} /></>);
    await waitFor(() => expect(both.container.querySelector('[data-register="day"] .n-verdict')?.getAttribute('data-verdict-state')).toBe('normal'));
    expect(both.container.querySelector('.n-dayband__headline')?.textContent).toBe(both.container.querySelector('[data-register="day"] .n-verdict__line')?.textContent);
  });

  it('the band, with the day not read: unknown, never "nothing"', () => {
    get.mockImplementation(() => new Promise(() => {}));
    const { container } = render(<DayBand hub={initialHubSnapshot(false)} clock={clock()} lang="en" demo={false} navigate={navigate} />);
    const cells = [...container.querySelectorAll('.n-dayband__button')];
    expect(cells[0].textContent).toContain('Checking…');
    expect(cells[1].textContent).toContain('Unknown');
    expect(cells[2].textContent).toContain('Unknown');
    expect(container.textContent).not.toContain('Nothing since');
  });

  const refusedPaths = (...paths: string[]) => get.mockImplementation(async (path: string) => {
    if (paths.some((p) => path.startsWith(p))) throw Object.assign(new Error('403'), { status: 403 });
    if (path.startsWith('/api/dashboard/today')) return { items: [], counts: {} };
    if (path.startsWith('/autonomy/tasks')) return { tasks: [], total: 0 };
    return healthyHub(path);
  });

  it('the band: the hub\'s real calendar rows give the time and the next event, never "Nothing more today" while one is ahead', async () => {
    const real = { ...hub(), calendar: HUB_CAL };
    const { container } = render(<DayBand hub={real} clock={clock()} lang="en" demo={false} navigate={navigate} />);
    const cells = [...container.querySelectorAll('.n-dayband__button')];
    expect(cells[1].textContent).toContain('14:00 · Raiffeisen quarterly review');
    expect(cells[1].textContent).toContain('in 3 h 10 min');
    expect(cells[1].textContent).not.toContain('Nothing more today');
  });

  it('the band: an event whose start was not read means the day is not known to be over', () => {
    const rows = { ...hub(), calendar: [{ tm: '', ti: 'Dentist', vw: '', state: '' }, { tm: '09:00', ti: 'Standup', vw: '', state: '' }] };
    const { container } = render(<DayBand hub={rows} clock={clock()} lang="en" demo={false} navigate={navigate} />);
    const cell = container.querySelectorAll('.n-dayband__button')[1];
    expect(cell.textContent).toContain('Start times not reported');
    expect(cell.textContent).not.toContain('Nothing more today');
    const over = { ...hub(), calendar: [{ tm: '09:00', ti: 'Standup', vw: '', state: '' }] };
    const done = render(<DayBand hub={over} clock={clock()} lang="en" demo={false} navigate={navigate} />);
    expect(done.container.querySelectorAll('.n-dayband__button')[1].textContent).toContain('Nothing more today');
  });

  it('the band: an empty calendar says it may be unconnected, not "No events today"', () => {
    const { container } = render(<DayBand hub={{ ...hub(), calendar: [] }} clock={clock()} lang="en" demo={false} navigate={navigate} />);
    const cell = container.querySelectorAll('.n-dayband__button')[1];
    expect(cell.textContent).toContain('Nothing on the calendar, or not connected');
    expect(container.textContent).not.toContain('No events today');
  });

  it('the band: with the docket and the probes refused and nothing recorded, it counts the unread sources and does not say all clear', async () => {
    refusedPaths('/autonomy/observer', '/autonomy/tasks');
    const { container } = render(<DayBand hub={hub()} clock={clock()} lang="en" demo={false} navigate={navigate} />);
    const away = container.querySelectorAll('.n-dayband__button')[2];
    await waitFor(() => expect(away.textContent).toContain('2 sources not read'));
    expect(away.textContent).toContain('Nothing since 06:00');
    expect(away.textContent).not.toMatch(/0 problems|0 held or blocked/);
  });

  it('the band: with the probes refused, a tally from them is left out, not 0', async () => {
    refusedPaths('/autonomy/observer');
    get.mockImplementation(async (path: string) => {
      if (path.startsWith('/autonomy/observer')) throw Object.assign(new Error('403'), { status: 403 });
      return healthyHub(path);
    });
    const { container } = render(<DayBand hub={hub()} clock={clock()} lang="en" demo={false} navigate={navigate} />);
    const away = container.querySelectorAll('.n-dayband__button')[2];
    await waitFor(() => expect(away.textContent).toContain('1 source not read'));
    expect(away.textContent).toContain('1 done');
    expect(away.textContent).not.toContain('problems');
  });

  it('the register: an empty record with the docket unread says what was not read, not just "Nothing recorded"', async () => {
    refusedPaths('/autonomy/tasks');
    const { container } = render(<DayRegister hub={hub()} clock={clock()} lang="en" demo={false} navigate={navigate} />);
    const block = container.querySelector('[data-day-block="away"]') as HTMLElement;
    await waitFor(() => expect(block.textContent).toContain('Entries raised on the docket are unknown without the owner credential.'));
    expect(block.textContent).toContain('Nothing recorded since 06:00 in the sources that answered.');
    expect(block.textContent).not.toMatch(/Nothing recorded since 06:00\.(?! )/);
  });

  it('the band and the register mounted together keep every aria-labelledby target unique', async () => {
    const h = hub();
    const both = render(<><DayBand hub={h} clock={clock()} lang="en" demo={false} navigate={navigate} /><DayRegister hub={h} clock={clock()} lang="en" demo={false} navigate={navigate} /></>);
    await waitFor(() => expect(both.container.querySelector('[data-register="day"] .n-verdict')?.getAttribute('data-verdict-state')).toBe('normal'));
    const ids = [...both.container.querySelectorAll('[id]')].map((e) => e.id);
    expect(ids.length).toBeGreaterThan(0);
    expect(new Set(ids).size).toBe(ids.length);
    for (const el of both.container.querySelectorAll('[aria-labelledby]')) {
      for (const id of (el.getAttribute('aria-labelledby') ?? '').split(' ')) expect(both.container.querySelectorAll('[id="' + id + '"]'), id).toHaveLength(1);
    }
  });

  it('the band in demo', () => {
    const { container } = render(<DayBand hub={hubOf({ demo: true, state: 'demo' })} clock={clock()} lang="en" demo navigate={navigate} />);
    const cells = [...container.querySelectorAll('.n-dayband__button')];
    expect(cells[0].textContent).toContain('Demo sample');
    expect(cells[2].textContent).toContain('Demo sample');
    expect(get).not.toHaveBeenCalled();
  });
});
