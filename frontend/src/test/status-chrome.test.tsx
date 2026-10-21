// @ts-nocheck
/* H133 — the live status chrome. The top bar's GATEWAY / SESSIONS / VER badges and the
   rail's gateway dot are pinned against a mocked `/status` poll: each badge shows what
   the poll answered, or an honest dash when it could not — never a plausible guess. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import React from 'react';
import { render } from '@testing-library/react';
import { loadJarvisData } from '../api/loaders';
import { readStatusChrome, STATUS_CHROME_UNKNOWN } from '../api/status-chrome';
import { Rail, TopBar, fitBadgeStrip } from '../shell';

const ok = (payload: unknown) => Promise.resolve({ ok: true, status: 200, json: async () => payload });
const down = () => Promise.reject(new TypeError('network down'));

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function stubStatus(status: any) {
  const fetchMock = vi.fn((url: string) => {
    if (url === '/status') return status === null ? down() : ok(status);
    return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

const T = { sub: 'sub', local: 'LOCAL', langName: 'EN', enterAmbient: 'ambient', comms: 'Comms' } as any;

function topBar(chrome) {
  return render(<TopBar clock={new Date(0)} lang="en" setLang={() => {}} accent="cyan" agents={[]} localPct={null}
    live={false} trust={null} llm={null} demo={false} setDemo={() => {}} serverUp={true}
    onPalette={() => {}} onAmbient={() => {}} chrome={chrome} t={T} />);
}

const badge = (container, key) => container.querySelector(`[data-chrome="${key}"]`);

describe('readStatusChrome', () => {
  it('maps the gateway, session and version fields of /status', () => {
    expect(readStatusChrome({
      version: '1.4.0',
      gateway: { state: 'running', running: ['telegram', 'discord'], running_count: 2, total: 3 },
      sessions: { active: 4, window_s: 900, state: 'known' },
    })).toEqual({
      gateway: { state: 'running', running: ['telegram', 'discord'], total: 3 },
      sessions: { active: 4, windowS: 900 },
      version: '1.4.0',
    });
  });

  it('falls back to unknown on missing or malformed fields', () => {
    expect(readStatusChrome({})).toEqual(STATUS_CHROME_UNKNOWN);
    expect(readStatusChrome(null)).toEqual(STATUS_CHROME_UNKNOWN);
    const odd = readStatusChrome({ gateway: { state: 'exploded', running: [1, 'x'] }, sessions: { active: -2 }, version: 7 });
    expect(odd.gateway.state).toBe('unknown');
    expect(odd.gateway.running).toEqual([]);   // an unknown state lists no channel
    expect(readStatusChrome({ gateway: { state: 'running', running: [1, '', 'x'], total: 2 } }).gateway.running).toEqual(['x']);
    expect(odd.sessions.active).toBeNull();
    expect(odd.version).toBeNull();
  });
});

describe('top-bar badges follow the polled /status', () => {
  it('shows running channels, the active-session count and the version', async () => {
    stubStatus({
      version: '1.4.0',
      gateway: { state: 'running', running: ['discord', 'telegram'], running_count: 2, total: 3 },
      sessions: { active: 5, window_s: 900, state: 'known' },
    });
    const data = await loadJarvisData(false);
    expect(data.chrome.gateway.running).toEqual(['discord', 'telegram']);
    const { container } = topBar(data.chrome);
    expect(badge(container, 'gateway').textContent).toContain('● 2/3');
    expect(badge(container, 'gateway').getAttribute('title')).toContain('discord, telegram');
    expect(badge(container, 'gateway').getAttribute('data-state')).toBe('running');
    expect(badge(container, 'sessions').textContent).toContain('5');
    expect(badge(container, 'sessions').getAttribute('title')).toContain('15 min');
    expect(badge(container, 'version').textContent).toContain('v1.4.0');
  });

  it('shows a stopped gateway and zero sessions as such', async () => {
    stubStatus({
      version: '1.4.0',
      gateway: { state: 'stopped', running: [], running_count: 0, total: 2 },
      sessions: { active: 0, window_s: 900, state: 'known' },
    });
    const { container } = topBar((await loadJarvisData(false)).chrome);
    expect(badge(container, 'gateway').textContent).toContain('○ STOPPED');
    expect(badge(container, 'gateway').getAttribute('data-state')).toBe('stopped');
    expect(badge(container, 'sessions').textContent).toContain('0');
  });

  it('shows dashes, not zeros, when the store or the server cannot answer', async () => {
    stubStatus({ version: '1.4.0', gateway: { state: 'none', running: [], total: 0 },
      sessions: { active: null, window_s: 900, state: 'unknown' } });
    let { container } = topBar((await loadJarvisData(false)).chrome);
    expect(badge(container, 'sessions').textContent).toContain('—');
    expect(badge(container, 'gateway').textContent).toContain('○ NONE');

    stubStatus(null);
    const offline = await loadJarvisData(false);
    expect(offline.serverUp).toBe(false);
    expect(offline.chrome).toEqual(STATUS_CHROME_UNKNOWN);
    ({ container } = topBar(offline.chrome));
    expect(badge(container, 'gateway').getAttribute('data-state')).toBe('unknown');
    expect(badge(container, 'gateway').textContent).toContain('—');
    expect(badge(container, 'sessions').textContent).toContain('—');
    expect(badge(container, 'version')).toBeNull();
  });
});

describe('rail gateway dot', () => {
  it('keeps the dot outside the label so the collapsed (icon-only) rail still shows it', async () => {
    stubStatus({ gateway: { state: 'running', running: ['slack'], running_count: 1, total: 1 } });
    const { chrome } = await loadJarvisData(false);
    const { container } = render(<Rail mode="cockpit" setMode={() => {}} gateway={chrome.gateway} t={T} />);
    const gw = container.querySelector('[data-chrome="rail-gateway"]');
    expect(gw.getAttribute('data-state')).toBe('running');
    expect(gw.getAttribute('title')).toContain('slack');
    const dot = gw.querySelector('.rail-gw-dot');
    expect(dot).not.toBeNull();
    expect(dot.closest('.rl')).toBeNull();          // `.rail .rl` is hidden when collapsed
    expect(gw.querySelector('.rl').textContent).toBe('GW 1');
  });

  it('marks an unknown gateway when no poll has answered', () => {
    const { container } = render(<Rail mode="cockpit" setMode={() => {}} t={T} />);
    expect(container.querySelector('[data-chrome="rail-gateway"]').getAttribute('data-state')).toBe('unknown');
  });
});

describe('brand strip sheds whole badges by priority', () => {
  /* jsdom has no layout, so widths are stubbed: every badge 70px, 9px gaps. The geometry in a
     real browser is pinned by e2e/status-chrome-layout.spec.ts; this pins the ORDER. */
  function strip(width: number, chrome = { gateway: { state: 'running', running: ['x'], total: 1 }, sessions: { active: 2, windowS: 900 }, version: '1.1.0' }) {
    const { container } = render(<TopBar clock={new Date(0)} lang="en" setLang={() => {}} accent="cyan" agents={[]} localPct={80}
      live={false} trust={null} llm={null} demo={false} setDemo={() => {}} serverUp={true}
      onPalette={() => {}} onAmbient={() => {}} chrome={chrome} t={T} />);
    const el = container.querySelector('.brand .badges') as HTMLElement;
    el.style.columnGap = '9px';
    Object.defineProperty(el, 'clientWidth', { configurable: true, value: width });
    for (const k of Array.from(el.children) as HTMLElement[]) {
      k.getBoundingClientRect = () => ({ width: k.hasAttribute('data-shed') ? 0 : 70 } as DOMRect);
    }
    fitBadgeStrip(el);
    const keys = (shed: boolean) => (Array.from(el.children) as HTMLElement[])
      .filter((k) => k.hasAttribute('data-shed') === shed).map((k) => k.querySelector('.k')!.textContent);
    return { shown: keys(false), shed: keys(true), container };
  }

  it('shows every badge when they fit', () => {
    expect(strip(8 * 70 + 7 * 9).shed).toEqual([]);
  });

  it('sheds SESSIONS, LOCAL, AGENTS, then MIC, then EGRESS — never LLM, DATA or GATEWAY first', () => {
    expect(strip(5 * 70 + 4 * 9).shown).toEqual(['LLM', 'DATA', 'GATEWAY', 'EGRESS', 'MIC']);
    expect(strip(5 * 70 + 4 * 9).shed).toEqual(['AGENTS', 'SESSIONS', 'LOCAL']);
    expect(strip(4 * 70 + 3 * 9).shown).toEqual(['LLM', 'DATA', 'GATEWAY', 'EGRESS']);
    expect(strip(3 * 70 + 2 * 9).shown).toEqual(['LLM', 'DATA', 'GATEWAY']);
  });

  it('keeps LLM as the last badge standing and never sheds to zero', () => {
    expect(strip(10).shown).toEqual(['LLM']);
  });

  it('a wider box brings shed badges back on the next fit', () => {
    const { container } = strip(3 * 70 + 2 * 9);
    const el = container.querySelector('.brand .badges') as HTMLElement;
    Object.defineProperty(el, 'clientWidth', { configurable: true, value: 2000 });
    fitBadgeStrip(el);
    expect(el.querySelectorAll('[data-shed]').length).toBe(0);
  });

  it('carries the version on the brand line, not as a strip badge', () => {
    const { container } = strip(2000);
    expect(container.querySelector('.brand-tx [data-chrome="version"]')!.textContent).toContain('v1.1.0');
    expect(container.querySelector('.brand .badges [data-chrome="version"]')).toBeNull();
  });
});
