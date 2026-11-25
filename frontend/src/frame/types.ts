/* The App → Frame contract (PHASE_B_PLAN.md §2.1, §9.2.6).

   App renders <Frame {...FrameProps}>{page body}</Frame> for every route but
   Glance. App keeps every piece of state it owns today; the frame reads the hub only through
   one HubSnapshot, which App builds with hubSnapshotFrom() on each loader commit:

     commitData: (d) => { …today's setters…; setHub((prev) => hubSnapshotFrom(d, prev)); }
     commitLocality: (raw) => { setLocality(raw); setHub((prev) => hubWithLocality(prev, raw)); }

   and seeds with initialHubSnapshot(demo) (and again when demo toggles). hubReading() gives the
   running head's "Data on screen" (live, stale after 2.5 loader intervals, offline, demo,
   Checking… before the first answer).

   The loader (api/loaders.ts, E3, additive) keeps four more /status fields and its own cycle
   time under the names HubLoaderData lists; hubSnapshotFrom validates them, so the loader may
   pass them raw. */
import type React from 'react';
import type { JarvisData } from '../api/loaders';
import type { HudRoute } from '../hud-routing';
import type { RoutePage } from '../nav/routes';
import type { PowerState } from '../power-chip';
import type { PressureState } from '../pressure-banner';
import type { Overrides } from '../shortcuts';
import type { HubSnapshot, HubTrust, LocalityCounts, Reading, TabTurn } from '../signals/types';
import { isStale, residencyFrom, slotUsageFrom } from '../signals/types';
import type { Scheme, SchemePreference, ThemeInfo } from '../theme/registry';
import { STATUS_CHROME_UNKNOWN } from '../api/status-chrome';
import { SAFE_MODE_OFF } from '../safe-mode-banner';
import type { Lang } from './strings';

/** How the frame moves between pages (App passes hud-routing's functions). */
export interface FrameNavigation {
  /** navigateHud(path, replace?): a logical path from nav/routes.ts pathOf(). */
  readonly navigate: (path: string, replace?: boolean) => void;
  /** closeHudOverlay(): Glance's Esc returns to where the owner was. */
  readonly closeOverlay: () => void;
}

/** The first-run notice (§4.4; it replaced the HUD v2 FirstRunBanner): the Frame shows it when the hub answered,
 *  no model is loaded, the model state is known, demo is off and the owner has not dismissed it. */
export interface FirstRunNotice {
  readonly dismissed: boolean;
  readonly onDismiss: () => void;
  /** "Show a demo sample": turns demo on. */
  readonly onDemo: () => void;
}

/** What App gives the Frame. Required fields are the contract; optional ones the integration
 *  step may add without breaking a component built against it. The notice inputs are drawn only
 *  when passed. */
