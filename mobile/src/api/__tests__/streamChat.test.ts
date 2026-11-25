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

  it('leaves slash commands unchanged when a direct reply was requested', () => {
    const handlers = { onToken: jest.fn(), onDone: jest.fn(), onError: jest.fn() };
    const cancel = streamChat(config, '  /new', 'jarvis', handlers, null, 'none');
    expect(JSON.parse(MockXHR.latest.body)).toEqual({ message: '  /new', agent: 'jarvis' });
    cancel();
  });

  it('sends a selected session ID, but omits absent and null IDs', () => {
    expect(JSON.parse(start('thread_123').xhr.body)).toEqual({
      message: 'hello', agent: 'jarvis', session_id: 'thread_123',
    });
    expect(JSON.parse(start().xhr.body)).toEqual({ message: 'hello', agent: 'jarvis' });
    expect(JSON.parse(start(null).xhr.body)).toEqual({ message: 'hello', agent: 'jarvis' });
  });

  it('sends explicit excerpts as attachments only and rejects invalid selections before opening', () => {
    const handlers = { onToken: jest.fn(), onDone: jest.fn(), onError: jest.fn() };
    const selected = [{ name: 'note.md', text: 'excerpt', source: 'private' }];
    streamChat(config, 'Question', 'jarvis', handlers, null, undefined, selected);
    expect(JSON.parse(MockXHR.latest.body)).toEqual({ message: 'Question', agent: 'jarvis',
      attachments: [{ name: 'note.md', text: 'excerpt' }] });
    for (const [message, excerpts] of [
      ['Question', []],
      ['Question', [{ name: 'note.md', text: '' }]],
      ['/new', [{ name: 'note.md', text: 'excerpt' }]],
    ] as Array<[string, { name: string; text: string }[]]>) {
      const before = MockXHR.created;
      streamChat(config, message, 'jarvis', handlers, null, undefined, excerpts);
      expect(MockXHR.created).toBe(before);
    }
    expect(handlers.onError).toHaveBeenCalledTimes(3);
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

  it('sends an owner-authorized history reference beside the prompt and requires an explicit end ACK', () => {
    const handlers = { onToken: jest.fn(), onDone: jest.fn(), onError: jest.fn() };
    const owner = { ...config, token: 'user-secret', adminToken: 'owner-secret' };
    const history = { session_id: 'source', turn: 1, revision: 'a'.repeat(64),
      excerpt: 'private source', allow_cloud: false, accidental: 'omit me' };
    streamChat(owner, 'Follow up', 'frigga', handlers, 'destination', undefined, undefined, history);
    const xhr = MockXHR.latest;
    expect(xhr.headers['X-Admin-Token']).toBe('owner-secret');
    expect(JSON.parse(xhr.body)).toEqual({ message: 'Follow up', agent: 'frigga',
      session_id: 'destination', history_reference: { session_id: 'source', turn: 1,
        revision: 'a'.repeat(64), excerpt: 'private source', allow_cloud: false } });
    xhr.emit({ type: 'end', text: 'Answer', session_id: 'destination', history_source_used: true });
    expect(handlers.onDone.mock.calls.at(-1)?.at(-1)).toBe(true);

    streamChat(owner, 'Follow up', 'frigga', handlers, 'destination', undefined, undefined, history);
    MockXHR.latest.emit({ type: 'end', text: 'No use', session_id: 'destination', history_source_used: 'true' });
    expect(handlers.onDone.mock.calls.at(-1)?.at(-1)).toBeUndefined();
  });

  it('rejects history disclosure without owner credentials, consent, bounded bytes, or separate attachments', () => {
    const handlers = { onToken: jest.fn(), onDone: jest.fn(), onError: jest.fn() };
    const history = { session_id: 'source', turn: 1, revision: 'a'.repeat(64),
      excerpt: 'source', allow_cloud: false };
    const owner = { ...config, adminToken: 'owner-secret' };
    const invalid: Array<[typeof config, string, { name: string; text: string }[] | undefined,
      typeof history]> = [
      [config, 'frigga', undefined, history],
      [owner, 'jarvis', undefined, history],
      [owner, 'frigga', [{ name: 'note', text: 'excerpt' }], history],
      [owner, 'frigga', undefined, { ...history, excerpt: '😀'.repeat(2001) }],
      [owner, 'frigga', undefined, { ...history, revision: 'wrong' }],
    ];
    for (const [server, agent, excerpts, reference] of invalid) {
      const before = MockXHR.created;
      streamChat(server, 'Follow up', agent, handlers, null, undefined, excerpts, reference);
      expect(MockXHR.created).toBe(before);
    }
    expect(handlers.onError).toHaveBeenCalledTimes(invalid.length);
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

  it('classifies only the exact missing-session 404 for the valid requested ID', () => {
    const { xhr, handlers } = start('thread_123');
    xhr.status = 404;
    xhr.responseText = JSON.stringify({ error: 'session_not_found' });
    xhr.readyState = 4;
    xhr.onreadystatechange?.();
    expect(handlers.onError).toHaveBeenCalledWith('Server returned HTTP 404', {
      kind: 'session_missing', sessionId: 'thread_123',
    });
  });

  it('keeps other errors and malformed/nonexact 404 bodies message-only', () => {
    const cases: Array<[number, string, string | undefined]> = [
      [404, '{"detail":"session_not_found"}', 'thread_123'],
      [404, '{"error":"Session_not_found"}', 'thread_123'],
      [404, '{"error":"session_not_found"}', undefined],
      [403, '{"error":"session_not_found"}', 'thread_123'],
      [503, '{"error":"session_not_found"}', 'thread_123'],
      [404, 'session_not_found', 'thread_123'],
    ];
    for (const [status, body, sessionId] of cases) {
      const { xhr, handlers } = start(sessionId);
      xhr.status = status;
      xhr.responseText = body;
      xhr.readyState = 4;
      xhr.onreadystatechange?.();
      expect(handlers.onError).toHaveBeenCalledTimes(1);
      expect(handlers.onError.mock.calls[0]).toHaveLength(1);
    }
  });

  it('passes the end frame session ID to onDone', () => {
    const { xhr, handlers } = start();
    xhr.emit({ type: 'end', text: 'reply', session_id: 'new_thread' });
    expect(handlers.onDone).toHaveBeenCalledWith('reply', 'new_thread');
  });

  it('forwards only an exact session transition matching the successful end ID', () => {
    const valid = start('missing');
    valid.xhr.emit({ type: 'end', text: 'New chat ready', session_id: 'fresh',
      session_transition: { command: 'new', session_id: 'fresh' } });
    expect(valid.handlers.onDone).toHaveBeenCalledWith('New chat ready', 'fresh', undefined,
      { command: 'new', sessionId: 'fresh' });

    const invalid = start('missing');
    invalid.xhr.emit({ type: 'end', text: 'No transition', session_id: 'fresh',
      session_transition: { command: 'new', session_id: 'other' } });
    expect(invalid.handlers.onDone).toHaveBeenCalledWith('No transition', 'fresh');
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

  it('forwards only the end frame receipt and preserves an unknown outcome', () => {
    const calls = [{ provider: 'ollama', model: 'qwen3/8b' }];
    const { xhr, handlers } = start('old_thread');
    xhr.emit({ type: 'token', text: 'partial', model_calls: calls });
    xhr.emit({ type: 'end', text: 'reply', session_id: 'old_thread', model_calls: calls });
    expect(handlers.onDone).toHaveBeenCalledWith('reply', 'old_thread', undefined, undefined, calls);

    const invalid = start('old_thread');
    invalid.xhr.emit({ type: 'end', text: 'reply', session_id: 'old_thread',
      model_calls: [{ provider: 'ollama', model: 'qwen3/8b', location: 'local' }] });
    expect(invalid.handlers.onDone).toHaveBeenCalledWith('reply', 'old_thread');
  });

  it('accepts measured agent activity only on the final frame, independently of latency', () => {
    const tools = { proposed: 0, queued: 0, executed: 0, failures: 0, basis: 'observed' };
    const { xhr, handlers } = start();
    xhr.emit({ type: 'token', text: '[Invitation sent via WhatsApp bridge]', outcome: { tools } });
    expect(handlers.onDone).not.toHaveBeenCalled();
    xhr.emit({ type: 'end', text: 'Draft', outcome: { tools } });
    expect(handlers.onDone).toHaveBeenCalledWith('Draft', undefined, { tools });
    for (const invalid of [{ ...tools, private: 'omit' }, { ...tools, executed: null },
      { ...tools, proposed: 1_000_001 }, { ...tools, failures: false }, { ...tools, basis: 'unknown' }]) {
      const bad = start();
      bad.xhr.emit({ type: 'end', text: 'Draft', outcome: { tools: invalid, latency_ms: 7 } });
      expect(bad.handlers.onDone).toHaveBeenCalledWith('Draft', undefined, { latency_ms: 7 });
    }
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

  it('times out after 45 seconds without new bytes despite repeated LOADING callbacks', () => {
    const { xhr, handlers } = start();
    xhr.emit({ type: 'start', agent: 'jarvis' });
    jest.advanceTimersByTime(44000);
    xhr.onreadystatechange?.();
    jest.advanceTimersByTime(1000);
    expect(xhr.aborted).toBe(true);
    expect(handlers.onError).toHaveBeenCalledWith('Stream stalled — no response from the hub');
  });

  it('keeps a long turn alive when SSE heartbeat bytes arrive', () => {
    const { xhr, handlers } = start();
    xhr.emit({ type: 'start', agent: 'jarvis' });
    for (let i = 0; i < 3; i++) {
      jest.advanceTimersByTime(30000);
      xhr.responseText += ': heartbeat\n\n';
      xhr.onreadystatechange?.();
    }
    xhr.emit({ type: 'end', text: 'reply' });
    expect(handlers.onDone).toHaveBeenCalledWith('reply', undefined);
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
