import { describe, expect, it } from 'vitest';
import { CONSOLE_PANELS } from '../console-routes';
import { HUD_MODES, parseHudRoute } from '../hud-routing';
import { stringProblems } from '../frame/strings';
import { ALL_PAGES, PAGES } from './areas';
import { ROUTE_STRINGS, areaAnchor, areaOfMode, areaOfPanel, landingPath, pageForRoute, pageTitle, pathOf } from './routes';

const at = (path: string, search = '', hash = '') => pageForRoute(parseHudRoute(path, search, hash));

describe('pageForRoute', () => {
  it('resolves every mode route, the four new views included', () => {
    for (const mode of HUD_MODES) {
      const page = at(`/v2/${mode}`);
      expect(page.entry.ref, mode).toEqual({ kind: 'mode', id: mode });
      expect(page.area, mode).not.toBeNull();
      expect(page.kind, mode).toBe(mode === 'cockpit' ? 'home' : mode === 'chat' ? 'chat' : mode === 'glance' ? 'glance' : 'mode');
    }
    for (const view of ['work', 'timeline', 'artifacts', 'glance']) expect(parseHudRoute(`/v2/${view}`).valid, view).toBe(true);
  });

  it('resolves every Console panel to its area, and the Console index to All pages', () => {
    for (const panel of CONSOLE_PANELS) {
      const page = at(`/v2/console/${panel.id}`);
      expect(page.kind, panel.id).toBe('panel');
      expect(page.entry.ref, panel.id).toEqual({ kind: 'panel', id: panel.id });
      expect(page.area?.id, panel.id).toBe(areaOfPanel(panel.id));
      expect(page.group?.pages, panel.id).toContain(page.entry);
    }
    expect(at('/v2/console')).toMatchObject({ kind: 'allPages', area: null, entry: ALL_PAGES, group: null });
  });

  it('keeps the root, the removed World links and unknown URLs on Home', () => {
    expect(at('/v2')).toMatchObject({ kind: 'home', area: { id: 'home' } });
    expect(at('/v2/')).toMatchObject({ kind: 'home' });
    expect(at('/v2/', '?world=1')).toMatchObject({ kind: 'home', entry: { key: 'mode:cockpit' } });
    expect(at('/v2/', '', '#world')).toMatchObject({ kind: 'home', entry: { key: 'mode:cockpit' } });
    expect(at('/v2/world')).toMatchObject({ kind: 'home', entry: { key: 'mode:cockpit' } });
    expect(at('/v2/no-such-page')).toMatchObject({ kind: 'home', entry: { key: 'mode:cockpit' } });
    expect(at('/v2/console/no-such-panel')).toMatchObject({ kind: 'home' });
    expect(pageForRoute({ mode: 'not-a-mode', panel: null })).toMatchObject({ kind: 'home' });
    expect(pageForRoute({ mode: 'console', panel: 'not-a-panel' })).toMatchObject({ kind: 'home' });
  });

  it('round-trips every page through its path', () => {
    for (const entry of [...PAGES, ALL_PAGES]) {
      const route = parseHudRoute(pathOf(entry.ref));
      expect(route.valid, entry.key).toBe(true);
      expect(pageForRoute(route).entry.key, entry.key).toBe(entry.key);
    }
    expect(pathOf({ kind: 'mode', id: 'work' })).toBe('/v2/work');
    expect(pathOf({ kind: 'panel', id: 'decision-inbox' })).toBe('/v2/console/decision-inbox');
    expect(pathOf({ kind: 'allPages' })).toBe('/v2/console');
    expect(landingPath('connect')).toBe('/v2/interop');
    expect(landingPath('settings')).toBe('/v2/admin');
    expect(landingPath('home')).toBe('/v2/cockpit');
  });
});

describe('pageTitle (§3.4)', () => {
  const title = (path: string, lang = 'en') => pageTitle(parseHudRoute(path), lang);

  it('names Home, landing pages, sub-pages and All pages', () => {
    expect(title('/v2/cockpit')).toBe('Today · Nerva');
    expect(title('/v2/')).toBe('Today · Nerva');
    expect(title('/v2/work')).toBe('Work · Nerva');
    expect(title('/v2/interop')).toBe('Connect · Nerva');
    expect(title('/v2/admin')).toBe('Settings · Nerva');
    expect(title('/v2/chat')).toBe('Conversation · Home · Nerva');
    expect(title('/v2/glance')).toBe('Glance · Home · Nerva');
    expect(title('/v2/observe')).toBe('Observe · Nerva');
    expect(title('/v2/console/decision-inbox')).toBe('Decisions · Work · Nerva');
    expect(title('/v2/console/kill-switch')).toBe('Emergency stop · Trust · Nerva');
    expect(title('/v2/console')).toBe('All pages · Nerva');
  });

  it('speaks Romanian', () => {
    expect(title('/v2/cockpit', 'ro')).toBe('Azi · Nerva');
    expect(title('/v2/console/decision-inbox', 'ro')).toBe('Decizii · Lucru · Nerva');
    expect(title('/v2/console', 'ro')).toBe('Toate paginile · Nerva');
    expect(stringProblems(ROUTE_STRINGS)).toEqual([]);
  });

  it('never says Console in a page title any more', () => {
    for (const panel of CONSOLE_PANELS) expect(title(`/v2/console/${panel.id}`), panel.id).not.toContain('· Console ·');
    for (const mode of HUD_MODES) expect(title(`/v2/${mode}`), mode).toMatch(/ · Nerva$/);
  });
});

describe('areas of modes and panels', () => {
  it('follow the registry', () => {
    expect(areaOfMode('observe')).toBe('observe');
    expect(areaOfMode('world')).toBeNull();
    expect(areaOfMode('comms')).toBe('connect');
    expect(areaOfMode('jobs')).toBe('work');
    expect(areaOfMode('artifacts')).toBe('memory');
    expect(areaOfMode('glance')).toBe('home');
    expect(areaOfMode('finance')).toBe('agents');
    expect(areaOfMode('console')).toBeNull();
    expect(areaOfPanel('kill-switch')).toBe('trust');
    expect(areaOfPanel('o-auth')).toBe('connect');
    expect(areaOfPanel('templates')).toBe('agents');
    expect(areaOfPanel('no-such-panel')).toBeNull();
    expect(areaAnchor('work')).toBe('area.work');
  });
});
