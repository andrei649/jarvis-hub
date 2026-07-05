import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { fetchChannelInbox, fetchChannelThread, sendChannelReply } from '../client';

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

describe('mobile channel inbox API', () => {
  it('fetches live channel inbox threads with user auth', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        threads: [
          {
            thread_id: 'telegram:abc123',
            channel: 'telegram',
            sender: '42',
            preview: 'ping',
            count: 2,
            unread: true,
            ts: 123,
          },
        ],
      }),
    );

    const out = await fetchChannelInbox({
      baseUrl: '192.168.1.20:8080/',
      token: 'user-token',
      adminToken: 'admin-token',
    });

    expect(mockFetch).toHaveBeenCalledWith(
      'http://192.168.1.20:8080/api/channels/inbox',
      expect.objectContaining({
        method: 'GET',
        headers: expect.objectContaining({
          'X-User-Token': 'user-token',
        }),
      }),
    );
    expect(out.threads).toHaveLength(1);
    expect(out.threads[0].thread_id).toBe('telegram:abc123');
  });

  it('normalizes sparse inbox payloads to stable arrays', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({}));

    const out = await fetchChannelInbox({ baseUrl: 'hub.local', token: '', adminToken: '' });

    expect(out).toEqual({ threads: [] });
  });

  it('fetches a single thread using an encoded thread id', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        thread: { thread_id: 'telegram:abc123', channel: 'telegram' },
        messages: [{ id: 'm1', text: 'ping', direction: 'in', ts: 456 }],
      }),
    );

    const out = await fetchChannelThread(
      { baseUrl: 'http://jarvis.lan', token: 'tok', adminToken: '' },
      'telegram:abc123',
    );

    expect(mockFetch).toHaveBeenCalledWith(
      'http://jarvis.lan/api/channels/inbox/telegram%3Aabc123',
      expect.objectContaining({ method: 'GET' }),
    );
    expect(out.messages[0].text).toBe('ping');
  });

  it('queues a governed reply from mobile without admin auth', async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true, queued: true, task_id: 99 }));

    const out = await sendChannelReply(
      { baseUrl: 'http://jarvis.lan', token: 'tok', adminToken: 'adm' },
      'telegram:abc123',
      'pong',
      'veronica',
    );

    expect(mockFetch).toHaveBeenCalledWith(
      'http://jarvis.lan/api/channels/inbox/telegram%3Aabc123/reply',
      expect.objectContaining({
        method: 'POST',
        headers: expect.not.objectContaining({ 'X-Admin-Token': 'adm' }),
        body: JSON.stringify({ text: 'pong', agent: 'veronica', source: 'mobile' }),
      }),
    );
    expect(out).toEqual({ ok: true, queued: true, task_id: 99 });
  });
});
