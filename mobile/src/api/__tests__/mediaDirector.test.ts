import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import {
  fetchMediaDevices,
  fetchMediaSessions,
  presentMedia,
  registerMediaDevice,
  removeMediaDevice,
  restoreMedia,
} from '../client';

const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
const config = { baseUrl: 'hub.local', token: 'user-token', adminToken: 'admin-token' };

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

describe('mobile Media Director API', () => {
  it('normalizes device and session reads without trusting malformed server values', async () => {
    mockFetch
      .mockResolvedValueOnce(
        jsonResponse({
          enabled: true,
          devices: [
            { id: 'tv-1', name: 'Living TV', kind: 'tv', room: 'living', supports: ['play', 7, 'show'] },
            { id: 9, name: null, supports: 'play' },
            { id: 'x'.repeat(65), name: 'Oversized id', kind: 'tv', supports: ['play'] },
          ],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          enabled: true,
          sessions: [
            {
              device_id: 'tv-1',
              content: { type: 'catalog', value: 'media-7' },
              mode: 'play',
              privacy: 'household',
              state: 'playing',
              started_at: 12.5,
              duration_seconds: 30,
              previous: { secret: 'must not reach the UI' },
            },
            { device_id: 'x'.repeat(65), content: { type: 'url', value: 'https://invalid.test' } },
            null,
          ],
        }),
      );

    const devices = await fetchMediaDevices(config);
    const sessions = await fetchMediaSessions(config);

    expect(devices).toEqual({
      enabled: true,
      hint: '',
      devices: [
        { id: 'tv-1', name: 'Living TV', kind: 'tv', room: 'living', supports: ['play', 'show'] },
      ],
    });
    expect(sessions).toEqual({
      enabled: true,
      hint: '',
      sessions: [
        {
          device_id: 'tv-1',
          content: { type: 'catalog', value: 'media-7' },
          mode: 'play',
          privacy: 'household',
          state: 'playing',
          started_at: 12.5,
          duration_seconds: 30,
        },
      ],
    });
  });

  it('keeps the default-off state explicit and stable', async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResponse({ enabled: false, hint: 'owner opt-in required', devices: 'bad' }))
      .mockResolvedValueOnce(jsonResponse({ enabled: false, hint: 'owner opt-in required' }));

    await expect(fetchMediaDevices(config)).resolves.toEqual({
      enabled: false,
      hint: 'owner opt-in required',
      devices: [],
    });
    await expect(fetchMediaSessions(config)).resolves.toEqual({
      enabled: false,
      hint: 'owner opt-in required',
      sessions: [],
    });
  });

  it('bounds server-controlled labels and content references before rendering', async () => {
    mockFetch
      .mockResolvedValueOnce(
        jsonResponse({
          enabled: true,
          hint: 'h'.repeat(1000),
          devices: [{ id: 'tv-1', name: 'n'.repeat(500), kind: 'k'.repeat(100), room: 'r'.repeat(200), supports: Array(30).fill('play') }],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          enabled: true,
          sessions: [{ device_id: 'tv-1', content: { type: 'url', value: 'v'.repeat(5000) } }],
        }),
      );

    const devices = await fetchMediaDevices(config);
    const sessions = await fetchMediaSessions(config);

    expect(devices.hint).toHaveLength(240);
    expect(devices.devices[0]).toMatchObject({
      id: 'tv-1',
      name: 'n'.repeat(120),
      kind: 'k'.repeat(32),
      room: 'r'.repeat(64),
    });
    expect(devices.devices[0].supports).toEqual(['play']);
    expect(sessions.sessions[0].device_id).toBe('tv-1');
    expect(sessions.sessions[0].content.value).toHaveLength(2048);
  });

  it('classifies disabled, queued, refused, unverified, and verified outcomes honestly', async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResponse({ enabled: false, hint: 'feature off' }))
      .mockResolvedValueOnce(jsonResponse({ enabled: true, status: 'queued', reason: 'approval_required' }))
      .mockResolvedValueOnce(
        jsonResponse({ enabled: true, status: 'completed', output: { ok: false, reason: 'no driver' } }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ enabled: true, status: 'completed', output: { ok: true, device_id: 'tv-1' } }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          enabled: true,
          status: 'completed',
          output: { ok: true, verified: true, device_id: 'tv-1', state: 'playing' },
        }),
      );

    const body = {
      content: { type: 'catalog' as const, value: 'media-7' },
      target: 'tv-1',
      mode: 'play' as const,
      privacy: 'household' as const,
      urgency: 'normal' as const,
    };
    await expect(presentMedia(config, body)).resolves.toMatchObject({ kind: 'disabled', reason: 'feature off' });
    await expect(presentMedia(config, body)).resolves.toMatchObject({ kind: 'queued', reason: 'approval_required' });
    await expect(presentMedia(config, body)).resolves.toMatchObject({ kind: 'refused', reason: 'no driver' });
    await expect(presentMedia(config, body)).resolves.toMatchObject({ kind: 'unverified', deviceId: 'tv-1' });
    await expect(presentMedia(config, body)).resolves.toEqual({
      kind: 'verified',
      status: 'completed',
      reason: '',
      deviceId: 'tv-1',
      state: 'playing',
    });
  });

  it('never promotes a malformed action envelope to verified success', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ status: 'completed', output: { ok: true, verified: true, device_id: 'tv-1' } }),
    );

    const result = await restoreMedia(config, 'tv-1');

    expect(result).toMatchObject({ kind: 'unknown', reason: 'invalid_media_response' });
  });

  it('uses explicit user routes for present and restore', async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResponse({ enabled: true, status: 'refused', reason: 'kernel_halted' }))
      .mockResolvedValueOnce(jsonResponse({ enabled: true, status: 'completed', output: { ok: true } }));

    await presentMedia(config, {
      content: { type: 'query', value: 'evening briefing' },
      target: 'speaker-1',
      mode: 'announce',
      privacy: 'private',
      urgency: 'high',
      duration_seconds: 45,
    });
    await restoreMedia(config, 'speaker/1');

    expect(mockFetch).toHaveBeenNthCalledWith(
      1,
      'http://hub.local/api/media/present',
      expect.objectContaining({ method: 'POST', body: expect.stringContaining('evening briefing') }),
    );
    expect(mockFetch).toHaveBeenNthCalledWith(
      2,
      'http://hub.local/api/media/restore/speaker%2F1',
      expect.objectContaining({ method: 'POST' }),
    );
    for (const [, init] of mockFetch.mock.calls) {
      expect(init?.headers).toEqual(expect.objectContaining({ 'X-User-Token': 'user-token' }));
      expect(init?.headers).not.toHaveProperty('X-Admin-Token');
    }
  });

  it('sends the admin token only for registry mutations', async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResponse({ enabled: true, device: { id: 'tv-1', name: 'TV', kind: 'tv' } }))
      .mockResolvedValueOnce(jsonResponse({ enabled: true, removed: 'tv-1' }));

    await registerMediaDevice(config, {
      id: 'tv-1',
      name: 'TV',
      kind: 'tv',
      room: 'living',
      supports: ['play'],
    });
    await removeMediaDevice(config, 'tv-1');

    for (const [, init] of mockFetch.mock.calls) {
      expect(init?.headers).toEqual(
        expect.objectContaining({ 'X-User-Token': 'user-token', 'X-Admin-Token': 'admin-token' }),
      );
    }
  });
});
