import { afterEach, describe, expect, it, vi } from 'vitest';
import { setCsrfToken, setSessionHooks } from './client';
import { eventJson, readSse, SseParser, streamSse, type SseEvent } from './sse';

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
  setSessionHooks(null);
});

function streamOf(chunks: (string | Uint8Array)[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(typeof chunk === 'string' ? encoder.encode(chunk) : chunk);
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>, signal?: AbortSignal): Promise<SseEvent[]> {
  const out: SseEvent[] = [];
  for await (const event of readSse(stream, signal)) out.push(event);
  return out;
}

describe('SseParser', () => {
  it('parses named events, ignores ping comments and defaults the name to "message"', () => {
    const parser = new SseParser();
    const events = parser.push(': ping\n\nevent: start\ndata: {"a":1}\n\n: ping\n\ndata: plain\n\n');
    expect(events).toEqual([
      { event: 'start', data: '{"a":1}', id: '' },
      { event: 'message', data: 'plain', id: '' },
    ]);
  });

  it('joins multi-line data with newlines and strips one leading space only', () => {
    const events = new SseParser().push('event: token\ndata: line one\ndata:  two\ndata\n\n');
    expect(events).toEqual([{ event: 'token', data: 'line one\n two\n', id: '' }]);
  });

  it('handles CRLF and lone CR line endings', () => {
    const events = new SseParser().push('event: a\r\ndata: 1\r\n\r\nevent: b\rdata: 2\r\r');
    expect(events.map((e) => [e.event, e.data])).toEqual([['a', '1'], ['b', '2']]);
  });

  it('keeps a partial event across chunks and a CRLF split between chunks', () => {
    const parser = new SseParser();
    expect(parser.push('event: done\r')).toEqual([]);
    expect(parser.push('\ndata: {"x"')).toEqual([]);
    expect(parser.push(':2}\r')).toEqual([]);
    expect(parser.push('\n\r\n')).toEqual([{ event: 'done', data: '{"x":2}', id: '' }]);
  });

  it('drops an event without data and resets the name after each dispatch', () => {
    const parser = new SseParser();
    expect(parser.push('event: lonely\n\ndata: x\n\n')).toEqual([{ event: 'message', data: 'x', id: '' }]);
  });

  it('remembers the last event id', () => {
    expect(new SseParser().push('id: 7\ndata: a\n\n')).toEqual([{ event: 'message', data: 'a', id: '7' }]);
  });
});

describe('readSse', () => {
  it('decodes a multi-byte character split across chunks', async () => {
    const bytes = new TextEncoder().encode('event: token\ndata: {"t":"ș"}\n\n');
    const cut = bytes.indexOf(0xc8) + 1; // inside the two-byte "ș"
    const events = await collect(streamOf([bytes.slice(0, cut), bytes.slice(cut)]));
    expect(eventJson<{ t: string }>(events[0])).toEqual({ t: 'ș' });
  });

  it('streams every event of a byte-by-byte delivery in order', async () => {
    const text = 'event: start\ndata: {"n":1}\n\n: ping\n\nevent: token\ndata: {"t":"Bună"}\n\nevent: done\ndata: {}\n\n';
    const events = await collect(streamOf([...new TextEncoder().encode(text)].map((b) => new Uint8Array([b]))));
    expect(events.map((e) => e.event)).toEqual(['start', 'token', 'done']);
  });

  it('drops an unterminated trailing event', async () => {
    const events = await collect(streamOf(['event: done\ndata: {}\n\nevent: token\ndata: half']));
    expect(events.map((e) => e.event)).toEqual(['done']);
  });

  it('stops and cancels the stream when aborted', async () => {
    const controller = new AbortController();
    let cancelled = false;
    const stream = new ReadableStream<Uint8Array>({
      start(c) { c.enqueue(new TextEncoder().encode('event: a\ndata: 1\n\n')); },
      cancel() { cancelled = true; },
    });
    const seen: string[] = [];
    for await (const event of readSse(stream, controller.signal)) {
      seen.push(event.event);
      controller.abort();
    }
    expect(seen).toEqual(['a']);
    expect(cancelled).toBe(true);
  });
});

describe('streamSse', () => {
  it('POSTs JSON with the CSRF header and an event-stream Accept', async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => new Response(streamOf(['event: done\ndata: {"ok":true}\n\n']), { status: 200, headers: { 'Content-Type': 'text/event-stream' } }));
    vi.stubGlobal('fetch', fetchMock);
    setCsrfToken('csrf-9');
    const events: SseEvent[] = [];
    for await (const event of streamSse('/api/workspace/conversations/1/messages', { json: { content: 'Salut' } })) events.push(event);
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = init.headers as Record<string, string>;
    expect(init.method).toBe('POST');
    expect(headers['X-CSRF-Token']).toBe('csrf-9');
    expect(headers.Accept).toBe('text/event-stream');
    expect(JSON.parse(String(init.body))).toEqual({ content: 'Salut' });
    expect(events).toEqual([{ event: 'done', data: '{"ok":true}', id: '' }]);
  });

  it('rejects a refused stream with the server code and reports an expired session', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: 'auth_required', message: '' }), { status: 401, headers: { 'Content-Type': 'application/json' } })));
    const onAuthRequired = vi.fn();
    setSessionHooks({ onAuthRequired, refreshCsrf: vi.fn() });
    const run = async () => { for await (const _ of streamSse('/api/workspace/conversations/1/messages')) { /* drain */ } };
    await expect(run()).rejects.toMatchObject({ code: 'auth_required', status: 401 });
    expect(onAuthRequired).toHaveBeenCalledTimes(1);
  });

  it('maps a malformed event payload to invalid_response', () => {
    expect(() => eventJson({ event: 'done', data: '{oops', id: '' })).toThrow(expect.objectContaining({ code: 'invalid_response' }));
  });
});
