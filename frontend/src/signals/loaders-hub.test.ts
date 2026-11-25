/* The loader keeps what the HubSnapshot reads from /status (api/loaders.ts, additive) and stamps
   the cycle's end; hubSnapshotFrom validates it. Nothing is invented when /status did not say. */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadJarvisData } from '../api/loaders';
import { HUB_LOADER_FIELDS, hubSnapshotFrom } from '../frame/types';

const ok = (payload: unknown) => Promise.resolve({ ok: true, status: 200, json: async () => payload });
const unavailable = () => Promise.resolve({ ok: false, status: 503, json: async () => ({}) });
const original = globalThis.fetch;
afterEach(() => { globalThis.fetch = original; vi.useRealTimers(); });

function hubSays(status: unknown) {
  globalThis.fetch = vi.fn((url: string) => (url === '/status' ? ok(status) : unavailable())) as unknown as typeof fetch;
}

const SLOTS = { turns: { running: 1, per_session: 1, cap: 4 }, lanes: [], subagents: { running: 0, cap: 2 } };

describe('loadJarvisData: the /status fields the hub snapshot reads', () => {
  it('keeps llm_backend, configured_model, residency_state and slots, raw, under the names HUB_LOADER_FIELDS lists', async () => {
    hubSays({ model_state: 'ready', loaded_model: 'gemma-4-31b', llm_backend: 'ollama', configured_model: 'gemma-4-31b', residency_state: 'known', slots: SLOTS });
    const data = await loadJarvisData(false);
    expect(HUB_LOADER_FIELDS).toEqual(['checkedAt', 'llmBackend', 'configuredModel', 'residencyState', 'slots']);
    expect(data.llmBackend).toBe('ollama');
    expect(data.configuredModel).toBe('gemma-4-31b');
    expect(data.residencyState).toBe('known');
    expect(data.slots).toEqual(SLOTS);
    const hub = hubSnapshotFrom(data, null);
    expect(hub).toMatchObject({ state: 'live', backend: 'ollama', configuredModel: 'gemma-4-31b', residency: 'known', slots: { turns: { running: 1, per_session: 1, cap: 4 } } });
  });

  it('keeps the hub calendar ts (its rows carry no tm), so the day register can read the start', async () => {
    const ts = '2026-11-23T14:00:00+02:00';
    globalThis.fetch = vi.fn((url: string) => (url === '/status' ? ok({ model_state: 'ready' })
      : url === '/dashboard' ? ok({ calendar: [{ ts, title: 'Raiffeisen review', owner: 'x', state: 'upcoming', duration_min: 60, location: 'Conf Room A' }, { ts: '2026-11-23', title: 'Holiday', state: 'upcoming' }] })
        : unavailable())) as unknown as typeof fetch;
    const data = await loadJarvisData(false);
    expect(data.calendar?.map((c: any) => [c.ti, c.vw, c.tm, c.ts])).toEqual([['Raiffeisen review', 'Conf Room A', '', ts], ['Holiday', '', '', '2026-11-23']]);
  });

  it('returns when the cycle finished, and the snapshot prefers it to its own clock', async () => {
    hubSays({ model_state: 'ready' });
    const before = Date.now();
    const data = await loadJarvisData(false);
    const after = Date.now();
    expect(data.checkedAt).toBeGreaterThanOrEqual(before);
    expect(data.checkedAt).toBeLessThanOrEqual(after);
    expect(hubSnapshotFrom(data, null, { now: 1 }).checkedAt).toBe(data.checkedAt);
  });

  it('leaves out what /status did not send: not reported, never a default', async () => {
    hubSays({ model_state: 'no_model', loaded_model: null });
    const data = await loadJarvisData(false);
    for (const field of ['llmBackend', 'configuredModel', 'residencyState', 'slots'] as const) expect(field in data, field).toBe(false);
    const hub = hubSnapshotFrom(data, null);
    expect([hub.backend, hub.configuredModel, hub.residency, hub.slots]).toEqual([null, null, null, null]);
  });

  it('keeps the hub\'s own "none" backend, and a slots answer the frame cannot read becomes null', async () => {
    hubSays({ model_state: 'offline', llm_backend: 'none', slots: { turns: 'many' } });
    const hub = hubSnapshotFrom(await loadJarvisData(false), null);
    expect([hub.backend, hub.slots]).toEqual(['none', null]);
  });

  it('an unreachable hub still stamps the cycle, and carries none of the /status fields', async () => {
    globalThis.fetch = vi.fn(() => unavailable()) as unknown as typeof fetch;
    const data = await loadJarvisData(false);
    expect(data.serverUp).toBe(false);
    expect(typeof data.checkedAt).toBe('number');
    expect(hubSnapshotFrom(data, null)).toMatchObject({ state: 'offline', backend: null, slots: null });
  });

  it('keeps decisionCard() as it was: one Dismiss action', async () => {
    const { decisionCard } = await import('../api/loaders');
    const card = decisionCard({ id: 7, title: 'Send the report', kind: 'send_email', agent: 'ultron', reversible: false });
    expect(card.actions).toEqual([{ l: 'Dismiss' }]);
    expect(card).toMatchObject({ id: 7, body: 'Send the report', who: 'ULTRON', kind: 'alert', live: true });
  });
});
