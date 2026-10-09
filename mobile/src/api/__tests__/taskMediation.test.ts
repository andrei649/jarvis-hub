import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { ApiError, fetchTaskMediationStatus } from '../client';

const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
const COUNTS = {
  authorized_enqueue: 2,
  governed: 3,
  refused_unmediated: 4,
  ungoverned_detected: 5,
};
const ADMIN_ONLY = { baseUrl: '  hub.local/  ', token: ' ', adminToken: '  adm  ' };

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

describe('native task mediation status API', () => {
  it('sends one admin-only GET with no body, the existing deadline and no retries', async () => {
    const timer = jest.spyOn(globalThis, 'setTimeout');
    try {
      mockFetch.mockResolvedValueOnce(jsonResponse({ mode: 'off', valid: true, stats: COUNTS }));
      const status = await fetchTaskMediationStatus(ADMIN_ONLY);
      expect(status).toEqual({ mode: 'off', valid: true, stats: COUNTS });
      expect(mockFetch).toHaveBeenCalledTimes(1);
      const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toBe('http://hub.local/autonomy/mediation');
      expect(init.method).toBe('GET');
      expect(init.body).toBeUndefined();
      expect(init.headers).toEqual({ Accept: 'application/json', 'X-Admin-Token': 'adm' });
      expect(init.signal).toBeDefined();
      expect(timer).toHaveBeenCalledWith(expect.any(Function), 15000);
    } finally {
      timer.mockRestore();
    }
  });

  it('sends both trimmed configured credentials without adding response fields', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({
      mode: 'hold', valid: true, stats: { ...COUNTS, private_marker: 'secret' },
      raw_events: ['secret'],
    }));
    const status = await fetchTaskMediationStatus({
      baseUrl: 'https://hub.local/', token: '  usr ', adminToken: ' adm ',
    });
    expect(status).toEqual({ mode: 'hold', valid: true, stats: COUNTS });
    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(init.headers).toEqual({
      Accept: 'application/json', 'X-User-Token': 'usr', 'X-Admin-Token': 'adm',
    });
  });

  it('accepts enforce with complete zero counts and invalid evidence only with null stats', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({
      mode: 'enforce', valid: true, stats: {
        authorized_enqueue: 0, governed: 0, refused_unmediated: 0, ungoverned_detected: 0,
      },
    }));
    mockFetch.mockResolvedValueOnce(jsonResponse({
      mode: 'enforce', valid: false, stats: null, internal_placeholder: COUNTS,
    }));
    await expect(fetchTaskMediationStatus(ADMIN_ONLY)).resolves.toEqual({
      mode: 'enforce', valid: true, stats: {
        authorized_enqueue: 0, governed: 0, refused_unmediated: 0, ungoverned_detected: 0,
      },
    });
    await expect(fetchTaskMediationStatus(ADMIN_ONLY)).resolves.toEqual({
      mode: 'enforce', valid: false, stats: null,
    });
  });

  it.each([
    null,
    [],
    { mode: 'unknown', valid: true, stats: COUNTS },
    { mode: 'off', valid: 'true', stats: COUNTS },
    { mode: 'off', valid: false, stats: COUNTS },
    { mode: 'off', valid: false },
    { mode: 'off', valid: true, stats: null },
    { mode: 'off', valid: true, stats: { ...COUNTS, governed: true } },
    { mode: 'off', valid: true, stats: { ...COUNTS, governed: '3' } },
    { mode: 'off', valid: true, stats: { ...COUNTS, governed: -1 } },
    { mode: 'off', valid: true, stats: { ...COUNTS, governed: 1.5 } },
    { mode: 'off', valid: true, stats: { ...COUNTS, governed: Number.MAX_SAFE_INTEGER + 1 } },
    { mode: 'off', valid: true, stats: { authorized_enqueue: 2, governed: 3, refused_unmediated: 4 } },
  ])('rejects malformed or incomplete evidence instead of inventing counts', async (body) => {
    mockFetch.mockResolvedValueOnce(jsonResponse(body));
    await expect(fetchTaskMediationStatus(ADMIN_ONLY)).rejects.toThrow('Invalid task mediation status');
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('rejects a missing admin credential locally without dispatch', async () => {
    await expect(fetchTaskMediationStatus({
      baseUrl: 'hub.local', token: 'user', adminToken: ' ',
    })).rejects.toThrow('Admin token required');
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it.each([401, 403, 503])('propagates HTTP %i without retry', async (code) => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ error: 'server-private' }, code));
    await expect(fetchTaskMediationStatus(ADMIN_ONLY)).rejects.toMatchObject({
      status: code,
    } satisfies Partial<ApiError>);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('propagates a network failure without retry', async () => {
    mockFetch.mockRejectedValueOnce(new Error('network-private'));
    await expect(fetchTaskMediationStatus(ADMIN_ONLY)).rejects.toBeInstanceOf(ApiError);
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});
