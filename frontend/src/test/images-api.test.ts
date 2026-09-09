import { beforeEach, describe, expect, it, vi } from 'vitest';
import { imageStatus, imageTask, proposeImage, imageBlob } from '../api/images';
import { apiFetchOnce } from '../api/client';

const id = 'a'.repeat(32);
const artifact = { id, bytes: 8, width: 512, height: 512 };
const png = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);
const reply = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
beforeEach(() => { localStorage.clear(); vi.stubGlobal('fetch', vi.fn()); });

describe('owner image transport', () => {
  it.each(['/\n/evil.invalid/', '/\t/evil.invalid/', '/\r/evil.invalid/'])('refuses URL control normalization before attaching credentials', async path => {
    expect(new URL(path, 'http://localhost').origin).toBe('http://evil.invalid');
    localStorage.setItem('hud.admin_token', 'owner-secret');
    await expect(apiFetchOnce(path, { admin: true })).rejects.toThrow('same-origin path required');
    expect(fetch).not.toHaveBeenCalled();
  });
  it('sends the exact local prompt once and keeps credentials in headers', async () => {
    localStorage.setItem('hud.user_token', 'user-secret');
    localStorage.setItem('hud.admin_token', 'owner-secret');
    vi.mocked(fetch).mockResolvedValue(reply({ reason: 'approval_required', task_id: 17 }, 202));
    expect(await proposeImage(' A tree\nwith rain ')).toBe(17);
    expect(fetch).toHaveBeenCalledTimes(1);
    const [path, options] = vi.mocked(fetch).mock.calls[0];
    expect(path).toBe('/api/media/generate');
    expect(JSON.parse(options.body as string)).toEqual({ kind: 'image', prompt: ' A tree\nwith rain ', cloud: false });
    expect(options.headers).toMatchObject({ 'X-User-Token': 'user-secret', 'X-Admin-Token': 'owner-secret' });
    expect(options.redirect).toBe('error');
  });
  it.each([401, 403])('never retries a proposal on auth failure %s', async status => {
    localStorage.setItem('hud.user_token', 'old-token');
    vi.mocked(fetch).mockResolvedValue(reply({ reason: 'PRIVATE' }, status));
    await expect(proposeImage('tree')).rejects.toMatchObject({ code: 'auth' });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it.each([reply({ task_id: 17 }, 202), reply({ reason: 'approval_required', task_id: true }, 202), reply({ reason: 'PRIVATE' }, 500)])('treats ambiguous proposal responses as uncertain without retry', async response => {
    vi.mocked(fetch).mockResolvedValue(response);
    await expect(proposeImage('tree')).rejects.toMatchObject({ code: 'uncertain' });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('does not claim a paused 200 response was queued', async () => {
    vi.mocked(fetch).mockResolvedValue(reply({ paused: true, ok: false }));
    await expect(proposeImage('tree')).rejects.toMatchObject({ code: 'refused' });
  });
  it('reads configured status without inventing reachability', async () => {
    vi.mocked(fetch).mockResolvedValue(reply({ local_image: { configured: true, local: true, approval_required: true, reachable: null, reason: 'PRIVATE' } }));
    expect(await imageStatus()).toEqual({ configured: true });
  });
  it('rejects malformed configuration instead of treating strings as booleans', async () => {
    vi.mocked(fetch).mockResolvedValue(reply({ local_image: { configured: 'yes' } }));
    await expect(imageStatus()).rejects.toMatchObject({ code: 'unavailable' });
  });
  it.each([
    { status: 401, type: 'application/json' }, { status: 500, type: 'application/json' },
    { status: 200, type: 'text/html' },
  ])('aborts an unread stalled response after status or MIME refusal', async ({ status, type }) => {
    vi.mocked(fetch).mockResolvedValue(new Response(new ReadableStream(), { status, headers: { 'Content-Type': type } }));
    await expect(imageStatus()).rejects.toBeTruthy();
    expect(vi.mocked(fetch).mock.calls[0][1].signal.aborted).toBe(true);
  });
  it.each(['../secret', '', 'A'.repeat(32), 'https://evil.invalid/x'])('rejects artifact ID %s before any request', async bad => {
    await expect(imageBlob({ ...artifact, id: bad })).rejects.toMatchObject({ code: 'unavailable' });
    expect(fetch).not.toHaveBeenCalled();
  });
  it('downloads PNG bytes through authenticated fetch and ignores backend URLs', async () => {
    localStorage.setItem('hud.user_token', 'user-secret');
    vi.mocked(fetch).mockResolvedValue(new Response(png, { headers: { 'Content-Type': 'image/png' } }));
    const blob = await imageBlob({ ...artifact, url: 'https://evil.invalid' } as any);
    expect(blob.size).toBe(8);
    expect(blob.type).toBe('image/png');
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe(`/api/media/generated/${id}`);
    expect(vi.mocked(fetch).mock.calls[0][1].headers).toMatchObject({ 'X-User-Token': 'user-secret' });
  });
  it.each([
    new Response(png, { headers: { 'Content-Type': 'text/html' } }),
    new Response('not a PNG', { headers: { 'Content-Type': 'image/png' } }),
    new Response(png, { headers: { 'Content-Type': 'image/png', 'Content-Length': '16777217' } }),
    new Response(new Uint8Array(9), { headers: { 'Content-Type': 'image/png' } }),
  ])('rejects wrong type, signature or bounded length', async response => {
    vi.mocked(fetch).mockResolvedValue(response);
    await expect(imageBlob(artifact)).rejects.toMatchObject({ code: 'unavailable' });
  });
  it('aborts a stalled body read and cancels its reader', async () => {
    const cancelled = vi.fn();
    vi.mocked(fetch).mockResolvedValue(new Response(new ReadableStream({ cancel: cancelled }), { headers: { 'Content-Type': 'image/png' } }));
    const controller = new AbortController();
    const result = imageBlob(artifact, controller.signal);
    await new Promise(resolve => setTimeout(resolve, 0));
    controller.abort();
    await expect(result).rejects.toMatchObject({ name: 'AbortError' });
    expect(cancelled).toHaveBeenCalledOnce();
  });
  it.each([
    { task_id: 18, state: 'ready', artifact },
    { task_id: 17, state: 'ready', artifact: { ...artifact, id: '../secret' } },
    { task_id: 17, state: 'ready', artifact: { ...artifact, bytes: true } },
    { task_id: 17, state: 'running', artifact: null },
    { task_id: 17, state: 'queued', artifact },
  ])('rejects malformed task projections', async value => {
    vi.mocked(fetch).mockResolvedValue(reply(value));
    await expect(imageTask(17)).rejects.toMatchObject({ code: 'unavailable' });
  });
  it('only exposes validated task fields', async () => {
    vi.mocked(fetch).mockResolvedValue(reply({ task_id: 17, state: 'ready', artifact: { ...artifact, path: 'PRIVATE' }, payload: 'PRIVATE' }));
    expect(await imageTask(17)).toEqual({ task_id: 17, state: 'ready', artifact });
  });
});
