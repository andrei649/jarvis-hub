/* An area's contents column: second-level navigation (PHASE_B_PLAN.md §3.3, §3.9).

   Lists the area's `listed` pages in their groups. The primary pages show first; the rest sit
   behind "N more pages" (open by default when the current page is one of them), and "Ctrl K
   finds any of the N" says where the rest are. A note sits beside a page only when its signal has
   a live value: the docket count beside Decisions (the owner's hand: the accent), payments
   waiting, the stop's word. On a duplicate (/v2/console/jobs) the page it duplicates is current.

   Links are real links (href keeps the base path and the query, so ?demo=1 survives); a plain
   click navigates in-app, a modified click opens as the browser does. */
import React, { useEffect, useId, useState } from 'react';
import { Mark } from '../frame/kit';
import { fmt, pick, plural, type Lang } from '../frame/strings';
import { pageHref } from '../hud-routing';
import { chordOf, displayChord, loadOverrides, type Overrides } from '../shortcuts';
import type { Attention } from '../signals/types';
import { textOf, type Area, type AttentionWords, type PageEntry } from './areas';
import { CONTENTS_STRINGS, contentsModel, noteFor, pagesWord, type ContentsItem } from './contents-model';
import './contents.css';

/** The words of a note: the mark (a problem or a held state), the short text, and the long text for
 *  assistive tech. The owner's hand (docket, payments) takes the accent. */
export function Note({ words, lang }: { words: AttentionWords; lang: Lang }) {
  return (
    <span className="n-contents-note" data-hand={words.hand ? 'true' : undefined} data-note="true">
      {words.mark && <Mark kind={words.mark} size="sm" lang={lang} />}
      <span aria-hidden="true">{words.short}</span>
      <span data-visually-hidden>{words.long}</span>
    </span>
  );
}

/** A link to a page: a real href, an in-app click. */
export function PageLink({ item, lang, navigate, attention, className }: {
  item: ContentsItem; lang: Lang; navigate: (path: string) => void; attention?: Attention; className?: string;
}) {
  const { entry, current, path } = item;
  const note = noteFor(entry, attention, lang);
  return (
    <a
      href={pageHref(path)} className={className} data-page={entry.key} aria-current={current ? 'page' : undefined}
      onClick={(e) => {
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        navigate(path);
      }}
    >
      <span className="n-toc-name">{textOf(entry.label, lang)}</span>
      {note && <Note words={note} lang={lang} />}
    </a>
  );
}

export interface ContentsColumnProps {
  area: Area;
  current: PageEntry;
  lang: Lang;
  attention: Attention;
  navigate: (path: string) => void;
  onFind: (filter?: 'panels') => void;
  /** App's shortcut overrides (a rebound Ctrl K shows as bound); storage is read only without them. */
  overrides?: Overrides;
}

export function ContentsColumn({ area, current, lang, attention, navigate, onFind, overrides }: ContentsColumnProps): React.JSX.Element {
  const s = pick(CONTENTS_STRINGS, lang);
  const uid = useId();
  const model = contentsModel(area, current);
  const [open, setOpen] = useState(model.currentInMore);
  // Arriving on a page that sits behind "more" opens them, so the current page is always visible.
  useEffect(() => { if (model.currentInMore) setOpen(true); }, [model.currentInMore, current.key]);
  const areaName = textOf(area.label, lang);
  const chord = displayChord(chordOf(overrides ?? loadOverrides(), 'session.palette'));
  const [findBefore, findAfter = ''] = fmt(s.find, { n: model.total }).split('{key}');
  const hasMore = model.moreCount > 0;

  return (
    <nav className="n-contents" data-frame="contents" data-area={area.id} aria-label={fmt(s.navLabel, { area: areaName })}>
      <header className="n-contents-head">
        <h2 className="n-contents-title">{areaName}</h2>
        <span className="n-contents-meta">{pagesWord(lang, model.total)}</span>
      </header>
      <div className="n-contents-body">
        <ul className="n-toc">
          {model.groups.map((g) => {
            const items = open ? [...g.primary, ...g.more].sort((a, b) => g.group.pages.indexOf(a.entry) - g.group.pages.indexOf(b.entry)) : g.primary;
            if (!items.length) return null;
            const headId = `${uid}-g-${g.group.id}`;
            return (
              <li key={g.group.id} className="n-toc-section" data-group={g.group.id}>
                {g.label && <div id={headId} className="n-toc-group">{textOf(g.label, lang)}</div>}
                <ul aria-labelledby={g.label ? headId : undefined}>
                  {items.map((item) => (
                    <li key={item.entry.key}>
                      <PageLink item={item} lang={lang} navigate={navigate} attention={attention} className="n-toc-link" />
                    </li>
                  ))}
                </ul>
              </li>
            );
          })}
          {hasMore && (
            <li>
              <button type="button" className="n-toc-more" aria-expanded={open} data-contents="more" onClick={() => setOpen((v) => !v)}>
                {open ? s.fewer : plural(lang, s.more, model.moreCount)}
              </button>
            </li>
          )}
        </ul>
        <p className="n-toc-find">
          {findBefore}<kbd className="n-kbd">{chord}</kbd>{findAfter}
        </p>
        <p className="n-toc-find">
          <button type="button" className="n-link n-toc-panel" data-contents="find-panel" onClick={() => onFind('panels')}>{s.findPanel}</button>
        </p>
      </div>
    </nav>
  );
}
