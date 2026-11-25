/* Routes ⇄ pages (PHASE_B_PLAN.md §3.1, §3.2, §3.4).

   Routes do not change: every HudRoute that parseHudRoute() accepts resolves to one page of
   the registry. This module adds no route and validates nothing; hud-routing.ts stays the only
   parser, and pageForRoute() only says which area and page a parsed route is.

     pageForRoute(route)  → { kind, area, entry, group }
                             kind: 'home' (/v2/cockpit) · 'chat' · 'glance' · 'mode' · 'panel'
                             (/v2/console/<id>) · 'allPages' (/v2/console, area null)
     pathOf(ref)          → '/v2/<mode>', '/v2/console/<id>' or '/v2/console'
     pageTitle(route, lang) → 'Today · Nerva' · '<Area> · Nerva' · '<Page> · <Area> · Nerva'
                             · 'All pages · Nerva'
     areaOfMode(id), areaOfPanel(id), areaAnchor(id) */
import type { HudRoute } from '../hud-routing';
import { defineStrings, fmt, pick, type Lang } from '../frame/strings';
import {
  ALL_PAGES, areaById, groupOf, pageForMode, pageForPanel, textOf,
  type Area, type AreaId, type Group, type PageEntry, type PageRef,
} from './areas';

export type PageKind = 'home' | 'chat' | 'glance' | 'mode' | 'panel' | 'allPages';

/** A parsed route, placed. `area` is null only for All pages. */
export interface RoutePage {
  readonly kind: PageKind;
  readonly area: Area | null;
  readonly entry: PageEntry;
  readonly group: Group | null;
}

/** The fields of a HudRoute this module reads. */
export type RouteLike = Pick<HudRoute, 'mode' | 'panel'>;

const HOME = pageForMode('cockpit') as PageEntry;

function kindOfMode(mode: string): PageKind {
  return mode === 'cockpit' ? 'home' : mode === 'chat' ? 'chat' : mode === 'glance' ? 'glance' : 'mode';
}

function placed(kind: PageKind, entry: PageEntry): RoutePage {
  return { kind, area: areaById(entry.area), entry, group: groupOf(entry) };
}

/** Which area and page a parsed route is. Anything the registry does not know resolves to Home
 *  (parseHudRoute already sends an invalid URL to /v2/cockpit). */
export function pageForRoute(route: RouteLike): RoutePage {
  if (route.mode === 'console') {
    if (!route.panel) return { kind: 'allPages', area: null, entry: ALL_PAGES, group: null };
    const entry = pageForPanel(route.panel);
    if (entry) return placed('panel', entry);
    return placed('home', HOME);
  }
  const entry = pageForMode(route.mode);
  return entry ? placed(kindOfMode(route.mode), entry) : placed('home', HOME);
}

/** The logical path a page opens (pass it to navigateHud or routeHref). */
export function pathOf(ref: PageRef): string {
  if (ref.kind === 'allPages') return '/v2/console';
  return ref.kind === 'panel' ? `/v2/console/${ref.id}` : `/v2/${ref.id}`;
}

/** The path of an area's landing page. */
export function landingPath(area: AreaId): string {
  const found = areaById(area);
  return found ? pathOf(found.landing.ref) : '/v2/cockpit';
}

export const ROUTE_STRINGS = defineStrings({
  en: { titleArea: '{area} · Nerva', titlePage: '{page} · {area} · Nerva', titleAlone: '{page} · Nerva' },
  ro: { titleArea: '{area} · Nerva', titlePage: '{page} · {area} · Nerva', titleAlone: '{page} · Nerva' },
});

/** The document title for a route (§3.4). The "· Console · Nerva" titles are gone. */
export function pageTitle(route: RouteLike, lang: Lang | string = 'en'): string {
  const s = pick(ROUTE_STRINGS, lang);
  const page = pageForRoute(route);
  if (page.kind === 'allPages' || page.kind === 'home' || !page.area) return fmt(s.titleAlone, { page: textOf(page.entry.label, lang) });
  const area = textOf(page.area.label, lang);
  if (page.entry.landing) return fmt(s.titleArea, { area });
  return fmt(s.titlePage, { page: textOf(page.entry.label, lang), area });
}

/** The area a mode belongs to (null for an id the registry does not place). */
export function areaOfMode(mode: string): AreaId | null {
  return pageForMode(mode)?.area ?? null;
}

/** The area a Console panel belongs to (explicit, or its group's default for a newer panel). */
export function areaOfPanel(panelId: string): AreaId | null {
  return pageForPanel(panelId)?.area ?? null;
}

/** The masthead link's anchor for agent tips and tours (§3.8): `area.<id>`. */
export function areaAnchor(area: AreaId): string {
  return `area.${area}`;
}
