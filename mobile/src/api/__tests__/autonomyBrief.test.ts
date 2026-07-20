import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { fetchAutonomyBrief } from '../client';

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

const CONFIG = { baseUrl: '192.168.1.20:8080/', token: 'user-token', adminToken: 'admin-token' };

describe('mobile morning brief API (spoken-brief parity)', () => {
  it('GETs /autonomy/brief with user AND admin auth', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ kind: 'morning', text: 'Raiffeisen review at 14:00.' }),
    );

    const out = await fetchAutonomyBrief(CONFIG);

    expect(out).toEqual({ kind: 'morning', text: 'Raiffeisen review at 14:00.' });
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://192.168.1.20:8080/autonomy/brief?kind=morning');
    const headers = init.headers as Record<string, string>;
    expect(headers['X-User-Token']).toBe('user-token');
    expect(headers['X-Admin-Token']).toBe('admin-token');
  });

  it('supports the evening retro kind', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ kind: 'evening', text: 'Done: 3 tasks.' }));
    const out = await fetchAutonomyBrief(CONFIG, 'evening');
    expect(out.kind).toBe('evening');
    expect(String(mockFetch.mock.calls[0][0])).toContain('kind=evening');
  });

  it('normalizes a malformed body to an honest empty brief', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ text: 42 }));
    const out = await fetchAutonomyBrief(CONFIG);
    expect(out).toEqual({ kind: 'morning', text: '' });
  });
});
