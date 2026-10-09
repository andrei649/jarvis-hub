import { beforeEach, expect, jest, test } from '@jest/globals';
import { listActiveImages, prepareSelectedImages, sendSelectedImages, SelectedImageError } from '../selectedImages';

const config = { baseUrl: ' hub.local/ ', token: ' user ', adminToken: ' admin ' };
const fetchMock = jest.fn() as jest.MockedFunction<typeof fetch>;
const ok = (body: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status,
  headers: { get: () => null }, text: async () => JSON.stringify(body) }) as unknown as Response;
const session = 'session-1';
const candidate = { prompt: ' Exact question ', agent: 'jarvis', sessionId: session,
  imageDigests: ['a'.repeat(64)], activeImageHandles: [] as string[] };
const review = { configured: true, reachable: null, review_token: 'r'.repeat(24), session_id: session,
  destination: 'http://127.0.0.1:11434', model: 'llava', backend: 'ollama', local: true, active_image_count: 0 };

beforeEach(() => { fetchMock.mockReset(); (globalThis as any).fetch = fetchMock; });

test('owner list and prepare use both trimmed headers, exact scope and exact prompt without retry', async () => {
  fetchMock.mockResolvedValueOnce(ok({ session_id: session, images: [{ handle: 'h'.repeat(24), count: 2, question: 'Earlier' }] }))
    .mockResolvedValueOnce(ok(review));
  expect(await listActiveImages(config, session, 'jarvis')).toEqual([{ handle: 'h'.repeat(24), count: 2, question: 'Earlier' }]);
  expect(await prepareSelectedImages(config, candidate)).toMatchObject({ reviewToken: 'r'.repeat(24), destination: review.destination });
  const [url, init] = fetchMock.mock.calls[1];
  expect(url).toBe('http://hub.local/api/vlm/composer/selected-prepare');
  expect(init?.headers).toMatchObject({ 'X-User-Token': 'user', 'X-Admin-Token': 'admin' });
  expect(JSON.parse(init?.body as string)).toMatchObject({ prompt: ' Exact question ', session_id: session,
    image_digests: ['a'.repeat(64)], active_image_handles: [] });
});

test('pre-aborted call dispatches nothing and malformed authority proof is unavailable', async () => {
  const controller = new AbortController(); controller.abort();
  await expect(listActiveImages(config, session, 'jarvis', controller.signal)).rejects.toThrow();
  expect(fetchMock).not.toHaveBeenCalled();
  fetchMock.mockResolvedValueOnce(ok({ ...review, local: false }));
  await expect(prepareSelectedImages(config, candidate)).rejects.toThrow();
});

test('send includes only selected merged-main fields and validates committed response', async () => {
  fetchMock.mockResolvedValueOnce(ok({ ok: true, committed: true, response: 'Answer', model: review.model,
    backend: 'ollama', destination: review.destination, local: true, active_image_handle: null }));
  const result = await sendSelectedImages(config, { ...candidate, images: ['data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB'],
    reviewToken: review.review_token, expectedDestination: review.destination, expectedModel: review.model });
  expect(result).toMatchObject({ response: 'Answer', activeImageHandle: null });
  const body = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
  expect(body).toEqual({ prompt: candidate.prompt, agent: 'jarvis', session_id: session,
    images: ['data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB'], active_image_handles: [], expected_destination: review.destination,
    expected_binding: review.review_token, review_token: review.review_token, remote_ack: false });
});

test('definite refusal is distinguishable from unknown delivery, and no response body leaks into errors', async () => {
  fetchMock.mockResolvedValueOnce(ok({ error: 'secret', reason: 'vlm_destination_changed' }, 409));
  await expect(sendSelectedImages(config, { ...candidate, images: ['data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB'], reviewToken: review.review_token,
    expectedDestination: review.destination, expectedModel: review.model })).rejects.toMatchObject({ definite: true, status: 409 });
  fetchMock.mockResolvedValueOnce(ok({ error: 'secret' }, 502));
  try { await sendSelectedImages(config, { ...candidate, images: ['data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB'], reviewToken: review.review_token,
    expectedDestination: review.destination, expectedModel: review.model }); } catch (e) {
    expect(e).toBeInstanceOf(SelectedImageError);
    expect((e as SelectedImageError).definite).toBe(false);
    expect(String(e)).not.toContain('secret');
  }
});

