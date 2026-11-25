/* Home — Today (PHASE_B_PLAN.md §5.1): the spread of registers, laid out per width in home.css.

     ≥ 2200   day 432 · conversation 1fr · docket 712 · agents and the record 404
     1680–    day 396 · conversation 1fr · docket 664           (agents, machine in the foot)
     1340–    DayBand above · conversation 1fr · docket minmax(500px, 44.5%)
     1100–    DayBand above · conversation 1fr · docket minmax(480px, 43.5%)
     ≤ 1099   one column: DayBand, docket, conversation (the page scrolls)

   The registers are the other engineers': the day (DayRegister and its folded DayBand,
   home/day), the conversation (TalkRegister, home/talk), the docket (docket/Docket) and, at
   2200px and wider, agents by exception with the record's tail (pages/AgentsRecordRegister).

   - The day register and the band read the same shared requests, so both stay mounted and the
     stylesheet shows one of them.
   - The fourth register reads feeds of its own (the record, the heartbeats), so it is mounted
     only while the viewport is that wide (§5.6: polled only while a page shows it). Without
     matchMedia (a test DOM) it is mounted and the stylesheet decides.
   - Under the day register a quiet "More in Home · 8 pages" opens Home's other pages (§3.3):
     Today has no contents column of its own. Below 1680px, where the day folds into its band, the
     same link ends the band and its list opens over the page (`popover`), so Home's pages are
     one click away at every width, not only through Ctrl K.
   - The conversation cell is the skip link's target. */
import React, { useEffect, useId, useState } from 'react';
import { Docket } from '../docket/Docket';
import { HOME_TALK_ID } from '../frame/ids';
import { PAGE_STRINGS } from '../frame/frame-strings';
import { fmt, pick, plural, type Lang } from '../frame/strings';
import { areaById, textOf } from '../nav/areas';
import { contentsModel } from '../nav/contents-model';
import { PageLink } from '../nav/ContentsColumn';
import { AgentsRecordRegister } from '../pages/AgentsRecordRegister';
import type { HubSnapshot, TabTurn } from '../signals/types';
import { DayBand } from './day/DayBand';
import { DayRegister } from './day/DayRegister';
import { TalkRegister } from './talk/TalkRegister';
import type { TalkInput } from './talk/types';
import './home.css';

export interface HomeProps {
  hub: HubSnapshot;
  /** App's minute clock. */
  clock: Date;
  lang: Lang;
  demo: boolean;
  navigate: (path: string) => void;
  talk: TalkInput;
  turns: readonly TabTurn[];
  /** A mid-turn question from this tab waits for the owner's answer (App's `question`): the
   *  working reply says "Waiting for your answer". */
  awaitingAnswer?: boolean;
}

/** "Monday, 23 November" / "luni, 23 noiembrie": the page's heading. Built from the locale's own
 *  names, in one order for both languages (en-GB drops the comma on some ICUs). */
export function dayTitle(clock: Date, lang: Lang): string {
  try {
    const parts = new Intl.DateTimeFormat(lang === 'ro' ? 'ro-RO' : 'en-GB', { weekday: 'long', day: 'numeric', month: 'long' }).formatToParts(clock);
    const part = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
    return `${part('weekday')}, ${part('day')} ${part('month')}`;
  } catch {
    return clock.toDateString();
  }
}

/** The width the fourth register is drawn at (xl, frame/frame.css). */
export const RECORD_QUERY = '(min-width: 2200px)';

function mediaList(query: string): MediaQueryList | null {
  try {
    return typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(query) || null : null;
  } catch {
    return null;
  }
}

/** Whether a media query matches, following changes. Where the DOM cannot say (no matchMedia),
 *  it answers `fallback`. */
export function useMediaQuery(query: string, fallback: boolean): boolean {
  const [matches, setMatches] = useState(() => mediaList(query)?.matches ?? fallback);
  useEffect(() => {
    const list = mediaList(query);
    if (!list) return undefined;
    const update = () => setMatches(list.matches);
    update();
    if (typeof list.addEventListener === 'function') {
      list.addEventListener('change', update);
      return () => list.removeEventListener('change', update);
    }
    list.addListener?.(update);
    return () => list.removeListener?.(update);
  }, [query]);
  return matches;
}

/** "More in Home · 8 pages": Home's other pages behind a quiet link at the foot of the day
 *  register (§3.3), in the order of Home's contents. The list opens in place, or over the page
 *  (`popover`: at the end of the day band, where opening in place would push the registers down). */
export function MoreInHome({ lang, navigate, popover = false }: { lang: Lang; navigate: (path: string) => void; popover?: boolean }) {
  const s = pick(PAGE_STRINGS, lang);
  const [open, setOpen] = useState(false);
  const listId = `n-home-more-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const home = areaById('home');
  if (!home) return null;
  const model = contentsModel(home, home.landing);
  const items = model.groups
    .flatMap((g) => [...g.primary, ...g.more].sort((a, b) => g.group.pages.indexOf(a.entry) - g.group.pages.indexOf(b.entry)))
    .filter((item) => !item.current);
  if (!items.length) return null;
  return (
    <div className={'n-home__more' + (popover ? ' n-home__more--popover' : '')} data-home-more={popover ? 'band' : 'register'}
      onKeyDown={popover ? (event) => { if (event.key === 'Escape' && open) { event.stopPropagation(); setOpen(false); } } : undefined}>
      <button type="button" className="n-link n-home__more-toggle" aria-expanded={open} aria-controls={listId}
        onClick={() => setOpen((value) => !value)}>
        {plural(lang, s.moreInHome, items.length, { area: textOf(home.label, lang) })}
      </button>
      <ul id={listId} className="n-toc n-home__more-list" hidden={!open}>
        {items.map((item) => (
          <li key={item.entry.key}><PageLink item={item} lang={lang} navigate={navigate} className="n-toc-link" /></li>
        ))}
      </ul>
    </div>
  );
}

export function Home({ hub, clock, lang, demo, navigate, talk, turns, awaitingAnswer = false }: HomeProps) {
  const s = pick(PAGE_STRINGS, lang);
  const wide = useMediaQuery(RECORD_QUERY, true);
  const day = { hub, clock, lang, demo, navigate };
  return (
    <div className="n-home" data-home="">
      <h1 data-visually-hidden="">{fmt(s.todayHeading, { date: dayTitle(clock, lang) })}</h1>
      <div className="n-home__bandrow" data-show-upto="m">
        <DayBand {...day} aside={<MoreInHome lang={lang} navigate={navigate} popover />} />
      </div>
      <div className="n-spread n-spread--home">
        <div className="n-spread__cell n-spread__cell--day" data-show-from="l">
          <DayRegister {...day} />
          <MoreInHome lang={lang} navigate={navigate} />
        </div>
        <div className="n-spread__cell n-spread__cell--talk" id={HOME_TALK_ID} tabIndex={-1}>
          <TalkRegister {...talk} variant="home" turns={turns} awaitingAnswer={awaitingAnswer} />
        </div>
        <div className="n-spread__cell n-spread__cell--docket">
          <Docket lang={lang} demo={demo} navigate={navigate} />
        </div>
        {wide && (
          <div className="n-spread__cell n-spread__cell--record" data-show-from="xl">
            <AgentsRecordRegister hub={hub} lang={lang} demo={demo} navigate={navigate} turns={turns} />
          </div>
        )}
      </div>
    </div>
  );
}
