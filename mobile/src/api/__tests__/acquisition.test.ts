import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { fetchAcquisitionEvents, fetchAcquisitionStatus } from '../client';
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

describe('mobile governed acquisition API', () => {
  it('normalizes bounded status and strips package paths and request detail', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({
      enabled: true,
      status: 'ready',
      reason: null,
      states: { missing: 2, installed: 1, injected: 999 },
      reuse: { reused: 1, generated: 1, blocked: 0, abandoned: 0, reuse_rate: 0.5 },
      packages: [{ name: 'acme_parser', version: '0.1.0', status: 'active', confidence: 9, path: 'C:/private/main.py', manifest: { goal: 'private goal' } }],
      audit: { status: 'healthy', events: 3, summarized_events: 2, chain_valid: true, cipher_path: 'C:/private' },
      requests: [{ goal: 'private goal' }],
    }));

    const result = await fetchAcquisitionStatus(config);
    expect(result).toEqual({
      enabled: true,
      status: 'ready',
      reason: '',
      states: { missing: 2, installed: 1 },
      reuse: { reused: 1, generated: 1, blocked: 0, abandoned: 0, reuse_rate: 0.5 },
      packages: [{ name: 'acme_parser', version: '0.1.0', status: 'active', confidence: 1 }],
      audit: { status: 'healthy', events: 3, summarized_events: 2, chain_valid: true },
    });
    expect(JSON.stringify(result)).not.toMatch(/private|path|manifest|request/i);
  });

  it('keeps only bounded event metadata and does not retain hashes or raw details', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({
      enabled: true,
      status: 'ready',
      events: [{
        sequence: 7,
        event_type: 'install.committed',
        actor: 'acquired-package-store',
        status: 'installed',
        occurred_at: 100,
        request_hash: 'a'.repeat(64),
        artifact_hash: 'b'.repeat(64),
        detail_hash: 'c'.repeat(64),
        details: { source_url: 'https://private.example' },
      }],
    }));
    const result = await fetchAcquisitionEvents(config);
    expect(result.events).toEqual([{
      sequence: 7,
      event_type: 'install.committed',
      actor: 'acquired-package-store',
      status: 'installed',
      occurred_at: 100,
    }]);
    expect(JSON.stringify(result)).not.toMatch(/hash|private|details|source_url/);
  });

  it('uses only the user token and represents default-off state honestly', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({
      enabled: false,
      status: 'disabled',
      reason: 'acquisition_disabled',
      states: {},
      reuse: {},
      packages: [],
      audit: { status: 'disabled', events: 0, summarized_events: 0, chain_valid: true },
    }));
    const result = await fetchAcquisitionStatus(config);
    expect(result.enabled).toBe(false);
    expect(result.reason).toBe('acquisition_disabled');
    expect(mockFetch).toHaveBeenCalledWith(
      'http://hub.local/api/acquisition/status',
      expect.objectContaining({ headers: expect.objectContaining({ 'X-User-Token': 'user-token' }) }),
    );
    expect(JSON.stringify(mockFetch.mock.calls[0][1])).not.toContain('X-Admin-Token');
  });
});
