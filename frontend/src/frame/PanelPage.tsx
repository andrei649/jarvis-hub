/* A Console panel as a page of its area (PHASE_B_PLAN.md §2.1, §4.5): /v2/console/<id> renders
   the panel inside its area's page frame instead of the Console overlay. The panel is the one
   gap.tsx's ConsolePanel chooses (the pinned PANEL_COMPONENTS[selected.component] lookup),
   loaded lazily with the gap chunk, keyed by its id. The frame's notices already list failed
   actions on every page, so the panel's own failure banner is off (showFailures={false}).
   Focus moves to the page heading on navigation, as the Console overlay did. A panel keeps its
   own source chip; the page head adds none (a duplicated title is accepted in Phase B). */
import React, { Suspense, lazy, useEffect, useRef } from 'react';
import type { RoutePage } from '../nav/routes';
import { RouteFallback } from '../route-boundary';
import type { Attention } from '../signals/types';
import { AreaPage } from './AreaPage';
import type { Lang } from './strings';

const ConsolePanel = lazy(() => import('../gap').then((m) => ({ default: m.ConsolePanel })));

export interface PanelPageProps {
  panelId: string;
  page: RoutePage;
  lang: Lang;
  attention: Attention;
  navigate: (path: string) => void;
  onFind: (filter?: 'panels') => void;
}

export function PanelPage({ panelId, page, lang, attention, navigate, onFind }: PanelPageProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, [panelId]);
  return (
    <AreaPage page={page} lang={lang} attention={attention} navigate={navigate} onFind={onFind} headingRef={heading}>
      <div className="n-areapage__panel" data-panel={panelId}>
        <Suspense fallback={<RouteFallback />}>
          <ConsolePanel key={panelId} panelId={panelId} showFailures={false} />
        </Suspense>
      </div>
    </AreaPage>
  );
}
