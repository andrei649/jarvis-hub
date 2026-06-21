/* H5.16 · client decoder for the sentence-level streaming TTS endpoint (`POST /tts/stream`).

   The server frames one sentence per record, in order:

       <json-header>\n<raw-audio-bytes>

   where the header is a single line of JSON
       {"idx": int, "text": str, "lang": str, "bytes": int, "done": bool}
   followed by exactly `bytes` audio bytes. A terminal frame {"done": true, "bytes": 0}
   (no audio) closes the stream. See the module comment in agents/web.py.

   This file is the missing browser half: a chunk-boundary-agnostic incremental parser
   (a network read can split a frame anywhere, even mid-header or mid-audio) plus a
   thin `streamTts` driver that pulls the response body and hands each ready frame to a
   callback. The parser is pure and fully unit-tested; the driver is a tiny wrapper so
   `voice.ts` stays small. Audio bytes are binary and may themselves contain 0x0A, so we
   only ever scan for the header-terminating newline, then consume audio by byte count. */

export interface TtsFrame {
  idx: number;
  text: string;
  lang: string;
  bytes: number;
  done: boolean;
  /** Exactly `bytes` audio bytes for this sentence (empty for skipped/terminal frames). */
  audio: Uint8Array;
}

// TS 6 makes Uint8Array generic over its backing buffer; `.subarray()` widens to
// ArrayBufferLike, so we pin our internal buffer type to the wide form to assign freely.
type Bytes = Uint8Array<ArrayBufferLike>;

function concat(a: Bytes, b: Bytes): Bytes {
  if (a.length === 0) return b;
  if (b.length === 0) return a;
  const out = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
}

/* Stateful decoder: feed it arbitrary byte chunks with `push()`, get back whatever
   complete frames are now available. Holds a partial frame across calls. */
export class TtsStreamParser {
  private buf: Bytes = new Uint8Array(0);
  private decoder = new TextDecoder('utf-8');
  // When we've parsed a header but not yet received its full audio payload.
  private pending: Omit<TtsFrame, 'audio'> | null = null;

  push(chunk: Uint8Array): TtsFrame[] {
    this.buf = concat(this.buf, chunk);
    const frames: TtsFrame[] = [];

    // Loop because a single chunk can complete several frames at once.
    for (;;) {
      if (this.pending === null) {
        // Looking for a header: bytes up to the first newline (0x0A).
        const nl = this.buf.indexOf(0x0a);
        if (nl === -1) break; // header not fully arrived yet
        const headerBytes = this.buf.subarray(0, nl);
        this.buf = this.buf.subarray(nl + 1);
        let header: Partial<TtsFrame>;
        try {
          header = JSON.parse(this.decoder.decode(headerBytes));
        } catch {
          // A malformed header would desync the whole stream — surface it loudly
          // rather than silently mis-framing the audio that follows.
          throw new Error('tts/stream: malformed frame header');
        }
        this.pending = {
          idx: Number(header.idx ?? 0),
          text: String(header.text ?? ''),
          lang: String(header.lang ?? ''),
          bytes: Number(header.bytes ?? 0),
          done: Boolean(header.done ?? false),
        };
      }

      // We have a header; do we have its audio payload yet?
      const need = this.pending.bytes;
      if (this.buf.length < need) break; // wait for more audio bytes
      const audio = this.buf.subarray(0, need);
      this.buf = this.buf.subarray(need);
      frames.push({ ...this.pending, audio });
      this.pending = null;
    }
    return frames;
  }

  /** True when no partial frame is buffered (clean frame boundary). */
  get atBoundary(): boolean {
    return this.pending === null && this.buf.length === 0;
  }
}

/** One-shot convenience for tests / non-streaming callers: decode a whole buffer. */
export function parseTtsStream(bytes: Uint8Array): TtsFrame[] {
  return new TtsStreamParser().push(bytes);
}

export interface StreamTtsOptions {
  headers?: Record<string, string>;
  /** Aborts the fetch + stops yielding further frames (barge-in / cancel). */
  cancelled?: () => boolean;
  signal?: AbortSignal;
}

/* Drive `POST /tts/stream` and invoke `onFrame` for each non-empty audio frame in order.

   Returns a status the caller acts on:
     'streamed'  — at least one audio frame was delivered (success).
     'disabled'  — server returned 409 (feature off) → caller falls back to whole-reply /tts.
     'unavailable' — non-OK / no body / no audio → caller falls back.
     'cancelled' — caller cancelled mid-stream.
   It deliberately never throws on a fallback-able condition, so `voice.ts` can keep its
   existing /tts path as a clean default-off fallback. */
export async function streamTts(
  text: string,
  lang: string,
  onFrame: (frame: TtsFrame) => Promise<void> | void,
  opts: StreamTtsOptions = {},
): Promise<'streamed' | 'disabled' | 'unavailable' | 'cancelled'> {
  if (opts.cancelled?.()) return 'cancelled';
  let res: Response;
  try {
    res = await fetch('/tts/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
      body: JSON.stringify({ text, lang }),
      signal: opts.signal,
    });
  } catch {
    return 'unavailable';
  }
  if (res.status === 409) return 'disabled'; // sentence streaming turned off — fall back
  if (!res.ok || !res.body) return 'unavailable';

  const reader = res.body.getReader();
  const parser = new TtsStreamParser();
  let delivered = 0;
  try {
    for (;;) {
      if (opts.cancelled?.()) {
        try { await reader.cancel(); } catch { /* already closed */ }
        return 'cancelled';
      }
      const { done, value } = await reader.read();
      if (value && value.length) {
        for (const frame of parser.push(value)) {
          if (frame.done) continue;        // terminal marker carries no audio
          if (frame.bytes === 0) continue; // sentence that failed to synthesize — skip
          if (opts.cancelled?.()) { try { await reader.cancel(); } catch { /* */ } return 'cancelled'; }
          await onFrame(frame);
          delivered++;
        }
      }
      if (done) break;
    }
  } catch {
    // Network drop mid-stream: if we already played something it's still a partial
    // success; otherwise let the caller fall back to the whole-reply path.
    return delivered > 0 ? 'streamed' : 'unavailable';
  }
  return delivered > 0 ? 'streamed' : 'unavailable';
}
