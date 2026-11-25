import { afterEach, beforeEach, expect, jest, test } from '@jest/globals';
import { fetchVaultExcerpts } from '../client';

const config = { baseUrl: 'http://hub.local', token: ' user ', adminToken: ' owner ' };
const originalFetch = globalThis.fetch;

beforeEach(() => { globalThis.fetch = jest.fn() as typeof fetch; });
afterEach(() => { globalThis.fetch = originalFetch; jest.useRealTimers(); });

function reply(body: unknown) {
  jest.mocked(fetch).mockResolvedValue({ ok: true, json: async () => body } as Response);
}

test('retrieves only bounded label and text with the typed question and explicit credentials', async () => {
  reply({ ok: true, attachments: [{ name: 'Atelier.md', text: 'Un pasaj', secret: 'omit' }],
    sources: { 'Atelier.md': { file: 'private/path' } } });
  const signal = new AbortController().signal;
  await expect(fetchVaultExcerpts(config, 'Ce știi despre iPod?', signal))
    .resolves.toEqual([{ name: 'Atelier.md', text: 'Un pasaj' }]);
  expect(fetch).toHaveBeenCalledWith('http://hub.local/api/os/brain/retrieve?q=Ce%20%C8%99tii%20despre%20iPod%3F',
    expect.objectContaining({ method: 'GET', signal: expect.any(AbortSignal), redirect: 'error', cache: 'no-store',
      credentials: 'omit', headers: { Accept: 'application/json',
        'X-User-Token': 'user', 'X-Admin-Token': 'owner' } }));
  reply({ ok: true, attachments: [] }); // Older hubs have no sources field.
  await expect(fetchVaultExcerpts(config, 'Old hub', signal)).resolves.toEqual([]);
});

test('rejects malformed, duplicate, oversized and empty excerpts', async () => {
  const valid = { name: 'note.md', text: 'content' };
  for (const attachments of [null, [valid, valid], [{ name: ' ', text: 'content' }],
    [{ name: 'note.md', text: ' ' }], [{ name: '😀'.repeat(201), text: 'content' }],
    [{ name: 'note.md', text: '😀'.repeat(1501) }], Array(5).fill(valid)]) {
    reply({ ok: true, attachments });
    await expect(fetchVaultExcerpts(config, 'Question', new AbortController().signal))
      .rejects.toThrow(/Invalid vault response/);
  }
});

test('aborts caller cancellation and enforces a lookup deadline', async () => {
  const controller = new AbortController();
  controller.abort();
  await expect(fetchVaultExcerpts(config, 'Question', controller.signal)).rejects.toMatchObject({ name: 'AbortError' });
  expect(fetch).not.toHaveBeenCalled();

  jest.useFakeTimers();
  jest.mocked(fetch).mockImplementation((_url, init) => new Promise((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
  }));
  const result = fetchVaultExcerpts(config, 'Question', new AbortController().signal);
  jest.advanceTimersByTime(10_000);
  await expect(result).rejects.toThrow(/timed out/);
});