export interface FrameProps {
  /** The parsed route (hud-routing.ts useHudRoute). */
  readonly route: HudRoute;
  /** pageForRoute(route): kind, area, page entry and group. */
  readonly page: RoutePage;
  /** The hub as App's loader last read it. */
  readonly hub: HubSnapshot;
  readonly lang: Lang;
  readonly setLang: (lang: Lang) => void;
  /** The resolved scheme (never 'system') and the owner's preference. */
  readonly scheme: Scheme;
  readonly schemePreference: SchemePreference;
  readonly setScheme: (scheme: SchemePreference) => void;
  /** The active theme (its `schemes` decides whether the scheme toggle can switch). */
  readonly theme: ThemeInfo;
  readonly navigation: FrameNavigation;
  /** Open the search and command sheet; 'panels' opens it filtered to panels (the backtick). */
  readonly onFind: (filter?: 'panels') => void;
  /** Go to Glance (/v2/glance). */
  readonly onGlance: () => void;
  /** The page body: Home, an AreaPage … */
  readonly children: React.ReactNode;
  readonly demo?: boolean;
  readonly onExitDemo?: () => void;
  /** The 420 × 620 desktop window. */
  readonly floating?: boolean;
  /** This tab's in-flight turns (App's textTurns with the reply stamps): the running foot's
   *  "Answering you (asked)". App always passes it; absent reads as none. */
  readonly turns?: readonly TabTurn[];
  /** shortcuts.ts useShortcutOverrides(): the masthead's Find key is
   *  displayChord(chordOf(overrides, 'session.palette')); the foot's key hint too. */
  readonly shortcutOverrides?: Overrides;
  /** App's useVoice() status ('off' | 'idle' | 'listening' | 'transcribing' | 'speaking' |
   *  'error'): the microphone item's "listening now". */
  readonly voiceStatus?: string;
  // ---- the notices (§4.4) ----
  /** usePower(demo) (H182). */
  readonly power?: PowerState;
  /** usePressure(demo) and its dismiss, for the notices' PressureBanner. The verdict does not
   *  read this: it reads its own Reading (signals/hooks.ts usePressureReading). */
  readonly pressure?: PressureState;
  readonly onDismissPressure?: (condition: string, bootId: string) => void;
  /** useHudRoute's notice ("Page not found. Returned to …") and its dismiss. */
  readonly routeNotice?: string;
  /** The page the router fell back to when it raised the notice (App records it when the notice
   *  appears); the notice names it, not the page on screen. */
  readonly routeNoticePage?: RoutePage | null;
  readonly onDismissRouteNotice?: () => void;
  /** App's appearance sync error with its Retry (today's `appearanceNotice` node). */
  readonly appearanceNotice?: React.ReactNode;
  readonly firstRun?: FirstRunNotice;
}

/** The loader's cadence (app.tsx polls every 30 s). */
export const LOADER_INTERVAL_MS = 30_000;

/** What App hands hubSnapshotFrom on a loader commit: today's JarvisData plus what E3 adds to it
 *  in api/loaders.ts, under exactly these names (raw /status values are fine; they are validated
 *  here, and a missing one reads as not reported). An intersection, so E3's own types for these
 *  fields fit. */
export type HubLoaderData = Partial<JarvisData> & {
  /** When the loader's cycle finished (epoch ms). */
  readonly checkedAt?: number;
  /** /status `llm_backend`. */
  readonly llmBackend?: unknown;
  /** /status `configured_model`. */
  readonly configuredModel?: unknown;
  /** /status `residency_state`. */
  readonly residencyState?: unknown;
  /** /status `slots`. */
  readonly slots?: unknown;
};
/** The names above, for a test of the loader. */
export const HUB_LOADER_FIELDS = ['checkedAt', 'llmBackend', 'configuredModel', 'residencyState', 'slots'] as const;

const NO_LLM = Object.freeze({ state: 'unknown', model: null, residents: [] }) as HubSnapshot['llm'];
const count = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v) && v >= 0;
/** A short identifier the hub sent (a backend or model name), trimmed; else null. */
const ident = (v: unknown, max: number): string | null => (typeof v === 'string' && v.trim() ? v.trim().slice(0, max) : null);

/** The snapshot before the loader's first commit: Checking… (or the demo sample), nothing invented. */
export function initialHubSnapshot(demo = false, intervalMs = LOADER_INTERVAL_MS): HubSnapshot {
  return {
    state: demo ? 'demo' : 'unknown',
    ...(demo ? {} : { reason: 'checking' as const }),
    demo,
    serverUp: false,
    checkedAt: null,
    lastGoodAt: null,
    intervalMs,
    llm: NO_LLM,
    backend: null,
    configuredModel: null,
    residency: null,
    slots: null,
    sys: null,
    safeMode: SAFE_MODE_OFF,
    chrome: STATUS_CHROME_UNKNOWN,
    trust: null,
    locality: null,
    agents: [],
    ticker: [],
    weather: null,
    calendar: [],
    tasks: [],
    sources: {},
  };
}

/** /api/trust/status as the snapshot keeps it: null unless it answered (the loader's own
 *  default says mic 'on', which is not a reading); anything but the exact words is unknown. */
function trustFrom(data: Partial<JarvisData>): HubTrust | null {
  if (!data.sources?.trust || !data.trust) return null;
  const t = data.trust;
  return {
    mic: t.mic === 'on' ? 'on' : t.mic === 'off' ? 'off' : 'unknown',
    strictLocal: t.strict_local === true,
    cloudAvailable: t.cloud_available === true,
    claudeAvailable: t.claude_available === true,
  };
}

