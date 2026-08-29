import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { fetchEstop } from '../client';

const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
const config = { baseUrl: 'hub.local', token: 'user-token', adminToken: 'admin-token' };

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response;
}

beforeEach(() => {
  mockFetch.mockReset();
  (globalThis as any).fetch = mockFetch;
});

describe('mobile emergency-stop API', () => {
  it('reads the engaged state with the user token only', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({
      engaged: true,
      state: { reason: 'drill', engaged_at: '2026-08-29T10:00:00+00:00' },
    }));

    await expect(fetchEstop(config)).resolves.toEqual({
      engaged: true,
      reason: 'drill',
      engaged_at: '2026-08-29T10:00:00+00:00',
    });
    expect(mockFetch).toHaveBeenCalledWith(
      'http://hub.local/api/ops/estop',
      expect.objectContaining({ method: 'GET', headers: expect.objectContaining({ 'X-User-Token': 'user-token' }) }),
    );
    // Read-only surface: engage/resume are admin-guarded and stay on the owner HUD.
    expect(mockFetch.mock.calls[0][1]?.headers).not.toHaveProperty('X-Admin-Token');
  });

  it('flattens the disengaged null state to empty metadata', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ engaged: false, state: null }));

    await expect(fetchEstop(config)).resolves.toEqual({ engaged: false, reason: '', engaged_at: '' });
  });

  it('stays honest on sparse or corrupt sentinels', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({}));
    // touch-created sentinel: engaged with no recorded metadata
    mockFetch.mockResolvedValueOnce(jsonResponse({ engaged: true, state: {} }));

    await expect(fetchEstop(config)).resolves.toEqual({ engaged: false, reason: '', engaged_at: '' });
    await expect(fetchEstop(config)).resolves.toEqual({ engaged: true, reason: '', engaged_at: '' });
  });
});
