/* The running foot keeps the status chrome's hooks and semantics (data-chrome="gateway" |
   "sessions" | "version": dashes, not zeros; an unknown gateway says so; no version element when
   the hub did not report one), says the machine's readings without a 0 for unknown, and shows the
   agents by exception from sources the hub can prove, saying which did not answer. */
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { STATUS_CHROME_UNKNOWN, readStatusChrome } from '../api/status-chrome';
import { resetPolling } from '../signals/poll';
import type { HubSnapshot, TabTurn } from '../signals/types';
import { RunningFoot } from './RunningFoot';
import { initialHubSnapshot } from './types';
import { ARMED, stubHub, type HubAnswer } from './test-support';

const chrome = (status: unknown) => readStatusChrome(status);
const hubWith = (over: Partial<HubSnapshot>): HubSnapshot => ({ ...initialHubSnapshot(), state: 'live', reason: undefined, serverUp: true, ...over } as HubSnapshot);
const part = (key: string) => document.querySelector(`[data-chrome="${key}"]`) as HTMLElement | null;
const agents = () => document.querySelector('[data-runfoot="agents"]') as HTMLElement;
/** The session count as drawn from 2200px (the whole sentence) and below it (the count alone,
 *  the sentence in its title): jsdom draws both, the CSS shows one. */
const sessionsLong = () => part('sessions')?.querySelector('[data-show-from="xl"]')?.textContent;
const sessionsShort = () => part('sessions')?.querySelector('[data-show-upto="l"]')?.textContent;
const TURN: TabTurn = { turnId: 1, agent: 'stark', askedAt: 1, startedAt: null, firstTokenAt: null };
const ROSTER = [{ id: 'jarvis', name: 'Jarvis' }, { id: 'stark', name: 'Stark' }, { id: 'pepper', name: 'Pepper' }];

function hub(over: Record<string, HubAnswer> = {}) {
  const answers: Record<string, HubAnswer> = {
    '/autonomy/tasks?status=blocked&limit=200': { status: 200, body: { tasks: [{ id: 7, agent: 'jarvis', title: 'Restart lmstudio' }] } },
    '/autonomy/tasks?status=running': { status: 200, body: { tasks: [] } },
    '/api/subagents': { status: 200, body: { spawns: [] } },
    '/api/dashboard/today?days=1&limit=50': { status: 200, body: { items: [] } },
    '/api/security/kill-switch': { status: 200, body: ARMED },
    ...over,
  };
  return stubHub((_method, path) => answers[path] ?? { status: 404 }, vi.stubGlobal);
}

beforeEach(() => { resetPolling(); hub(); });
afterEach(() => { resetPolling(); vi.unstubAllGlobals(); });

