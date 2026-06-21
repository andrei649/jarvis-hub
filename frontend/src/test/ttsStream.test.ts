// @ts-nocheck
/* H5.16 · unit tests for the streaming-TTS client decoder (src/api/ttsStream.ts).
   Pure logic + a fetch/ReadableStream-mocked driver — no network, no real audio. These
   pin the wire framing (header\n + N audio bytes), chunk-boundary resilience, and the
   fallback status contract that voice.ts relies on. */
import { describe, it, expect, vi } from 'vitest';
import { parseTtsStream, TtsStreamParser, streamTts } from '../api/ttsStream';

const enc = new TextEncoder();

// Build one wire frame: `<json-header>\n<audio-bytes>`.
function frame(header: object, audio: number[] = []): Uint8Array {
  const head = enc.encode(JSON.stringify(header) + '\n');
  const body = Uint8Array.from(audio);
  const out = new Uint8Array(head.length + body.length);
  out.set(head, 0); out.set(body, head.length);
  return out;
}
function concatAll(parts: Uint8Array[]): Uint8Array {
  const n = parts.reduce((s, p) => s + p.length, 0);
  const out = new Uint8Array(n);
  let o = 0; for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}

describe('parseTtsStream (one-shot)', () => {
  it('decodes a single frame with its audio payload', () => {
    const f = frame({ idx: 0, text: 'Hello.', lang: 'en', bytes: 3, done: false }, [1, 2, 3]);
    const frames = parseTtsStream(f);
    expect(frames).toHaveLength(1);
    expect(frames[0].idx).toBe(0);
    expect(frames[0].text).toBe('Hello.');
    expect(Array.from(frames[0].audio)).toEqual([1, 2, 3]);
  });

  it('decodes several ordered frames in one buffer', () => {
    const buf = concatAll([
      frame({ idx: 0, text: 'One.', lang: 'en', bytes: 2, done: false }, [10, 11]),
      frame({ idx: 1, text: 'Two.', lang: 'en', bytes: 1, done: false }, [22]),
      frame({ done: true, bytes: 0 }),
    ]);
    const frames = parseTtsStream(buf);
    expect(frames.map((f) => f.text)).toEqual(['One.', 'Two.', '']);
    expect(frames[2].done).toBe(true);
  });

  it('does NOT mis-frame audio that contains a newline byte (0x0A)', () => {
    // audio payload includes 0x0A — the parser must consume by byte count, not by newline.
    const f = frame({ idx: 0, text: 'x', lang: 'en', bytes: 4, done: false }, [0x0a, 0x0a, 5, 0x0a]);
    const frames = parseTtsStream(f);
    expect(frames).toHaveLength(1);
    expect(Array.from(frames[0].audio)).toEqual([0x0a, 0x0a, 5, 0x0a]);
  });
});

describe('TtsStreamParser (incremental, arbitrary chunk boundaries)', () => {
  it('reassembles frames split mid-header and mid-audio across pushes', () => {
    const whole = concatAll([
      frame({ idx: 0, text: 'Alpha.', lang: 'en', bytes: 3, done: false }, [1, 2, 3]),
      frame({ idx: 1, text: 'Beta.', lang: 'en', bytes: 2, done: false }, [4, 5]),
    ]);
    const parser = new TtsStreamParser();
    const got = [];
    // Feed one byte at a time — the worst-case fragmentation.
    for (let i = 0; i < whole.length; i++) got.push(...parser.push(whole.subarray(i, i + 1)));
    expect(got.map((f) => f.text)).toEqual(['Alpha.', 'Beta.']);
    expect(Array.from(got[0].audio)).toEqual([1, 2, 3]);
    expect(Array.from(got[1].audio)).toEqual([4, 5]);
    expect(parser.atBoundary).toBe(true);
  });

  it('holds a partial frame and is not at a boundary until completed', () => {
    const parser = new TtsStreamParser();
    const f = frame({ idx: 0, text: 'x', lang: 'en', bytes: 5, done: false }, [1, 2, 3, 4, 5]);
    const head = f.subarray(0, f.length - 2);  // missing 2 audio bytes
    expect(parser.push(head)).toHaveLength(0);
    expect(parser.atBoundary).toBe(false);
    const out = parser.push(f.subarray(f.length - 2));
    expect(out).toHaveLength(1);
    expect(parser.atBoundary).toBe(true);
  });

  it('throws on a malformed header rather than silently desyncing', () => {
    const parser = new TtsStreamParser();
    expect(() => parser.push(enc.encode('not-json\n'))).toThrow(/malformed frame header/);
  });
});

