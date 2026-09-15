import React from 'react';
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, beforeEach } from 'vitest';
import { parseHudRoute, useHudRoute, navigateHud, closeHudOverlay, routeHref, HUD_MODES } from '../hud-routing';
import { CONSOLE_PANELS } from '../console-routes';
import { useDemoMode } from '../demo-mode';

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
      expect(parseHudRoute(`/v2/console/${panel.id}`)).toMatchObject({ mode: 'console', panel: panel.id, valid: true, title: `${panel.label} · Console · Nerva` });
    }
  });
  it.each(['/v2/missing', '/v2/console/no-such-panel', '/v2/chat/extra', '/v2/%ZZ', '/elsewhere'])('rejects unknown path %s', path => {
    expect(parseHudRoute(path)).toMatchObject({ valid: false, mode: 'cockpit', path: '/v2/cockpit' });
  });
  it('keeps console index distinct from the selected panel', () => {
    expect(parseHudRoute('/v2/console')).toMatchObject({ valid: true, mode: 'console', panel: null });
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
  });
  it('replaces root/unknown routes, updates titles and reports unknown URLs', async () => {
    window.history.replaceState(null, '', '/v2/console/unknown?demo=1#anchor');
    const { result } = renderHook(() => useHudRoute());
    await waitFor(() => expect(window.location.pathname).toBe('/v2/cockpit'));
    expect(result.current.notice).toContain('not found');
    expect(window.location.search).toBe('?demo=1');
    expect(document.title).toBe('Cockpit · Nerva');
  });
  it('pushes navigation once, restores Back/Forward and survives remount', async () => {
    const { result, unmount } = renderHook(() => useHudRoute());
    act(() => navigateHud('/v2/memory'));
    expect(result.current.route.mode).toBe('memory');
    const length = history.length;
    act(() => navigateHud('/v2/memory'));
    expect(history.length).toBe(length);
    act(() => navigateHud('/v2/console/decision-inbox'));
    expect(document.title).toBe('Decision Inbox · Console · Nerva');
    act(() => history.back());
    await waitFor(() => expect(result.current.route.mode).toBe('memory'));
    act(() => history.forward());
    await waitFor(() => expect(result.current.route.panel).toBe('decision-inbox'));
    unmount();
    const reloaded = renderHook(() => useHudRoute());
    expect(reloaded.result.current.route.panel).toBe('decision-inbox');
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
  it.each(['/v2/world', '/v2/console/decision-inbox'])('preserves the invoking mode and unrelated state across remount at %s', path => {
    history.replaceState({ foreign: { selected: 42 } }, '', '/v2/chat?keep=1#anchor');
    const first = renderHook(() => ({ routing: useHudRoute(), demo: useDemoMode() }));
    act(() => navigateHud(path));
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
  it.each(['/v2/world', '/v2/console/decision-inbox'])('closes a direct bookmark at %s to cockpit', path => {
    history.replaceState({ foreign: 'untouched' }, '', path + '?demo=1');
    renderHook(() => useHudRoute());
    act(() => closeHudOverlay());
    expect(location.pathname).toBe('/v2/cockpit');
    expect(history.state.foreign).toBe('untouched');
  });
  it('preserves the return chain when moving between overlays and console panels', () => {
    history.replaceState(null, '', '/v2/chat');
    renderHook(() => useHudRoute());
    act(() => navigateHud('/v2/world'));
    act(() => navigateHud('/v2/console'));
    act(() => navigateHud('/v2/console/decision-inbox'));
    act(() => navigateHud('/v2/world'));
    act(() => closeHudOverlay());
    expect(location.pathname).toBe('/v2/console/decision-inbox');
    act(() => closeHudOverlay());
    expect(location.pathname).toBe('/v2/world');
    act(() => closeHudOverlay());
    expect(location.pathname).toBe('/v2/chat');
  });
});
