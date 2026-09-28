import { beforeEach, describe, expect, it, jest } from '@jest/globals';
import { ttsFetchBase64 } from '../client';

const mockFetch = jest.fn() as jest.MockedFunction<typeof fetch>;
const config = { baseUrl: 'hub.local', token: 'user-token', adminToken: 'admin-token' };

beforeEach(() => {
  mockFetch.mockReset();
  (globalThis as any).fetch = mockFetch;
});

describe('mobile TTS (H526)', () => {
  it("reads the hub's 204 as nothing to say: '' — not an error, not an empty clip", async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, status: 204, blob: async () => { throw new Error('no body'); } } as any);
    await expect(ttsFetchBase64(config, '```\nls\n```', 'ro')).resolves.toBe('');
    expect(mockFetch).toHaveBeenCalledWith(
      'http://hub.local/tts',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ text: '```\nls\n```', lang: 'ro' }) }),
    );
  });

  it('still names a real failure', async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 500 } as any);
    await expect(ttsFetchBase64(config, 'Salut', 'ro')).rejects.toThrow('TTS failed (HTTP 500)');
    mockFetch.mockResolvedValueOnce({ ok: false, status: 401 } as any);
    await expect(ttsFetchBase64(config, 'Salut', 'ro')).rejects.toThrow('Unauthorized');
  });
});
