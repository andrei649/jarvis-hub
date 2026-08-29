import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { fetchHouseState } from '../client';

const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
const config = { baseUrl: 'hub.local', token: 'user-token', adminToken: 'admin-token' };

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response;
}

beforeEach(() => {
  mockFetch.mockReset();
  (globalThis as any).fetch = mockFetch;
});

describe('mobile House Brain API', () => {
  it('normalizes and bounds topology and pseudonymous presence', async () => {
    const privateId = `occ-${'a'.repeat(32)}`;
    const sharedId = `occ-${'b'.repeat(32)}`;
    mockFetch.mockResolvedValueOnce(jsonResponse({
      enabled: true,
      status: 'live',
      reason: 'r'.repeat(400),
      observed_at: 100,
      freshness_seconds: 2,
      rooms: [
        { room_id: 'kitchen', name: 'Kitchen', secret: 'drop' },
        { room_id: 7, name: 'bad' },
        ...Array.from({ length: 600 }, (_, index) => ({ room_id: `room-${index}`, name: `Room ${index}` })),
      ],
      devices: [
        { entity_id: 'light.kitchen', domain: 'light', state: 'on', room_id: 'kitchen', attributes: { secret: true } },
        { entity_id: 'x'.repeat(129), domain: 'light', state: 'on' },
      ],
      presence: [
        { occupant_id: privateId, status: 'present', room_id: 'bedroom', privacy: 'private', confidence: 0.9, fresh: true },
        { occupant_id: sharedId, status: 'present', room_id: 'kitchen', privacy: 'household', confidence: 0.8, fresh: true },
        { occupant_id: 'Alice Example', status: 'present', room_id: 'office' },
      ],
      presence_status: 'live',
      privacy_status: 'live',
    }));

    const result = await fetchHouseState(config);

    expect(result.enabled).toBe(true);
    expect(result.status).toBe('live');
    expect(result.presence_status).toBe('live');
    expect(result.reason).toHaveLength(256);
    expect(result.rooms).toHaveLength(500);
    expect(result.rooms[0]).toEqual({ room_id: 'kitchen', name: 'Kitchen' });
    expect(result.devices).toEqual([
      { entity_id: 'light.kitchen', domain: 'light', state: 'on', room_id: 'kitchen' },
    ]);
    expect(result.presence).toEqual([
      { occupant_id: privateId, status: 'present', privacy: 'private', confidence: 0.9, fresh: true },
      { occupant_id: sharedId, status: 'present', room_id: 'kitchen', privacy: 'household', confidence: 0.8, fresh: true },
    ]);
  });

  it('keeps disabled and degraded states explicit and uses only the user token', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ enabled: false, status: 'disabled', reason: 'house_brain_disabled' }));

    await expect(fetchHouseState(config)).resolves.toEqual({
      enabled: false,
      status: 'disabled',
      reason: 'house_brain_disabled',
      observed_at: 0,
      freshness_seconds: null,
      rooms: [],
      devices: [],
      presence: [],
      privacy_status: 'unavailable',
    });
    expect(mockFetch).toHaveBeenCalledWith(
      'http://hub.local/api/house/state',
      expect.objectContaining({ method: 'GET', headers: expect.objectContaining({ 'X-User-Token': 'user-token' }) }),
    );
    expect(mockFetch.mock.calls[0][1]?.headers).not.toHaveProperty('X-Admin-Token');
  });

  it('keeps presence_status honest: valid values pass, unknown values stay absent', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ enabled: true, status: 'live', presence_status: 'off' }));
    mockFetch.mockResolvedValueOnce(jsonResponse({ enabled: true, status: 'live', presence_status: 'bogus' }));

    const withStatus = await fetchHouseState(config);
    expect(withStatus.presence_status).toBe('off');

    const withBogus = await fetchHouseState(config);
    expect(withBogus).not.toHaveProperty('presence_status');
  });
});