// ── streamTts driver ───────────────────────────────────────────────────
function mockStreamResponse(chunks: Uint8Array[], opts: any = {}) {
  let i = 0;
  const reader = {
    read: vi.fn(async () => (i < chunks.length ? { done: false, value: chunks[i++] } : { done: true, value: undefined })),
    cancel: vi.fn(async () => {}),
  };
  return {
    status: opts.status ?? 200,
    ok: opts.ok ?? true,
    body: opts.noBody ? null : { getReader: () => reader },
    _reader: reader,
  };
}

describe('streamTts driver', () => {
  it('plays each non-empty frame in order and reports "streamed"', async () => {
    const resp = mockStreamResponse([
      frame({ idx: 0, text: 'One.', lang: 'en', bytes: 2, done: false }, [1, 1]),
      frame({ idx: 1, text: 'Two.', lang: 'en', bytes: 2, done: false }, [2, 2]),
      frame({ done: true, bytes: 0 }),
    ]);
    global.fetch = vi.fn().mockResolvedValue(resp) as any;
    const played: string[] = [];
    const status = await streamTts('One. Two.', 'en', (f) => { played.push(f.text); });
    expect(status).toBe('streamed');
    expect(played).toEqual(['One.', 'Two.']);  // terminal done-frame carries no audio → skipped
  });

  it('skips sentences that failed to synthesize (bytes:0)', async () => {
    const resp = mockStreamResponse([
      frame({ idx: 0, text: 'ok.', lang: 'en', bytes: 1, done: false }, [9]),
      frame({ idx: 1, text: 'failed.', lang: 'en', bytes: 0, done: false }, []),
      frame({ done: true, bytes: 0 }),
    ]);
    global.fetch = vi.fn().mockResolvedValue(resp) as any;
    const played: string[] = [];
    await streamTts('x', 'en', (f) => { played.push(f.text); });
    expect(played).toEqual(['ok.']);
  });

  it('returns "disabled" on 409 without calling onFrame (feature off → fall back)', async () => {
    global.fetch = vi.fn().mockResolvedValue({ status: 409, ok: false, body: null }) as any;
    const onFrame = vi.fn();
    const status = await streamTts('x', 'en', onFrame);
    expect(status).toBe('disabled');
    expect(onFrame).not.toHaveBeenCalled();
  });

  it('returns "unavailable" on a non-OK response', async () => {
    global.fetch = vi.fn().mockResolvedValue({ status: 503, ok: false, body: null }) as any;
    const status = await streamTts('x', 'en', vi.fn());
    expect(status).toBe('unavailable');
  });

  it('returns "unavailable" when fetch itself throws (network drop)', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('offline')) as any;
    const status = await streamTts('x', 'en', vi.fn());
    expect(status).toBe('unavailable');
  });

  it('cancels before fetching when already cancelled', async () => {
    const fetchFn = vi.fn();
    global.fetch = fetchFn as any;
    const status = await streamTts('x', 'en', vi.fn(), { cancelled: () => true });
    expect(status).toBe('cancelled');
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it('stops mid-stream and cancels the reader when cancelled flips true', async () => {
    const resp = mockStreamResponse([
      frame({ idx: 0, text: 'One.', lang: 'en', bytes: 1, done: false }, [1]),
      frame({ idx: 1, text: 'Two.', lang: 'en', bytes: 1, done: false }, [2]),
    ]);
    global.fetch = vi.fn().mockResolvedValue(resp) as any;
    let cancelled = false;
    const played: string[] = [];
    const status = await streamTts(
      'One. Two.', 'en',
      (f) => { played.push(f.text); cancelled = true; },
      { cancelled: () => cancelled },
    );
    expect(status).toBe('cancelled');
    expect(played).toEqual(['One.']);     // stopped after the first frame
    expect(resp._reader.cancel).toHaveBeenCalled();
  });
});
