/* Test doubles for the two transports fetch cannot fake on its own: a server-sent event stream
   the test feeds event by event (spec §8 framing), and an XMLHttpRequest whose upload progress
   and answer the test drives (the upload path, api/documents.ts). */
import { vi } from 'vitest';

export interface SseChannel {
  /** A fresh Response over the channel's stream, to answer the POST with. */
  response: () => Response;
  send: (event: string, data: unknown) => void;
  ping: () => void;
  close: () => void;
  readonly cancelled: boolean;
}

export function sseChannel(): SseChannel {
  const encoder = new TextEncoder();
  let controller: ReadableStreamDefaultController<Uint8Array> | null = null;
  let cancelled = false;
  const stream = new ReadableStream<Uint8Array>({
    start(c) { controller = c; },
    cancel() { cancelled = true; },
  });
  return {
    response: () => new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }),
    send: (event, data) => controller?.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)),
    ping: () => controller?.enqueue(encoder.encode(': ping\n\n')),
    close: () => controller?.close(),
    get cancelled() { return cancelled; },
  };
}

type Handler = (() => void) | null;

export class FakeXhr {
  static instances: FakeXhr[] = [];

  method = '';
  url = '';
  headers: Record<string, string> = {};
  body: unknown = null;
  status = 0;
  responseText = '';
  aborted = false;
  private responseType = '';
  upload: { onprogress: ((event: { lengthComputable: boolean; loaded: number; total: number }) => void) | null; onload: Handler } = { onprogress: null, onload: null };
  onload: Handler = null;
  onerror: Handler = null;
  onabort: Handler = null;

  constructor() { FakeXhr.instances.push(this); }

  open(method: string, url: string) { this.method = method; this.url = url; }
  setRequestHeader(name: string, value: string) { this.headers[name] = value; }
  getResponseHeader(name: string) { return name.toLowerCase() === 'content-type' ? this.responseType || null : null; }
  send(body: unknown) { this.body = body; }
  abort() { this.aborted = true; this.onabort?.(); }

  /** Test driver: bytes sent so far. */
  progress(loaded: number, total: number) { this.upload.onprogress?.({ lengthComputable: true, loaded, total }); }

  /** Test driver: the last byte left, then the server answered with JSON. */
  respond(status: number, body: unknown) {
    this.upload.onload?.();
    this.status = status;
    this.responseType = 'application/json';
    this.responseText = JSON.stringify(body);
    this.onload?.();
  }
}

/** Installs FakeXhr as the global XMLHttpRequest for this test (vi.unstubAllGlobals undoes it). */
export function installFakeXhr(): typeof FakeXhr {
  FakeXhr.instances = [];
  vi.stubGlobal('XMLHttpRequest', FakeXhr);
  return FakeXhr;
}