describe('RunningFoot', () => {
  it('is the frame\'s running foot', () => {
    render(<RunningFoot hub={initialHubSnapshot()} lang="en" demo={false} turns={[]} />);
    expect(document.querySelector('footer[data-frame="runfoot"]')).not.toBeNull();
  });

  it('shows running channels, the active sessions and the version', () => {
    render(<RunningFoot lang="en" demo={false} turns={[]} hub={hubWith({ chrome: chrome({
      version: '1.4.0', gateway: { state: 'running', running: ['telegram', 'voice'], running_count: 2, total: 3 },
      sessions: { active: 5, window_s: 900, state: 'known' },
    }) })} />);
    expect(part('gateway')?.getAttribute('data-state')).toBe('running');
    expect(part('gateway')?.textContent).toContain('2 of 3 running');
    expect(part('gateway')?.getAttribute('title')).toBe('telegram, voice');
    expect(sessionsLong()).toBe('5 sessions in the last 15 min');
    expect(sessionsShort()).toBe('5 sessions');
    expect(part('sessions')?.getAttribute('title')).toBe('5 sessions in the last 15 min');
    expect(part('version')?.textContent).toBe('Nerva 1.4.0');
  });

  it('draws the channels at every width: whole from 2200px, a compact reading below it (status chrome H133)', () => {
    render(<RunningFoot lang="en" demo={false} turns={[]} hub={hubWith({ chrome: chrome({
      version: '1.4.0', gateway: { state: 'running', running: ['telegram'], running_count: 1, total: 1 },
      sessions: { active: 2, window_s: 900, state: 'known' },
    }) })} />);
    const channels = document.querySelector('[data-runfoot="channels"]') as HTMLElement;
    // no width hides the group: the gateway and the session count are painted on a laptop too
    expect(channels.hasAttribute('data-show-from')).toBe(false);
    expect(channels.hasAttribute('data-show-upto')).toBe(false);
    expect(channels.contains(part('gateway'))).toBe(true);
    expect(channels.contains(part('sessions'))).toBe(true);
    // the gateway reads the same at every width; only the sessions' window moves into the title
    expect(part('gateway')?.querySelector('[data-show-from], [data-show-upto]')).toBeNull();
    expect(sessionsShort()).toBe('2 sessions');
  });

  it('shows a stopped gateway and zero sessions as such', () => {
    render(<RunningFoot lang="en" demo={false} turns={[]} hub={hubWith({ chrome: chrome({
      version: '1.4.0', gateway: { state: 'stopped', running: [], total: 2 }, sessions: { active: 0, window_s: 900 },
    }) })} />);
    expect(part('gateway')?.getAttribute('data-state')).toBe('stopped');
    expect(part('gateway')?.textContent).toContain('Stopped');
    expect(sessionsLong()).toBe('0 sessions in the last 15 min');
    expect(sessionsShort()).toBe('0 sessions');
  });

  it('says "the recent window" when the hub counted sessions without saying over what window, never a made-up one', () => {
    const { unmount } = render(<RunningFoot lang="en" demo={false} turns={[]} hub={hubWith({ chrome: chrome({
      version: '1.4.0', gateway: { state: 'running', running: ['x'], total: 1 }, sessions: { active: 3 },
    }) })} />);
    expect(sessionsLong()).toBe('3 sessions in the recent window');
    expect(part('sessions')?.getAttribute('title')).toBe('3 sessions in the recent window');
    expect(part('sessions')?.textContent).not.toMatch(/min/);
    unmount();
    render(<RunningFoot lang="ro" demo={false} turns={[]} hub={hubWith({ chrome: chrome({ sessions: { active: 1 } }) })} />);
    expect(sessionsLong()).toBe('1 sesiune în intervalul recent');
    expect(sessionsShort()).toBe('1 sesiune');
  });

  it('shows dashes, not zeros, when the hub cannot answer, and no version it was not told', () => {
    render(<RunningFoot lang="en" demo={false} turns={[]} hub={hubWith({ chrome: chrome({
      gateway: { state: 'none', running: [], total: 0 }, sessions: { active: null, window_s: 900, state: 'unknown' },
    }) })} />);
    expect(part('gateway')?.textContent).toContain('None configured');
    expect(part('sessions')?.textContent).toBe('sessions —');
    expect(part('version')).toBeNull();
  });

  it('says an unknown gateway is unknown', () => {
    render(<RunningFoot hub={{ ...initialHubSnapshot(), chrome: STATUS_CHROME_UNKNOWN }} lang="en" demo={false} turns={[]} />);
    expect(part('gateway')?.getAttribute('data-state')).toBe('unknown');
    expect(part('gateway')?.querySelector('[data-mark="unknown"]')).not.toBeNull();
    expect(part('gateway')?.textContent).toContain('Unknown');
    expect(part('sessions')?.textContent).toBe('sessions —');
    expect(document.querySelector('.n-runfoot__ver')?.textContent).toBe('Nerva');
  });

  it('reads the machine from /status.sys: a reading without a total is unknown, never 0, and latency is not measured', () => {
    const { unmount } = render(<RunningFoot lang="en" demo={false} turns={[]}
      hub={hubWith({ sys: { ram_used: 6, ram_total: 32, vram_used: 23, vram_total: 24, gpu_load: 3 } as any })} />);
    expect(document.querySelector('[data-machine="ram"]')?.textContent).toBe('RAM19%');
    expect(document.querySelector('[data-machine="vram"]')?.textContent).toBe('VRAM96%');
    expect(document.querySelector('[data-machine="gpu"]')?.textContent).toBe('GPU load3%');
    expect(document.querySelector('[data-machine="latency"]')?.textContent).toBe('Latency p50Unknown — not measured');
    unmount();
    render(<RunningFoot lang="en" demo={false} turns={[]} hub={hubWith({ sys: { ram_used: 0, ram_total: 0, vram_used: 0, vram_total: 0, gpu_load: 0 } as any })} />);
    for (const key of ['ram', 'vram', 'gpu']) {
      const item = document.querySelector(`[data-machine="${key}"]`) as HTMLElement;
      expect(item.getAttribute('data-state')).toBe('unknown');
      expect(item.textContent).toContain('Unknown — not reported');
      expect(item.textContent).not.toMatch(/\d/);
    }
  });

  it('keeps an unknown machine reading\'s words in its title and in their own span, which phone widths read, not draw', () => {
    render(<RunningFoot lang="ro" demo={false} turns={[]} hub={hubWith({ sys: { ram_used: 0, ram_total: 0, vram_used: 0, vram_total: 0, gpu_load: 0 } as any })} />);
    for (const key of ['ram', 'vram', 'gpu', 'latency']) {
      const item = document.querySelector(`[data-machine="${key}"]`) as HTMLElement;
      const words = item.querySelector('.n-runfoot__words') as HTMLElement;
      // frame.css reads the span, not draws it, below 760px (frame-fit-css.test.ts); the mark stays
      expect(words.textContent).toMatch(/^Necunoscut — /);
      expect(item.getAttribute('title')).toBe(words.textContent);
      expect(item.querySelector('[data-mark="unknown"]')).not.toBeNull();
    }
    // a reading that is known keeps its detail as its title ("6 of 32 GB")
    render(<RunningFoot lang="en" demo={false} turns={[]} hub={hubWith({ sys: { ram_used: 6, ram_total: 32, vram_used: 23, vram_total: 24, gpu_load: 3 } as any })} />);
    expect(document.querySelectorAll('[data-machine="ram"]')[1]?.getAttribute('title')).toBe('6 of 32 GB');
  });

  it('shows the agents by exception, from what the hub proves, and never says "idle"', async () => {
    render(<RunningFoot lang="en" demo={false} turns={[TURN]} hub={hubWith({ agents: ROSTER, sources: { agents: true } })} />);
    await waitFor(() => expect(agents().querySelector('[data-activity="waitingOnYou"]')?.textContent).toBe('1 waiting on you'));
    expect(agents().querySelector('.n-runfoot__lead')?.textContent).toBe('Agents 3');
    expect(agents().querySelector('[data-activity="waitingOnYou"] [data-mark="seal-open"]')).not.toBeNull();
    expect(agents().querySelector('[data-activity="working"]')?.textContent).toBe('1 working');
    expect(agents().querySelector('[data-activity="noActivity"]')?.textContent).toBe('1 no activity reported');
    // below 1680px, where the foot also carries the channels, the remainder is left to the agents pages
    expect(agents().querySelector('[data-activity="noActivity"]')?.getAttribute('data-show-from')).toBe('l');
    expect(agents().querySelector('[data-activity="waitingOnYou"]')?.hasAttribute('data-show-from')).toBe(false);
    expect(document.querySelector('[data-frame="runfoot"]')?.textContent).not.toMatch(/\bidle\b/i);
  });

  it('says the roster was not reported, and which sources did not answer', async () => {
    vi.unstubAllGlobals();
    hub({ '/autonomy/tasks?status=running': { status: 403, body: { detail: 'admin token required' } } });
    render(<RunningFoot lang="en" demo={false} turns={[]} hub={hubWith({ agents: [], sources: {} })} />);
    expect(agents().querySelector('.n-runfoot__lead')?.textContent).toBe('Agents: not reported');
    await waitFor(() => expect(agents().textContent).toContain('Running work: unknown without the owner credential'));
  });

  it('labels the demo sample and derives nothing from it', () => {
    const calls = (() => { vi.unstubAllGlobals(); resetPolling(); return hub(); })();
    render(<RunningFoot lang="en" demo turns={[]} hub={{ ...initialHubSnapshot(true), agents: ROSTER }} />);
    expect(agents().textContent).toBe('Agents 3Demo sample');
    expect(document.querySelector('[data-machine="ram"]')?.textContent).toBe('RAMDemo sample');
    expect(calls).toEqual([]);
  });

  it('draws no hub channel or session count over the demo sample, only its label', () => {
    // the hub's chrome is polled whatever the page shows; under ?demo=1 the foot must not read it
    render(<RunningFoot lang="en" demo turns={[]} hub={{ ...initialHubSnapshot(true), agents: ROSTER, chrome: chrome({
      version: '1.4.0', gateway: { state: 'running', running: ['fictitious-channel'], running_count: 1, total: 1 },
      sessions: { active: 41, window_s: 900, state: 'known' },
    }) }} />);
    const channels = document.querySelector('[data-runfoot="channels"]') as HTMLElement;
    expect(channels.textContent).toBe('ChannelsDemo sample');
    expect(channels.textContent).not.toContain('41');
    expect(channels.innerHTML).not.toContain('fictitious-channel');
    expect(part('gateway')?.getAttribute('data-state')).toBe('demo');
    expect(part('sessions')).toBeNull();
  });

  it('gives the key hint at the widest width: Ctrl K finds everything, no shortcut signs or rejects', () => {
    render(<RunningFoot hub={initialHubSnapshot()} lang="en" demo={false} turns={[]} shortcutOverrides={{}} />);
    const hint = document.querySelector('[data-runfoot="keys"]') as HTMLElement;
    expect(hint.getAttribute('data-show-from')).toBe('xl');
    expect(hint.querySelector('kbd')?.textContent).toMatch(/^(Ctrl\+K|⌘K)$/);
    expect(hint.textContent).toContain('finds every area, panel, agent and action');
    expect(hint.textContent).toContain('No keyboard shortcut signs or rejects');
  });

  it('leaves the agents and the machine to Home\'s spread at the widest width', () => {
    render(<RunningFoot hub={initialHubSnapshot()} lang="en" demo={false} turns={[]} spread />);
    expect(document.querySelector('[data-runfoot="agents"]')?.getAttribute('data-show-upto')).toBe('l');
    expect(document.querySelector('[data-runfoot="machine"]')?.getAttribute('data-show-upto')).toBe('l');
  });

  it('speaks Romanian', () => {
    render(<RunningFoot lang="ro" demo={false} turns={[]} hub={hubWith({ chrome: chrome({
      version: '1.4.0', gateway: { state: 'running', running: ['x'], total: 1 }, sessions: { active: 21, window_s: 900 },
    }) })} />);
    expect(sessionsLong()).toBe('21 de sesiuni în ultimele 15 min');
    expect(sessionsShort()).toBe('21 de sesiuni');
    expect(part('gateway')?.textContent).toContain('1 din 1 pornite');
    expect(document.querySelector('[data-machine="latency"]')?.textContent).toContain('Necunoscut — nemăsurat');
    expect(screen.getByRole('group', { name: 'Agenți, prin excepție' })).toBeTruthy();
  });
});
