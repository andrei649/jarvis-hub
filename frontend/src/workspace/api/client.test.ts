import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, query, request, setCsrfToken, setSessionHooks, WorkspaceApiError } from './client';
import { apiError, json, mockFetch } from '../test/mockApi';

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
  setSessionHooks(null);
});

describe('CSRF header', () => {
  it('rides on every mutating method and never on reads', async () => {
    const mock = mockFetch({
      'GET /api/workspace/me': { ok: true },
      'POST /api/workspace/x': { ok: true },
      'PUT /api/workspace/x': { ok: true },
      'PATCH /api/workspace/x': { ok: true },
      'DELETE /api/workspace/x': json(204),
    });
    setCsrfToken('tok-123');
    await api.get('/api/workspace/me');
    await api.post('/api/workspace/x', { a: 1 });
    await api.put('/api/workspace/x', { a: 1 });
    await api.patch('/api/workspace/x', { a: 1 });
    await api.del('/api/workspace/x');
    const [get, ...writes] = mock.calls;
    expect(get.headers['X-CSRF-Token']).toBeUndefined();
    expect(writes.map((c) => c.headers['X-CSRF-Token'])).toEqual(['tok-123', 'tok-123', 'tok-123', 'tok-123']);
  });

  it('sends JSON with credentials and no-store, and an empty JSON object for a bodiless POST', async () => {
    const mock = mockFetch({ 'POST /api/workspace/logout': json(204) });
    await api.post('/api/workspace/logout');
    const init = mock.fn.mock.calls[0][1] as RequestInit;
    expect(init.credentials).toBe('same-origin');
    expect(init.cache).toBe('no-store');
    expect(mock.calls[0].headers['Content-Type']).toBe('application/json');
    expect(mock.calls[0].body).toEqual({});
  });
});

describe('error mapping', () => {
  it('turns {error, message, ...extra} into a typed WorkspaceApiError', async () => {
    mockFetch({ 'POST /api/workspace/login': apiError(429, 'too_many_attempts', { retry_after_seconds: 600 }) });
    const err = (await api.post('/api/workspace/login', {}).catch((e: unknown) => e)) as WorkspaceApiError;
    expect(err).toBeInstanceOf(WorkspaceApiError);
    expect(err.code).toBe('too_many_attempts');
    expect(err.status).toBe(429);
    expect(err.extra).toEqual({ retry_after_seconds: 600 });
    expect(err.message).toBe('server says too_many_attempts');
  });

  it('maps FastAPI validation bodies to invalid_request', async () => {
    mockFetch({ 'POST /api/workspace/x': json(422, { detail: [{ loc: ['body'], msg: 'bad' }] }) });
    await expect(api.post('/api/workspace/x', {})).rejects.toMatchObject({ code: 'invalid_request', status: 422 });
  });

  it('maps a non-JSON 5xx (a proxy error page) to server_error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>Bad gateway</html>', { status: 502, headers: { 'Content-Type': 'text/html' } })));
    await expect(api.get('/api/workspace/me')).rejects.toMatchObject({ code: 'server_error', status: 502 });
  });

  it('maps a network failure to network_error and lets aborts through untouched', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch'); }));
    await expect(api.get('/api/workspace/me')).rejects.toMatchObject({ code: 'network_error', status: 0 });
    vi.stubGlobal('fetch', vi.fn(async () => { throw new DOMException('aborted', 'AbortError'); }));
    await expect(api.get('/api/workspace/me')).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('resolves 204 to undefined and rejects malformed JSON as invalid_response', async () => {
    mockFetch({ 'DELETE /api/workspace/x': json(204) });
    await expect(api.del('/api/workspace/x')).resolves.toBeUndefined();
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{not json', { status: 200 })));
    await expect(api.get('/api/workspace/x')).rejects.toMatchObject({ code: 'invalid_response' });
  });
});

describe('session recovery', () => {
  it('reports auth_required once to the session layer and still rejects', async () => {
    mockFetch({ 'GET /api/workspace/me': apiError(401, 'auth_required') });
    const onAuthRequired = vi.fn();
    setSessionHooks({ onAuthRequired, refreshCsrf: vi.fn() });
    await expect(api.get('/api/workspace/me')).rejects.toMatchObject({ code: 'auth_required' });
    expect(onAuthRequired).toHaveBeenCalledTimes(1);
  });

  it('does not treat a wrong password (401 invalid_credentials) as an expired session', async () => {
    mockFetch({ 'POST /api/workspace/login': apiError(401, 'invalid_credentials') });
    const onAuthRequired = vi.fn();
    setSessionHooks({ onAuthRequired, refreshCsrf: vi.fn() });
    await expect(api.post('/api/workspace/login', {})).rejects.toMatchObject({ code: 'invalid_credentials' });
    expect(onAuthRequired).not.toHaveBeenCalled();
  });

  it('skips the hook for public auth calls', async () => {
    mockFetch({ 'POST /api/workspace/login': apiError(401, 'auth_required') });
    const onAuthRequired = vi.fn();
    setSessionHooks({ onAuthRequired, refreshCsrf: vi.fn() });
    await expect(request('POST', '/api/workspace/login', { json: {}, skipAuthRedirect: true })).rejects.toBeInstanceOf(WorkspaceApiError);
    expect(onAuthRequired).not.toHaveBeenCalled();
  });

  it('refreshes a rotated CSRF token and replays the write once', async () => {
    let attempt = 0;
    const mock = mockFetch({
      'PATCH /api/workspace/me': () => (++attempt === 1 ? apiError(403, 'csrf_failed') : { user: { id: 1 } }),
    });
    setCsrfToken('old');
    const refreshCsrf = vi.fn(async () => { setCsrfToken('new'); return 'new'; });
    setSessionHooks({ onAuthRequired: vi.fn(), refreshCsrf });
    await expect(api.patch('/api/workspace/me', { name: 'A' })).resolves.toEqual({ user: { id: 1 } });
    expect(refreshCsrf).toHaveBeenCalledTimes(1);
    expect(mock.calls.map((c) => c.headers['X-CSRF-Token'])).toEqual(['old', 'new']);
  });

  it('gives up when the refresh finds no session (no endless replay)', async () => {
    const mock = mockFetch({ 'POST /api/workspace/x': apiError(403, 'csrf_failed') });
    setSessionHooks({ onAuthRequired: vi.fn(), refreshCsrf: vi.fn(async () => null) });
    await expect(api.post('/api/workspace/x', {})).rejects.toMatchObject({ code: 'csrf_failed' });
    expect(mock.calls).toHaveLength(1);
  });

  it('does not replay a 403 that is not a CSRF failure', async () => {
    const refreshCsrf = vi.fn();
    mockFetch({ 'POST /api/workspace/me/password': apiError(403, 'wrong_password') });
    setSessionHooks({ onAuthRequired: vi.fn(), refreshCsrf });
    await expect(api.post('/api/workspace/me/password', {})).rejects.toMatchObject({ code: 'wrong_password' });
    expect(refreshCsrf).not.toHaveBeenCalled();
  });
});

describe('query()', () => {
  it('drops empty values and encodes booleans as 1/0', () => {
    expect(query({ a: 1, b: undefined, c: '', d: null, e: true, f: 'x y' })).toBe('?a=1&e=1&f=x+y');
    expect(query({ a: undefined })).toBe('');
  });
});
