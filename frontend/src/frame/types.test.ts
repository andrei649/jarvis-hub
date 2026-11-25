import { describe, expect, it } from 'vitest';
import { STATUS_CHROME_UNKNOWN } from '../api/status-chrome';
import { SAFE_MODE_OFF } from '../safe-mode-banner';
import {
  HUB_LOADER_FIELDS, LOADER_INTERVAL_MS, hubReading, hubSnapshotFrom, hubWithLocality, initialHubSnapshot, localityFrom,
} from './types';

const T0 = 1_700_000_000_000;
const live = {
  demo: false, serverUp: true, live: true,
  llm: { state: 'ready', model: 'gemma-4-31b', residents: [] },
  agents: [{ id: 'jarvis' }], sys: null, ticker: [], weather: null, calendar: [], heartbeat: [], tasks: [], decisions: [],
  trust: { mic: 'off', strict_local: true, cloud_available: false, claude_available: false },
  sources: { tasks: true, trust: true, agents: true },
  safeMode: SAFE_MODE_OFF, chrome: STATUS_CHROME_UNKNOWN,
} as const;

describe('initialHubSnapshot', () => {
  it('is Checking… with nothing invented', () => {
    const hub = initialHubSnapshot();
    expect(hub).toMatchObject({ state: 'unknown', reason: 'checking', serverUp: false, checkedAt: null, lastGoodAt: null, trust: null, locality: null, sys: null });
    expect(hub).toMatchObject({ backend: null, configuredModel: null, residency: null, slots: null });
    expect(hub.llm.state).toBe('unknown');
    expect(hub.intervalMs).toBe(LOADER_INTERVAL_MS);
    expect(hubReading(hub, T0)).toMatchObject({ state: 'unknown', reason: 'checking' });
    expect(initialHubSnapshot(true).state).toBe('demo');
  });
});

