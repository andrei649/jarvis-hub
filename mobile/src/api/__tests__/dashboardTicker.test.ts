import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { fetchDashboard, fetchTicker } from '../client';

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

describe('mobile dashboard and ticker API', () => {
  it('fetches dashboard ambient data with user auth', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        weather: {
          city: 'Bucuresti',
          temp: '24',
          desc: 'clear',
          wind: '7 km/h',
          humidity: '40%',
          feels: '25',
          updated: 'now',
          forecast: [{ d: 'Mon', t: '26' }],
        },
        calendar: [{ title: 'standup' }],
        notifications: [{ text: 'backup complete' }],
      }),
    );

    const out = await fetchDashboard({
      baseUrl: '192.168.1.20:8080/',
      token: 'user-token',
      adminToken: 'admin-token',
    });

    expect(mockFetch).toHaveBeenCalledWith(
      'http://192.168.1.20:8080/dashboard',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({
          'X-User-Token': 'user-token',
        }),
      }),
    );
    expect(out.weather?.city).toBe('Bucuresti');
    expect(out.weather?.forecast).toEqual([{ d: 'Mon', t: '26' }]);
    expect(out.calendar).toHaveLength(1);
    expect(out.notifications).toHaveLength(1);
  });

  it('normalizes sparse dashboard payloads to stable arrays', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ weather: { city: 'Bucuresti', forecast: 'bad' } }));

    const out = await fetchDashboard({ baseUrl: 'hub.local', token: '', adminToken: '' });

    expect(out.calendar).toEqual([]);
    expect(out.notifications).toEqual([]);
    expect(out.weather?.forecast).toEqual([]);
  });

  it('fetches ticker rows and normalizes display fields', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        ticker: [
          { agent: 'steve', verb: 'WARNING', obj: 'GPU hot', pct: 87, pri: 'high' },
          { agent: 'pepper', verb: 'monitoring', text: 'calendar', bar: 42, cls: 'mid' },
        ],
      }),
    );

    const out = await fetchTicker({ baseUrl: 'http://jarvis.lan', token: 'tok', adminToken: 'adm' });

    expect(mockFetch).toHaveBeenCalledWith(
      'http://jarvis.lan/ticker',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ 'X-User-Token': 'tok' }),
      }),
    );
    expect(out.ticker).toEqual([
      { agent: 'steve', verb: 'WARNING', obj: 'GPU hot', text: 'GPU hot', pct: 87, pri: 'high', bar: 87, cls: 'high' },
      {
        agent: 'pepper',
        verb: 'monitoring',
        text: 'calendar',
        bar: 42,
        cls: 'mid',
      },
    ]);
  });

  it('normalizes sparse ticker payloads to a stable array', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({}));

    const out = await fetchTicker({ baseUrl: 'hub.local', token: '', adminToken: '' });

    expect(out).toEqual({ ticker: [] });
  });
});
