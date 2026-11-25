/* Titles come from the page registry and only Glance is an overlay (PHASE_B_PLAN.md §3.4).
   hud-routing.test.tsx pins the routes themselves; the HUD v2 titles (`… · Console · Nerva`) and
   its World and Console overlays went with the classic shell (stage 5). */
import React from 'react';
import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { CONSOLE_PANELS } from '../console-routes';
import { HUD_MODES, closeHudOverlay, navigateHud, parseHudRoute, useHudRoute } from '../hud-routing';
import { pageTitle } from '../nav/routes';

beforeEach(() => { history.replaceState(null, '', '/v2/cockpit'); });
afterEach(() => { history.replaceState(null, '', '/'); localStorage.clear(); });

describe('titles', () => {
  it('come from pageTitle for every mode and panel; no "· Console ·" title is left', () => {
    for (const mode of HUD_MODES) {
      const route = parseHudRoute(`/v2/${mode}`);
      expect(route.title, mode).toBe(pageTitle(route));
      expect(route.title, mode).toMatch(/ · Nerva$/);
    }
    for (const panel of CONSOLE_PANELS) {
      const route = parseHudRoute(`/v2/console/${panel.id}`);
      expect(route.title, panel.id).toBe(pageTitle(route));
      expect(route.title, panel.id).not.toContain('Console');
    }
    expect(parseHudRoute('/v2/cockpit').title).toBe('Today · Nerva');
    expect(parseHudRoute('/v2/trust').title).toBe('Trust · Nerva');
    expect(parseHudRoute('/v2/console/payments').title).toBe('Payments · Trust · Nerva');
    expect(parseHudRoute('/v2/console').title).toBe('All pages · Nerva');
    expect(parseHudRoute('/v2/nowhere').title).toBe('Today · Nerva');
    expect(parseHudRoute('/v2/trust', '', '', true).title).toBe('Conversation · Home · Nerva');
  });

  it('are set on the document in the owner\'s language', () => {
    history.replaceState(null, '', '/v2/console/payments');
    function Probe({ lang }: { lang: string }) { useHudRoute(false, lang); return null; }
    const { rerender } = render(<Probe lang="en" />);
    expect(document.title).toBe('Payments · Trust · Nerva');
    rerender(<Probe lang="ro" />);
    expect(document.title).toMatch(/ · Încredere · Nerva$/);
  });
});

describe('overlays', () => {
  it('make World and the Console ordinary pages: no return record, Back walks plain history', () => {
    navigateHud('/v2/world');
    expect(history.state?.__nervaHudRoute).toBeUndefined();
    navigateHud('/v2/console/logs');
    expect(history.state?.__nervaHudRoute).toBeUndefined();
    navigateHud('/v2/console');
    expect(history.state?.__nervaHudRoute).toBeUndefined();
  });

  it('keep Glance as the one overlay, and Esc returns to where the owner was', () => {
    navigateHud('/v2/trust');
    navigateHud('/v2/glance');
    expect(history.state.__nervaHudRoute).toEqual({ path: '/v2/trust', parent: null });
    act(() => closeHudOverlay());
    expect(location.pathname).toBe('/v2/trust');
  });

  it('send a direct load of Glance back to the cockpit', () => {
    history.replaceState(null, '', '/v2/glance');
    act(() => closeHudOverlay());
    expect(location.pathname).toBe('/v2/cockpit');
  });
});

describe('a browser that still carries the deleted switch\'s classic word', () => {
  it('gets the same titles and the same overlays: there is one frame', () => {
    history.replaceState(null, '', '/v2/cockpit?frame=classic');
    localStorage.setItem('hud.frame', 'classic');
    expect(parseHudRoute('/v2/console/payments').title).toBe('Payments · Trust · Nerva');
    expect(parseHudRoute('/v2/nowhere').title).toBe('Today · Nerva');
    navigateHud('/v2/world');
    expect(history.state?.__nervaHudRoute).toBeUndefined();
    expect(location.search).toBe('?frame=classic');   // the context is kept, and means nothing
  });
});
