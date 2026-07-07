import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { fetchTasks } from '../client';

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

describe('mobile tasks API', () => {
  it('fetches the read-only task board with user auth', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        tasks: [
          {
            id: 'task-1',
            owner: 'friday',
            label: 'Security scan',
            project: 'Security',
            state: 'running',
          },
        ],
      }),
    );

    const out = await fetchTasks({
      baseUrl: '192.168.1.20:8080/',
      token: 'user-token',
      adminToken: 'admin-token',
    });

    expect(mockFetch).toHaveBeenCalledWith(
      'http://192.168.1.20:8080/tasks',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({
          'X-User-Token': 'user-token',
        }),
      }),
    );
    expect(out.tasks[0].owner).toBe('friday');
    expect(out.tasks[0].state).toBe('running');
  });

  it('normalizes sparse task payloads to a stable array', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({}));

    const out = await fetchTasks({ baseUrl: 'hub.local', token: '', adminToken: '' });

    expect(out).toEqual({ tasks: [] });
  });
});
