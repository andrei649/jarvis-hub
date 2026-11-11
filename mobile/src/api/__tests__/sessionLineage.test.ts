import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { fetchSessions, resumeSession, resumeTarget } from '../client';

/* H440 — the hub lists one row per conversation (continuations are left out) and says
   which lineage member a resume opens; the resume list opens that member. */

const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
const config = { baseUrl: 'hub.local', token: 'user-token', adminToken: 'admin-token' };

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response;
}

beforeEach(() => {
  mockFetch.mockReset();
  (globalThis as any).fetch = mockFetch;
});

describe('mobile session lineage', () => {
  it('resumes the newest member of a lineage, else the row itself', () => {
    expect(resumeTarget({ id: 'root', resume_id: 'cont-3', continuations: 2 })).toBe('cont-3');
    expect(resumeTarget({ id: 'solo', resume_id: 'solo', continuations: 0 })).toBe('solo');
    expect(resumeTarget({ id: 'old-hub' })).toBe('old-hub');
    expect(resumeTarget({ id: 'blank', resume_id: '' })).toBe('blank');
  });

  it('keeps the lineage fields of a listed row and posts the resume target', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({
      sessions: [{ id: 'root', title: 'Trip plan', resume_id: 'cont-3', continuations: 2 }],
    }));
    const [row] = await fetchSessions(config);
    expect(row).toMatchObject({ id: 'root', title: 'Trip plan', resume_id: 'cont-3', continuations: 2 });

    mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true, session: 'cont-3', turns: [] }));
    await expect(resumeSession(config, resumeTarget(row))).resolves.toMatchObject({ session: 'cont-3' });
    const [, init] = mockFetch.mock.calls[1];
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({ session_id: 'cont-3' });
  });
});