/** /api/analytics/locality, validated: counts must be whole numbers, local_pct a number or null. */
export function localityFrom(raw: unknown): LocalityCounts | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  if (!count(r.local) || !count(r.cloud) || !count(r.unknown) || !count(r.total)) return null;
  if (r.local_pct !== null && (typeof r.local_pct !== 'number' || !Number.isFinite(r.local_pct))) return null;
  return { ...r, local_pct: r.local_pct as number | null, local: r.local, cloud: r.cloud, unknown: r.unknown, total: r.total } as LocalityCounts;
}

/** The snapshot after one loader commit. Pure: the clock comes from `opts.now` (default
 *  Date.now()) unless the loader stamped the cycle itself (`data.checkedAt`). A hub that did not
 *  answer keeps the previous good time, so "Offline · last good reading 10:44" can be said.
 *  `opts.locality`: undefined keeps the previous figure, null clears it, a raw answer replaces it.
 *  The /status fields (backend, configured model, residency, slots) are this commit's only: null
 *  when /status did not answer or the loader did not supply them. */
export function hubSnapshotFrom(
  data: HubLoaderData,
  previous: HubSnapshot | null,
  opts: { now?: number; locality?: unknown; intervalMs?: number } = {},
): HubSnapshot {
  const checkedAt = typeof data.checkedAt === 'number' && Number.isFinite(data.checkedAt) ? data.checkedAt : opts.now ?? Date.now();
  const demo = !!data.demo;
  const serverUp = !!data.serverUp;
  const locality = opts.locality === undefined ? previous?.locality ?? null : localityFrom(opts.locality);
  const answered = serverUp || demo;
  return {
    state: demo ? 'demo' : serverUp ? 'live' : 'offline',
    ...(!demo && !serverUp ? { reason: 'network' as const } : {}),
    demo,
    serverUp,
    checkedAt,
    lastGoodAt: serverUp ? checkedAt : previous?.lastGoodAt ?? null,
    intervalMs: opts.intervalMs ?? previous?.intervalMs ?? LOADER_INTERVAL_MS,
    llm: data.llm ?? NO_LLM,
    backend: answered ? ident(data.llmBackend, 64) : null,
    configuredModel: answered ? ident(data.configuredModel, 200) : null,
    residency: answered ? residencyFrom(data.residencyState) : null,
    slots: answered ? slotUsageFrom(data.slots) : null,
    sys: data.sys ?? null,
    safeMode: data.safeMode ?? SAFE_MODE_OFF,
    chrome: data.chrome ?? STATUS_CHROME_UNKNOWN,
    trust: trustFrom(data),
    locality,
    agents: Array.isArray(data.agents) ? data.agents : [],
    ticker: Array.isArray(data.ticker) ? data.ticker : [],
    weather: data.weather ?? null,
    calendar: Array.isArray(data.calendar) ? data.calendar : [],
    tasks: Array.isArray(data.tasks) ? data.tasks : [],
    sources: { ...(data.sources || {}) },
  };
}

/** The snapshot with a new /api/analytics/locality answer (App's commitLocality). */
export function hubWithLocality(hub: HubSnapshot, raw: unknown): HubSnapshot {
  return { ...hub, locality: localityFrom(raw) };
}

/** The running head's "Data on screen": the snapshot's state, turned stale when no good answer
 *  has come for 2.5 loader intervals (a stalled loader commits nothing). */
export function hubReading(hub: HubSnapshot, now: number = Date.now()): Reading<null> {
  const base = { value: null, checkedAt: hub.checkedAt, lastGoodAt: hub.lastGoodAt, intervalMs: hub.intervalMs, source: '/status' };
  if (hub.state === 'live' && isStale(hub.lastGoodAt, hub.intervalMs, now)) return { ...base, state: 'stale' };
  return { ...base, state: hub.state, ...(hub.reason ? { reason: hub.reason } : {}) };
}
