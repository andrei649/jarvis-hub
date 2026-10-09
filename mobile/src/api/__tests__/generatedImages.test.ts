import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import {
  fetchGeneratedImageStatus, proposeGeneratedImage, fetchGeneratedTask, fetchGeneratedPng,
} from '../generatedImages';

const config = { baseUrl: 'hub.local', token: 'user-secret', adminToken: 'admin-secret' };
const fetchMock = jest.fn() as jest.MockedFunction<typeof fetch>;
const reply = (body: unknown, status = 200): Response => ({
  status, ok: status >= 200 && status < 300,
  headers: { get: () => null },
  text: async () => JSON.stringify(body),
} as unknown as Response);

beforeEach(() => { fetchMock.mockReset(); (globalThis as any).fetch = fetchMock; });

describe('native generated image transport', () => {
  it('keeps configured distinct from reachable and includes both configured auth headers', async () => {
    fetchMock.mockResolvedValueOnce(reply({ local_image: { configured: true, local: true, approval_required: true, reachable: null, reason: 'not_probed' } }));
    await expect(fetchGeneratedImageStatus(config, new AbortController().signal)).resolves.toEqual({ configured: true, reachable: null, reason: 'not_probed' });
    expect(fetchMock).toHaveBeenCalledWith('http://hub.local/api/media', expect.objectContaining({
      headers: expect.objectContaining({ 'X-User-Token': 'user-secret', 'X-Admin-Token': 'admin-secret' }),
    }));
  });

  it('submits the exact prompt once and accepts only a valid 202 approval task', async () => {
    fetchMock.mockResolvedValueOnce(reply({ ok: false, reason: 'approval_required', task_id: 42 }, 202));
    const prompt = '  dusk forest, amber light  ';
    await expect(proposeGeneratedImage(config, prompt, new AbortController().signal)).resolves.toEqual({ kind: 'queued', taskId: 42 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({
      method: 'POST', body: JSON.stringify({ kind: 'image', prompt, cloud: false }),
    }));
  });

  it('does not claim a task from malformed approval or refusal envelopes', async () => {
    fetchMock.mockResolvedValueOnce(reply({ reason: 'approval_required', task_id: '42' }, 202));
    await expect(proposeGeneratedImage(config, 'moon', new AbortController().signal)).rejects.toMatchObject({ outcome: 'unknown' });
    fetchMock.mockResolvedValueOnce(reply({ ok: false, reason: 'local_image_disabled' }, 422));
    await expect(proposeGeneratedImage(config, 'moon', new AbortController().signal)).resolves.toEqual({ kind: 'refused', reason: 'local_image_disabled' });
  });

  it('does not dispatch any request with an already aborted signal', async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(proposeGeneratedImage(config, 'moon', controller.signal)).rejects.toMatchObject({ outcome: 'transport' });
    await expect(fetchGeneratedImageStatus(config, controller.signal)).rejects.toMatchObject({ outcome: 'transport' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('requires complete configured status but accepts an off status error shape', async () => {
    fetchMock.mockResolvedValueOnce(reply({ local_image: { configured: true, reachable: null } }));
    await expect(fetchGeneratedImageStatus(config, new AbortController().signal)).rejects.toMatchObject({ outcome: 'invalid' });
    fetchMock.mockResolvedValueOnce(reply({ local_image: { configured: false, reason: 'disabled' } }));
    await expect(fetchGeneratedImageStatus(config, new AbortController().signal)).resolves.toEqual({ configured: false, reachable: null, reason: 'disabled' });
  });

  it('treats a server error after POST dispatch as unknown delivery', async () => {
    fetchMock.mockResolvedValueOnce(reply({ reason: 'internal_error' }, 500));
    await expect(proposeGeneratedImage(config, 'moon', new AbortController().signal)).rejects.toMatchObject({ outcome: 'unknown' });
  });

  it('reports unknown delivery on a stalled POST even when fetch ignores abort', async () => {
    jest.useFakeTimers();
    try {
      fetchMock.mockImplementationOnce(() => new Promise<Response>(() => {}));
      const pending = proposeGeneratedImage(config, 'moon', new AbortController().signal);
      const assertion = expect(pending).rejects.toMatchObject({ outcome: 'unknown' });
      await jest.advanceTimersByTimeAsync(15001);
      await assertion;
    } finally { jest.useRealTimers(); }
  });

  it('validates admin task state, ID, and bounded ready artifact', async () => {
    const artifact = { id: 'a'.repeat(32), bytes: 100, width: 512, height: 512 };
    fetchMock.mockResolvedValueOnce(reply({ task_id: 42, state: 'ready', artifact }));
    await expect(fetchGeneratedTask(config, 42, new AbortController().signal)).resolves.toEqual({ taskId: 42, state: 'ready', artifact });
    expect(fetchMock.mock.calls[0][1]).toEqual(expect.objectContaining({ headers: expect.objectContaining({ 'X-Admin-Token': 'admin-secret' }) }));
    fetchMock.mockResolvedValueOnce(reply({ task_id: 42, state: 'ready', artifact: { ...artifact, bytes: 17 * 1024 * 1024 } }));
    await expect(fetchGeneratedTask(config, 42, new AbortController().signal)).rejects.toThrow('Invalid image task');
    fetchMock.mockResolvedValueOnce(reply({ task_id: 42, state: 'queued' }));
    await expect(fetchGeneratedTask(config, 42, new AbortController().signal)).rejects.toMatchObject({ outcome: 'invalid' });
  });
  it('accepts failed only as an exact task with null artifact and never reads image bytes', async () => {
    fetchMock.mockResolvedValueOnce(reply({ task_id: 42, state: 'failed', artifact: null, reason: 'PRIVATE', prompt: 'PRIVATE' }));
    await expect(fetchGeneratedTask(config, 42, new AbortController().signal)).resolves.toEqual({ taskId: 42, state: 'failed', artifact: null });
    for (const value of [
      { task_id: 43, state: 'failed', artifact: null },
      { task_id: 42, state: 'failed', artifact: { id: 'a'.repeat(32), bytes: 8, width: 1, height: 1 } },
      { task_id: 42, state: 'failure', artifact: null },
    ]) {
      fetchMock.mockResolvedValueOnce(reply(value));
      await expect(fetchGeneratedTask(config, 42, new AbortController().signal)).rejects.toMatchObject({ outcome: 'invalid' });
    }
    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(fetchMock.mock.calls.every(([url]) => String(url).endsWith('/api/media/generation-tasks/42'))).toBe(true);
  });

  it('rejects non-PNG, oversized, and mismatched artifact downloads before preview', async () => {
    const id = 'a'.repeat(32);
    const binary = (base64: string, size: number, contentType = 'image/png'): Response => ({
      ok: true, status: 200, headers: { get: (name: string) => name.toLowerCase() === 'content-type' ? contentType : name.toLowerCase() === 'content-length' ? String(size) : null },
      blob: async () => ({ size } as Blob),
    } as unknown as Response);
    class Reader {
      result: string | null = null;
      onloadend?: () => void;
      onerror?: () => void;
      readAsDataURL() { this.result = `data:image/png;base64,${current}`; this.onloadend?.(); }
    }
    let current = 'bm90LXBuZw==';
    (globalThis as any).FileReader = Reader;
    fetchMock.mockResolvedValueOnce(binary(current, 7));
    await expect(fetchGeneratedPng(config, id, 7, new AbortController().signal)).rejects.toThrow('Invalid PNG');
    current = 'iVBORw0KGgoAAAANSUhEUg==';
    fetchMock.mockResolvedValueOnce(binary(current, 17 * 1024 * 1024));
    await expect(fetchGeneratedPng(config, id, 17 * 1024 * 1024, new AbortController().signal)).rejects.toThrow('Invalid PNG');
    fetchMock.mockResolvedValueOnce(binary(current, 10));
    await expect(fetchGeneratedPng(config, id, 11, new AbortController().signal)).rejects.toThrow('Invalid PNG');
    fetchMock.mockResolvedValueOnce(binary(current, 10, 'image/png-spoof'));
    await expect(fetchGeneratedPng(config, id, 10, new AbortController().signal)).rejects.toThrow('Invalid PNG');
    fetchMock.mockResolvedValueOnce({ ...binary(current, 10), headers: { get: (name: string) => name === 'content-type' ? 'image/png' : null } } as Response);
    await expect(fetchGeneratedPng(config, id, 10, new AbortController().signal)).rejects.toThrow('Invalid PNG');
  });
});
