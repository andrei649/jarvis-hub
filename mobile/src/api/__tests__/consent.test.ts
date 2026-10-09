import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { ApiError, decideApprovalConsent, validatedConsentOffer } from '../client';

const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
const config = { baseUrl: 'http://jarvis.lan', token: 'usr', adminToken: 'adm' };
const revision = 'a'.repeat(64);

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

beforeEach(() => {
  mockFetch.mockReset();
  (globalThis as any).fetch = mockFetch;
});

describe('mobile consent API', () => {
  it('projects only a bounded consent offer from server data', () => {
    expect(validatedConsentOffer({
      revision, count: 2, choices: ['session', 'always', 'deny'],
      categories: [{ description: 'Read workspace files', permanent: true, key: 'private' }],
      private_owner_evidence: { token: 'secret' },
    })).toEqual({
      revision, count: 2, choices: ['session', 'always', 'deny'],
      categories: [{ description: 'Read workspace files', permanent: true }],
    });
  });

  it.each([
    { revision: 'A'.repeat(64), count: 1, choices: ['session', 'always', 'deny'], categories: [{ description: 'Read', permanent: true }] },
    { revision, count: 0, choices: ['session', 'always', 'deny'], categories: [{ description: 'Read', permanent: true }] },
    { revision, count: 65, choices: ['session', 'always', 'deny'], categories: [{ description: 'Read', permanent: true }] },
    { revision, count: 1, choices: ['session', 'session', 'deny'], categories: [{ description: 'Read', permanent: true }] },
    { revision, count: 1, choices: ['session', 'always', 'deny'], categories: [{ description: '', permanent: true }] },
    { revision, count: 1, choices: ['session', 'always', 'deny'], categories: [{ description: 'x'.repeat(1025), permanent: true }] },
    { revision, count: 1, choices: ['session', 'always', 'deny'], categories: [{ description: 'Read', permanent: 'yes' }] },
    { revision, count: 1, choices: ['session', 'always', 'deny'], categories: [] },
  ])('rejects malformed or unbounded offers %#', offer => {
    expect(validatedConsentOffer(offer)).toBeNull();
  });

  it('sends exact revision and optional reason with admin authentication', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true, tasks: [{ id: 42, status: 'approved' }] }));
    const out = await decideApprovalConsent(config, 42, 'always', revision, 'Remember this');
    expect(out.tasks).toEqual([{ id: 42, status: 'approved' }]);
    expect(mockFetch).toHaveBeenCalledWith('http://jarvis.lan/autonomy/tasks/42/consent',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'X-User-Token': 'usr', 'X-Admin-Token': 'adm' }),
        body: JSON.stringify({ choice: 'always', revision, reason: 'Remember this' }),
      }));
  });

  it('omits the optional reason from the request body', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true, tasks: [{ id: 7, status: 'rejected' }] }));
    await decideApprovalConsent(config, 7, 'deny', revision);
    expect(JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string)).toEqual({
      choice: 'deny', revision,
    });
  });

  it.each([
    [0, 'session', revision, undefined],
    [Number.MAX_SAFE_INTEGER + 1, 'session', revision, undefined],
    [7, 'grant', revision, undefined],
    [7, 'session', 'A'.repeat(64), undefined],
    [7, 'session', revision, 'x'.repeat(281)],
  ])('rejects invalid request input before fetch %#', async (id, choice, rev, reason) => {
    await expect(decideApprovalConsent(config, id as number, choice as any, rev as string, reason as string | undefined))
      .rejects.toBeInstanceOf(ApiError);
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('counts Unicode code points rather than UTF-16 units for the reason limit', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true, tasks: [{ id: 7, status: 'approved' }] }));
    await decideApprovalConsent(config, 7, 'session', revision, '😀'.repeat(280));
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it.each([
    { ok: false, tasks: [{ id: 7, status: 'approved' }] },
    { ok: true, tasks: [] },
    { ok: true, tasks: [{ id: 8, status: 'approved' }] },
    { ok: true, tasks: [{ id: '7', status: 'approved' }] },
    { ok: true, tasks: [{ id: 7 }] },
    { ok: true, tasks: Array.from({ length: 65 }, (_, i) => ({ id: i + 1, status: 'approved' })) },
    { ok: true, tasks: [{ id: 7, status: 'approved' }, { id: 7, status: 'approved' }] },
    { ok: true, tasks: [{ id: 7, status: 'running' }] },
    { ok: true, tasks: [{ id: 7, status: 'approved' }, { id: 8, status: 'rejected' }] },
  ])('refuses unconfirmed consent response %#', async body => {
    mockFetch.mockResolvedValueOnce(jsonResponse(body));
    await expect(decideApprovalConsent(config, 7, 'session', revision)).rejects.toBeInstanceOf(ApiError);
  });

  it('requires deny to return rejected tasks', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true, tasks: [{ id: 7, status: 'approved' }] }));
    await expect(decideApprovalConsent(config, 7, 'deny', revision)).rejects.toBeInstanceOf(ApiError);
  });

  it('accepts the queue maximum of 64 distinct approved members', async () => {
    const tasks = Array.from({ length: 64 }, (_, i) => ({ id: i + 1, status: 'approved' }));
    mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true, tasks }));
    await expect(decideApprovalConsent(config, 7, 'session', revision)).resolves.toEqual({ ok: true, tasks });
  });

  it('propagates stale HTTP 409 without retrying or fetching a replacement offer', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ error: 'offer changed' }, 409));
    await expect(decideApprovalConsent(config, 7, 'session', revision))
      .rejects.toMatchObject({ status: 409 });
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});
