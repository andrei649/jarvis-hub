/* Today: the calendar from the loader and the weather line (PHASE_B_PLAN.md §5.2).
   The hub cannot tell a connected, empty calendar from one that is not connected (gap-2 D10), so
   an empty list says both. Past and next come from the minute clock. */
import React, { useId } from 'react';
import { Mark, SecHead, SourceLabel } from '../../frame/kit';
import { pick, type Lang } from '../../frame/strings';
import type { HubSnapshot, Reading } from '../../signals/types';
import { DAY_STRINGS } from './strings';
import { scheduleOf, untilWords, weatherLine } from './schedule';
import './day.css';

export interface TodayListProps {
  hub: HubSnapshot;
  /** The hub as a reading (hubReading(hub, now)): the label's state. */
  hubState: Reading<null>;
  clock: Date;
  lang: Lang;
}

export function TodayList({ hub, hubState, clock, lang }: TodayListProps) {
  const s = pick(DAY_STRINGS, lang);
  const headingId = useId();
  const items = scheduleOf(hub.calendar, clock);
  const weather = weatherLine(hub.weather);
  const answered = hubState.state === 'live' || hubState.state === 'demo' || hubState.state === 'stale';
  const state = hubState.state === 'live' && !items.length ? 'empty' : hubState.state;
  const label = { state, reason: hubState.reason, status: hubState.status, lastGoodAt: hubState.lastGoodAt } as Pick<Reading<unknown>, 'state' | 'reason' | 'status' | 'lastGoodAt'>;
  return (
    <section className="n-day__block" aria-labelledby={headingId} data-day-block="today">
      <SecHead title={<span id={headingId}>{s.today}</span>} aside={<>{weather && <span>{weather}</span>}<SourceLabel reading={label} lang={lang} /></>} />
      {items.length > 0 ? (
        <ol className="n-schedule">
          {items.map((item, i) => {
            const until = item.phase === 'next' ? untilWords(item.minutes, clock, lang) : null;
            return (
              <li key={`${item.time}|${item.title}|${i}`} className={`n-schedule__row is-${item.phase}`} data-phase={item.phase}>
                {item.phase === 'next'
                  ? <span className="n-schedule__mark" role="img" aria-label={s.nextTag}><Mark kind="work" size="sm" /></span>
                  : <span aria-hidden="true" />}
                <time className="n-schedule__time">{item.allDay ? s.allDay : item.time}</time>
                <span className="n-schedule__what">{item.title}</span>
                <span className="n-schedule__where">
                  {item.where}
                  {item.where && until ? ' · ' : ''}
                  {until && <b>{until}</b>}
                </span>
              </li>
            );
          })}
        </ol>
      ) : answered ? (
        <p className="n-state n-state--unknown n-day__note">{s.todayEmpty}</p>
      ) : (
        <p className="n-state n-state--unknown n-day__note">{s.todayUnknown}</p>
      )}
    </section>
  );
}
