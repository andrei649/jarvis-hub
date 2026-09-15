// @vitest-environment node
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { expect, it, vi } from 'vitest';

function worker(prefix: string) {
  const handlers: Record<string, Function> = {};
  const names = ['another-app', 'nerva-hud-v2:other:1'];
  const deleted: string[] = [];
  const opened: string[] = [];
  const put = vi.fn();
  const caches = { keys: async () => names, delete: async (key: string) => deleted.push(key),
    open: async (key: string) => { opened.push(key); return {add: vi.fn(), put, match: vi.fn()}; }, match: vi.fn() };
  runInNewContext(readFileSync(new URL('../../public/sw-v2.js', import.meta.url), 'utf8'), {
    URL, Response, fetch: vi.fn().mockResolvedValue(new Response('ok')), caches,
    self: {location: {origin:'https://example.test'}, registration: {scope:`https://example.test${prefix}/`},
      clients:{claim:vi.fn()}, skipWaiting:vi.fn(), addEventListener:(name:string, fn:Function) => handlers[name] = fn },
  });
  return {handlers, deleted, opened, caches, put};
}
it('keeps unrelated origin caches during activation', async () => {
  const w = worker('/nerva'); let pending: Promise<unknown> = Promise.resolve();
  w.handlers.activate({waitUntil:(p:Promise<unknown>) => pending=p}); await pending;
  expect(w.deleted).toEqual([]);
});
it('uses distinct caches and shell URLs for two deployment prefixes', async () => {
  const one = worker('/one'), two = worker('/two');
  for (const w of [one,two]) {let p: Promise<unknown> = Promise.resolve(); w.handlers.install({waitUntil:(v:Promise<unknown>) => p=v}); await p;}
  expect(one.opened[0]).not.toBe(two.opened[0]);
});
it('intercepts only its prefixed HUD assets and navigation, never APIs or another app', () => {
  const w = worker('/nerva');
  for (const path of ['/api/private','/nerva/api/private','/v2/assets/x.js','/other/v2/chat']) {
    const respondWith = vi.fn();
    w.handlers.fetch({request:{method:'GET',url:'https://example.test'+path,mode:'navigate'},respondWith});
    expect(respondWith).not.toHaveBeenCalled();
  }
  const respondWith = vi.fn();
  w.handlers.fetch({request:{method:'GET',url:'https://example.test/nerva/v2/assets/x.js',mode:'cors'},respondWith});
  expect(respondWith).toHaveBeenCalledOnce();
});
