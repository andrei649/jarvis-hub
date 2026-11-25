/* The decision client (PHASE_B_PLAN.md §5.4, §9.4 E4): exact POST bodies for accept, reject,
   defer, edit, a group reject and a consent answer; the reason; the hub's own refusal words;
   nothing posted in demo; the feed read again after every decision. `fetch` is mocked, so the
   real client (headers, admin token, refusal bodies) runs. The source scan that only this module
   posts to /autonomy/tasks/ is decisions-source.test.ts. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { refreshPolled, resetPolling } from '../signals/poll';
import { DOCKET_FEED_PATH } from '../docket/types';
import { REASON_MAX, decide, decideConsent, hubWords, listBlocked, preview, rejectEach, rejectGroup } from './decisions';

type Answer = { status?: number; body?: unknown };
let answers: (url: string, init?: RequestInit) => Answer;
let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  resetPolling();
  try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'owner-token'); } catch { /* ignore */ }
  history.replaceState(null, '', '/v2/cockpit');
  answers = () => ({ body: { ok: true } });
  fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const { status = 200, body = {} } = answers(url, init);
    return { ok: status >= 200 && status < 300, status, json: async () => body } as unknown as Response;
  });
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { resetPolling(); vi.unstubAllGlobals(); history.replaceState(null, '', '/'); });

const calls = () => fetchMock.mock.calls.map(([url, init]) => ({
  url: String(url), method: init?.method ?? 'GET', body: init?.body === undefined ? undefined : JSON.parse(String(init.body)),
  headers: (init?.headers ?? {}) as Record<string, string>,
}));
const postsOnly = () => calls().filter((c) => c.method === 'POST');
/** The docket (or the masthead's count) reads the feed through the shared poller; then a decision
 *  reads it again. The calls are cleared, so a test sees only what the decision does. */
async function feedIsRead() {
  await refreshPolled(DOCKET_FEED_PATH, { admin: true });
  fetchMock.mockClear();
}

