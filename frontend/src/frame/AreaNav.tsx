/* The nine areas (PHASE_B_PLAN.md §4.1, §3.9): nav[aria-label="Areas"], one link per area in
   masthead order, aria-current="page" on the area of the page on screen, the attention note
   beside it ("Work 9 need you", "Observe ■ 4 services down"), and data-anchor="area.<id>" for
   agent tips and tours (§3.8). A note is drawn only when the attention model has one: an
   unknown count is no note at all. Long and short notes sit side by side, switched by width;
   the link's accessible name carries the long one. The short note is the first words of the long
   one (nav/areas.ts) and a word space parts the area's name from its note, so what is drawn at
   any width, "Work 9" or "Work 9 need you", is part of that name (WCAG 2.5.3; axe
   label-content-name-mismatch read "Work9" without the space).

   The note's third form is its count alone ("12", "■ 4"; a broken record is its mark alone):
   hidden until the masthead runs out of room (Masthead.tsx, the fit steps "notes" and "hand").
   Whatever form is drawn, the words stay in the link's name and in its tooltip (title). The
   count is a figure the note already carries, never new copy. */
import React from 'react';
import { routeHref } from '../hud-routing';
import { AREAS, areaNote, attentionWords, textOf, type Area } from '../nav/areas';
import { areaAnchor, landingPath } from '../nav/routes';
import type { Attention, AttentionNote } from '../signals/types';
import { Mark } from './kit';
import { MASTHEAD_STRINGS } from './frame-strings';
import { fmt, pick, type Lang } from './strings';

/** A plain left click is handled in the app; anything else (new tab, a modifier) is the browser's. */
export function inAppClick(event: React.MouseEvent): boolean {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

export interface AreaNavProps {
  /** The area of the page on screen (null on All pages). */
  current: Area | null;
  lang: Lang;
  attention: Attention;
  navigate: (path: string) => void;
  /** After a link is followed (the drawer closes). */
  onNavigate?: () => void;
  className?: string;
}

/** A note's count alone (its most compact form): the figure the note carries, or null for a note
 *  that has none (a broken record is drawn as its mark alone). */
export function noteCount(note: AttentionNote): string | null {
  return 'count' in note && typeof note.count === 'number' ? String(note.count) : null;
}

export function AreaNav({ current, lang, attention, navigate, onNavigate, className }: AreaNavProps) {
  const s = pick(MASTHEAD_STRINGS, lang);
  return (
    <nav className={['n-areas', className].filter(Boolean).join(' ')} aria-label={s.areas}>
      {AREAS.map((area) => {
        const path = landingPath(area.id);
        const label = textOf(area.label, lang);
        const note = areaNote(area, attention);
        const words = note ? attentionWords(note, lang) : null;
        const count = note ? noteCount(note) : null;
        const name = words ? fmt(s.areaWithNote, { area: label, note: words.long }) : undefined;
        const isCurrent = current?.id === area.id;
        return (
          <a key={area.id} className="n-areas__link" href={routeHref(path)} data-anchor={areaAnchor(area.id)} data-area={area.id}
            aria-current={isCurrent ? 'page' : undefined} aria-label={name} title={name}
            onClick={(event) => {
              if (!inAppClick(event)) return;
              event.preventDefault();
              navigate(path);
              onNavigate?.();
            }}>
            <span className="n-areas__label">{label}</span>
            {words && (
              <>
                {/* the word space: a flex container draws no white space between its items, so it
                    changes nothing on screen; it keeps the link's words apart for assistive tech */}
                {' '}
                <span className={['n-areas__note', words.hand ? 'n-areas__note--hand' : ''].filter(Boolean).join(' ')} data-note={note!.key}>
                  {words.mark && <Mark kind={words.mark} size="sm" lang={lang} />}
                  <span className="n-areas__words" data-show-from="l">{words.long}</span>
                  <span className="n-areas__words" data-show-upto="m">{words.short}</span>
                  {count !== null && <span className="n-areas__count">{count}</span>}
                </span>
              </>
            )}
          </a>
        );
      })}
    </nav>
  );
}
