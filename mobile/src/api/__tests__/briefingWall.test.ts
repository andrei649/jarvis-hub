import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { readBriefingWall } from '../briefingWall';

const config = { baseUrl: ' hub.local/ ', token: ' user-secret ', adminToken: ' admin-secret ' };
const paths = ['/healthz', '/api/agents', '/tasks?view=running', '/api/trust/status', '/api/analytics/locality',
  '/autonomy/approvals', '/dashboard', '/status', '/api/voice/capabilities', '/heartbeat/status'];
const bodies: Record<string, unknown> = {
  '/healthz': { status: 'ok', debug: 'ignore me' },
  '/api/agents': { agents: [{ id: 'jarvis', status: 'ready', tier: 'CNS', soul: 'private' },
    { id: 'frigga', status: 'idle', tier: 'FND' }] },
  '/tasks?view=running': { view: 'running', history_included: false,
    tasks: [{ owner: 'frigga', state: 'Running', payload: 'secret task content' }] },
  '/api/trust/status': { mic: 'on', strict_local: false, cloud_available: false, claude_available: true },
  '/api/analytics/locality': { local: 1, cloud: 7, unknown: 2, total: 10, local_pct: 12 },
  '/autonomy/approvals': { pending: [{ id: 4, status: 'blocked', payload: 'approval secret' },
    { id: 5, status: 'proposed', title: 'private title' }], counts: { total: 2 }, reversible: [] },
  '/dashboard': { calendar: [{ ts: '2026-10-09T11:30:00+00:00', state: 'next', title: 'private meeting' }],
    notifications: [{ body: 'private notification' }] },
  '/status': { model_state: 'ready', model_loaded: true,
    resident_models: [{ id: 'private-model', provider: 'lm-studio' }], configured_model: 'private-model' },
  '/api/voice/capabilities': { stt: true, tts: true, tts_local: true, local_only: false,
    providers: [{ key: 'private provider' }] },
  '/heartbeat/status': { scheduler_running: true,
    heartbeats: [{ agent_id: 'frigga', next_run: 'private next run', trigger: 'private trigger' }],
    blocked: [{ agent_id: 'ultron', path: 'private path', digest: 'private digest' }] },
};
const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
function reply(body: unknown, status = 200, length?: string): Response {
  return { ok: status >= 200 && status < 300, status,
    headers: { get: (name: string) => name.toLowerCase() === 'content-length' ? length ?? null : null },
    text: async () => JSON.stringify(body),
  } as Response;
}
function route(url: string): string { return url.slice('http://hub.local'.length); }
beforeEach(() => {
  mockFetch.mockReset();
  (globalThis as any).fetch = mockFetch;
  mockFetch.mockImplementation(async url => reply(bodies[route(String(url))]));
});

