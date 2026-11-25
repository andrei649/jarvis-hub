/* The day register of Home (PHASE_B_PLAN.md §5.1, §5.2): the date and the minute, the verdict with
   its causes and remedy, This machine (≥ 2200 px only), Today, and While you were away.
   Everything it draws is a Reading with a state; nothing is invented in demo, where the section
   says "Demo sample" and the sources it cannot read are said to be unread. */
import React from 'react';
import { Register, SourceLabel } from '../../frame/kit';
import { clockTime } from '../../frame/kit/strings';
import { demoReading, type HubSnapshot } from '../../signals/types';
import type { Lang } from '../../frame/strings';
import { AwayList } from './AwayList';
import { ThisMachine } from './ThisMachine';
import { TodayList } from './TodayList';
import { Verdict } from './Verdict';
import { useDay } from './useDay';
import './day.css';

export interface DayProps {
  hub: HubSnapshot;
  /** App's minute clock. */
  clock: Date;
  lang: Lang;
  demo: boolean;
  /** navigateHud: a logical path from nav/routes pathOf(). */
  navigate: (path: string) => void;
}

/** "Monday, 23 November" in the language. */
export function dayTitle(clock: Date, lang: Lang): string {
  try {
    return new Intl.DateTimeFormat(lang === 'ro' ? 'ro-RO' : 'en-GB', { weekday: 'long', day: 'numeric', month: 'long' }).format(clock);
  } catch {
    return clock.toDateString();
  }
}

export function DayRegister({ hub, clock, lang, demo, navigate }: DayProps) {
  const day = useDay(hub, lang, clock, demo);
  const showDemo = demo || hub.demo;
  const iso = `${clock.getFullYear()}-${String(clock.getMonth() + 1).padStart(2, '0')}-${String(clock.getDate()).padStart(2, '0')}T${clockTime(clock)}`;
  return (
    <Register
      register="day"
      className="n-day"
      title={dayTitle(clock, lang)}
      meta={(
        <>
          {showDemo && <SourceLabel reading={demoReading(null)} lang={lang} />}
          <time dateTime={iso}><b>{clockTime(clock)}</b></time>
        </>
      )}
    >
      <Verdict verdict={day.verdict} lang={lang} navigate={navigate} />
      <div className="n-day__machine" data-show-from="xl">
        <ThisMachine readings={day.machine} hubState={day.hubState} lang={lang} />
      </div>
      <TodayList hub={hub} hubState={day.hubState} clock={clock} lang={lang} />
      <AwayList summary={day.away} words={day.awayWords} today={day.today} lang={lang} demo={showDemo}
        names={day.names} recordPath={day.recordPath} navigate={navigate} />
    </Register>
  );
}
