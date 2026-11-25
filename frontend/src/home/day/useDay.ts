/* Everything the day register and the day band draw, gathered once per component: the verdict
   (signals/hooks.ts useVerdict, the same call Glance makes), While you were away, the machine and
   the schedule. Both components call it; the readings underneath are shared requests. */
import { useMemo } from 'react';
import { docketHref } from '../../docket/links';
import { hubReading } from '../../frame/types';
import { routeHref } from '../../hud-routing';
import type { Lang } from '../../frame/strings';
import { awayEntries, awaySince, awayWords, type AwaySummary, type AwayWords } from '../../signals/away';
import { useAway, useBlockedTasks, useLastSeenAt, useVerdict } from '../../signals/hooks';
import { machineReadings } from '../../signals/machine';
import type { HubSnapshot, MachineReading, Reading, Verdict } from '../../signals/types';
import type { TodayFeed } from '../../signals/wire';
import { scheduleOf, type ScheduleItem } from './schedule';

/** The day's record page (Today panel). */
const RECORD_PATH = '/v2/console/today';

export interface DayData {
  readonly verdict: Verdict;
  readonly today: Reading<TodayFeed>;
  readonly away: AwaySummary;
  readonly awayWords: AwayWords;
  readonly machine: readonly MachineReading[];
  readonly schedule: readonly ScheduleItem[];
  /** The hub as a reading, for the Today and machine source labels. */
  readonly hubState: Reading<null>;
  /** id → display name, for the "who" column. */
  readonly names: Readonly<Record<string, string>>;
  /** Where "Open the day's record" goes (ready href). */
  readonly recordHref: string;
  readonly recordPath: string;
}

export function useDay(hub: HubSnapshot, lang: Lang, clock: Date, demo: boolean): DayData {
  const verdict = useVerdict(hub, lang, { demo });
  const today = useAway({ demo });
  const blocked = useBlockedTasks({ demo });
  const lastSeen = useLastSeenAt();
  const now = clock.getTime();
  const hubState = hubReading(hub, now);
  const recordHref = routeHref(RECORD_PATH);
  // Problems that began meanwhile are read from the service probes: when those did not answer (or
  // the hub did not), the list says nothing about problems and must not read as an all-clear.
  const problemsRead = demo || verdict.state === 'demo'
    || (verdict.state !== 'offline' && verdict.state !== 'checking' && !(verdict.missingKeys ?? []).includes('missingProbes'));

  const since = useMemo(() => awaySince(lastSeen, now), [lastSeen, Math.floor(now / 60_000)]);   // eslint-disable-line react-hooks/exhaustive-deps
  const away = awayEntries({
    today, blocked, causes: demo ? [] : verdict.causes, checkedAt: verdict.checkedAt, since, now, docketHref, recordHref, problemsRead,
  });
  const words = awayWords(away, lang, now);
  const machine = machineReadings({ sys: hub.sys, hubState: hubState.state, hubReason: hubState.reason }, lang);
  const schedule = useMemo(() => scheduleOf(hub.calendar, clock), [hub.calendar, Math.floor(now / 60_000)]);   // eslint-disable-line react-hooks/exhaustive-deps
  const names = useMemo(() => {
    const out: Record<string, string> = {};
    hub.agents.forEach((a) => {
      if (a && typeof a.id === 'string' && typeof a.name === 'string' && a.name.trim()) out[a.id.toLowerCase()] = a.name.trim();
    });
    return out;
  }, [hub.agents]);
  return { verdict, today, away, awayWords: words, machine, schedule, hubState, names, recordHref, recordPath: RECORD_PATH };
}

/** "pepper" → "Pepper": the hub's name when the roster has it, else the id capitalised. */
export function agentName(names: Readonly<Record<string, string>>, id: string | null): string | null {
  if (!id) return null;
  return names[id] ?? id.charAt(0).toUpperCase() + id.slice(1);
}