describe('hubSnapshotFrom', () => {
  it('is live when /status answered, stamped with the commit time', () => {
    const hub = hubSnapshotFrom(live as any, null, { now: T0 });
    expect(hub).toMatchObject({ state: 'live', serverUp: true, checkedAt: T0, lastGoodAt: T0, demo: false });
    expect(hub.llm.model).toBe('gemma-4-31b');
    expect(hub.agents).toEqual([{ id: 'jarvis' }]);
    expect(hub.sources).toEqual({ tasks: true, trust: true, agents: true });
  });

  it('goes offline when the hub stops answering, keeping the last good time', () => {
    const first = hubSnapshotFrom(live as any, null, { now: T0 });
    const down = hubSnapshotFrom({ ...live, serverUp: false } as any, first, { now: T0 + 30_000 });
    expect(down).toMatchObject({ state: 'offline', reason: 'network', checkedAt: T0 + 30_000, lastGoodAt: T0 });
    const never = hubSnapshotFrom({ ...live, serverUp: false } as any, null, { now: T0 });
    expect(never).toMatchObject({ state: 'offline', lastGoodAt: null });
  });

  it('prefers the loader\'s own cycle stamp when it sends one', () => {
    expect(hubSnapshotFrom({ ...live, checkedAt: T0 - 5 } as any, null, { now: T0 }).checkedAt).toBe(T0 - 5);
  });

  it('keeps trust unknown unless /api/trust/status answered, and parses it fail-closed', () => {
    const unanswered = hubSnapshotFrom({ ...live, trust: { mic: 'on', strict_local: false }, sources: { tasks: true, trust: false } } as any, null, { now: T0 });
    expect(unanswered.trust).toBeNull();
    const answered = hubSnapshotFrom(live as any, null, { now: T0 });
    expect(answered.trust).toEqual({ mic: 'off', strictLocal: true, cloudAvailable: false, claudeAvailable: false });
    const odd = hubSnapshotFrom({ ...live, trust: { mic: 'ON', strict_local: 'false' } } as any, null, { now: T0 });
    expect(odd.trust).toEqual({ mic: 'unknown', strictLocal: false, cloudAvailable: false, claudeAvailable: false });
  });

  it('labels demo as demo', () => {
    expect(hubSnapshotFrom({ ...live, demo: true } as any, null, { now: T0 }).state).toBe('demo');
  });

  it('keeps the locality figure across commits until a new answer replaces it', () => {
    const counts = { local_pct: 95, local: 115, cloud: 6, unknown: 6, total: 127 };
    const first = hubSnapshotFrom(live as any, null, { now: T0, locality: counts });
    expect(first.locality).toMatchObject(counts);
    const next = hubSnapshotFrom(live as any, first, { now: T0 + 30_000 });
    expect(next.locality).toMatchObject(counts);
    expect(hubWithLocality(next, null).locality).toBeNull();
    expect(hubWithLocality(next, { local_pct: null, local: 0, cloud: 0, unknown: 0, total: 0 }).locality).toMatchObject({ local_pct: null, total: 0 });
  });

  it('keeps the /status backend, configured model, residency and slots the loader supplies', () => {
    expect(HUB_LOADER_FIELDS).toEqual(['checkedAt', 'llmBackend', 'configuredModel', 'residencyState', 'slots']);
    const slots = {
      turns: { running: 2, per_session: 1, cap: 4 },
      lanes: [{ channel: 'telegram', running: 0, queued: 1, lanes: 1, cap: 2 }],
      subagents: { running: 1, cap: 4 },
    };
    const hub = hubSnapshotFrom({ ...live, llmBackend: 'ollama', configuredModel: ' gemma-4-31b ', residencyState: 'known', slots } as any, null, { now: T0 });
    expect(hub).toMatchObject({ backend: 'ollama', configuredModel: 'gemma-4-31b', residency: 'known', slots });
    // the hub's own words are kept: 'none' is its statement that no backend is configured
    expect(hubSnapshotFrom({ ...live, llmBackend: 'none', residencyState: 'offline' } as any, null, { now: T0 }))
      .toMatchObject({ backend: 'none', residency: 'offline' });
  });

  it('says not reported (null) for a /status field that is missing, unreadable or from a hub that did not answer', () => {
    const missing = hubSnapshotFrom(live as any, null, { now: T0 });
    expect(missing).toMatchObject({ backend: null, configuredModel: null, residency: null, slots: null });
    const odd = hubSnapshotFrom({ ...live, llmBackend: '  ', configuredModel: 42, residencyState: 'maybe', slots: { turns: { running: 1 } } } as any, null, { now: T0 });
    expect(odd).toMatchObject({ backend: null, configuredModel: null, residency: null, slots: null });
    const partial = hubSnapshotFrom({ ...live, slots: { turns: { running: -1 }, lanes: [{ running: 1 }, { channel: 'web', running: 'x' }], subagents: null } } as any, null, { now: T0 });
    expect(partial.slots).toEqual({ turns: null, lanes: [{ channel: 'web', running: null, queued: null, lanes: null, cap: null }], subagents: null });
    const first = hubSnapshotFrom({ ...live, llmBackend: 'ollama', residencyState: 'known' } as any, null, { now: T0 });
    const down = hubSnapshotFrom({ ...live, serverUp: false, llmBackend: 'ollama', residencyState: 'known' } as any, first, { now: T0 + 30_000 });
    expect(down).toMatchObject({ state: 'offline', backend: null, configuredModel: null, residency: null, slots: null });
  });

  it('rejects a locality answer it cannot read', () => {
    expect(localityFrom({ local_pct: 100 })).toBeNull();
    expect(localityFrom({ local_pct: '100', local: 1, cloud: 0, unknown: 0, total: 1 })).toBeNull();
    expect(localityFrom({ local_pct: 50, local: -1, cloud: 0, unknown: 0, total: 1 })).toBeNull();
    expect(localityFrom('nope')).toBeNull();
  });
});

describe('hubReading', () => {
  it('turns stale 2.5 loader intervals after the last good answer', () => {
    const hub = hubSnapshotFrom(live as any, null, { now: T0 });
    expect(hubReading(hub, T0 + 75_000).state).toBe('live');
    expect(hubReading(hub, T0 + 75_001)).toMatchObject({ state: 'stale', lastGoodAt: T0 });
    const down = hubSnapshotFrom({ ...live, serverUp: false } as any, hub, { now: T0 + 30_000 });
    expect(hubReading(down, T0 + 200_000)).toMatchObject({ state: 'offline', reason: 'network', lastGoodAt: T0 });
  });
});
