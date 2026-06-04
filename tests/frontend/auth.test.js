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
