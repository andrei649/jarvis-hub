// HF-1: auth.js wraps window.fetch to attach the user access token
// (localStorage 'hud.user_token') to same-origin requests, with a
// prompt-and-retry on 401. The harness boots the real shipped file in JSDOM.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

let env, calls;

function stubFetch(sequence) {
  // Returns a fetch stub that records (url, init) and yields the next response.
  calls = [];
  let i = 0;
  return (url, init) => {
    calls.push({ url, init });
    const status = sequence[Math.min(i, sequence.length - 1)];
    i += 1;
    return Promise.resolve({ status });
  };
}

function hdr(init, name) {
  // init.headers is a Headers instance set by auth.js.
  return init && init.headers && typeof init.headers.get === 'function'
    ? init.headers.get(name)
    : undefined;
}

afterEach(() => env && env.cleanup());

describe('auth.js fetch wrapper', () => {
  it('attaches X-User-Token to same-origin requests when a token is stored', async () => {
    env = loadHud({ files: ['auth'], fetch: stubFetch([200]) });
    env.window.localStorage.setItem('hud.user_token', 'tok123');
    await env.window.fetch('/api/cognition');
    expect(calls).toHaveLength(1);
    expect(hdr(calls[0].init, 'X-User-Token')).toBe('tok123');
  });

  it('adds no token when none is stored', async () => {
    env = loadHud({ files: ['auth'], fetch: stubFetch([200]) });
    await env.window.fetch('/status');
    expect(hdr(calls[0].init, 'X-User-Token')).toBeFalsy();
  });

  it('does not leak the token to cross-origin requests', async () => {
    env = loadHud({ files: ['auth'], fetch: stubFetch([200]) });
    env.window.localStorage.setItem('hud.user_token', 'secret');
    await env.window.fetch('https://evil.example/collect');
    expect(hdr(calls[0].init, 'X-User-Token')).toBeUndefined();
  });

  it('does not attach or prompt for a token on protocol-relative and normalized cross-origin URLs', async () => {
    env = loadHud({ files: ['auth'], fetch: stubFetch([401]) });
    env.window.localStorage.setItem('hud.user_token', 'synthetic-secret');
    env.window.prompt = vi.fn(() => 'another-secret');
    const external = [
      '//external.example/collect',
      '/\\external.example/collect',
      String.raw`\\external.example/collect`,
    ];
    for (const url of external) {
      expect(new env.window.URL(url, env.window.location.href).origin).not.toBe(env.window.location.origin);
      await env.window.fetch(url);
    }
    expect(calls).toHaveLength(external.length);
    for (const call of calls) expect(hdr(call.init, 'X-User-Token')).toBeUndefined();
    expect(env.window.prompt).not.toHaveBeenCalled();
  });

  it('accepts resolved same-origin absolute, protocol-relative, and normal relative URLs', async () => {
    env = loadHud({ files: ['auth'], fetch: stubFetch([200]) });
    env.window.localStorage.setItem('hud.user_token', 'synthetic-secret');
    const local = [
      'http://127.0.0.1:8080/api/cognition',
      '//127.0.0.1:8080/api/cognition',
      '/api/cognition',
      'api/cognition',
      '\\api/cognition',
    ];
    for (const url of local) await env.window.fetch(url);
    expect(calls).toHaveLength(local.length);
    for (const call of calls) expect(hdr(call.init, 'X-User-Token')).toBe('synthetic-secret');
  });

  it('fails closed for malformed URLs and leaves URL objects untouched', async () => {
    env = loadHud({ files: ['auth'], fetch: stubFetch([200]) });
    env.window.localStorage.setItem('hud.user_token', 'synthetic-secret');
    await env.window.fetch('http://[invalid');
    const objectUrl = new env.window.URL('/api/cognition', env.window.location.href);
    await env.window.fetch(objectUrl);
    expect(calls).toHaveLength(2);
    expect(hdr(calls[0].init, 'X-User-Token')).toBeUndefined();
    expect(hdr(calls[1].init, 'X-User-Token')).toBeUndefined();
    expect(calls[1].url).toBe(objectUrl);
  });

  it('does not leak an injected token when one plain options object is reused externally', async () => {
    env = loadHud({ files: ['auth'], fetch: stubFetch([200]) });
    env.window.localStorage.setItem('hud.user_token', 'synthetic-secret');
    const headers = { 'X-Trace': 'same-options' };
    const opts = { method: 'GET', headers };
    await env.window.fetch('/api/status', opts);
    expect(hdr(calls[0].init, 'X-User-Token')).toBe('synthetic-secret');
    expect(hdr(calls[0].init, 'X-Trace')).toBe('same-options');
    await env.window.fetch('//external.example/collect', opts);
    expect(calls).toHaveLength(2);
    expect(opts.headers).toBe(headers);
    expect(headers).toEqual({ 'X-Trace': 'same-options' });
    expect(calls[1].init).toBe(opts);
    expect(hdr(calls[1].init, 'X-User-Token')).toBeUndefined();
  });

  it('does not change caller-owned Headers when options are reused externally', async () => {
    env = loadHud({ files: ['auth'], fetch: stubFetch([200]) });
    env.window.localStorage.setItem('hud.user_token', 'synthetic-secret');
    const headers = new env.window.Headers({ 'X-Trace': 'headers-object' });
    const opts = { headers };
    await env.window.fetch('/api/status', opts);
    expect(hdr(calls[0].init, 'X-User-Token')).toBe('synthetic-secret');
    expect(calls[0].init.headers).not.toBe(headers);
    await env.window.fetch('//external.example/collect', opts);
    expect(calls).toHaveLength(2);
    expect(opts.headers).toBe(headers);
    expect(headers.get('X-User-Token')).toBeNull();
    expect(calls[1].init).toBe(opts);
  });

  it('retries a 401 once without mutating frozen caller options', async () => {
    env = loadHud({ files: ['auth'], fetch: stubFetch([401, 200]) });
    env.window.prompt = vi.fn(() => 'fresh-token');
    const headers = Object.freeze({ 'X-Trace': 'frozen' });
    const opts = Object.freeze({ method: 'POST', headers });
    const resp = await env.window.fetch('/chat', opts);
    expect(resp.status).toBe(200);
    expect(calls).toHaveLength(2);
    expect(env.window.prompt).toHaveBeenCalledTimes(1);
    expect(hdr(calls[1].init, 'X-User-Token')).toBe('fresh-token');
    expect(hdr(calls[1].init, 'X-Trace')).toBe('frozen');
    expect(opts.headers).toBe(headers);
    expect(opts.__authRetry).toBeUndefined();
  });

  it('does not leave a retry token or marker in options later sent externally', async () => {
    env = loadHud({ files: ['auth'], fetch: stubFetch([401, 200, 200]) });
    env.window.prompt = vi.fn(() => 'fresh-token');
    const headers = { 'X-Trace': 'retry-then-external' };
    const opts = { method: 'POST', headers };
    await env.window.fetch('/chat', opts);
    expect(hdr(calls[1].init, 'X-User-Token')).toBe('fresh-token');
    await env.window.fetch('//external.example/collect', opts);
    expect(calls).toHaveLength(3);
    expect(calls[2].init).toBe(opts);
    expect(opts).toEqual({ method: 'POST', headers: { 'X-Trace': 'retry-then-external' } });
    expect(env.window.prompt).toHaveBeenCalledTimes(1);
  });

  it('preserves a caller-provided user header without replacing it', async () => {
    env = loadHud({ files: ['auth'], fetch: stubFetch([200]) });
    env.window.localStorage.setItem('hud.user_token', 'stored-token');
    const opts = { headers: { 'X-User-Token': 'caller-token' } };
    await env.window.fetch('/api/status', opts);
    expect(hdr(calls[0].init, 'X-User-Token')).toBe('caller-token');
    expect(opts.headers).toEqual({ 'X-User-Token': 'caller-token' });
    await env.window.fetch('//external.example/collect', opts);
    expect(calls[1].init).toBe(opts);
    expect(calls[1].init.headers['X-User-Token']).toBe('caller-token'); // caller supplied deliberately
  });

  it('prompts once on 401, stores the token, and retries', async () => {
    env = loadHud({ files: ['auth'], fetch: stubFetch([401, 200]) });
    env.window.prompt = vi.fn(() => 'fresh-token');
    const resp = await env.window.fetch('/chat', { method: 'POST' });
    expect(env.window.prompt).toHaveBeenCalledTimes(1);
    expect(calls).toHaveLength(2); // original + one retry
    expect(hdr(calls[1].init, 'X-User-Token')).toBe('fresh-token');
    expect(env.window.localStorage.getItem('hud.user_token')).toBe('fresh-token');
    expect(resp.status).toBe(200);
  });

  it('exposes JarvisAuth set/get/clear helpers', async () => {
    env = loadHud({ files: ['auth'], fetch: stubFetch([200]) });
    env.window.JarvisAuth.setToken('  abc  ');
    expect(env.window.JarvisAuth.getToken()).toBe('abc');
    env.window.JarvisAuth.clear();
    expect(env.window.JarvisAuth.getToken()).toBe('');
  });
});
