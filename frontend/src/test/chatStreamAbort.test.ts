/* Stop-generating: postStream threads an AbortSignal into fetch, and a
   mid-stream abort surfaces as an AbortError rejection after the body reader
   is cancelled — the caller (runTurn) keeps the partial text, no error notice.
   Mock patterns mirror ttsStream.test.ts / actions.test.ts. */
import { describe, it, expect, vi } from 'vitest';
import { postStream } from '../api/client';

const enc = new TextEncoder();

function mockStream(reader: any) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, body: { getReader: () => reader } });
  globalThis.fetch = fn as any;
  return fn;
}

describe('postStream abort (stop generating)', () => {
  it('threads the AbortSignal into the fetch init', async () => {
    const reader = {
      read: vi.fn(async () => ({ done: true, value: undefined })),
      cancel: vi.fn(async () => {}),
    };
    const fn = mockStream(reader);
    const ac = new AbortController();
    await postStream('/chat/stream', { message: 'hi' }, () => {}, { signal: ac.signal });
    expect(fn.mock.calls[0][1].signal).toBe(ac.signal);
  });

  it('rejects with AbortError and cancels the reader on mid-stream abort', async () => {
    const ac = new AbortController();
    const events: any[] = [];
    const reader = {
      read: vi.fn()
        .mockResolvedValueOnce({ done: false, value: enc.encode('data: {"type":"token","text":"Par"}\n\n') })
        // Subsequent reads hang until the signal aborts them — like a live fetch.
        .mockImplementation(() => new Promise((_, rej) => {
          const boom = () => rej(new DOMException('aborted', 'AbortError'));
          if (ac.signal.aborted) return boom();
          ac.signal.addEventListener('abort', boom);
        })),
      cancel: vi.fn(async () => {}),
    };
    mockStream(reader);
    const p = postStream('/chat/stream', { message: 'hi' }, (e) => events.push(e), { signal: ac.signal });
    await new Promise((r) => setTimeout(r, 0));   // let the first chunk flush
    ac.abort();
    await expect(p).rejects.toMatchObject({ name: 'AbortError' });
    expect(events.some((e) => e.type === 'token')).toBe(true); // partial was delivered
    expect(reader.cancel).toHaveBeenCalled();                  // stream cleanly closed
  });
});
