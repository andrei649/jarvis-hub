import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals';
import { streamChat } from '../client';
import { normalizeTurnOutcome } from '../../chat/turnOutcome';

const config = { baseUrl: 'http://hub.local', token: '', adminToken: '' };

class MockXHR {
  static latest: MockXHR;
  static created = 0;
  readyState = 0;
  status = 0;
  responseText = '';
  body = '';
  headers: Record<string, string> = {};
  aborted = false;
  onreadystatechange?: () => void;
  onerror?: () => void;

  constructor() {
    MockXHR.latest = this;
    MockXHR.created += 1;
  }

  open() {}
  setRequestHeader(name: string, value: string) { this.headers[name] = value; }
  send(body: string) { this.body = body; }
  abort() {
    this.aborted = true;
    this.status = 0;
    this.readyState = 4;
    this.onreadystatechange?.();
  }

  emit(frame: object) {
    this.responseText += `data: ${JSON.stringify(frame)}\n\n`;
    this.status = 200;
    this.readyState = 3;
    this.onreadystatechange?.();
  }

  close() {
    this.status = 200;
    this.readyState = 4;
    this.onreadystatechange?.();
  }
}

describe('streamChat session continuity', () => {
  const originalXHR = globalThis.XMLHttpRequest;

  beforeEach(() => {
    jest.useFakeTimers();
    MockXHR.created = 0;
    globalThis.XMLHttpRequest = MockXHR as unknown as typeof XMLHttpRequest;
  });

  afterEach(() => {
    globalThis.XMLHttpRequest = originalXHR;
    jest.clearAllTimers();
    jest.useRealTimers();
  });

  function start(sessionId?: string | null, serverConfig = config) {
    const handlers = {
      onStart: jest.fn(),
      onToken: jest.fn(),
      onDone: jest.fn(),
      onError: jest.fn(),
    };
    const cancel = streamChat(serverConfig, 'hello', 'jarvis', handlers, sessionId);
    return { xhr: MockXHR.latest, handlers, cancel };
  }

  it('sends a selected session ID, but omits absent and null IDs', () => {
    expect(JSON.parse(start('thread_123').xhr.body)).toEqual({
      message: 'hello', agent: 'jarvis', session_id: 'thread_123',
    });
    expect(JSON.parse(start().xhr.body)).toEqual({ message: 'hello', agent: 'jarvis' });
    expect(JSON.parse(start(null).xhr.body)).toEqual({ message: 'hello', agent: 'jarvis' });
  });

  it('forwards configured user and owner credentials as headers only', () => {
    const { xhr } = start('thread_123', {
      ...config, token: ' user-secret ', adminToken: ' owner-secret ',
    });
    expect(xhr.headers['X-User-Token']).toBe('user-secret');
    expect(xhr.headers['X-Admin-Token']).toBe('owner-secret');
    expect(JSON.parse(xhr.body)).toEqual({
      message: 'hello', agent: 'jarvis', session_id: 'thread_123',
    });
    expect(start(undefined, { ...config, adminToken: '   ' }).xhr.headers).not.toHaveProperty('X-Admin-Token');
  });

  it('rejects invalid non-null selected IDs before opening a stream', () => {
    for (const invalid of ['', '../other', 42, { id: 'thread_123' }]) {
      const before = MockXHR.created;
      const { handlers } = start(invalid as string);
      expect(MockXHR.created).toBe(before);
      expect(handlers.onError).toHaveBeenCalledWith(expect.stringMatching(/invalid session id/i));
      expect(handlers.onDone).not.toHaveBeenCalled();
    }
  });

  it('passes the end frame session ID to onDone', () => {
    const { xhr, handlers } = start();
    xhr.emit({ type: 'end', text: 'reply', session_id: 'new_thread' });
    expect(handlers.onDone).toHaveBeenCalledWith('reply', 'new_thread');
  });

  it('passes only a validated current-turn duration from an explicit end', () => {
    const { xhr, handlers } = start('old_thread');
    xhr.emit({ type: 'token', text: 'partial', outcome: { latency_ms: 999 } });
    xhr.emit({ type: 'end', text: 'reply', session_id: 'new_thread',
      outcome: { latency_ms: 137, token: 'never forward' } });
    expect(handlers.onToken).toHaveBeenCalledWith('partial');
    expect(handlers.onDone).toHaveBeenCalledTimes(1);
    expect(handlers.onDone).toHaveBeenCalledWith('reply', 'new_thread', { latency_ms: 137 });
    xhr.emit({ type: 'end', text: 'late', session_id: 'other', outcome: { latency_ms: 555 } });
    expect(handlers.onDone).toHaveBeenCalledTimes(1);
  });

  it('accepts exact zero and omits a third argument for absent or invalid measurements', () => {
    const zero = start();
    zero.xhr.emit({ type: 'end', text: 'zero', outcome: { latency_ms: 0 } });
    expect(zero.handlers.onDone).toHaveBeenCalledWith('zero', undefined, { latency_ms: 0 });
    for (const invalid of [undefined, null, {}, [], true, '12',
      { latency_ms: null }, { latency_ms: true }, { latency_ms: '12' },
      { latency_ms: -1 }, { latency_ms: 1.5 }, { latency_ms: Number.MAX_SAFE_INTEGER + 1 },
      { latency_ms: Infinity }]) {
      const { xhr, handlers } = start();
      xhr.emit({ type: 'end', text: 'reply', outcome: invalid });
      expect(handlers.onDone).toHaveBeenCalledTimes(1);
      expect(handlers.onDone.mock.calls[0]).toEqual(['reply', undefined]);
    }
  });

  it('never invents duration when the 200 stream closes without an end frame', () => {
    const { xhr, handlers } = start();
    xhr.emit({ type: 'token', text: 'partial' });
    xhr.close();
    expect(handlers.onDone.mock.calls).toEqual([['', undefined]]);
    xhr.emit({ type: 'end', text: 'late', outcome: { latency_ms: 13 } });
    expect(handlers.onDone).toHaveBeenCalledTimes(1);
  });

  it('requires an own safe-integer latency and projects no extra fields', () => {
    const inherited = Object.create({ latency_ms: 7 });
    expect(normalizeTurnOutcome(inherited)).toBeNull();
    expect(normalizeTurnOutcome({ latency_ms: Number.NaN })).toBeNull();
    expect(normalizeTurnOutcome({ latency_ms: 0.0, payload: 'secret' })).toEqual({ latency_ms: 0 });
    expect(normalizeTurnOutcome({ latency_ms: Number.MAX_SAFE_INTEGER })).toEqual({
      latency_ms: Number.MAX_SAFE_INTEGER,
    });
  });

  it('preserves null and ignores absent or malformed end IDs', () => {
    const cases: Array<[object, string | null | undefined]> = [
      [{ type: 'end', text: 'reply' }, undefined],
      [{ type: 'end', text: 'reply', session_id: null }, null],
      [{ type: 'end', text: 'reply', session_id: 42 }, undefined],
      [{ type: 'end', text: 'reply', session_id: { id: 'other' } }, undefined],
      [{ type: 'end', text: 'reply', session_id: '../other' }, undefined],
    ];
    for (const [frame, expected] of cases) {
      const { xhr, handlers } = start();
      xhr.emit(frame);
      expect(handlers.onDone).toHaveBeenCalledWith('reply', expected);
    }
  });

  it('does not deliver callbacks after cancellation, including late end frames', () => {
    const { xhr, handlers, cancel } = start('old_thread');
    xhr.emit({ type: 'token', text: 'partial' });
    cancel();
    expect(xhr.aborted).toBe(true);
    xhr.emit({ type: 'end', text: 'stale', session_id: 'old_thread' });
    xhr.onerror?.();
    jest.advanceTimersByTime(45000);
    expect(handlers.onToken).toHaveBeenCalledTimes(1);
    expect(handlers.onDone).not.toHaveBeenCalled();
    expect(handlers.onError).not.toHaveBeenCalled();
  });

  it('ignores trailing frames and late callbacks after an end frame', () => {
    const { xhr, handlers } = start();
    xhr.responseText = [
      { type: 'end', text: 'first', session_id: 'first_thread' },
      { type: 'token', text: 'late' },
      { type: 'end', text: 'second', session_id: 'second_thread' },
    ].map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join('');
    xhr.readyState = 3;
    xhr.status = 200;
    xhr.onreadystatechange?.();
    xhr.emit({ type: 'token', text: 'later' });
    xhr.close();
    xhr.onerror?.();
    jest.advanceTimersByTime(45000);
    expect(handlers.onDone).toHaveBeenCalledTimes(1);
    expect(handlers.onDone).toHaveBeenCalledWith('first', 'first_thread');
    expect(handlers.onToken).not.toHaveBeenCalled();
    expect(handlers.onError).not.toHaveBeenCalled();
  });
});