describe('decide', () => {
  it.each([
    ['accept', {}, { action: 'accept' }],
    ['reject', {}, { action: 'reject' }],
    ['defer', {}, { action: 'defer' }],
    ['reject', { reason: '  Use the staging address  ' }, { action: 'reject', reason: 'Use the staging address' }],
    ['accept', { reason: '   ' }, { action: 'accept' }],
    ['edit', { payload: { amount: 50 } }, { action: 'edit', payload: { amount: 50 } }],
    ['edit', { payload: { amount: 50 }, reason: 'smaller' }, { action: 'edit', payload: { amount: 50 }, reason: 'smaller' }],
  ] as const)('%s %j posts exactly %j, with the owner credential', async (action, opts, body) => {
    const outcome = await decide(7, action, opts as never);
    expect(outcome).toMatchObject({ ok: true, status: null, reason: null });
    const [post] = postsOnly();
    expect(post.url).toBe('/autonomy/tasks/7/decision');
    expect(JSON.stringify(post.body)).toBe(JSON.stringify(body));      // keys in this order, nothing else
    expect(post.headers['X-Admin-Token']).toBe('owner-token');
  });

  it('reads the decisions feed again after the decision, and resolves only once that answer landed', async () => {
    let posted = false;
    let feedReads = 0;
    answers = (url, init) => {
      if (init?.method === 'POST') { posted = true; return { body: { ok: true } }; }
      if (url === DOCKET_FEED_PATH && posted) feedReads += 1;
      return { body: { tasks: [] } };
    };
    await feedIsRead();
    await decide(9, 'accept');
    expect(feedReads).toBe(1);
    expect(calls().map((c) => `${c.method} ${c.url}`)).toEqual(['POST /autonomy/tasks/9/decision', `GET ${DOCKET_FEED_PATH}`]);
  });

  it('reads nothing more when nobody reads the feed (the classic frame: the inbox reloads its own list)', async () => {
    await decide(9, 'reject');
    await rejectGroup({ id: 'g', leader_id: 1, member_ids: [1, 2], count: 2, snapshot: 's'.repeat(32) });
    await rejectEach([3, 4]);
    expect(calls().map((c) => c.method)).toEqual(['POST', 'POST', 'POST', 'POST']);
  });

  it('returns the hub\'s own words for a refusal, and says nothing it was not told', async () => {
    answers = (_url, init) => (init?.method === 'POST' ? { status: 409, body: { error: 'decision could not be applied' } } : { body: { tasks: [] } });
    expect(await decide(9, 'accept')).toMatchObject({ ok: false, status: 409, reason: 'decision could not be applied' });
    answers = (_url, init) => (init?.method === 'POST' ? { status: 422, body: { detail: [{ msg: 'too long' }] } } : { body: { tasks: [] } });
    expect(await decide(9, 'accept')).toMatchObject({ ok: false, status: 422, reason: '[{"msg":"too long"}]' });
    answers = (_url, init) => (init?.method === 'POST' ? { status: 500, body: null } : { body: { tasks: [] } });
    expect(await decide(9, 'accept')).toMatchObject({ ok: false, status: 500, reason: null });
    fetchMock.mockImplementation(async () => { throw new TypeError('Failed to fetch'); });
    expect(await decide(9, 'accept')).toMatchObject({ ok: false, status: null, reason: null });
  });

  it('refuses, before posting anything, a call it cannot send as asked', async () => {
    await expect(decide(0, 'accept')).rejects.toThrow();
    await expect(decide(1.5, 'accept')).rejects.toThrow();
    await expect(decide(3, 'approve' as never)).rejects.toThrow();
    await expect(decide(3, 'edit')).rejects.toThrow();
    await expect(decide(3, 'edit', { payload: [1, 2] as never })).rejects.toThrow();
    await expect(decide(3, 'accept', { payload: { a: 1 } })).rejects.toThrow();
    await expect(decide(3, 'reject', { reason: 'x'.repeat(REASON_MAX + 1) })).rejects.toThrow();
    expect(fetchMock).not.toHaveBeenCalled();
    await decide(3, 'reject', { reason: 'x'.repeat(REASON_MAX) });
    expect(postsOnly()).toHaveLength(1);
  });

  it('posts nothing while the demo sample is on', async () => {
    history.replaceState(null, '', '/v2/cockpit?demo=1');
    expect(await decide(402, 'accept')).toMatchObject({ ok: false, demo: true });
    expect(await rejectGroup({ id: 'g', leader_id: 1, member_ids: [1, 2], count: 2, snapshot: 's'.repeat(32) })).toMatchObject({ ok: false, demo: true });
    expect(await decideConsent(3, { choice: 'deny', revision: 'a'.repeat(64) })).toMatchObject({ ok: false, demo: true });
    expect(await rejectEach([1, 2])).toMatchObject({ rejected: [], refused: [], demo: true });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('rejectGroup', () => {
  const group = { id: 'task group/1', leader_id: 41, member_ids: [41, 42], count: 2, snapshot: 'f'.repeat(32) };

  it('sends back the snapshot and members exactly as the feed sent them, with the reason', async () => {
    await rejectGroup(group, ' not now ');
    const [post] = postsOnly();
    expect(post.url).toBe('/autonomy/tasks/groups/task%20group%2F1/reject');
    expect(JSON.stringify(post.body)).toBe(JSON.stringify({ snapshot: 'f'.repeat(32), member_ids: [41, 42], reason: 'not now' }));
    await rejectGroup(group);
    expect(JSON.stringify(postsOnly()[1].body)).toBe(JSON.stringify({ snapshot: 'f'.repeat(32), member_ids: [41, 42] }));
  });

  it('says the hub\'s words when the group changed', async () => {
    answers = (_url, init) => (init?.method === 'POST' ? { status: 409, body: { error: 'approval group changed' } } : { body: { tasks: [] } });
    expect(await rejectGroup(group)).toMatchObject({ ok: false, status: 409, reason: 'approval group changed' });
  });

  it('refuses a group it could not send back', async () => {
    for (const bad of [{ ...group, id: '' }, { ...group, snapshot: '' }, { ...group, member_ids: [41] }, { ...group, member_ids: [41, 0] }]) {
      await expect(rejectGroup(bad)).rejects.toThrow();
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('decideConsent', () => {
  it('answers the exact offer revision', async () => {
    const revision = 'c'.repeat(64);
    await decideConsent(73, { choice: 'session', revision, reason: 'synthetic workspace' });
    const [post] = postsOnly();
    expect(post.url).toBe('/autonomy/tasks/73/consent');
    expect(JSON.stringify(post.body)).toBe(JSON.stringify({ choice: 'session', revision, reason: 'synthetic workspace' }));
    await expect(decideConsent(73, { choice: 'always', revision: 'stale' })).rejects.toThrow();
    await expect(decideConsent(73, { choice: 'forever' as never, revision })).rejects.toThrow();
  });
});

describe('rejectEach', () => {
  it('rejects every request in turn, reports each refusal, and reads the feed once at the end', async () => {
    answers = (url, init) => {
      if (init?.method !== 'POST') return { body: { tasks: [] } };
      if (url.includes('/12/')) return { status: 409, body: { error: 'task is not waiting' } };
      if (url.includes('/14/')) return { status: 403, body: {} };
      return { body: { ok: true } };
    };
    await feedIsRead();
    const outcome = await rejectEach([11, 12, 13, 14], { reason: 'fixtures' });
    expect(outcome.rejected).toEqual([11, 13]);
    expect(outcome.refused).toEqual([{ id: 12, status: 409, reason: 'task is not waiting' }, { id: 14, status: 403, reason: null }]);
    expect(postsOnly().map((p) => [p.url, JSON.stringify(p.body)])).toEqual([11, 12, 13, 14]
      .map((id) => [`/autonomy/tasks/${id}/decision`, JSON.stringify({ action: 'reject', reason: 'fixtures' })]));
    expect(calls().filter((c) => c.method === 'GET' && c.url === DOCKET_FEED_PATH)).toHaveLength(1);
    const all = calls();
    expect(all[all.length - 1].url).toBe(DOCKET_FEED_PATH);
  });
});

describe('the reads', () => {
  it('preview and listBlocked are admin GETs', async () => {
    answers = () => ({ body: { would_execute: false } });
    expect(await preview(5)).toEqual({ would_execute: false });
    expect(await listBlocked()).toEqual({ would_execute: false });
    expect(calls().map((c) => [c.method, c.url, c.headers['X-Admin-Token']])).toEqual([
      ['GET', '/api/autonomy/tasks/5/preview', 'owner-token'], ['GET', DOCKET_FEED_PATH, 'owner-token']]);
    await expect(preview(-1)).rejects.toThrow();
  });

  it('hubWords reads the three refusal dialects and nothing else', () => {
    expect(hubWords({ body: { error: 'a' } })).toBe('a');
    expect(hubWords({ body: { ok: false, reason: 'b' } })).toBe('b');
    expect(hubWords({ body: { detail: 'c' } })).toBe('c');
    expect(hubWords({ status: 500, message: 'POST /x -> 500' })).toBeNull();
    expect(hubWords(null)).toBeNull();
  });
});
