/* A mode as a page of its area (PHASE_B_PLAN.md §4.5, §6): AreaPage around today's mode
   component (passed as children: AgentsMode, MemoryMode, BuildMode, …).

   A mode that draws from live sources (`liveKeys`, the keys of App's MODE_LIVE_KEYS) is shown
   only when one of them is live, or in demo; otherwise the area-page empty state replaces it,
   as ModeEmpty did in the legacy shell — "Nothing to show yet — this page's source has not
   answered. It fills in when it does." with "Show a demo sample". The page head's source label
   says which: Live, Demo sample, or Unknown. The live flags (api/live.ts) carry no check time
   and stay set after a source stops answering, so a live mode follows the hub's own reading
   (`hubState`): when the hub is stale or offline the head says so, never "Live", and with no
   time it does not have. A mode with no source keys (Agents, Projects, Scheduled jobs, World
   signals, and the Ledger's own pages) is always drawn and keeps its own labels. Mode bodies
   load lazily: while one loads, the page head and the contents column stay and only the body
   says "Loading page…". */
import React, { Suspense } from 'react';
import type { HudMode } from '../hud-modes';
import type { RoutePage } from '../nav/routes';
import { RouteFallback } from '../route-boundary';
import type { Attention, Reading, ReadingState } from '../signals/types';
import { AreaPage } from './AreaPage';
import type { Lang } from './strings';

export interface ModePageProps {
  mode: HudMode;
  page: RoutePage;
  lang: Lang;
  attention: Attention;
  navigate: (path: string) => void;
  onFind: (filter?: 'panels') => void;
  demo: boolean;
  /** useLiveModes().live: which V2 keys carry real data now. */
  live: Readonly<Record<string, boolean>>;
  onDemo: () => void;
  /** The mode's live keys (App's MODE_LIVE_KEYS[mode]); none for a mode that is always drawn. */
  liveKeys?: readonly string[] | null;
  /** The hub's own reading now (frame/types.ts hubReading(hub).state): a live mode is not called
   *  live while the hub is stale or offline. */
  hubState?: ReadingState;
  children?: React.ReactNode;
}

/** The mode page's state: whether it is drawn, and the source label its head carries. */
export function modePageState(liveKeys: readonly string[] | null | undefined, live: Readonly<Record<string, boolean>>, demo: boolean,
  hubState?: ReadingState): { empty: boolean; source: Reading<unknown> | null } {
  if (!liveKeys || !liveKeys.length) return { empty: false, source: null };
  const isLive = liveKeys.some((key) => live[key] === true);
  if (isLive && !demo && (hubState === 'stale' || hubState === 'offline')) {
    // what is on the page came from the hub before it stopped answering; no time is known for it
    return { empty: false, source: { state: hubState, value: null, checkedAt: null, lastGoodAt: null } };
  }
  if (isLive) return { empty: false, source: { state: 'live', value: null, checkedAt: null, lastGoodAt: null } };
  if (demo) return { empty: false, source: { state: 'demo', value: null, checkedAt: null, lastGoodAt: null, basis: 'seeded' } };
  return { empty: true, source: { state: 'unknown', value: null, checkedAt: null, lastGoodAt: null } };
}

export function ModePage({ mode, page, lang, attention, navigate, onFind, demo, live, onDemo, liveKeys, hubState, children }: ModePageProps) {
  const { empty, source } = modePageState(liveKeys, live, demo, hubState);
  return (
    <AreaPage page={page} lang={lang} attention={attention} navigate={navigate} onFind={onFind}
      source={source} empty={empty} onDemo={onDemo}>
      <div className="n-areapage__mode" data-mode={mode}><Suspense fallback={<RouteFallback />}>{children}</Suspense></div>
    </AreaPage>
  );
}
