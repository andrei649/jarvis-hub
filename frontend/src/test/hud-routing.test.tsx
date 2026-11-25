/* HUD URLs (PHASE_B_PLAN.md §3.4, §8.3): route validity is unchanged; titles come from the page
   registry (`<Page> · <Area> · Nerva`, the `· Console ·` titles are gone); World and the Console
   are ordinary pages, so Back and Forward walk plain history, and Glance is the one overlay whose
   close returns to where the owner was. */
import React from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import { parseHudRoute, useHudRoute, navigateHud, closeHudOverlay, routeHref, HUD_MODES } from '../hud-routing';
import { CONSOLE_PANELS } from '../console-routes';
import { useDemoMode } from '../demo-mode';
import { areaById, pageForPanel } from '../nav/areas';

beforeEach(() => window.history.replaceState(null, '', '/v2/'));

describe('HUD URLs', () => {
  it('initializes every registered mode from a reloadable URL', () => {
    for (const mode of HUD_MODES) {
      const route = parseHudRoute(`/v2/${mode}`);
      expect(route).toMatchObject({ mode, valid: true, path: `/v2/${mode}` });
      expect(route.title).toContain('Nerva');
    }
  });
  it('registers every console panel with unique explicit addresses', () => {
    expect(CONSOLE_PANELS.length).toBeGreaterThan(100);
    expect(new Set(CONSOLE_PANELS.map(p => p.id)).size).toBe(CONSOLE_PANELS.length);
    for (const panel of CONSOLE_PANELS) {
      // titled as a page of its area: `<Page> · <Area> · Nerva`, from the registry's labels
      const entry = pageForPanel(panel.id);
      const area = areaById(entry?.area);
      expect(entry, panel.id).not.toBeNull();
      expect(area, panel.id).not.toBeNull();
      const title = `${entry!.label.en} · ${area!.label.en} · Nerva`;
      expect(parseHudRoute(`/v2/console/${panel.id}`)).toMatchObject({ mode: 'console', panel: panel.id, valid: true, title });
      expect(title, panel.id).not.toContain('Console');
    }
  });
  it.each(['/v2/missing', '/v2/console/no-such-panel', '/v2/chat/extra', '/v2/%ZZ', '/elsewhere'])('rejects unknown path %s', path => {
    expect(parseHudRoute(path)).toMatchObject({ valid: false, mode: 'cockpit', path: '/v2/cockpit' });
  });
  it('keeps console index distinct from the selected panel', () => {
    expect(parseHudRoute('/v2/console')).toMatchObject({ valid: true, mode: 'console', panel: null, title: 'All pages · Nerva' });
  });
  it('supports root aliases and legacy world links', () => {
    expect(parseHudRoute('/v2/')).toMatchObject({ mode: 'cockpit', valid: true });
    expect(parseHudRoute('/v2', '?world=1')).toMatchObject({ mode: 'world', valid: true });
    expect(parseHudRoute('/v2/', '', '#world')).toMatchObject({ mode: 'world', valid: true });
    expect(parseHudRoute('/v2/chat', '?world=1', '#world').mode).toBe('chat');
  });
  it('keeps floating chat truthful even with a different bookmark', () => {
    expect(parseHudRoute('/v2/', '?desktop=floating', '', true).mode).toBe('chat');
    expect(parseHudRoute('/v2/memory', '?desktop=floating', '', true)).toMatchObject({ mode: 'chat', valid: false });
  });
  it('preserves unrelated query and hash while clearing old World toggles', () => {
    expect(routeHref('/v2/chat', 'http://localhost/v2/?demo=1&desktop=floating&keep=ok#anchor')).toBe('/v2/chat?demo=1&desktop=floating&keep=ok#anchor');
    expect(routeHref('/v2/chat', 'http://localhost/v2/?world=1&demo=1#world')).toBe('/v2/chat?demo=1');
    expect(routeHref('/v2/chat', 'http://localhost/v2/console/pending-skills#skill=print-proof')).toBe('/v2/chat');
  });
  it('replaces root/unknown routes, updates titles and reports unknown URLs', async () => {
    window.history.replaceState(null, '', '/v2/console/unknown?demo=1#anchor');
    const { result } = renderHook(() => useHudRoute());
    await waitFor(() => expect(window.location.pathname).toBe('/v2/cockpit'));
    expect(result.current.notice).toContain('not found');
    expect(window.location.search).toBe('?demo=1');
    expect(document.title).toBe('Today · Nerva');
  });
  it('pushes navigation once, restores Back/Forward and survives remount', async () => {
    const { result, unmount } = renderHook(() => useHudRoute());
    act(() => navigateHud('/v2/memory'));
    expect(result.current.route.mode).toBe('memory');
    expect(document.title).toBe('Memory · Nerva');
    const length = history.length;
    act(() => navigateHud('/v2/memory'));
    expect(history.length).toBe(length);
    act(() => navigateHud('/v2/console/decision-inbox'));
    expect(document.title).toBe('Decisions · Work · Nerva');
    act(() => history.back());
    await waitFor(() => expect(result.current.route.mode).toBe('memory'));
    await waitFor(() => expect(document.title).toBe('Memory · Nerva'));
    act(() => history.forward());
    await waitFor(() => expect(result.current.route.panel).toBe('decision-inbox'));
    unmount();
    const reloaded = renderHook(() => useHudRoute());
    expect(reloaded.result.current.route.panel).toBe('decision-inbox');
    expect(document.title).toBe('Decisions · Work · Nerva');
  });
  it('keeps demo query toggles and popstate compatible with navigation', async () => {
    const { result } = renderHook(() => ({ routing: useHudRoute(), demo: useDemoMode() }));
    act(() => result.current.demo[1](true));
    act(() => navigateHud('/v2/agents'));
    expect(window.location.search).toBe('?demo=1');
    act(() => { history.pushState(null, '', '/v2/chat'); window.dispatchEvent(new PopStateEvent('popstate')); });
    expect(result.current.demo[0]).toBe(false);
    expect(result.current.routing.route.mode).toBe('chat');
  });
});


