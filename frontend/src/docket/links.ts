/* The docket's public face for other modules (PHASE_B_PLAN.md §5.4, §9.2.4).

   The anchor rule: a docket entry renders with id="docket-entry-<taskId>" and
   data-docket-entry="<taskId>", and the hash #docket-entry-<taskId> on /v2/cockpit opens that
   entry and scrolls to it.

   Links. Other modules link to a docket entry only through docketHref() / openDocketEntry(), and
   to the Decisions page opened on one card through decisionsHref() / openDecisionsCard() (a
   request that is not on the docket, and the special kinds decided there). The hrefs are READY
   hrefs — base path and query kept, so ?demo=1 survives — not logical paths:
   never pass them to navigateHud or routeHref, which put them into URL.pathname and so
   percent-encode their '?' and '#' (the route then fails to parse and falls back to Today). Draw
   the link as <a href={…Href(id)}> and navigate in the app with the matching open…(id) in its
   onClick (after preventDefault).

   useDocketSummary() (masthead, Glance) and useDocketTitle(id) (the conversation's approval
   slip) are the docket's two read hooks. They live in docket/useDocket.ts and are re-exported
   here; import them from here. Both read the decisions feed through the shared poller: before
   its first answer they are unknown ("Checking…"), never a 0 and never an all-clear. Each takes
   an optional `{demo}` (default: the URL's ?demo=1, which App's demo state follows). */
import { notifyHudRouteChange, routeHref } from '../hud-routing';

export { useDocketSummary, useDocketTitle } from './useDocket';

export const DOCKET_ANCHOR_PREFIX = 'docket-entry-';
/** Home, where the docket is. */
export const DOCKET_PATH = '/v2/cockpit';
/** The Decisions page (the Decision Inbox panel). */
export const DECISIONS_PATH = '/v2/console/decision-inbox';
/** The query parameter the Decision Inbox reads to open on one card (gap.tsx, H137). */
export const DECISIONS_CARD_PARAM = 'card';

/** The element id (and the hash, without '#') of a docket entry. */
export function docketAnchorId(taskId: number | string): string {
  return `${DOCKET_ANCHOR_PREFIX}${taskId}`;
}

/** The task id a location hash names ('#docket-entry-42' → 42), or null. */
export function docketTaskFromHash(hash: string): number | null {
  const match = /^#docket-entry-(\d{1,15})$/.exec(hash || '');
  if (!match) return null;
  const id = Number(match[1]);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

/** `path` as routeHref writes it (base path, the query kept), with the query adjusted and the
 *  hash replaced. The query is re-serialised only when `query` changes it. */
function hrefTo(path: string, query: (params: URLSearchParams) => void, hash: string): string {
  const url = new URL(routeHref(path), window.location.origin);
  query(url.searchParams);
  url.hash = hash;
  return `${url.pathname}${url.search}${url.hash}`;
}

/** A ready href for an <a> to a docket entry: Home (base path and query kept, so ?demo=1
 *  survives; a Decisions `card` is dropped) with the entry's hash. Not a logical path: navigate
 *  with openDocketEntry(), never navigateHud. */
export function docketHref(taskId: number | string): string {
  return hrefTo(DOCKET_PATH, (params) => { if (params.has(DECISIONS_CARD_PARAM)) params.delete(DECISIONS_CARD_PARAM); },
    docketAnchorId(taskId));
}

/** A ready href for an <a> to the Decisions page opened on one card: for a request that is not
 *  on the docket, and for the special kinds decided there. Base path and query kept (?demo=1),
 *  `card` set to the id, no hash. Not a logical path: navigate with
 *  openDecisionsCard(), never navigateHud or routeHref. */
export function decisionsHref(taskId: number | string): string {
  return hrefTo(DECISIONS_PATH, (params) => params.set(DECISIONS_CARD_PARAM, String(taskId)), '');
}

/** hud-routing.ts keeps its overlay-return record (where an overlay's Close goes) under this
 *  history-state key. It belongs to the entry it was written for, so an entry opened here never
 *  carries it; the other state fields are kept, as navigateHud keeps them. */
const OVERLAY_RETURN_KEY = '__nervaHudRoute';

function freshState(): unknown {
  const state = window.history.state;
  if (!state || typeof state !== 'object' || Object.getPrototypeOf(state) !== Object.prototype
      || !(OVERLAY_RETURN_KEY in state)) return state;
  const { [OVERLAY_RETURN_KEY]: _dropped, ...rest } = state as Record<string, unknown>;
  return rest;
}

const currentHref = () => window.location.pathname + window.location.search + window.location.hash;

/** One history entry for a ready href (Back returns to where the owner was), then the router is
 *  told. Already there: nothing is pushed. */
function openHref(href: string): void {
  if (href !== currentHref()) window.history.pushState(freshState(), '', href);
  notifyHudRouteChange();
}

/** Go to a docket entry in the app. */
export function openDocketEntry(taskId: number | string): void {
  openHref(docketHref(taskId));
}

/** Go to the Decisions page opened on one card, in the app. */
export function openDecisionsCard(taskId: number | string): void {
  openHref(decisionsHref(taskId));
}

/** hud-routing.ts's route-change event, mirrored (like OVERLAY_RETURN_KEY above): the docket
 *  listens for it to follow #docket-entry-<id> after openDocketEntry(), which pushes history
 *  without a hashchange. links.test.tsx checks notifyHudRouteChange() still fires it. */
export const HUD_ROUTE_EVENT = 'nerva-route-change';
