/**
 * Server-sent-events decoding for the Jarvis chat stream.
 *
 * The hub emits `data: {json}\n\n` frames (agents/web.py → chat_stream). React
 * Native's `fetch` has no readable-stream body, so callers read `responseText`
 * from an XHR as it grows and feed the growth here. This module is intentionally
 * pure (no RN/XHR imports) so it can be unit-tested in isolation.
 */

export type SseEvent = {
  type: 'start' | 'token' | 'end' | string;
  text?: string;
  agent?: string;
};

/**
 * Stateful decoder. Push raw text chunks (the *new* part of responseText) and
 * get back any fully-formed events. Partial trailing lines are buffered until
 * their terminating newline arrives.
 */
export class SseDecoder {
  private buffer = '';

  /** Feed the next chunk of response text; returns newly completed events. */
  push(chunk: string): SseEvent[] {
    this.buffer += chunk;
    const events: SseEvent[] = [];
    let nl: number;
    while ((nl = this.buffer.indexOf('\n')) >= 0) {
      const line = this.buffer.slice(0, nl);
      this.buffer = this.buffer.slice(nl + 1);
      const evt = parseSseLine(line);
      if (evt) events.push(evt);
    }
    return events;
  }

  /** Drain any buffered, un-terminated line (e.g. a stream that ends without a final newline). */
  flush(): SseEvent[] {
    const rest = this.buffer;
    this.buffer = '';
    const evt = parseSseLine(rest);
    return evt ? [evt] : [];
  }
}

/** Parse a single SSE line (`data: {...}`) into an event, or null if not a data frame. */
export function parseSseLine(raw: string): SseEvent | null {
  const line = raw.trim();
  if (!line.startsWith('data:')) return null;
  const payload = line.slice(line.indexOf(':') + 1).trim();
  if (!payload) return null;
  try {
    const parsed = JSON.parse(payload);
    if (parsed && typeof parsed === 'object' && typeof parsed.type === 'string') {
      return parsed as SseEvent;
    }
  } catch {
    // Non-JSON keep-alive or comment — ignore.
  }
  return null;
}
