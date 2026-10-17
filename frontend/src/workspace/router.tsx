/* A small path router for /workspace/… (no dependency, spec §10).

   Locations are kept logical inside the app — "/admin/users" — and mapped to the public URL with
   base-path.ts, so the same bundle works at the host root and behind a path prefix such as
   /nerva (the server injects window.__NERVA_BASE_PATH__). Patterns use ":name" segments;
   matching is exact, segment by segment, and parameters are URI-decoded. */
import React, { useEffect, useSyncExternalStore } from 'react';
import { appUrl, logicalPath } from '../base-path';

const APP_PREFIX = '/workspace';
const NAVIGATE_EVENT = 'nerva-workspace:navigate';

export interface Location { path: string; search: string; hash: string }

/** The in-app path for a browser pathname, or null when the URL is outside the Workspace. */
export function toAppPath(pathname: string): string | null {
  const logical = logicalPath(pathname);
  if (logical === null) return null;
  if (logical === APP_PREFIX || logical === `${APP_PREFIX}/`) return '/';
  if (!logical.startsWith(`${APP_PREFIX}/`)) return null;
  const inner = logical.slice(APP_PREFIX.length);
  return inner.length > 1 && inner.endsWith('/') ? inner.replace(/\/+$/, '') : inner;
}

/** Public URL of an in-app location ("/admin/users?x=1" → "<base>/workspace/admin/users?x=1"). */
export function hrefFor(to: string): string {
  const path = to.startsWith('/') ? to : `/${to}`;
  return appUrl(path === '/' ? `${APP_PREFIX}/` : `${APP_PREFIX}${path}`);
}

/** Maps a server-provided link (a notification's `link`) to an in-app path, when it is one. */
export function appPathFromLink(link: string): string | null {
  if (!link || !link.startsWith('/') || link.startsWith('//')) return null;
  const cut = link.search(/[?#]/);
  const pathPart = cut === -1 ? link : link.slice(0, cut);
  const rest = cut === -1 ? '' : link.slice(cut);
  // Accept both a logical link ("/workspace/…") and one that already carries the root path.
  try {
    const inner = toAppPath(pathPart) ?? toAppPath(appUrl(pathPart));
    return inner === null ? null : inner + rest;
  } catch {
    return null;  // appUrl refuses backslashes and control characters: not a link we follow
  }
}

let snapshot: Location | null = null;

function readLocation(): Location {
  const { pathname, search, hash } = window.location;
  const path = toAppPath(pathname) ?? `\u0000${pathname}`;
  if (!snapshot || snapshot.path !== path || snapshot.search !== search || snapshot.hash !== hash) {
    snapshot = { path, search, hash };
  }
  return snapshot;
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener('popstate', onChange);
  window.addEventListener(NAVIGATE_EVENT, onChange);
  return () => {
    window.removeEventListener('popstate', onChange);
    window.removeEventListener(NAVIGATE_EVENT, onChange);
  };
}

/** The in-app path of the last `quiet` navigation, until the shell consumes it. */
let quietPath: string | null = null;

/**
 * `quiet`: the page is updating its own URL in place (a new conversation got its id, a drawer
 * opened or closed) — the shell keeps focus where the user is instead of moving it to the
 * page heading as it does for a real page change.
 */
export function navigate(to: string, opts: { replace?: boolean; quiet?: boolean } = {}): void {
  const url = hrefFor(to);
  quietPath = opts.quiet ? toAppPath(new URL(url, window.location.origin).pathname) : null;
  if (opts.replace) window.history.replaceState(null, '', url);
  else window.history.pushState(null, '', url);
  window.dispatchEvent(new Event(NAVIGATE_EVENT));
}

/** True when the shell's path change at *path* came from a quiet navigation (read once). */
export function consumeQuietNavigation(path: string): boolean {
  const quiet = quietPath !== null && quietPath === path;
  quietPath = null;
  return quiet;
}

/** The current location; `path` starts with "\0" when the URL is not a Workspace page. */
export function useLocation(): Location {
  return useSyncExternalStore(subscribe, readLocation, readLocation);
}

export function isOutsideApp(location: Location): boolean {
  return location.path.startsWith('\u0000');
}

export type Params = Record<string, string>;

export function matchRoute(pattern: string, path: string): Params | null {
  const want = pattern.split('/').filter(Boolean);
  const have = path.split('/').filter(Boolean);
  if (want.length !== have.length) return null;
  const params: Params = {};
  for (let i = 0; i < want.length; i += 1) {
    if (want[i].startsWith(':')) {
      try {
        params[want[i].slice(1)] = decodeURIComponent(have[i]);
      } catch {
        return null;
      }
    } else if (want[i] !== have[i]) {
      return null;
    }
  }
  return params;
}

export interface RouteDef {
  path: string;
  render: (params: Params) => React.ReactNode;
}

export function resolveRoute(routes: RouteDef[], path: string): { route: RouteDef; params: Params } | null {
  for (const route of routes) {
    const params = matchRoute(route.path, path);
    if (params) return { route, params };
  }
  return null;
}

/** Navigates once on mount (e.g. "/" → "/assistant"), replacing the history entry. */
export function Redirect({ to }: { to: string }) {
  useEffect(() => { navigate(to, { replace: true }); }, [to]);
  return null;
}

export interface LinkProps extends Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, 'href'> {
  to: string;
}

/** An anchor with a real href (open in a new tab works) that navigates in-app on a plain click. */
export function Link({ to, onClick, target, ...rest }: LinkProps) {
  return (
    <a
      href={hrefFor(to)}
      target={target}
      onClick={(event) => {
        onClick?.(event);
        if (event.defaultPrevented || event.button !== 0 || target === '_blank') return;
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        navigate(to);
      }}
      {...rest}
    />
  );
}

/** Sets the document title as "<page> · Nerva Workspace". */
export function useDocumentTitle(title: string): void {
  useEffect(() => {
    document.title = title ? `${title} · Nerva Workspace` : 'Nerva Workspace';
  }, [title]);
}
