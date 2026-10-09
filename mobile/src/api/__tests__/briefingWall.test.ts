import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { readBriefingWall } from '../briefingWall';

const config = { baseUrl: ' hub.local/ ', token: ' user-secret ', adminToken: ' admin-secret ' };
const paths = ['/healthz', '/api/agents', '/tasks?view=running', '/api/trust/status', '/api/analytics/locality'];
const bodies: Record<string, unknown> = {
  '/healthz': { status: 'ok', debug: 'ignore me' },
  '/api/agents': { agents: [{ id: 'jarvis', status: 'ready', tier: 'CNS', soul: 'private' },
    { id: 'frigga', status: 'idle', tier: 'FND' }] },
  '/tasks?view=running': { view: 'running', history_included: false,
    tasks: [{ owner: 'frigga', state: 'Running', payload: 'secret task content' }] },
  '/api/trust/status': { mic: 'on', strict_local: false, cloud_available: false, claude_available: true },
  '/api/analytics/locality': { local: 1, cloud: 7, unknown: 2, total: 10, local_pct: 12 },
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
  it('starts five parallel GETs, sends both trimmed credentials, and keeps only validated fields', async () => {
    const pending: Array<(response: Response) => void> = [];
    mockFetch.mockImplementation(() => new Promise(resolve => { pending.push(resolve); }));
    const reading = readBriefingWall(config, new AbortController().signal);
    expect(mockFetch).toHaveBeenCalledTimes(5);
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
    expect(JSON.stringify(result)).not.toMatch(/secret|private|payload|soul/);
    for (const value of Object.values(result)) expect(value.checkedAt).toEqual(expect.any(Number));
  });

  it('keeps real empty arrays and an unknown-only locality as available without a fabricated percent', async () => {
    mockFetch.mockImplementation(async url => {
      const path = route(String(url));
      if (path === '/api/agents') return reply({ agents: [] });
      if (path === '/tasks?view=running') return reply({ view: 'running', history_included: false, tasks: [] });
      if (path === '/api/analytics/locality') return reply({ local: 0, cloud: 0, unknown: 3, total: 3, local_pct: null });
      return reply(bodies[path]);
    });
    const result = await readBriefingWall(config, new AbortController().signal);
    expect(result.agents).toMatchObject({ status: 'available', value: [] });
    expect(result.tasks).toMatchObject({ status: 'available', value: [] });
    expect(result.locality).toMatchObject({ status: 'available', value: { percent: null, total: 3 } });
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
    expect(mockFetch).toHaveBeenCalledTimes(5);
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
});
