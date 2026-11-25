import { appUrl, logicalPath } from './base-path';
import { useEffect, useState, useSyncExternalStore } from 'react';
import { CONSOLE_PANELS, CONSOLE_PANEL_MAP } from './console-routes';

import { HUD_MODES, HUD_MODES_SET } from './hud-modes';
import { pageTitle } from './nav/routes';
export { HUD_MODES, HUD_MODES_SET } from './hud-modes';
export type HudRoute = { mode: string; panel: string | null; path: string; title: string; valid: boolean };
const CHANGE = 'nerva-route-change';

export function parseHudRoute(pathname: string, search = '', hash = '', floating = false): HudRoute {
  const fallback = floating ? 'chat' : 'cockpit';
  const root = pathname === '/' || pathname === '/v2' || pathname === '/v2/';
  const legacyWorld = root && (new URLSearchParams(search).get('world') === '1' || hash === '#world');
  const path = root ? `/v2/${floating ? 'chat' : legacyWorld ? 'world' : fallback}` : pathname.replace(/\/$/, '');
  const parts = path.split('/');
  const mode = parts[2];
  // Bolt Optimization: O(1) Map lookup via CONSOLE_PANEL_MAP avoids O(120) array scan on every route parse call
  const panel = mode === 'console' && parts.length === 4 ? CONSOLE_PANEL_MAP.get(parts[3]) || null : null;
  // Bolt Optimization: O(1) Set lookup via HUD_MODES_SET avoids O(N) array scan on every route parse call
  const valid = parts[1] === 'v2' && (!floating || mode === 'chat') && (
    (parts.length === 3 && (HUD_MODES_SET.has(mode) || mode === 'console')) || !!panel
  );
  // Titles come from the page registry (PHASE_B_PLAN.md §3.4), in English here; useHudRoute()
  // titles the document in the owner's language.
  if (!valid) {
    return { mode: fallback, panel: null, path: `/v2/${fallback}`, title: pageTitle({ mode: fallback, panel: null }), valid: false };
  }
  return { mode, panel: panel?.id || null, path, valid: true, title: pageTitle({ mode, panel: panel?.id || null }) };
}

export function routeHref(path: string, href = window.location.href): string {
  const url = new URL(href, window.location.origin);
  if (logicalPath(url.pathname) === '/v2/console/pending-skills' && path !== '/v2/console/pending-skills'
      && url.hash.startsWith('#skill=')) url.hash = '';
  url.pathname = appUrl(path);
  // Legacy World toggles are consumed by routing; all other context is preserved.
  url.searchParams.delete('world');
  if (url.hash === '#world') url.hash = '';
  return `${url.pathname}${url.search}${url.hash}`;
}

/** The href of a page reached from a list of pages (the contents column, All pages): routeHref(), but
 *  without what belongs to the page being left: a Decisions `card` and the hash (a docket entry, a
 *  skill). The rest of the context (?demo=1, …) is kept. */
export function pageHref(path: string, href = window.location.href): string {
  const url = new URL(href, window.location.origin);
  url.searchParams.delete('card');
  url.hash = '';
  return routeHref(path, url.toString());
}

const HISTORY_ROUTE = '__nervaHudRoute';
type OverlayReturn = { path: string; parent: OverlayReturn | null };
// World and All pages are ordinary pages and Glance is the one overlay (PHASE_B_PLAN.md §3.4), so
// Back and Forward walk ordinary history and only Glance remembers where to return to.
function isOverlay(mode: string) { return mode === 'glance'; }
function historyRecord(): Record<string, unknown> {
  const state = window.history.state;
  // Keep unrelated state fields, and retain non-record state without coercing it.
  return state && Object.getPrototypeOf(state) === Object.prototype
    ? state : { __nervaHudOriginalState: state };
}
function writeNavigation(path: string, replace: boolean, state: unknown, page = false): void {
  const href = page ? pageHref(path) : routeHref(path);
  if (href === snapshot()) return;
  window.history[replace ? 'replaceState' : 'pushState'](state, '', href);
  notifyHudRouteChange();
}
/** In-app navigation to a page picked from a page (the contents column, All pages, a page's own
 *  links): the address its link's href names (pageHref), so a click and an open-in-new-tab land on
 *  the same page — without the Decisions `card` or the hash of the page being left, which would
 *  otherwise follow the owner from page to page. Glance (the one overlay) keeps navigateHud's
 *  return record, so it goes through navigateHud. */
export function navigatePage(path: string): void {
  if (isOverlay(parseHudRoute(path).mode)) { navigateHud(path); return; }
  writeNavigation(path, false, window.history.state, true);
}
export function navigateHud(path: string, replace = false): void {
  const current = parseHudRoute(logicalPath(window.location.pathname) ?? '', window.location.search, window.location.hash);
  const target = parseHudRoute(path);
  let state = window.history.state;
  if (target.valid && isOverlay(target.mode) && current.mode !== target.mode) {
    // Each entry owns its origin. Panel-to-panel navigation keeps the same origin;
    // entering another overlay snapshots the return chain rather than a global ref.
    state = { ...historyRecord(), [HISTORY_ROUTE]: {
      path: current.path,
      parent: isOverlay(current.mode) ? state?.[HISTORY_ROUTE] || null : null,
    } satisfies OverlayReturn };
  }
  writeNavigation(path, replace, state);
}
export function closeHudOverlay(): void {
  const current = parseHudRoute(logicalPath(window.location.pathname) ?? '');
  const origin = window.history.state?.[HISTORY_ROUTE] as OverlayReturn | undefined;
  const target = typeof origin?.path === 'string' ? parseHudRoute(origin.path) : null;
  const validReturn = target?.valid && target.mode !== current.mode;
  // Restoring the parent's metadata also handles a history entry written before World and the
  // Console became pages. A shared link without entry metadata always has a deterministic close
  // target.
  const state = { ...historyRecord(), [HISTORY_ROUTE]: validReturn ? origin.parent : null };
  writeNavigation(validReturn ? target.path : '/v2/cockpit', false, state);
}
export function notifyHudRouteChange() { window.dispatchEvent(new Event(CHANGE)); }
function snapshot() { return window.location.pathname + window.location.search + window.location.hash; }
function subscribe(update: () => void) {
  window.addEventListener('popstate', update);
  window.addEventListener(CHANGE, update);
  return () => { window.removeEventListener('popstate', update); window.removeEventListener(CHANGE, update); };
}
/** `lang` titles the document (the registry's labels are in both languages). */
export function useHudRoute(floating = false, lang: string = 'en') {
  const href = useSyncExternalStore(subscribe, snapshot, () => '/v2/');
  const url = new URL(href, window.location.origin);
  const route = parseHudRoute(logicalPath(url.pathname) ?? '', url.search, url.hash, floating);
  const [notice, setNotice] = useState('');
  useEffect(() => {
    if (!route.valid) setNotice('Page not found. Returned to ' + route.mode + '.');
    document.title = pageTitle(route, lang);
    if (url.pathname !== appUrl(route.path)) navigateHud(route.path, true);
  }, [href, floating, lang]);
  return { route, navigate: navigateHud, notice, dismissNotice: () => setNotice('') };
}
