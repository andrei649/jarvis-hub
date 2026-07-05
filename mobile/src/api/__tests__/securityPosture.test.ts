import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import {
  fetchSecurityGovernance,
  fetchSecurityKillSwitch,
  fetchSecurityLoopBreaker,
  fetchSecurityPosture,
} from '../client';

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

describe('mobile security posture API', () => {
  it('fetches governance scorecard with user auth', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        pass: true,
        overall_score: 0.98,
        threshold: 0.9,
        injection: { score: 1, passed: 6, n: 6 },
        harm: { score: 0.95, passed: 5, n: 6 },
        owasp: { score: 1, covered: 10, total: 10 },
      }),
    );

    const out = await fetchSecurityGovernance({
      baseUrl: '192.168.1.20:8080/',
      token: 'user-token',
      adminToken: 'admin-token',
    });

    expect(mockFetch).toHaveBeenCalledWith(
      'http://192.168.1.20:8080/api/security/governance',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ 'X-User-Token': 'user-token' }),
      }),
    );
    expect(out).toEqual({
      pass: true,
      overall_score: 0.98,
      threshold: 0.9,
      injection: { score: 1, passed: 6, n: 6 },
      harm: { score: 0.95, passed: 5, n: 6 },
      owasp: { score: 1, covered: 10, total: 10 },
    });
  });

  it('fetches packaged posture with admin auth', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        secrets: { encrypted_at_rest: true, backend: 'fernet' },
        skills: { require_signed: true, total: 3, trusted: 2, untrusted: 1, untrusted_names: ['demo'] },
        sandbox: { backend: 'docker', isolated: true, docker_available: true, insecure_host_exec: false },
        guardrails: { mode: 'BLOCK' },
      }),
    );

    const out = await fetchSecurityPosture({
      baseUrl: 'http://jarvis.lan',
      token: 'tok',
      adminToken: 'adm',
    });

    expect(mockFetch).toHaveBeenCalledWith(
      'http://jarvis.lan/api/security/posture',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({ 'X-Admin-Token': 'adm' }),
      }),
    );
    expect(out.skills.untrusted_names).toEqual(['demo']);
    expect(out.sandbox.isolated).toBe(true);
    expect(out.guardrails.mode).toBe('BLOCK');
  });

  it('fetches kill-switch and loop-breaker status', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ global: true, halted: { global: { reason: 'owner' } } }));
    mockFetch.mockResolvedValueOnce(jsonResponse({ tripped: false, threshold: 4, window_seconds: 30 }));

    const config = { baseUrl: 'hub.local', token: '', adminToken: '' };
    const kill = await fetchSecurityKillSwitch(config);
    const loop = await fetchSecurityLoopBreaker(config);

    expect(mockFetch).toHaveBeenNthCalledWith(
      1,
      'http://hub.local/api/security/kill-switch',
      expect.objectContaining({ method: 'GET' }),
    );
    expect(mockFetch).toHaveBeenNthCalledWith(
      2,
      'http://hub.local/api/security/loop-breaker',
      expect.objectContaining({ method: 'GET' }),
    );
    expect(kill.global).toBe(true);
    expect(loop.tripped).toBe(false);
  });

  it('normalizes sparse security payloads', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ pass: 'yes', overall_score: 'bad' }));
    mockFetch.mockResolvedValueOnce(jsonResponse({ skills: 'bad', sandbox: null }));
    mockFetch.mockResolvedValueOnce(jsonResponse({ halted: 'bad' }));
    mockFetch.mockResolvedValueOnce(jsonResponse({ tripped: 'bad' }));

    const config = { baseUrl: 'hub.local', token: '', adminToken: '' };

    await expect(fetchSecurityGovernance(config)).resolves.toEqual({
      pass: false,
      overall_score: 0,
      threshold: 0,
      injection: { score: 0, passed: 0, n: 0 },
      harm: { score: 0, passed: 0, n: 0 },
      owasp: { score: 0, covered: 0, total: 0 },
    });
    await expect(fetchSecurityPosture(config)).resolves.toEqual({
      secrets: { encrypted_at_rest: false, backend: '' },
      skills: { require_signed: false, total: 0, trusted: 0, untrusted: 0, untrusted_names: [] },
      sandbox: { backend: '', isolated: false, docker_available: false, insecure_host_exec: false },
      guardrails: { mode: '' },
    });
    await expect(fetchSecurityKillSwitch(config)).resolves.toEqual({ global: false, halted: {} });
    await expect(fetchSecurityLoopBreaker(config)).resolves.toEqual({ tripped: false });
  });
});
