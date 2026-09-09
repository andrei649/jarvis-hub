import { beforeEach, describe, expect, it, vi } from 'vitest';
import { memoryNodes, memoryNeighborhood } from '../api/memory-map';
const node = { name: 'Alpha', type: 'project' };
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
beforeEach(() => { localStorage.clear(); vi.stubGlobal('fetch', vi.fn()); });
describe('read-only memory graph transport', () => {
  it('sends user auth in headers and searches a bounded page using GET only', async () => {
    localStorage.setItem('hud.user_token', 'user-secret');
    vi.mocked(fetch).mockResolvedValue(response({ entities: [{ ...node, properties: { private: 'not-rendered' } }], total: 1 }));
    expect(await memoryNodes('Alpha & Beta')).toEqual([node]);
    const [path, options] = vi.mocked(fetch).mock.calls[0];
    expect(path).toBe('/api/kg/entities?limit=100&q=Alpha%20%26%20Beta');
    expect(options.method).toBe('GET');
    expect(options.headers).toMatchObject({ 'X-User-Token': 'user-secret' });
    expect(options.redirect).toBe('error');
  });
  it.each([401, 403])('refuses auth status %s without retrying', async status => {
    localStorage.setItem('hud.user_token', 'expired');
    vi.mocked(fetch).mockResolvedValue(response({ error: 'PRIVATE' }, status));
    await expect(memoryNodes()).rejects.toMatchObject({ code: 'auth' });
    expect(fetch).toHaveBeenCalledOnce();
  });
  it.each([
    { entities: [], error: 'graph not available' }, { entities: [{}] }, { entities: [null] },
    { entities: [{ name: 'Alpha', type: 7 }] }, { entities: Array.from({ length: 101 }, () => node) },
  ])('rejects invalid list contracts', async value => {
    vi.mocked(fetch).mockResolvedValue(response(value));
    await expect(memoryNodes()).rejects.toMatchObject({ code: 'unavailable' });
  });
  it.each(['..', '.', '../secrets', 'x\\y', 'bad\nname', ''])('never fetches unsafe detail identity %s', async name => {
    await expect(memoryNeighborhood(name)).rejects.toMatchObject({ code: 'unavailable' });
    expect(fetch).not.toHaveBeenCalled();
  });
  it('encodes the selected name as one path segment and exposes only relation fields', async () => {
    const name = 'Școală & research';
    vi.mocked(fetch).mockResolvedValue(response({ entity: { name, type: 'project', properties: { secret: 'PRIVATE' } },
      relations: [{ source: name, relation: 'USES', target: 'Tool', properties: { secret: 'PRIVATE' } }] }));
    expect(await memoryNeighborhood(name)).toEqual({ entity: { name, type: 'project' }, relations: [{ source: name, relation: 'USES', target: 'Tool' }], clipped: false });
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/api/kg/entities/' + encodeURIComponent(name));
  });
  it.each([
    { entity: { ...node, name: 'Wrong' }, relations: [] },
    { entity: node, relations: [{ source: 'Other', relation: 'USES', target: 'Unrelated' }] },
    { entity: node, relations: [{ source: 'Alpha', relation: null, target: 'Other' }] },
    { entity: node, relations: null },
  ])('rejects mismatched or malformed neighborhoods', async value => {
    vi.mocked(fetch).mockResolvedValue(response(value));
    await expect(memoryNeighborhood('Alpha')).rejects.toMatchObject({ code: 'unavailable' });
  });
  it('bounds relation rendering and states when rows were clipped', async () => {
    vi.mocked(fetch).mockResolvedValue(response({ entity: node, relations: Array.from({ length: 101 }, () => ({ source: 'Alpha', relation: 'USES', target: 'Tool' })) }));
    const result = await memoryNeighborhood('Alpha');
    expect(result.relations).toHaveLength(100);
    expect(result.clipped).toBe(true);
  });
  it.each([
    new Response('{}', { headers: { 'Content-Type': 'text/html' } }),
    new Response('{}', { headers: { 'Content-Type': 'application/json', 'Content-Length': '1048577' } }),
    new Response(' '.repeat(1048577), { headers: { 'Content-Type': 'application/json' } }),
  ])('refuses wrong MIME or bodies above the byte bound and aborts transport', async value => {
    vi.mocked(fetch).mockResolvedValue(value);
    await expect(memoryNodes()).rejects.toMatchObject({ code: 'unavailable' });
    expect(vi.mocked(fetch).mock.calls[0][1].signal.aborted).toBe(true);
  });
  it('cancels a stalled body when the selected request is aborted', async () => {
    const cancel = vi.fn();
    vi.mocked(fetch).mockResolvedValue(new Response(new ReadableStream({ cancel }), { headers: { 'Content-Type': 'application/json' } }));
    const controller = new AbortController();
    const promise = memoryNodes('', controller.signal);
    await new Promise(resolve => setTimeout(resolve, 0)); controller.abort();
    await expect(promise).rejects.toMatchObject({ name: 'AbortError' });
    expect(cancel).toHaveBeenCalledOnce();
  });
  it('ends a stalled response at its deadline without retrying', async () => {
    vi.useFakeTimers();
    try {
      const cancel = vi.fn();
      vi.mocked(fetch).mockResolvedValue(new Response(new ReadableStream({ cancel }), { headers: { 'Content-Type': 'application/json' } }));
      const result = expect(memoryNodes()).rejects.toMatchObject({ code: 'unavailable' });
      await vi.advanceTimersByTimeAsync(10_000);
      await result;
      expect(cancel).toHaveBeenCalledOnce();
      expect(fetch).toHaveBeenCalledOnce();
      expect(vi.mocked(fetch).mock.calls[0][1].signal.aborted).toBe(true);
    } finally { vi.useRealTimers(); }
  });
});
