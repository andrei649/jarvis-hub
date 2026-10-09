import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals';
import { fetchModelRoles } from '../advisory';

const config = { baseUrl: 'hub.local/', token: '', adminToken: 'admin-only' };
const reply = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;
const mockFetch = jest.fn<typeof fetch>();

beforeEach(() => { mockFetch.mockReset(); (globalThis as any).fetch = mockFetch; });
afterEach(() => { jest.useRealTimers(); });

describe('read-only model roles', () => {
  it('uses configured admin credentials when no user token exists', async () => {
    mockFetch.mockResolvedValue(reply({ roles: [], reachable: null }));
    await expect(fetchModelRoles(config)).resolves.toEqual({ roles: [], reachable: null });
    expect(mockFetch).toHaveBeenCalledWith('http://hub.local/api/llm/roles', expect.objectContaining({
      method: 'GET', headers: expect.objectContaining({ 'X-Admin-Token': 'admin-only' }),
    }));
  });

  it('distinguishes a valid empty configuration from a malformed response', async () => {
    mockFetch.mockResolvedValueOnce(reply({ roles: [], reachable: null }));
    await expect(fetchModelRoles(config)).resolves.toEqual({ roles: [], reachable: null });
    mockFetch.mockResolvedValueOnce(reply({ reachable: null }));
    await expect(fetchModelRoles(config)).rejects.toThrow('Invalid model roles response');
    mockFetch.mockResolvedValueOnce(reply({ roles: [{ role: 'judge', configured: true, note: { unsafe: true } }], reachable: null }));
    await expect(fetchModelRoles(config)).rejects.toThrow('Invalid model roles response');
  });

  it('bounds a fetch that never settles, even if transport ignores abort', async () => {
    jest.useFakeTimers();
    mockFetch.mockImplementation(() => new Promise(() => {}));
    const request = fetchModelRoles(config);
    const assertion = expect(request).rejects.toThrow('timed out');
    await jest.advanceTimersByTimeAsync(15000);
    await assertion;
  });

  it('rejects a pre-aborted request before sending and a late response after abort', async () => {
    const aborted = new AbortController(); aborted.abort();
    await expect(fetchModelRoles(config, aborted.signal)).rejects.toThrow();
    expect(mockFetch).not.toHaveBeenCalled();
    const controller = new AbortController();
    let finish!: (response: Response) => void;
    mockFetch.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const request = fetchModelRoles(config, controller.signal);
    controller.abort();
    await expect(request).rejects.toThrow();
    finish(reply({ roles: [{ role: 'old', configured: true }], reachable: null }));
  });
});
