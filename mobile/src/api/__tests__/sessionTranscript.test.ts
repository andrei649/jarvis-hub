import { afterEach, beforeEach, expect, it, jest } from '@jest/globals';
import * as client from '../client';
const config = { baseUrl: 'https://hub.test/', token: ' user ', adminToken: ' owner ' };
const transcript = () => ({ schema_version: 1, session_id: 'root', scope: 'retained_current_history', redacted: true, turn_count: 2,
  turns: [{ role: 'user', content: 'Question', agent_id: null, timestamp: '2026-11-13T12:00:00Z' },
    { role: 'assistant', content: 'Answer', agent_id: 'frigga', timestamp: '2026-11-13T12:00:01Z' }] });
const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
const originalFetch = globalThis.fetch;
const response = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body }) as Response;
beforeEach(() => { mockFetch.mockReset(); globalThis.fetch = mockFetch; });
afterEach(() => { globalThis.fetch = originalFetch; });
it('exposes explicit owner-authorized transcript fetch without resuming a session', async () => {
  expect(client).toHaveProperty('fetchSessionTranscript');
  mockFetch.mockResolvedValue(response(transcript()));
  await expect(client.fetchSessionTranscript(config, 'root')).resolves.toEqual(transcript());
  expect(mockFetch).toHaveBeenCalledTimes(1);
  expect(mockFetch).toHaveBeenCalledWith('https://hub.test/sessions/root/transcript', expect.objectContaining({ method: 'GET', headers: expect.objectContaining({ 'X-User-Token': 'user', 'X-Admin-Token': 'owner' }) }));
});
it.each([401, 403, 404, 405, 500])('does not retry, fallback or resume for transcript HTTP %s', async status => {
  mockFetch.mockResolvedValue(response({}, status));
  await expect(client.fetchSessionTranscript(config, 'root')).rejects.toThrow();
  expect(mockFetch).toHaveBeenCalledTimes(1);
  expect(String(mockFetch.mock.calls[0][0])).toContain('/root/transcript');
});
it('does not retry transport failures', async () => {
  mockFetch.mockRejectedValue(new Error('offline'));
  await expect(client.fetchSessionTranscript(config, 'root')).rejects.toThrow(); expect(mockFetch).toHaveBeenCalledTimes(1);
});
it.each(['', '../private', 'safe\n', 'a'.repeat(129)])('rejects invalid requested session %j before HTTP', async id => {
  await expect(client.fetchSessionTranscript(config, id)).rejects.toThrow(); expect(mockFetch).not.toHaveBeenCalled();
});
it.each([
  { schema_version: 2 }, { schema_version: '1' }, { session_id: 'other' }, { scope: 'all_history' }, { redacted: false },
  { turn_count: 1 }, { turn_count: 2.5 }, { turns: null },
])('rejects malformed envelope %#', async patch => {
  mockFetch.mockResolvedValue(response({ ...transcript(), ...patch }));
  await expect(client.fetchSessionTranscript(config, 'root')).rejects.toThrow();
});
it.each([
  { role: 'system' }, { role: 'tool' }, { content: {} }, { agent_id: 3 }, { timestamp: null },
  { timestamp: undefined }, { content: undefined }, { agent_id: undefined },
])('rejects malformed turns %#', async patch => {
  const body = transcript(); Object.assign(body.turns[0], patch); mockFetch.mockResolvedValue(response(body));
  await expect(client.fetchSessionTranscript(config, 'root')).rejects.toThrow();
});
it('projects a field whitelist before any export can serialize the document', async () => {
  const body = transcript();
  Object.assign(body, { token: 'private-owner-token', metadata: { secret: 'private' } });
  Object.assign(body.turns[0], { tool_calls: ['private'], internal: 'private' });
  mockFetch.mockResolvedValue(response(body));
  const projected = await client.fetchSessionTranscript(config, 'root');
  expect(projected).toEqual(transcript()); expect(JSON.stringify(projected)).not.toContain('private');
});
it('accepts empty history and the maximum turn count', async () => {
  for (const count of [0, 100]) {
    const body = { ...transcript(), turn_count: count, turns: Array.from({ length: count }, () => transcript().turns[0]) };
    mockFetch.mockResolvedValueOnce(response(body)); await expect(client.fetchSessionTranscript(config, 'root')).resolves.toEqual(body);
  }
});
it('rejects 101 turns and oversized UTF8 content', async () => {
  mockFetch.mockResolvedValueOnce(response({ ...transcript(), turn_count: 101, turns: Array.from({ length: 101 }, () => transcript().turns[0]) }));
  await expect(client.fetchSessionTranscript(config, 'root')).rejects.toThrow();
  const body = transcript(); body.turns[0].content = '😀'.repeat(550000);
  mockFetch.mockResolvedValueOnce(response(body)); await expect(client.fetchSessionTranscript(config, 'root')).rejects.toThrow();
});
it('enforces the exact compact JSON UTF8 limit at 2 MiB', async () => {
  const body = transcript(); body.turns[0].content = '';
  const overhead = JSON.stringify(body).length;
  body.turns[0].content = 'a'.repeat(2 * 1024 * 1024 - overhead);
  mockFetch.mockResolvedValueOnce(response(body)); await expect(client.fetchSessionTranscript(config, 'root')).resolves.toEqual(body);
  body.turns[0].content += 'a'; mockFetch.mockResolvedValueOnce(response(body));
  await expect(client.fetchSessionTranscript(config, 'root')).rejects.toThrow();
});
