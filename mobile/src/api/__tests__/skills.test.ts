import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { fetchSkills } from '../client';

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

describe('mobile skills API', () => {
  it('fetches the read-only skills catalog with user auth', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        skills: {
          weather: {
            name: 'Weather',
            version: '1.2.0',
            description: 'Local weather lookup',
            agents: ['jarvis', 'friday'],
            commands: [{ name: 'weather.today' }],
          },
        },
      }),
    );

    const out = await fetchSkills({
      baseUrl: '192.168.1.20:8080/',
      token: 'user-token',
      adminToken: 'admin-token',
    });

    expect(mockFetch).toHaveBeenCalledWith(
      'http://192.168.1.20:8080/skills',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({
          'X-User-Token': 'user-token',
        }),
      }),
    );
    expect(out.skills).toEqual([
      {
        key: 'weather',
        name: 'Weather',
        version: '1.2.0',
        description: 'Local weather lookup',
        agents: ['jarvis', 'friday'],
        commands: [{ name: 'weather.today' }],
      },
    ]);
  });

  it('normalizes map payloads into a stable sorted array', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        skills: {
          zeta: { description: 'Last skill', agents: 'bad', commands: 'bad' },
          alpha: { name: 'Alpha', version: '0.1.0' },
        },
      }),
    );

    const out = await fetchSkills({ baseUrl: 'hub.local', token: '', adminToken: '' });

    expect(out.skills).toEqual([
      {
        key: 'alpha',
        name: 'Alpha',
        version: '0.1.0',
        description: '',
        agents: [],
        commands: [],
      },
      {
        key: 'zeta',
        name: 'zeta',
        version: '',
        description: 'Last skill',
        agents: [],
        commands: [],
      },
    ]);
  });

  it('normalizes sparse skills payloads to a stable array', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({}));

    const out = await fetchSkills({ baseUrl: 'hub.local', token: '', adminToken: '' });

    expect(out).toEqual({ skills: [] });
  });
});