test('ignored native fetch hangs still hit a deadline', async () => {
  jest.useFakeTimers();
  try {
    fetchMock.mockImplementationOnce(() => new Promise(() => {}));
    const promise = listActiveImages(config, session, 'jarvis');
    const assertion = expect(promise).rejects.toMatchObject({ definite: false });
    await jest.advanceTimersByTimeAsync(5001);
    await assertion;
  } finally { jest.useRealTimers(); }
});

test('three individually valid 3 MiB new images exceed the aggregate cap before any dispatch', async () => {
  const each = 'data:image/png;base64,' + 'A'.repeat(4 * 1024 * 1024);
  const payload = { ...candidate, imageDigests: ['a'.repeat(64), 'b'.repeat(64), 'c'.repeat(64)],
    images: [each, each, each], reviewToken: review.review_token,
    expectedDestination: review.destination, expectedModel: review.model };
  await expect(sendSelectedImages(config, payload)).rejects.toMatchObject({ definite: true });
  expect(fetchMock).not.toHaveBeenCalled();
});

test('accepts the backend maximum active list with bounded multibyte question labels', async () => {
  const rows = Array.from({ length: 32 }, (_, i) => ({ handle: `${String(i).padStart(2, '0')}${'h'.repeat(22)}`,
    count: 1, question: '😀'.repeat(120) }));
  const raw = JSON.stringify({ session_id: session, images: rows });
  fetchMock.mockResolvedValueOnce({ ok: true, status: 200,
    headers: { get: () => String(raw.length) }, text: async () => raw } as unknown as Response);
  expect(await listActiveImages(config, session, 'jarvis')).toHaveLength(32);
});

test('accepts canonical HTTPS loopback origins but refuses a path or model drift as proof', async () => {
  fetchMock.mockResolvedValueOnce(ok({ ...review, destination: 'https://127.0.0.2:11434' }));
  await expect(prepareSelectedImages(config, candidate)).resolves.toMatchObject({ destination: 'https://127.0.0.2:11434' });
  fetchMock.mockResolvedValueOnce(ok({ ...review, destination: 'http://127.0.0.1:11434/api/chat' }));
  await expect(prepareSelectedImages(config, candidate)).rejects.toThrow();
  fetchMock.mockResolvedValueOnce(ok({ ok: true, committed: true, response: 'Answer', model: 'another-model',
    backend: 'ollama', destination: review.destination, local: true, active_image_handle: null }));
  await expect(sendSelectedImages(config, { ...candidate,
    images: ['data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB'],
    reviewToken: review.review_token, expectedDestination: review.destination,
    expectedModel: review.model })).rejects.toMatchObject({ definite: false });
});

test('pre-aborted selected send dispatches zero requests', async () => {
  const controller = new AbortController(); controller.abort();
  await expect(sendSelectedImages(config, { ...candidate,
    images: ['data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB'],
    reviewToken: review.review_token, expectedDestination: review.destination,
    expectedModel: review.model }, controller.signal)).rejects.toThrow();
  expect(fetchMock).not.toHaveBeenCalled();
});

test('duplicate active handles in a response do not become ambiguous selectors', async () => {
  fetchMock.mockResolvedValueOnce(ok({ session_id: session, images: [
    { handle: 'h'.repeat(24), count: 1, question: 'One' },
    { handle: 'h'.repeat(24), count: 1, question: 'Two' },
  ] }));
  await expect(listActiveImages(config, session, 'jarvis')).rejects.toThrow();
});
