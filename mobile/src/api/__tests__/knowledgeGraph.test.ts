import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { fetchKgEntities, fetchKgEntity, fetchKgFactHistory, fetchKgFacts } from '../client';

const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

beforeEach(() => {
  mockFetch.mockReset();
  (globalThis as any).fetch = mockFetch;
});

describe('mobile knowledge graph API', () => {
  it('fetches searchable KG entities with user auth', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        entities: [
          { name: 'Andrei Popescu', type: 'person', properties: { city: 'Bucharest' } },
          { name: 'Jarvis Hub', type: 'project' },
        ],
        total: 2,
      }),
    );

    const out = await fetchKgEntities(
      { baseUrl: '192.168.1.20:8080/', token: 'user-token', adminToken: 'admin-token' },
      { query: 'Andrei', limit: 25 },
    );

    expect(mockFetch).toHaveBeenCalledWith(
      'http://192.168.1.20:8080/api/kg/entities?q=Andrei&limit=25',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ 'X-User-Token': 'user-token' }),
      }),
    );
    expect(out).toEqual({
      entities: [
        { name: 'Andrei Popescu', type: 'person', properties: { city: 'Bucharest' } },
        { name: 'Jarvis Hub', type: 'project', properties: {} },
      ],
      total: 2,
    });
  });

  it('fetches one KG entity with relations', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        entity: { name: 'Andrei Popescu', type: 'person' },
        relations: [{ source: 'Andrei Popescu', relation: 'works_on', target: 'Jarvis Hub' }],
      }),
    );

    const out = await fetchKgEntity({ baseUrl: 'http://jarvis.lan', token: 'tok', adminToken: '' }, 'Andrei Popescu');

    expect(mockFetch).toHaveBeenCalledWith(
      'http://jarvis.lan/api/kg/entities/Andrei%20Popescu',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ 'X-User-Token': 'tok' }),
      }),
    );
    expect(out).toEqual({
      entity: { name: 'Andrei Popescu', type: 'person', properties: {} },
      relations: [{ source: 'Andrei Popescu', relation: 'works_on', target: 'Jarvis Hub', properties: {} }],
    });
  });

  it('fetches current facts and subject history', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        at: 123,
        facts: [{ id: 1, subject: 'Andrei', predicate: 'lives_in', object: 'Bucharest', valid_from: 100 }],
      }),
    );
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        subject: 'Andrei',
        history: [{ id: 1, subject: 'Andrei', predicate: 'lives_in', object: 'Bucharest', valid_from: 100 }],
      }),
    );

    const config = { baseUrl: 'hub.local', token: '', adminToken: '' };
    const facts = await fetchKgFacts(config, { subject: 'Andrei', predicate: 'lives_in' });
    const history = await fetchKgFactHistory(config, 'Andrei', 'lives_in');

    expect(mockFetch).toHaveBeenNthCalledWith(
      1,
      'http://hub.local/api/kg/facts/as-of?subject=Andrei&predicate=lives_in',
      expect.objectContaining({ method: 'GET' }),
    );
    expect(mockFetch).toHaveBeenNthCalledWith(
      2,
      'http://hub.local/api/kg/facts/history?subject=Andrei&predicate=lives_in',
      expect.objectContaining({ method: 'GET' }),
    );
    expect(facts.facts).toHaveLength(1);
    expect(history.history).toHaveLength(1);
  });

  it('normalizes sparse KG payloads', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ entities: 'bad' }));
    mockFetch.mockResolvedValueOnce(jsonResponse({ entity: null, relations: 'bad' }));
    mockFetch.mockResolvedValueOnce(jsonResponse({ facts: 'bad' }));
    mockFetch.mockResolvedValueOnce(jsonResponse({ subject: 42, history: 'bad' }));

    const config = { baseUrl: 'hub.local', token: '', adminToken: '' };

    await expect(fetchKgEntities(config)).resolves.toEqual({ entities: [], total: 0 });
    await expect(fetchKgEntity(config, 'x')).resolves.toEqual({ relations: [] });
    await expect(fetchKgFacts(config)).resolves.toEqual({ facts: [] });
    await expect(fetchKgFactHistory(config, 'x')).resolves.toEqual({ subject: '42', history: [] });
  });
});
