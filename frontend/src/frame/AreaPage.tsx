/* The area page (PHASE_B_PLAN.md §4.5): every page of an area that is not Home's Today.

     ┌ contents ┐ ┌ page ──────────────────────────────────────────────┐
     │ the area │ │ Title                 ● Live · checked 10:50  [toolbar]│
     │ pages    │ ├────────────────────────────────────────────────────┤
     │ …        │ │ the page body, scrolling by itself                  │
     └──────────┘ └────────────────────────────────────────────────────┘

   - The head: the title (the area's name on its landing page, the page's label elsewhere), a
     SourceLabel when the page has one source to report, and PageHeaderBar as the toolbar slot
     (a page that calls usePageHeader, as Jobs does, puts its toolbar there).
   - The contents column: 232px (264 at ≥ 2200, 200 at ≤ 1679, 176 at ≤ 1339). It is the
     navigation engineer's ContentsColumn (nav/ContentsColumn.tsx): the area's pages, the notes
     beside them from `attention`, "N more pages", and "Find a panel…" (`onFind('panels')`).
     All pages (/v2/console) belongs to no area and has no column.
   - The body scrolls by itself. `empty` replaces it with the area-page empty state: "Nothing to
     show yet — this page's source has not answered. It fills in when it does." and, when the
     page can show one, "Show a demo sample". The contents column stays usable.
   - A body that overflows with nothing in it a keyboard can reach (a read-only page, as several
     are in the demo sample) takes the focus itself, as a group named by the page title, so the
     part below the fold can be scrolled from the keyboard (WCAG 2.1.1; axe
     scrollable-region-focusable). That is what Chromium does for such a scroller on its own; the
     attributes make it hold in every engine and say what the focused region is. */
import React, { useEffect, useId, useRef, useState } from 'react';
import { PageHeaderBar, PageHeaderProvider } from '../page-header';
import { textOf } from '../nav/areas';
import { ContentsColumn } from '../nav/ContentsColumn';
import type { RoutePage } from '../nav/routes';
import type { Attention, Reading } from '../signals/types';
import { Mark, SourceLabel } from './kit';
import { PAGE_STRINGS } from './frame-strings';
import { pick, type Lang } from './strings';
import './frame.css';

export interface AreaPageProps {
  page: RoutePage;
  lang: Lang;
  attention: Attention;
  navigate: (path: string) => void;
  /** For the contents column's "Find a panel…" (the search sheet filtered to panels). */
  onFind: (filter?: 'panels') => void;
  /** The page's one source, when it has one to report. */
  source?: Reading<unknown> | null;
  /** The source has not answered: the empty state replaces the body. */
  empty?: boolean;
  /** "Show a demo sample" (sets ?demo=1). */
  onDemo?: () => void;
  /** The page title's element, for a page that moves focus to it on navigation. */
  headingRef?: React.Ref<HTMLHeadingElement>;
  children?: React.ReactNode;
}

/** The title a page's head shows: the area on its landing page ("Trust", not "Overview"), else
 *  the page's own label. Home is the exception: its landing is Today, and Home's own heading
 *  says so ("Today — Monday, 23 November"), so it is named "Today". */
export function pageHeading(page: RoutePage, lang: Lang | string): string {
  if (page.kind !== 'home' && page.area && page.entry.landing) return textOf(page.area.label, lang);
  return textOf(page.entry.label, lang);
}

export function AreaEmpty({ lang, onDemo }: { lang: Lang; onDemo?: () => void }) {
  const s = pick(PAGE_STRINGS, lang);
  return (
    <div className="n-areapage__empty" data-empty="">
      <Mark kind="unknown" lang={lang} />
      <p className="n-areapage__empty-text">{s.empty}</p>
      {onDemo && <button type="button" className="n-btn n-btn--sm" onClick={onDemo}>{s.showDemo}</button>}
    </div>
  );
}

/** A page body the registry knows but no component draws: one quiet line, nothing invented.
 *  Every HUD mode has its page, so this is only App's defensive fallback. */
export function SlotNote({ lang }: { lang: Lang }) {
  return <p className="n-areapage__slot" data-slot="placeholder">{pick(PAGE_STRINGS, lang).notWired}</p>;
}

/** What a keyboard can reach inside the page body. */
const REACHABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), '
  + 'textarea:not([disabled]), summary, iframe, [contenteditable=""], [contenteditable="true"], [tabindex]:not([tabindex="-1"])';

/** True while the scroller overflows and holds nothing a keyboard can reach (no layout, as in
 *  jsdom, is never an overflow). Rechecked on the next frame after its size, its content or a
 *  control's state changes. */
export function useScrollerNeedsFocus(ref: React.RefObject<HTMLElement | null>): boolean {
  const [needed, setNeeded] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    let frame = 0;
    const measure = () => {
      frame = 0;
      const overflows = el.scrollHeight > el.clientHeight + 1 && /auto|scroll/.test(getComputedStyle(el).overflowY);
      const reachable = overflows && Array.from(el.querySelectorAll<HTMLElement>(REACHABLE)).some((c) => c.getClientRects().length > 0);
      setNeeded(overflows && !reachable);
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(measure); };
    const sizes = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(schedule);
    const watchSizes = () => {
      if (!sizes) return;
      sizes.disconnect();
      sizes.observe(el);
      for (const child of Array.from(el.children)) sizes.observe(child);
    };
    const content = typeof MutationObserver === 'undefined' ? null : new MutationObserver((records) => {
      // a new or removed child of the body is a new box to watch; anything else is only a recheck
      if (records.some((r) => r.type === 'childList' && r.target === el)) watchSizes();
      schedule();
    });
    watchSizes();
    content?.observe(el, { childList: true, subtree: true, attributes: true, attributeFilter: ['disabled', 'tabindex', 'href', 'hidden', 'class', 'style'] });
    schedule();
    return () => {
      sizes?.disconnect();
      content?.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, [ref]);
  return needed;
}

export function AreaPage({ page, lang, attention, navigate, onFind, source, empty = false, onDemo, headingRef, children }: AreaPageProps) {
  const headingId = `n-areapage-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const title = pageHeading(page, lang);
  const bodyRef = useRef<HTMLDivElement>(null);
  const bodyTakesFocus = useScrollerNeedsFocus(bodyRef);
  return (
    <PageHeaderProvider routeKey={page.entry.key}>
      <div className={['n-areapage', page.area ? '' : 'n-areapage--wide'].filter(Boolean).join(' ')}
        data-areapage={page.kind} data-area={page.area?.id ?? 'none'}>
        {page.area && (
          <div className="n-areapage__contents">
            <ContentsColumn area={page.area} current={page.entry} lang={lang} attention={attention} navigate={navigate} onFind={onFind} />
          </div>
        )}
        <section className="n-areapage__main" aria-labelledby={headingId}>
          <header className="n-areapage__head">
            <h1 className="n-areapage__title" id={headingId} tabIndex={-1} ref={headingRef}>{title}</h1>
            <div className="n-areapage__meta">
              {source && <SourceLabel reading={source} lang={lang} />}
              <div className="n-areapage__tools"><PageHeaderBar title={null} /></div>
            </div>
          </header>
          <div className="n-areapage__body" ref={bodyRef}
            {...(bodyTakesFocus ? { tabIndex: 0, role: 'group', 'aria-labelledby': headingId, 'data-scroll-focus': '' } : {})}>
            {empty ? <AreaEmpty lang={lang} onDemo={onDemo} /> : children}
          </div>
        </section>
      </div>
    </PageHeaderProvider>
  );
}