describe('overlay entry return destinations', () => {
  it('returns Glance to the invoking page with its query, hash and unrelated state, across remount', () => {
    history.replaceState({ foreign: { selected: 42 } }, '', '/v2/chat?keep=1#anchor');
    const first = renderHook(() => ({ routing: useHudRoute(), demo: useDemoMode() }));
    act(() => navigateHud('/v2/glance'));
    expect(location.pathname).toBe('/v2/glance');
    act(() => first.result.current.demo[1](true));
    expect(history.state.foreign).toEqual({ selected: 42 });
    first.unmount();
    // Browser reload retains the history entry but loses component refs.
    renderHook(() => useHudRoute());
    act(() => closeHudOverlay());
    expect(location.pathname).toBe('/v2/chat');
    expect(location.search).toBe('?keep=1&demo=1');
    expect(location.hash).toBe('#anchor');
    expect(history.state.foreign).toEqual({ selected: 42 });
  });
  it.each(['/v2/world', '/v2/console/decision-inbox'])('makes %s an ordinary page: no return record, and Back restores the invoking page and its state across remount', async path => {
    history.replaceState({ foreign: { selected: 42 } }, '', '/v2/chat?keep=1#anchor');
    const first = renderHook(() => useHudRoute());
    act(() => navigateHud(path));
    expect(location.pathname).toBe(path);
    expect(history.state.foreign).toEqual({ selected: 42 });
    expect(history.state.__nervaHudRoute).toBeUndefined();
    first.unmount();
    // Browser reload retains the history entry but loses component refs.
    const reloaded = renderHook(() => useHudRoute());
    act(() => history.back());
    await waitFor(() => expect(reloaded.result.current.route.mode).toBe('chat'));
    expect(location.pathname).toBe('/v2/chat');
    expect(location.search).toBe('?keep=1');
    expect(location.hash).toBe('#anchor');
    expect(history.state.foreign).toEqual({ selected: 42 });
  });
  it.each(['/v2/glance', '/v2/world', '/v2/console/decision-inbox'])('closes a direct bookmark at %s to cockpit', path => {
    history.replaceState({ foreign: 'untouched' }, '', path + '?demo=1');
    renderHook(() => useHudRoute());
    act(() => closeHudOverlay());
    expect(location.pathname).toBe('/v2/cockpit');
    expect(history.state.foreign).toBe('untouched');
  });
  it('returns Glance to the page it was opened from after moving between pages, which Back walks as plain history', async () => {
    history.replaceState(null, '', '/v2/chat');
    const { result } = renderHook(() => useHudRoute());
    act(() => navigateHud('/v2/world'));
    act(() => navigateHud('/v2/console'));
    act(() => navigateHud('/v2/console/decision-inbox'));
    // moving between pages (World, All pages, a panel) writes no return record
    expect(history.state?.__nervaHudRoute).toBeUndefined();
    act(() => navigateHud('/v2/glance'));
    // Glance again from Glance is the same entry and keeps where it returns to
    const length = history.length;
    act(() => navigateHud('/v2/glance'));
    expect(history.length).toBe(length);
    expect(history.state.__nervaHudRoute).toEqual({ path: '/v2/console/decision-inbox', parent: null });
    // Back walks the pages one by one, as the browser keeps them
    act(() => history.back());
    await waitFor(() => expect(result.current.route.panel).toBe('decision-inbox'));
    act(() => history.back());
    await waitFor(() => expect(location.pathname).toBe('/v2/console'));
    expect(result.current.route).toMatchObject({ mode: 'console', panel: null });
    act(() => history.back());
    await waitFor(() => expect(result.current.route.mode).toBe('world'));
    act(() => history.back());
    await waitFor(() => expect(result.current.route.mode).toBe('chat'));
    // Forward to Glance again, and its close returns to the page it was opened from
    act(() => history.go(4));
    await waitFor(() => expect(result.current.route.mode).toBe('glance'));
    act(() => closeHudOverlay());
    expect(location.pathname).toBe('/v2/console/decision-inbox');
  });
});
