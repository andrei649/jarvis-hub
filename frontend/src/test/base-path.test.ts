import { afterEach, expect, it, vi } from 'vitest';
import { apiGet } from '../api/client';
import { routeHref, navigateHud } from '../hud-routing';

afterEach(() => { delete (window as any).__NERVA_BASE_PATH__; vi.unstubAllGlobals(); history.replaceState(null, '', '/'); });
it('prefixes API transport while preserving token headers', async () => {
  (window as any).__NERVA_BASE_PATH__ = '/nerva';
  const fetch = vi.fn().mockResolvedValue(new Response('{}'));
  vi.stubGlobal('fetch', fetch);
  await apiGet('/api/status');
  expect(fetch.mock.calls[0][0]).toBe('/nerva/api/status');
});
it('writes public hrefs but keeps per-entry overlay origins logical', () => {
  (window as any).__NERVA_BASE_PATH__ = '/nerva';
  history.replaceState({ other: 1 }, '', '/nerva/v2/chat?demo=1#anchor');
  expect(routeHref('/v2/memory')).toBe('/nerva/v2/memory?demo=1#anchor');
  navigateHud('/v2/world');
  expect(location.pathname).toBe('/nerva/v2/world');
  expect(history.state).toEqual({ other: 1, __nervaHudRoute: {path: '/v2/chat', parent: null} });
});

import { renderHook, act, cleanup } from '@testing-library/react';
import { useHudRoute, closeHudOverlay } from '../hud-routing';
import { logicalPath, internalLink } from '../base-path';
import { apiFetchOnce, postStream, setToken } from '../api/client';
afterEach(() => {cleanup(); setToken('');});
it('initializes deep panel bookmarks and canonicalizes under the prefix', () => {
  window.__NERVA_BASE_PATH__ = '/one/two';
  history.replaceState(null, '', '/one/two/v2/console/decision-inbox?demo=1');
  const {result} = renderHook(() => useHudRoute());
  expect(result.current.route.panel).toBe('decision-inbox');
  expect(document.title).toBe('Decision Inbox · Console · Nerva');
  expect(location.pathname).toBe('/one/two/v2/console/decision-inbox');
});
it('preserves historical overlay close targets and popstate beneath a prefix', () => {
  window.__NERVA_BASE_PATH__ = '/one';
  history.replaceState({ unrelated: 'kept' }, '', '/one/v2/chat?demo=1#anchor');
  const {result} = renderHook(() => useHudRoute());
  act(() => navigateHud('/v2/world'));
  const saved = history.state;
  act(() => {closeHudOverlay(); navigateHud('/v2/memory'); navigateHud('/v2/world');});
  act(() => {history.replaceState(saved, '', '/one/v2/world?demo=1#anchor'); window.dispatchEvent(new PopStateEvent('popstate'));});
  expect(result.current.route.mode).toBe('world');
  act(() => closeHudOverlay());
  expect(location.pathname + location.search + location.hash).toBe('/one/v2/chat?demo=1#anchor');
  expect(history.state.unrelated).toBe('kept');
});
it('keeps floating chat and unknown fallback inside its deployment', () => {
  window.__NERVA_BASE_PATH__ = '/one';
  history.replaceState(null, '', '/one/v2/unknown?desktop=floating&demo=1');
  const {result} = renderHook(() => useHudRoute(true));
  expect(result.current.route.mode).toBe('chat');
  expect(location.pathname + location.search).toBe('/one/v2/chat?desktop=floating&demo=1');
});
it('matches prefix boundaries and leaves external and blob links alone', () => {
  window.__NERVA_BASE_PATH__ = '/one';
  expect(logicalPath('/one/v2/chat')).toBe('/v2/chat');
  expect(logicalPath('/one2/v2/chat')).toBeNull();
  expect(internalLink('/api/images/a')).toBe('/one/api/images/a');
  for (const url of ['https://world.test/x', '//world.test/x', 'blob:https://example.test/x', '#anchor']) expect(internalLink(url)).toBe(url);
});
it('preserves one-attempt credentials and streams from the prefixed endpoint', async () => {
  window.__NERVA_BASE_PATH__ = '/one'; setToken('local-test-token');
  const fetch = vi.fn().mockResolvedValueOnce(new Response('{}')).mockResolvedValueOnce(new Response('data: {"text":"ready"}\n\n'));
  vi.stubGlobal('fetch', fetch);
  await apiFetchOnce('/api/media/propose', {method:'POST', body:{text:'draft'}});
  expect(fetch.mock.calls[0]).toEqual(['/one/api/media/propose', expect.objectContaining({redirect:'error', credentials:'same-origin', headers:expect.objectContaining({'X-User-Token':'local-test-token'})})]);
  const events: unknown[] = []; await postStream('/chat/stream', {text:'test'}, e => events.push(e));
  expect(fetch.mock.calls[1][0]).toBe('/one/chat/stream');
  expect(events).toEqual([{text:'ready'}]);
});

import { appUrl } from '../base-path';
it('refuses non-logical transport inputs instead of joining them to a deployment', () => {
  window.__NERVA_BASE_PATH__ = '/one';
  for (const value of ['https://other.test/api', '//other.test/api', 'relative', '/\\other.test', '/bad\npath']) {
    expect(() => appUrl(value)).toThrow('logical root path required');
  }
});