describe('native briefing wall read projection', () => {
  it('does not invent a reported tier when a roster row omits it', async () => {
    mockFetch.mockImplementation(async url => route(String(url)) === '/api/agents'
      ? reply({ agents: [{ id: 'frigga', status: 'idle' }] }) : reply(bodies[route(String(url))]));
    const result = await readBriefingWall(config, new AbortController().signal);
    expect(result.agents).toMatchObject({ status: 'unavailable', value: null });
    expect(result.health.status).toBe('available');
  });
  it('starts ten parallel GETs, sends both trimmed credentials, and keeps only validated fields', async () => {
    const pending: Array<(response: Response) => void> = [];
    mockFetch.mockImplementation(() => new Promise(resolve => { pending.push(resolve); }));
    const reading = readBriefingWall(config, new AbortController().signal);
    expect(mockFetch).toHaveBeenCalledTimes(10);
    expect(mockFetch.mock.calls.map(call => route(String(call[0])))).toEqual(paths);
    for (const [url, options] of mockFetch.mock.calls) {
      expect(String(url)).toMatch(/^http:\/\/hub\.local\//);
      expect(options).toMatchObject({ method: 'GET', cache: 'no-store', redirect: 'error',
        headers: { Accept: 'application/json', 'X-User-Token': 'user-secret', 'X-Admin-Token': 'admin-secret' } });
    }
    pending.forEach((done, index) => done(reply(bodies[paths[index]])));
    const result = await reading;
    expect(result.health).toMatchObject({ status: 'available', value: { up: true } });
    expect(result.agents).toMatchObject({ status: 'available', value: [
      { id: 'jarvis', status: 'ready', tier: 'CNS' }, { id: 'frigga', status: 'idle', tier: 'FND' },
    ] });
    expect(result.tasks).toMatchObject({ status: 'available', value: [{ owner: 'frigga', state: 'running' }] });
    expect(result.trust).toMatchObject({ status: 'available', value: { mic: 'on', strictLocal: false, cloudAvailable: true } });
    // Python round(12.5) is 12. Unknown runs are excluded from the denominator.
    expect(result.locality).toMatchObject({ status: 'available', value: { local: 1, cloud: 7, unknown: 2, total: 10, percent: 12 } });
    expect(result.approvals).toMatchObject({ status: 'available', value: { pending: 2 } });
    expect(result.calendar).toMatchObject({ status: 'available', value: { returned: 1 } });
    expect(result.model).toMatchObject({ status: 'available', value: { state: 'ready', residentCount: 1 } });
    expect(result.voice).toMatchObject({ status: 'available', value: { stt: true, tts: true, ttsLocal: true, localOnly: false } });
    expect(result.heartbeat).toMatchObject({ status: 'available', value: { running: true, scheduled: 1, blocked: 1 } });
    expect(JSON.stringify(result)).not.toMatch(/secret|private|payload|soul|next_run|digest|trigger/);
    for (const value of Object.values(result)) expect(value.checkedAt).toEqual(expect.any(Number));
  });

  it('keeps real empty arrays and an unknown-only locality as available without a fabricated percent', async () => {
    mockFetch.mockImplementation(async url => {
      const path = route(String(url));
      if (path === '/api/agents') return reply({ agents: [] });
      if (path === '/tasks?view=running') return reply({ view: 'running', history_included: false, tasks: [] });
      if (path === '/api/analytics/locality') return reply({ local: 0, cloud: 0, unknown: 3, total: 3, local_pct: null });
      if (path === '/autonomy/approvals') return reply({ pending: [], counts: { total: 0 } });
      if (path === '/dashboard') return reply({ calendar: [] });
      if (path === '/status') return reply({ model_state: 'unknown', model_loaded: false, resident_models: [] });
      if (path === '/heartbeat/status') return reply({ scheduler_running: false, heartbeats: [], blocked: [] });
      return reply(bodies[path]);
    });
    const result = await readBriefingWall(config, new AbortController().signal);
    expect(result.agents).toMatchObject({ status: 'available', value: [] });
    expect(result.tasks).toMatchObject({ status: 'available', value: [] });
    expect(result.locality).toMatchObject({ status: 'available', value: { percent: null, total: 3 } });
    expect(result.approvals).toMatchObject({ status: 'available', value: { pending: 0 } });
    expect(result.calendar).toMatchObject({ status: 'unavailable', value: null });
    expect(result.model).toMatchObject({ status: 'available', value: { state: 'unknown', residentCount: 0 } });
    expect(result.heartbeat).toMatchObject({ status: 'available', value: { running: false, scheduled: 0, blocked: 0 } });
  });

  it('accepts bounded RFC3339 calendar timestamps with nine fractional second digits', async () => {
    mockFetch.mockImplementation(async url => route(String(url)) === '/dashboard'
      ? reply({ calendar: [{ ts: '2026-10-09T11:30:00.123456789+00:00', state: 'next' }] })
      : reply(bodies[route(String(url))]));
    const result = await readBriefingWall(config, new AbortController().signal);
    expect(result.calendar).toMatchObject({ status: 'available', value: { returned: 1 } });
  });

  it('marks only malformed or failed sources unavailable and retains healthy peers', async () => {
    mockFetch.mockImplementation(async url => {
      const path = route(String(url));
      if (path === '/api/agents') return reply({ agents: [{ id: 'jarvis', status: 'ready' }, { id: 'jarvis', status: 'idle' }] });
      if (path === '/tasks?view=running') return reply({ view: 'history', history_included: true, tasks: [] });
      if (path === '/api/trust/status') throw new Error('token=private server detail');
      if (path === '/api/analytics/locality') return reply({ local: 1, cloud: 0, unknown: 0, total: 2, local_pct: 100 });
      return reply(bodies[path]);
    });
    const result = await readBriefingWall(config, new AbortController().signal);
    expect(result.health.status).toBe('available');
    for (const key of ['agents', 'tasks', 'trust', 'locality'] as const) {
      expect(result[key]).toMatchObject({ status: 'unavailable', value: null });
    }
    expect(JSON.stringify(result)).not.toContain('token=private');
  });

  it('rejects a pre-aborted read without dispatching any request', async () => {
    const abort = new AbortController(); abort.abort();
    await expect(readBriefingWall(config, abort.signal)).rejects.toThrow('Briefing read cancelled.');
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('rejects the aggregate promptly when the caller aborts even if fetch ignores cancellation', async () => {
    mockFetch.mockImplementation(() => new Promise(() => {}));
    const abort = new AbortController();
    const reading = readBriefingWall(config, abort.signal);
    expect(mockFetch).toHaveBeenCalledTimes(10);
    abort.abort();
    await expect(reading).rejects.toThrow('Briefing read cancelled.');
  });

  it('times out one ignored body read at five seconds and leaves healthy peers available', async () => {
    jest.useFakeTimers();
    try {
      mockFetch.mockImplementation(async url => route(String(url)) === '/api/agents'
        ? { ...reply({ agents: [] }), text: () => new Promise<string>(() => {}) } as Response
        : reply(bodies[route(String(url))]));
      const reading = readBriefingWall(config, new AbortController().signal);
      await jest.advanceTimersByTimeAsync(5001);
      const result = await reading;
      expect(result.agents.status).toBe('unavailable');
      expect(result.health.status).toBe('available');
    } finally { jest.useRealTimers(); }
  });

  it('rejects oversized declared or buffered JSON per source without TextEncoder', async () => {
    const encoder = (globalThis as any).TextEncoder;
    (globalThis as any).TextEncoder = undefined;
    try {
      mockFetch.mockImplementation(async url => {
        const path = route(String(url));
        if (path === '/healthz') return reply(bodies[path], 200, '262145');
        if (path === '/api/agents') return { ...reply({ agents: [] }), text: async () => 'x'.repeat(262145) } as Response;
        return reply(bodies[path]);
      });
      const result = await readBriefingWall(config, new AbortController().signal);
      expect(result.health.status).toBe('unavailable');
      expect(result.agents.status).toBe('unavailable');
      expect(result.tasks.status).toBe('available');
    } finally { (globalThis as any).TextEncoder = encoder; }
  });

  it('refuses invalid task rows and misleading locality percentages', async () => {
    mockFetch.mockImplementation(async url => {
      const path = route(String(url));
      if (path === '/tasks?view=running') return reply({ view: 'running', history_included: false,
        tasks: [{ owner: 'frigga', state: 'done', status: 'running' }] });
      if (path === '/api/analytics/locality') return reply({ local: 0, cloud: 0, unknown: 0, total: 0, local_pct: 100 });
      return reply(bodies[path]);
    });
    const result = await readBriefingWall(config, new AbortController().signal);
    expect(result.tasks.status).toBe('unavailable');
    expect(result.locality.status).toBe('unavailable');
  });

  it('independently refuses malformed optional feeds without turning refusal into zero', async () => {
    mockFetch.mockImplementation(async url => {
      const path = route(String(url));
      if (path === '/autonomy/approvals') return reply({ pending: [{ id: 4, status: 'running' }], counts: { total: 1 } });
      if (path === '/dashboard') return reply({ calendar: [{ ts: '2026-02-31', state: 'next', title: 'private' }] });
      if (path === '/status') return reply({ model_state: 'ready', model_loaded: false, resident_models: [] });
      if (path === '/api/voice/capabilities') return reply({ stt: true, tts: 'true', tts_local: false, local_only: false });
      if (path === '/heartbeat/status') return reply({ scheduler_running: true,
        heartbeats: [{ agent_id: 'frigga' }, { agent_id: 'frigga' }], blocked: [] });
      return reply(bodies[path]);
    });
    const result = await readBriefingWall(config, new AbortController().signal);
    expect(result.health.status).toBe('available');
    for (const key of ['approvals', 'calendar', 'model', 'voice', 'heartbeat'] as const) {
      expect(result[key]).toMatchObject({ status: 'unavailable', value: null });
    }
    expect(JSON.stringify(result)).not.toContain('private');
  });

  it('checks decision identity/count, bounded samples, model rows and heartbeat quarantine independently', async () => {
    const invalid: Record<string, unknown> = {
      '/autonomy/approvals': { pending: [{ id: 8, status: 'blocked' }, { id: 8, status: 'proposed' }], counts: { total: 2 } },
      '/dashboard': { calendar: Array.from({ length: 11 }, () => ({ ts: '2026-10-09', state: 'next' })) },
      '/status': { model_state: 'ready', model_loaded: true, resident_models: [{ id: '', provider: 'lm-studio' }] },
      '/heartbeat/status': { scheduler_running: false, heartbeats: [], blocked: [{ agent_id: '' }] },
    };
    mockFetch.mockImplementation(async url => reply(invalid[route(String(url))] ?? bodies[route(String(url))]));
    const result = await readBriefingWall(config, new AbortController().signal);
    for (const key of ['approvals', 'calendar', 'model', 'heartbeat'] as const) {
      expect(result[key].status).toBe('unavailable');
    }
    expect(result.voice.status).toBe('available');
  });

  it('keeps an admin refusal for approvals isolated from user and public reads', async () => {
    mockFetch.mockImplementation(async url => route(String(url)) === '/autonomy/approvals'
      ? reply({ error: 'admin required' }, 403) : reply(bodies[route(String(url))]));
    const result = await readBriefingWall({ ...config, adminToken: '' }, new AbortController().signal);
    expect(result.approvals).toMatchObject({ status: 'unavailable', value: null });
    expect(result.agents.status).toBe('available');
    expect(result.calendar.status).toBe('available');
    expect(mockFetch.mock.calls[5][1]?.headers).not.toHaveProperty('X-Admin-Token');
    expect(JSON.stringify(result)).not.toContain('admin required');
  });

  it('rejects source-specific row caps and a starting model without hiding other sources', async () => {
    mockFetch.mockImplementation(async url => {
      const path = route(String(url));
      if (path === '/autonomy/approvals') return reply({ pending: Array.from({ length: 101 }, (_, id) =>
        ({ id: id + 1, status: 'blocked' })), counts: { total: 101 } });
      if (path === '/status') return reply({ status: 'starting' });
      if (path === '/heartbeat/status') return reply({ scheduler_running: true,
        heartbeats: Array.from({ length: 257 }, (_, id) => ({ agent_id: `a${id}` })), blocked: [] });
      return reply(bodies[path]);
    });
    const result = await readBriefingWall(config, new AbortController().signal);
    expect(result.approvals.status).toBe('unavailable');
    expect(result.model.status).toBe('unavailable');
    expect(result.heartbeat.status).toBe('unavailable');
    expect(result.calendar.status).toBe('available');
  });

  it('dispatches nothing for an unconfigured base and returns unavailable for every source', async () => {
    const result = await readBriefingWall({ ...config, baseUrl: '' }, new AbortController().signal);
    expect(mockFetch).not.toHaveBeenCalled();
    expect(Object.keys(result)).toHaveLength(10);
    for (const source of Object.values(result)) expect(source).toMatchObject({ status: 'unavailable', value: null });
  });
});
