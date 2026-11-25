/* While you were away: what the hub did, raised and found since this browser last looked
   (PHASE_B_PLAN.md §5.2). Oldest first; held, blocked, raised and problem lines in semibold;
   titles are the hub's plain text (a React text node, never markup); the total is the accountant's
   line under the list. */
import React, { useId } from 'react';
import { docketHref, openDocketEntry } from '../../docket/links';
import { Mark, SecHead, SourceLabel, Total, markWord } from '../../frame/kit';
import { clockTime } from '../../frame/kit/strings';
import { pick, type Lang } from '../../frame/strings';
import { routeHref } from '../../hud-routing';
import type { AwaySummary, AwayWords } from '../../signals/away';
import type { AwayEntry, Reading } from '../../signals/types';
import { DAY_STRINGS } from './strings';
import { agentName } from './useDay';
import './day.css';

export interface AwayListProps {
  summary: AwaySummary;
  words: AwayWords;
  /** The day's feed, for the section's source label. */
  today: Reading<unknown>;
  lang: Lang;
  demo: boolean;
  names: Readonly<Record<string, string>>;
  /** Where "Open the day's record" goes. */
  recordPath: string;
  navigate: (path: string) => void;
}

/** The mark's own word for an entry (its accessible name). */
const entryWord = (entry: AwayEntry, lang: Lang): string => markWord(entry.mark, lang);

export function AwayList({ summary, words, today, lang, demo, names, recordPath, navigate }: AwayListProps) {
  const s = pick(DAY_STRINGS, lang);
  const headingId = useId();
  const todayCurrent = today.state === 'live' || today.state === 'empty';
  const recordLink = (
    <a className="n-link" href={routeHref(recordPath)} onClick={(event) => { event.preventDefault(); navigate(recordPath); }}>{s.openRecord}</a>
  );
  return (
    <section className="n-day__block" aria-labelledby={headingId} data-day-block="away">
      <SecHead
        title={<span id={headingId}>{s.away}</span>}
        aside={<><span>{words.since}</span><SourceLabel reading={today} lang={lang} /></>}
      />
      {summary.entries.length > 0 && (
        <ol className="n-away">
          {summary.entries.map((entry) => {
            const who = agentName(names, entry.agent);
            return (
              <li key={entry.id} className={`n-away__row${entry.exception ? ' is-exception' : ''}`} data-away-kind={entry.kind} data-at-kind={entry.atKind ?? 'event'}>
                <span className="n-away__mark" role="img" aria-label={entryWord(entry, lang)}><Mark kind={entry.mark} size="sm" /></span>
                <time className="n-away__time" dateTime={new Date(entry.at).toISOString()}>{clockTime(entry.at)}</time>
                <span className="n-away__who">{who}</span>
                <span className="n-away__what">
                  {entry.href && entry.source === 'docket'
                    ? <a className="n-link" href={entry.href || docketHref(entry.id)}
                      onClick={(event) => { event.preventDefault(); openDocketEntry(entry.id.replace(/^docket:/, '')); }}>{entry.title || words.docketEntry(entry.id)}</a>
                    : entry.title || words.docketEntry(entry.id)}
                  {entry.atKind === 'checked' && <span className="n-away__meta"> · {words.checked(entry.at)}</span>}
                </span>
              </li>
            );
          })}
        </ol>
      )}
      {summary.entries.length === 0 && (
        demo
          ? <p className="n-state n-state--unknown n-day__note">{s.awayDemo}</p>
          : !todayCurrent
            ? <p className="n-state n-state--unknown n-day__note">{s.awayUnknown}</p>
            : <p className="n-state n-day__note">{summary.unread.length > 0 ? words.emptyPartial : words.empty}</p>
      )}
      {summary.unread.length > 0 && !demo && (
        <ul className="n-away__unread">{words.unread.map((line) => <li key={line}>{line}</li>)}</ul>
      )}
      {summary.entries.length > 0 && !demo ? (
        <Total aside={recordLink}>
          <b>{words.totals.entries}</b>
          <span className="n-away__tally"><Mark kind="done" size="sm" />{words.totals.done}</span>
          <span className="n-away__tally"><Mark kind="held" size="sm" /><Mark kind="blocked" size="sm" />{words.totals.heldOrBlocked}</span>
          <span className="n-away__tally"><Mark kind="problem" size="sm" />{words.totals.problems}</span>
        </Total>
      ) : todayCurrent && !demo ? <p className="n-away__open">{recordLink}</p> : null}
    </section>
  );
}
