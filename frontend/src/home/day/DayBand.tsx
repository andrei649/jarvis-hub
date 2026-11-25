/* The day, folded (PHASE_B_PLAN.md §5.1, §5.2): below 1680 px the day register has no room, so its
   three headlines become one band of disclosure cells — the verdict, the next event, the away
   summary — and each opens the full list as a popover. The same derivations as the register
   (home/day/useDay.ts), so the band can never disagree with it, or with Glance. */
import React from 'react';
import { Disclosure, Mark } from '../../frame/kit';
import { clockTime } from '../../frame/kit/strings';
import { fmt, pick, type Lang } from '../../frame/strings';
import { VERDICT_STRINGS } from '../../signals/verdict';
import { AwayList } from './AwayList';
import { TodayList } from './TodayList';
import { Verdict } from './Verdict';
import { untilWords } from './schedule';
import { DAY_STRINGS } from './strings';
import { useDay } from './useDay';
import type { DayProps } from './DayRegister';
import './day.css';

const STATE_WORD = {
  demo: 'stateDemo', checking: 'stateChecking', offline: 'stateOffline', halted: 'stateHalted',
  degraded: 'stateDegraded', problem: 'stateProblem', normal: 'stateNormal', unknown: 'stateUnknown',
} as const;

/** `aside`: a fourth cell at the band's end (Home puts "More in Home" there: below 1680px the day
 *  register, whose foot carries it, is not drawn). */
export function DayBand({ hub, clock, lang, demo, navigate, aside }: DayProps & { aside?: React.ReactNode }) {
  const s = pick(DAY_STRINGS, lang);
  const words = pick(VERDICT_STRINGS, lang);
  const day = useDay(hub, lang, clock, demo);
  const showDemo = demo || hub.demo;
  const { verdict, schedule } = day;

  const rest = [
    verdict.since !== null ? fmt(s.sinceTime, { time: clockTime(verdict.since) }) : null,
    verdict.checkedAt !== null ? fmt(s.checkedAt, { time: clockTime(verdict.checkedAt) }) : null,
  ].filter(Boolean).join(' · ');

  const next = schedule.find((item) => item.phase === 'next') ?? null;
  const afterNext = next ? schedule.slice(schedule.indexOf(next) + 1).find((item) => item.phase === 'later') ?? null : null;
  const until = next ? untilWords(next.minutes, clock, lang) : null;
  const calendarAnswered = day.hubState.state === 'live' || day.hubState.state === 'stale' || day.hubState.state === 'demo';
  // "Nothing more today" only when every event's start was read and all are over; an event
  // without a readable start could still be ahead. An empty list is the combined sentence: the hub
  // cannot tell an empty calendar from one that is not connected.
  const unreadStart = schedule.find((item) => item.phase === 'unknown') ?? null;
  const nextHeadline = next ? `${next.time} · ${next.title}`
    : unreadStart ? (unreadStart.allDay ? `${s.allDay} · ${unreadStart.title}` : s.bandTimesUnknown)
      : schedule.length > 0 ? s.bandNothingNext
        : calendarAnswered ? s.bandNoCalendar : s.bandAwayUnknown;
  const nextRest = next
    ? [until, afterNext ? fmt(s.bandThen, { time: afterNext.time, title: afterNext.title }) : null].filter(Boolean).join(' · ')
    : '';

  const w = day.awayWords;
  const known = day.away.known;
  const todayCurrent = day.today.state === 'live' || day.today.state === 'empty';
  const awayHeadline = showDemo ? s.bandAwayDemo
    : !todayCurrent ? s.bandAwayUnknown
      : day.away.entries.length === 0
        ? [fmt(s.bandAwayNone, { time: clockTime(day.away.since.at) }), w.unreadCount].filter(Boolean).join(' · ')
        : [known.done ? w.totals.done : null, known.heldOrBlocked ? w.totals.heldOrBlocked : null, known.problems ? w.totals.problems : null, w.unreadCount]
          .filter(Boolean).join(' · ');

  return (
    <div className={'n-dayband' + (aside ? ' n-dayband--aside' : '')} role="group" aria-label={s.bandRegion} data-frame="dayband">
      <Disclosure className="n-dayband__cell" buttonClassName="n-dayband__button" panelClassName="n-dayband__panel" title={s.bandHealth}
        label={(
          <>
            <Mark kind={verdict.mark} />
            <span data-visually-hidden>{words[STATE_WORD[verdict.state]]}: </span>
            <b className="n-dayband__headline">{verdict.headline}</b>
            {rest && <span className="n-dayband__rest">{rest}</span>}
          </>
        )}>
        <Verdict verdict={verdict} lang={lang} navigate={navigate} />
      </Disclosure>
      <Disclosure className="n-dayband__cell" buttonClassName="n-dayband__button" panelClassName="n-dayband__panel" title={s.bandNext}
        label={(
          <>
            <span className="n-dayband__k">{s.nextTag}</span>
            <b className="n-dayband__headline">{nextHeadline}</b>
            {nextRest && <span className="n-dayband__rest">{nextRest}</span>}
          </>
        )}>
        <TodayList hub={hub} hubState={day.hubState} clock={clock} lang={lang} />
      </Disclosure>
      <Disclosure className="n-dayband__cell" buttonClassName="n-dayband__button" panelClassName="n-dayband__panel" title={s.bandAway} align="end"
        label={(
          <>
            <span className="n-dayband__k">{s.away}</span>
            <b className="n-dayband__headline">{awayHeadline}</b>
          </>
        )}>
        <AwayList summary={day.away} words={day.awayWords} today={day.today} lang={lang} demo={showDemo}
          names={day.names} recordPath={day.recordPath} navigate={navigate} />
      </Disclosure>
      {aside && <div className="n-dayband__cell n-dayband__aside">{aside}</div>}
    </div>
  );
}
