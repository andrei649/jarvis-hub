import { appUrl, logicalPath } from './base-path';
import { useEffect, useState, useSyncExternalStore } from 'react';
import { CONSOLE_PANELS } from './console-routes';

import { HUD_MODES } from './hud-modes';
export { HUD_MODES } from './hud-modes';
export type HudRoute = { mode: string; panel: string | null; path: string; title: string; valid: boolean };
const CHANGE = 'nerva-route-change';

export function parseHudRoute(pathname: string, search = '', hash = '', floating = false): HudRoute {
  const fallback = floating ? 'chat' : 'cockpit';
  const root = pathname === '/' || pathname === '/v2' || pathname === '/v2/';
  const legacyWorld = root && (new URLSearchParams(search).get('world') === '1' || hash === '#world');
  const path = root ? `/v2/${floating ? 'chat' : legacyWorld ? 'world' : fallback}` : pathname.replace(/\/$/, '');
  const parts = path.split('/');
  const mode = parts[2];
  const panel = mode === 'console' && parts.length === 4 ? CONSOLE_PANELS.find(p => p.id === parts[3]) : null;
  const valid = parts[1] === 'v2' && (!floating || mode === 'chat') && (
    (parts.length === 3 && (HUD_MODES.includes(mode as any) || mode === 'console')) || !!panel
  );
  if (!valid) return { mode: fallback, panel: null, path: `/v2/${fallback}`, title: `${floating ? 'Chat' : 'Cockpit'} · Nerva`, valid: false };
  return { mode, panel: panel?.id || null, path, valid: true, title: panel ? `${panel.label} · Console · Nerva` : `${mode[0].toUpperCase()}${mode.slice(1)} · Nerva` };
}

export function routeHref(path: string, href = window.location.href): string {
  const url = new URL(href, window.location.origin);
  url.pathname = appUrl(path);
  // Legacy World toggles are consumed by routing; all other context is preserved.
  url.searchParams.delete('world');
  if (url.hash === '#world') url.hash = '';
  return `${url.pathname}${url.search}${url.hash}`;
}

const HISTORY_ROUTE = '__nervaHudRoute';
type OverlayReturn = { path: string; parent: OverlayReturn | null };
function isOverlay(mode: string) { return mode === 'world' || mode === 'console'; }
function historyRecord(): Record<string, unknown> {
  const state = window.history.state;
  // Keep unrelated state fields, and retain non-record state without coercing it.
  return state && Object.getPrototypeOf(state) === Object.prototype
    ? state : { __nervaHudOriginalState: state };
}
function writeNavigation(path: string, replace: boolean, state: unknown): void {
  const href = routeHref(path);
  if (href === snapshot()) return;
  window.history[replace ? 'replaceState' : 'pushState'](state, '', href);
  notifyHudRouteChange();
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
  // Restoring the parent's metadata also handles nested World/Console visits.
  // A shared link without entry metadata always has a deterministic close target.
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
export function useHudRoute(floating = false) {
  const href = useSyncExternalStore(subscribe, snapshot, () => '/v2/');
  const url = new URL(href, window.location.origin);
  const route = parseHudRoute(logicalPath(url.pathname) ?? '', url.search, url.hash, floating);
  const [notice, setNotice] = useState('');
  useEffect(() => {
    if (!route.valid) setNotice('Page not found. Returned to ' + route.mode + '.');
    document.title = route.title;
    if (url.pathname !== appUrl(route.path)) navigateHud(route.path, true);
  }, [href, floating]);
  return { route, navigate: navigateHud, notice, dismissNotice: () => setNotice('') };
}
