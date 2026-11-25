import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals';
jest.mock('expo/fetch', () => ({ fetch: (...args: Parameters<typeof fetch>) => globalThis.fetch(...args) }));
import { compareAgents } from '../agentOpinions';

const config = { baseUrl: 'hub.local/', token: ' user ', adminToken: ' owner ' };
const oldFetch = globalThis.fetch;
const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
const response = (status: number, body: unknown) =>
  ({ status, text: async () => JSON.stringify(body) }) as Response;

beforeEach(() => { mockFetch.mockReset(); globalThis.fetch = mockFetch; });
afterEach(() => { globalThis.fetch = oldFetch; jest.useRealTimers(); });

describe('native agent opinions', () => {
  it('sends one owner-only text request and preserves mixed outcomes in requested order', async () => {
    mockFetch.mockResolvedValue(response(200, { opinions: [
      { agent: 'frigga', ok: false, reason: 'route_unavailable' },
      { agent: 'jarvis', ok: true, text: 'Actual answer', model: 'local-model', route: 'local-lmstudio' },
    ] }));
    await expect(compareAgents(config, '  Compare this  ', ['jarvis', 'frigga'], false)).resolves.toEqual([
      { agent: 'jarvis', ok: true, text: 'Actual answer', model: 'local-model', route: 'local-lmstudio' },
      { agent: 'frigga', ok: false, reason: 'route_unavailable' },
    ]);
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(mockFetch).toHaveBeenCalledWith('http://hub.local/api/agents/opinions', expect.objectContaining({
      method: 'POST', redirect: 'error', credentials: 'omit',
      body: JSON.stringify({ question: 'Compare this', agents: ['jarvis', 'frigga'], allow_cloud: false }),
      headers: { Accept: 'application/json', 'Content-Type': 'application/json', 'Cache-Control': 'no-store',
        'X-User-Token': 'user', 'X-Admin-Token': 'owner' },
      signal: expect.any(AbortSignal),
    }));
  });

  it('requires valid bounded input before network', async () => {
    for (const [question, agents] of [
      [' ', ['jarvis', 'frigga']], ['x'.repeat(4097), ['jarvis', 'frigga']],
      ['\ud800', ['jarvis', 'frigga']], ['question', ['jarvis', 'jarvis']],
      ['question', ['../bad', 'frigga']],
    ] as [string, [string, string]][]) {
      await expect(compareAgents(config, question, agents, false)).rejects.toThrow('Invalid comparison request');
    }
    await expect(compareAgents({ ...config, baseUrl: 'http://user:secret@other.test' },
      'question', ['jarvis', 'frigga'], false)).rejects.toThrow('Invalid server URL');
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('lets a fresh direct localhost hub establish owner identity without invented credentials', async () => {
    mockFetch.mockResolvedValue(response(200, { opinions: [
      { agent: 'jarvis', ok: true, text: 'Local answer' },
      { agent: 'frigga', ok: false, reason: 'route_unavailable' },
    ] }));
    await expect(compareAgents({ baseUrl: 'http://127.0.0.1:8000', token: '', adminToken: '' },
      'Question', ['jarvis', 'frigga'], false)).resolves.toHaveLength(2);
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(mockFetch).toHaveBeenCalledWith('http://127.0.0.1:8000/api/agents/opinions',
      expect.objectContaining({ credentials: 'omit', headers: {
        Accept: 'application/json', 'Content-Type': 'application/json', 'Cache-Control': 'no-store',
      }, body: JSON.stringify({ question: 'Question', agents: ['jarvis', 'frigga'], allow_cloud: false }) }));
  });

  it('passes explicit cloud consent and keeps actual success metadata', async () => {
    mockFetch.mockResolvedValue(response(200, { opinions: [
      { agent: 'athena', ok: true, text: 'Cloud answer', route: 'cloud-gemini', model: 'gemini-live' },
      { agent: 'howard', ok: false, reason: 'cloud_disabled' },
    ] }));
    const result = await compareAgents(config, 'Question', ['athena', 'howard'], true);
    expect(result[0]).toEqual({ agent: 'athena', ok: true, text: 'Cloud answer', route: 'cloud-gemini', model: 'gemini-live' });
    expect(result[1]).toEqual({ agent: 'howard', ok: false, reason: 'cloud_disabled' });
    expect(JSON.parse(String(mockFetch.mock.calls[0][1]?.body)).allow_cloud).toBe(true);
  });

  it('refuses malformed, duplicate, missing, and unrequested opinions without partial attribution', async () => {
    const valid = { agent: 'jarvis', ok: true, text: 'Answer', route: 'local' };
    for (const opinions of [
      [valid], [valid, valid], [valid, { agent: 'other', ok: false, reason: 'x' }],
      [valid, { agent: 'frigga', ok: 'false' }],
      [{ agent: 'jarvis', ok: true, text: '' }, { agent: 'frigga', ok: false, reason: 'x' }],
      [valid, { agent: 'frigga', ok: false, reason: { private: 'do-not-echo' } }],
    ]) {
      mockFetch.mockResolvedValueOnce(response(200, { opinions }));
      await expect(compareAgents(config, 'Question', ['jarvis', 'frigga'], false))
        .rejects.toThrow('Invalid comparison response');
    }
    expect(mockFetch).toHaveBeenCalledTimes(6);
  });

  it('rejects a pre-aborted request and cancels a fetch that ignores abort', async () => {
    const prior = new AbortController(); prior.abort();
    await expect(compareAgents(config, 'Question', ['jarvis', 'frigga'], false, prior.signal))
      .rejects.toThrow('cancelled');
    expect(mockFetch).not.toHaveBeenCalled();
    mockFetch.mockImplementation(() => new Promise(() => {}));
    const controller = new AbortController();
    const pending = compareAgents(config, 'Question', ['jarvis', 'frigga'], false, controller.signal);
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(mockFetch).toHaveBeenCalledTimes(1);
    controller.abort();
    await expect(pending).rejects.toThrow('cancelled');
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('times out even if native transport ignores abort, with no retry', async () => {
    jest.useFakeTimers();
    mockFetch.mockImplementation(() => new Promise(() => {}));
    const pending = compareAgents(config, 'Question', ['jarvis', 'frigga'], false);
    const assertion = expect(pending).rejects.toThrow('timed out');
    await jest.advanceTimersByTimeAsync(131_000);
    await assertion;
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('uses generic safe errors for HTTP, redirect, and broken JSON', async () => {
    const oversized = jest.fn(async () => '{}');
    mockFetch.mockResolvedValueOnce({ status: 200, headers: new Headers({ 'Content-Length': '9999999' }), text: oversized } as unknown as Response);
    await expect(compareAgents(config, 'Question', ['jarvis', 'frigga'], false)).rejects.toThrow('Invalid comparison response');
    expect(oversized).not.toHaveBeenCalled();
    mockFetch.mockResolvedValueOnce(response(403, { detail: 'private server detail' }));
    await expect(compareAgents(config, 'Question', ['jarvis', 'frigga'], false))
      .rejects.toMatchObject({ status: 403, message: 'Owner authorization required' });
    mockFetch.mockRejectedValueOnce(new Error('redirect to private destination'));
    await expect(compareAgents(config, 'Question', ['jarvis', 'frigga'], false))
      .rejects.toThrow('Comparison unavailable');
    mockFetch.mockResolvedValueOnce({ status: 200, text: async () => '{not json' } as Response);
    await expect(compareAgents(config, 'Question', ['jarvis', 'frigga'], false))
      .rejects.toThrow('Invalid comparison response');
    expect(mockFetch).toHaveBeenCalledTimes(4);
  });
});
