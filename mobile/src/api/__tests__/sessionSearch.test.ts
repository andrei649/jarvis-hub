import { afterEach, beforeEach, expect, it, jest } from '@jest/globals';
import { searchSessionMessages } from '../client';

const config = { baseUrl: 'https://hub.test/', token: ' user ', adminToken: ' owner ' };
const hit = { session_id: 'root', turn: 3, role: 'assistant', timestamp: '2026-11-13T12:00:01Z',
  agent_id: 'frigga', snippet: '…Answer…' };
const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
const originalFetch = globalThis.fetch;
const response = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body }) as Response;
beforeEach(() => { mockFetch.mockReset(); globalThis.fetch = mockFetch; });
afterEach(() => { globalThis.fetch = originalFetch; });

it('searches as owner and returns only bounded known fields', async () => {
  mockFetch.mockResolvedValue(response({ hits: [{ ...hit, private: 'secret' }], truncated: false,
    stopped_by: null, token: 'secret' }));
  await expect(searchSessionMessages(config, '  Answer  ')).resolves.toEqual({ hits: [hit],
    truncated: false, stopped_by: null });
  expect(mockFetch).toHaveBeenCalledWith('https://hub.test/sessions/search', expect.objectContaining({
    method: 'POST', body: JSON.stringify({ query: 'Answer', limit: 20 }),
    headers: expect.objectContaining({ 'X-User-Token': 'user', 'X-Admin-Token': 'owner' }),
  }));
  expect(mockFetch).toHaveBeenCalledTimes(1);
});

it.each(['', ' ', 'a'.repeat(257), 'bad\0query'])('rejects invalid query before HTTP', async query => {
  await expect(searchSessionMessages(config, query)).rejects.toThrow('Invalid search query');
  expect(mockFetch).not.toHaveBeenCalled();
});

it.each([401, 403, 500])('uses short safe errors for HTTP %s without retry', async status => {
  mockFetch.mockResolvedValue(response({ error: 'private backend detail' }, status));
  await expect(searchSessionMessages(config, 'Answer')).rejects.toThrow(status < 500
    ? 'Owner sign-in required' : 'Could not search saved messages');
  expect(mockFetch).toHaveBeenCalledTimes(1);
});

it('explains the server keyword limit without echoing its response', async () => {
  mockFetch.mockResolvedValue(response({ error: 'bad_query' }, 400));
  await expect(searchSessionMessages(config, 'one two three four five six seven eight nine'))
    .rejects.toThrow('Search with one to eight terms.');
});

it.each([
  { hits: null, truncated: false, stopped_by: null },
  { hits: [hit], truncated: 'false', stopped_by: null },
  { hits: [hit], truncated: false, stopped_by: 'limit' },
  { hits: [{ ...hit, turn: -1 }], truncated: false, stopped_by: null },
  { hits: [{ ...hit, session_id: '../private' }], truncated: false, stopped_by: null },
  { hits: [{ ...hit, role: 'system' }], truncated: false, stopped_by: null },
  { hits: [{ ...hit, snippet: '😀'.repeat(243) }], truncated: false, stopped_by: null },
])('rejects malformed or oversized response %#', async body => {
  mockFetch.mockResolvedValue(response(body));
  await expect(searchSessionMessages(config, 'Answer')).rejects.toThrow('Invalid search response');
});
