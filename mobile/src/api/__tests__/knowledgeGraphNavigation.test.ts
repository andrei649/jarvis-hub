import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { fetchGraphEntities, fetchGraphEntity, fetchGraphFacts, fetchGraphHistory } from '../knowledgeGraph';

const config = { baseUrl: 'https://hub.test', token: 'user-token', adminToken: 'admin-secret' };
const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
const response = (body: unknown, status = 200): Response => ({
  ok: status >= 200 && status < 300, status,
  headers: { get: () => null },
  text: async () => JSON.stringify(body),
} as unknown as Response);

beforeEach(() => {
  mockFetch.mockReset();
  (globalThis as { fetch: typeof fetch }).fetch = mockFetch;
});

describe('bounded native graph reads', () => {
  it('uses current user credentials and existing GET fields for all graph reads', async () => {
    mockFetch.mockResolvedValueOnce(response({ entities: [{ name: 'A', type: 'person' }], total: 1 }));
    mockFetch.mockResolvedValueOnce(response({ entity: { name: 'A', type: 'person' }, relations: [] }));
    mockFetch.mockResolvedValueOnce(response({ facts: [] }));
    mockFetch.mockResolvedValueOnce(response({ subject: 'A', history: [] }));
    await fetchGraphEntities(config, 'a');
    await fetchGraphEntity(config, 'A');
    await fetchGraphFacts(config);
    await fetchGraphHistory(config, 'A');
    expect(mockFetch.mock.calls.map(([url]) => url)).toEqual([
      'https://hub.test/api/kg/entities?limit=50&q=a',
      'https://hub.test/api/kg/entities/A',
      'https://hub.test/api/kg/facts/as-of',
      'https://hub.test/api/kg/facts/history?subject=A',
    ]);
    for (const [, init] of mockFetch.mock.calls) {
      expect(init).toEqual(expect.objectContaining({ method: 'GET', headers: expect.objectContaining({ 'X-User-Token': 'user-token' }), signal: expect.anything() }));
      expect((init?.headers as Record<string, string>)['X-Admin-Token']).toBeUndefined();
    }
  });

  it('sends a configured admin token when it is the only credential', async () => {
    mockFetch.mockResolvedValueOnce(response({ entities: [], total: 0 }));
    await fetchGraphEntities({ ...config, token: '' }, '');
    const headers = mockFetch.mock.calls[0][1]?.headers as Record<string, string>;
    expect(headers['X-Admin-Token']).toBe('admin-secret');
    expect(headers['X-User-Token']).toBeUndefined();
  });

  it('treats the list endpoint’s 200 error body as unavailable', async () => {
    mockFetch.mockResolvedValueOnce(response({ entities: [], error: 'graph not available' }));
    await expect(fetchGraphEntities(config, '')).rejects.toThrow('graph not available');
  });

  it('aborts a superseded read and reports a deadline separately', async () => {
    const controller = new AbortController();
    mockFetch.mockImplementation((_url, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    }));
    const cancelled = fetchGraphEntity(config, 'A', controller.signal);
    controller.abort();
    await expect(cancelled).rejects.toMatchObject({ name: 'AbortError' });
    jest.useFakeTimers();
    try {
      const timed = fetchGraphHistory(config, 'A');
      const outcome = expect(timed).rejects.toThrow('timed out');
      await jest.advanceTimersByTimeAsync(10_001);
      await outcome;
    } finally { jest.useRealTimers(); }
  });

  it('rejects oversized and unrelated detail data rather than making empty relations', async () => {
    mockFetch.mockResolvedValueOnce(response({ entity: { name: 'A', type: 'person' }, relations: [] }, 503));
    await expect(fetchGraphEntity(config, 'A')).rejects.toThrow('503');
    mockFetch.mockResolvedValueOnce({ ...response({}), headers: { get: (name: string) => name === 'content-length' ? '1048577' : null } } as Response);
    await expect(fetchGraphEntities(config, '')).rejects.toThrow('too large');
    mockFetch.mockResolvedValueOnce(response({ entity: { name: 'A', type: 'person' }, relations: [{ source: 'X', target: 'Y', relation: 'knows' }] }));
    await expect(fetchGraphEntity(config, 'A')).rejects.toThrow('unrelated');
  });

  it('rejects history that belongs to another subject', async () => {
    mockFetch.mockResolvedValueOnce(response({ subject: 'B', history: [] }));
    await expect(fetchGraphHistory(config, 'A')).rejects.toThrow('subject');
    mockFetch.mockResolvedValueOnce(response({ subject: 'A', history: [{ subject: 'B', predicate: 'knows', object: 'C' }] }));
    await expect(fetchGraphHistory(config, 'A')).rejects.toThrow('subject');
  });

  it.each([['A', 1], ['ș', 2], ['中', 3], ['😀', 4]] as const)('enforces the UTF-8 body limit without a native TextEncoder (%s)', async (character, width) => {
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'TextEncoder');
    Object.defineProperty(globalThis, 'TextEncoder', { value: undefined, configurable: true, writable: true });
    try {
      const payload = (note: string) => ({ entities: [{ name: 'A', type: 'person', properties: { note } }] });
      // The empty JSON envelope is ASCII; each fixture's UTF-8 width is explicit.
      const available = 1024 * 1024 - JSON.stringify(payload('')).length;
      const note = character.repeat(Math.floor(available / width)) + ' '.repeat(available % width);
      mockFetch.mockResolvedValueOnce(response(payload(note)));
      await expect(fetchGraphEntities(config, '')).resolves.toMatchObject({ entities: [{ name: 'A' }] });
      mockFetch.mockResolvedValueOnce(response(payload(note + 'x')));
      await expect(fetchGraphEntities(config, '')).rejects.toThrow('too large');
    } finally {
      if (descriptor) Object.defineProperty(globalThis, 'TextEncoder', descriptor);
      else Reflect.deleteProperty(globalThis, 'TextEncoder');
    }
  });
});
