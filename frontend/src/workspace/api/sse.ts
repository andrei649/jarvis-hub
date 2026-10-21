/* Server-sent events over fetch.

   EventSource cannot POST, cannot send the CSRF header and cannot be aborted per request, so the
   assistant stream (spec §8) is read from a fetch ReadableStream instead. The parser follows the
   WHATWG event-stream rules that matter here: LF, CRLF and lone-CR line endings; `event:` names;
   multi-line `data:` joined with "\n"; one optional space after the colon; `:` comment lines
   (the server's `: ping` keep-alives) ignored; an event dispatched on a blank line; a trailing
   event without a blank line dropped (it never completed). Chunks may split anywhere — inside a
   line, between CR and LF, or inside a multi-byte UTF-8 character. */
import { baseHeaders, reportSessionFailure, toApiError, WorkspaceApiError } from './client';

export interface SseEvent {
  event: string;
  data: string;
  id: string;
}

/** Incremental parser: feed decoded text, collect complete events. */
export class SseParser {
  private buffer = '';
  private lastWasCR = false;
  private eventName = '';
  private dataLines: string[] = [];
  private lastId = '';

  /** Feeds a decoded text chunk and returns the events it completed. */
  push(chunk: string): SseEvent[] {
    const events: SseEvent[] = [];
    let text = chunk;
    // A CRLF split across chunks: the CR already ended the line, so drop the LF.
    if (this.lastWasCR && text.startsWith('\n')) text = text.slice(1);
    this.lastWasCR = false;
    this.buffer += text;
    let start = 0;
    for (let i = 0; i < this.buffer.length; i += 1) {
      const ch = this.buffer[i];
      if (ch !== '\n' && ch !== '\r') continue;
      const line = this.buffer.slice(start, i);
      if (ch === '\r') {
        if (i + 1 < this.buffer.length) {
          if (this.buffer[i + 1] === '\n') i += 1;
        } else {
          this.lastWasCR = true;
        }
      }
      start = i + 1;
      const event = this.line(line);
      if (event) events.push(event);
    }
    this.buffer = this.buffer.slice(start);
    return events;
  }

  private line(line: string): SseEvent | null {
    if (line === '') return this.dispatch();
    if (line.startsWith(':')) return null;
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'event') this.eventName = value;
    else if (field === 'data') this.dataLines.push(value);
    else if (field === 'id' && !value.includes('\u0000')) this.lastId = value;
    return null;
  }

  private dispatch(): SseEvent | null {
    const hasData = this.dataLines.length > 0;
    const event = { event: this.eventName || 'message', data: this.dataLines.join('\n'), id: this.lastId };
    this.eventName = '';
    this.dataLines = [];
    return hasData ? event : null;
  }
}

/** Reads a byte stream to the end (or until aborted), yielding parsed events in order. */
export async function* readSse(stream: ReadableStream<Uint8Array>, signal?: AbortSignal): AsyncGenerator<SseEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder('utf-8');
  const parser = new SseParser();
  const onAbort = () => { reader.cancel().catch(() => undefined); };
  signal?.addEventListener('abort', onAbort, { once: true });
  try {
    while (true) {
      if (signal?.aborted) return;
      const { value, done } = await reader.read();
      if (done) break;
      for (const event of parser.push(decoder.decode(value, { stream: true }))) yield event;
    }
    for (const event of parser.push(decoder.decode())) yield event;
  } finally {
    signal?.removeEventListener('abort', onAbort);
    reader.releaseLock();
  }
}

export interface StreamOptions {
  json?: unknown;
  signal?: AbortSignal;
}

/**
 * POSTs (with the CSRF header) and streams named events back. A non-2xx answer — the request
 * was refused before any event (e.g. `409 conversation_busy`, `429 rate_limited`) — rejects
 * with a WorkspaceApiError carrying the server's code, exactly like the JSON client.
 */
export async function* streamSse(url: string, opts: StreamOptions = {}): AsyncGenerator<SseEvent> {
  const headers = baseHeaders('POST', { Accept: 'text/event-stream', 'Content-Type': 'application/json' });
  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST', headers, body: JSON.stringify(opts.json ?? {}),
      credentials: 'same-origin', cache: 'no-store', signal: opts.signal,
    });
  } catch (err) {
    if ((err as Error)?.name === 'AbortError') return;
    throw new WorkspaceApiError('network_error', String((err as Error)?.message || ''), 0);
  }
  if (!response.ok) {
    const error = await toApiError(response);
    reportSessionFailure(error);
    throw error;
  }
  if (!response.body) throw new WorkspaceApiError('invalid_response', '', response.status);
  yield* readSse(response.body, opts.signal);
}

/** Parses an event's JSON data; a malformed payload becomes a typed error, never a crash. */
export function eventJson<T>(event: SseEvent): T {
  try {
    return JSON.parse(event.data) as T;
  } catch {
    throw new WorkspaceApiError('invalid_response', '', 200);
  }
}
