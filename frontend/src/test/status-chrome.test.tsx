// @ts-nocheck
/* H133 — the live status chrome: the gateway (with the channels running), the active-session count
   and the hub's version, read from the polled /status. They are drawn in the running foot since the
   Ledger frame (PHASE_B_PLAN.md §4.3, §8.2 row 17), under the same data-chrome hooks the HUD v2 top
   bar used; the top bar's badges and the rail's gateway dot were deleted with the classic shell, and
   the badge-shedding tests with them (no badges remain). Each shows what the poll answered, or an
   honest dash when it could not — never a plausible guess. Here the real loader feeds the real hub
   snapshot and the real running foot; RunningFoot.test.tsx pins the foot's words in detail. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React from 'react';
import { render } from '@testing-library/react';
import { loadJarvisData } from '../api/loaders';
import { readStatusChrome, STATUS_CHROME_UNKNOWN } from '../api/status-chrome';
import { RunningFoot } from '../frame/RunningFoot';
import { hubSnapshotFrom, initialHubSnapshot } from '../frame/types';
import { resetPolling } from '../signals/poll';

const ok = (payload: unknown) => Promise.resolve({ ok: true, status: 200, json: async () => payload });
const down = () => Promise.reject(new TypeError('network down'));

beforeEach(() => { resetPolling(); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); resetPolling(); });

function stubStatus(status: any) {
  const fetchMock = vi.fn((url: string) => {
    if (url === '/status') return status === null ? down() : ok(status);
    return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

/** The loader reads /status, App commits it into the hub snapshot, the running foot draws it. */
async function foot(status: any) {
  stubStatus(status);
  const data = await loadJarvisData(false);
  const hub = hubSnapshotFrom(data, initialHubSnapshot());
  const view = render(<RunningFoot hub={hub} lang="en" demo={false} turns={[]} />);
  return { data, hub, ...view };
}

const part = (container, key) => container.querySelector(`[data-chrome="${key}"]`);

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

describe('the running foot follows the polled /status', () => {
  it('shows running channels, the active-session count and the version', async () => {
    const { data, container } = await foot({
      version: '1.4.0',
      gateway: { state: 'running', running: ['discord', 'telegram'], running_count: 2, total: 3 },
      sessions: { active: 5, window_s: 900, state: 'known' },
    });
    expect(data.chrome.gateway.running).toEqual(['discord', 'telegram']);
    expect(part(container, 'gateway').textContent).toContain('2 of 3 running');
    expect(part(container, 'gateway').getAttribute('title')).toBe('discord, telegram');
    expect(part(container, 'gateway').getAttribute('data-state')).toBe('running');
    // from 2200px the whole sentence; below, the count alone with the window in its title (CSS shows one)
    expect(part(container, 'sessions').querySelector('[data-show-from="xl"]')?.textContent).toBe('5 sessions in the last 15 min');
    expect(part(container, 'sessions').querySelector('[data-show-upto="l"]')?.textContent).toBe('5 sessions');
    expect(part(container, 'sessions').getAttribute('title')).toBe('5 sessions in the last 15 min');
    expect(part(container, 'version').textContent).toBe('Nerva 1.4.0');
  });

  it('shows a stopped gateway and zero sessions as such', async () => {
    const { container } = await foot({
      version: '1.4.0',
      gateway: { state: 'stopped', running: [], running_count: 0, total: 2 },
      sessions: { active: 0, window_s: 900, state: 'known' },
    });
    expect(part(container, 'gateway').textContent).toContain('Stopped');
    expect(part(container, 'gateway').getAttribute('data-state')).toBe('stopped');
    expect(part(container, 'sessions').querySelector('[data-show-from="xl"]')?.textContent).toBe('0 sessions in the last 15 min');
    expect(part(container, 'sessions').querySelector('[data-show-upto="l"]')?.textContent).toBe('0 sessions');
  });

  it('shows dashes, not zeros, when the store or the server cannot answer', async () => {
    const first = await foot({ version: '1.4.0', gateway: { state: 'none', running: [], total: 0 },
      sessions: { active: null, window_s: 900, state: 'unknown' } });
    expect(part(first.container, 'sessions').textContent).toBe('sessions —');
    expect(part(first.container, 'gateway').textContent).toContain('None configured');
    first.unmount();
    resetPolling();
    vi.unstubAllGlobals();

    const offline = await foot(null);
    expect(offline.data.serverUp).toBe(false);
    expect(offline.data.chrome).toEqual(STATUS_CHROME_UNKNOWN);
    expect(offline.hub.state).toBe('offline');
    expect(part(offline.container, 'gateway').getAttribute('data-state')).toBe('unknown');
    expect(part(offline.container, 'gateway').textContent).toContain('Unknown');
    expect(part(offline.container, 'gateway').textContent).not.toMatch(/\d/);
    expect(part(offline.container, 'sessions').textContent).toBe('sessions —');
    expect(part(offline.container, 'version')).toBeNull();
  });
});
