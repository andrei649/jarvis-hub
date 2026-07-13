import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import {
  fetchCameraEvents,
  fetchCameraStatus,
  searchCameraEvents,
} from '../client';
import type { ServerConfig } from '../../storage/settings';

const config: ServerConfig = {
  baseUrl: 'http://hub.local',
  token: 'user-token',
  adminToken: '',
};

const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
(globalThis as any).fetch = mockFetch;

function jsonResponse(payload: unknown): Response {
  return { ok: true, status: 200, json: async () => payload } as Response;
}

beforeEach(() => {
  mockFetch.mockReset();
});

describe('mobile Camera Intelligence API', () => {
  it('normalizes bounded status and strips unknown transport detail', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({
      enabled: true,
      status: 'healthy',
      reason: null,
      source: { status: 'online', camera_count: 999, last_success_at: 100, last_error: 'source_offline', origin: 'http://private' },
      storage: { status: 'ready', items: 2, bytes: 300, last_sweep_at: 90, path: 'C:/private' },
    }));
    await expect(fetchCameraStatus(config)).resolves.toEqual({
      enabled: true,
      status: 'healthy',
      reason: '',
      source: { status: 'online', camera_count: 128, last_success_at: 100, last_error: 'source_offline' },
      storage: { status: 'ready', items: 2, bytes: 300, last_sweep_at: 90 },
    });
  });

  it('normalizes metadata events and never retains snapshot or private fields', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({
      enabled: true,
      status: 'ok',
      reason: null,
      interpretation: { label: 'person' },
      events: [{
        event_id: 'event-1',
        camera_id: 'front-door',
        label: 'person',
        occurred_at: 100,
        confidence: 1.4,
        anonymous: true,
        zone: 'porch',
        room_id: 'entry',
        description: 'An anonymous person left a package.',
        description_provenance: 'local_vlm_on_demand',
        snapshot_url: 'http://private/snapshot.jpg',
        vault_id: 'private-id',
      }],
    }));
    const result = await fetchCameraEvents(config);
    expect(result.events).toEqual([{
      event_id: 'event-1',
      camera_id: 'front-door',
      label: 'person',
      occurred_at: 100,
      confidence: 1,
      anonymous: true,
      zone: 'porch',
      room_id: 'entry',
      description: 'An anonymous person left a package.',
      description_provenance: 'local_vlm_on_demand',
    }]);
    expect(JSON.stringify(result)).not.toMatch(/snapshot|vault_id|private-id/);
  });

  it('posts the natural-language query in the body, never the URL', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({
      enabled: true,
      status: 'empty',
      reason: 'no_matches',
      interpretation: { label: 'person' },
      events: [],
    }));
    await searchCameraEvents(config, 'courier yesterday', 25);
    expect(mockFetch).toHaveBeenCalledWith(
      'http://hub.local/api/cameras/search',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'X-User-Token': 'user-token' }),
        body: JSON.stringify({ query: 'courier yesterday', limit: 25 }),
      }),
    );
    expect(mockFetch.mock.calls[0][0]).not.toContain('courier');
  });

  it('represents the default-off response honestly', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({
      enabled: false,
      status: 'disabled',
      reason: 'camera_disabled',
      source: null,
      storage: null,
    }));
    await expect(fetchCameraStatus(config)).resolves.toEqual({
      enabled: false,
      status: 'disabled',
      reason: 'camera_disabled',
      source: null,
      storage: null,
    });
  });
});
