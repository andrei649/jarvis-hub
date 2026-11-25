/* Timeline (/v2/timeline): the day as lanes, one per agent with something today
   (PHASE_B_PLAN.md §6; the Console direction's lanes, without the lens).

   Every mark is a real event from a named source (lanes.ts): finished actions, holds that wait for
   the owner (a stub says "since 2 Jul" when older than today; a numbered pin links to the docket
   entry), running work, and each agent's next heartbeat as a tick. Problems the observer reports
   name no agent, so they sit on a System lane. A source that did not answer draws nothing and is
   named in the foot; "no activity" is only said for agents the hub has been asked about. Titles
   are plain text. The right-hand column carries each agent's state (agents by exception). */
import React, { useMemo } from 'react';
import { Mark, Register, SourceLabel, clockTime } from '../frame/kit';
import { defineStrings, fmt, pick, plural, type Lang } from '../frame/strings';
import { docketHref, openDocketEntry } from '../docket/links';
import type { HubSnapshot, TabTurn } from '../signals/types';
import { agentsByException } from '../signals/agents-exception';
import { useAway, useBlockedTasks, useHeartbeats, useKillSwitchReading, useObserver, useRunningTasks, useSubagents } from '../signals/hooks';
import { buildTimeline, position, NO_AGENT, type Lane, type LaneEvent, type TimelineModel } from './lanes';
import { doneActions, useBlockedFeed, useRunningFeed, useSubagentsFeed } from './sources';
import { drawable, sinceWords, stamp } from './common';
import { IDENT } from '../theme/type';
import './pages.css';

export const TIMELINE_STRINGS = defineStrings({
  en: {
    title: 'Today by agent',
    demoNote: 'Demo sample: no live events are drawn.',
    laneLabel: 'Lanes of the day, one per agent with something today',
    hours: 'Hours',
    nowLabel: 'Now',
    doneEv: '{time} finished: {title}',
    holdEv: 'Waits for you {since}: {title}',
    holdPin: 'Decision {pin}: {title}',
    runTask: 'Running {since}: {title}',
    runSub: 'Sub-agent running {since}',
    runSubTask: 'Sub-agent running {since}: {task}',
    runStalled: 'Sub-agent, stalled, {since}',
    startUnknown: 'start time not reported',
    runTab: 'Asked {agent} at {time}',
    tick: 'Next check {time}',
    system: 'System',
    systemNone: 'No problems reported.',
    systemUnknown: 'Problems: not known, the observer did not answer.',
    systemEv: '{key}{detail}',
    systemSince: 'since {when}',
    systemSinceUnknown: 'start time not reported',
    noAgent: 'No agent named',
    dashed: 'Cloud only: unavailable while no cloud model is configured.',
    stateWaiting: { one: 'Waiting on you · {n}', few: 'Waiting on you · {n}', other: 'Waiting on you · {n}' },
    stateWorking: 'Working',
    stateFinished: { one: 'Finished today · {n}', few: 'Finished today · {n}', other: 'Finished today · {n}' },
    stateUnavailable: 'Unavailable',
    stateHalted: 'Halted',
    stateNone: 'No activity reported',
    folded: { one: '{n} agent with no activity reported today: {names}', few: '{n} agents with no activity reported today: {names}', other: '{n} agents with no activity reported today: {names}' },
    sources: 'Sources',
    srcToday: 'Finished',
    srcDocket: 'Waiting',
    srcRunning: 'Running',
    srcSubagents: 'Sub-agents',
    srcHeartbeats: 'Next checks',
    srcObserver: 'System',
    hidden: 'Not drawn because the hub did not answer: {which}.',
  },
  ro: {
    title: 'Ziua pe agenți',
    demoNote: 'Mostră demo: nu se desenează evenimente reale.',
    laneLabel: 'Culoarele zilei, unul pentru fiecare agent cu ceva azi',
    hours: 'Ore',
    nowLabel: 'Acum',
    doneEv: '{time} terminat: {title}',
    holdEv: 'Te așteaptă {since}: {title}',
    holdPin: 'Decizia {pin}: {title}',
    runTask: 'Rulează {since}: {title}',
    runSub: 'Sub-agent în lucru {since}',
    runSubTask: 'Sub-agent în lucru {since}: {task}',
    runStalled: 'Sub-agent blocat, {since}',
    startUnknown: 'ora de început nu este raportată',
    runTab: 'L-ai întrebat pe {agent} la {time}',
    tick: 'Următoarea verificare {time}',
    system: 'Sistem',
    systemNone: 'Nicio problemă raportată.',
    systemUnknown: 'Probleme: necunoscut, observatorul nu a răspuns.',
    systemEv: '{key}{detail}',
    systemSince: 'din {when}',
    systemSinceUnknown: 'ora de început nu este raportată',
    noAgent: 'Niciun agent numit',
    dashed: 'Doar cloud: indisponibil cât timp niciun model cloud nu este configurat.',
    stateWaiting: { one: 'Te așteaptă · {n}', few: 'Te așteaptă · {n}', other: 'Te așteaptă · {n}' },
    stateWorking: 'Lucrează',
    stateFinished: { one: 'Terminat azi · {n}', few: 'Terminat azi · {n}', other: 'Terminat azi · {n}' },
    stateUnavailable: 'Indisponibil',
    stateHalted: 'Oprit',
    stateNone: 'Nicio activitate raportată',
    folded: { one: '{n} agent fără activitate raportată azi: {names}', few: '{n} agenți fără activitate raportată azi: {names}', other: '{n} de agenți fără activitate raportată azi: {names}' },
    sources: 'Surse',
    srcToday: 'Terminat',
    srcDocket: 'În așteptare',
    srcRunning: 'În lucru',
    srcSubagents: 'Sub-agenți',
    srcHeartbeats: 'Următoarele verificări',
    srcObserver: 'Sistem',
    hidden: 'Nu este desenat pentru că hubul nu a răspuns: {which}.',
  },
});

type S = typeof TIMELINE_STRINGS.en;

function stateWords(lane: Lane, s: S, lang: Lang | string): string | null {
  const st = lane.state;
  if (!st) return null;
  switch (st.activity) {
    case 'waitingOnYou': return plural(lang, s.stateWaiting, st.count ?? 0);
    case 'working': return s.stateWorking;
    case 'finishedToday': return plural(lang, s.stateFinished, st.count ?? 0);
    case 'unavailable': return s.stateUnavailable;
    case 'halted': return s.stateHalted;
    default: return s.stateNone;
  }
}

/** The hub's own start time in words: "since 08:14", "since 2 Jul", or that it was not reported. */
function startWords(startedAt: number | null, now: number, lang: Lang | string, s: S): string {
  return startedAt === null ? s.startUnknown : sinceWords(startedAt, now, lang);
}

function Event({ ev, model, s, lang, agentName, open }: { ev: LaneEvent; model: TimelineModel; s: S; lang: Lang | string; agentName: string; open: (id: number) => (e: React.MouseEvent) => void }) {
  const now = model.now;
  switch (ev.kind) {
    case 'done': return (
      <li className="n-lanes__ev n-lanes__ev--done" style={{ left: `${position(model, ev.at)}%` }} data-ev="done">
        <Mark kind="done" size="sm" /><span className="n-lanes__sr">{fmt(s.doneEv, { time: clockTime(ev.at), title: ev.title })}</span>
      </li>
    );
    case 'hold': return (
      <li className="n-lanes__ev n-lanes__ev--hold" style={{ left: `${position(model, ev.since)}%`, width: `${Math.max(0.8, position(model, now) - position(model, ev.since))}%` }} data-ev="hold" data-stub={ev.stub ? 'true' : undefined} data-start={ev.startedAt === null ? 'unknown' : undefined}>
        {ev.stub && ev.olderThan !== null && <span className="n-lanes__stub">{sinceWords(ev.olderThan, now, lang)}</span>}
        <a className="n-lanes__pin" href={docketHref(ev.id)} onClick={open(ev.id)} aria-label={fmt(s.holdPin, { pin: ev.pin, title: ev.title })}>{ev.pin}</a>
        <span className="n-lanes__sr">{fmt(s.holdEv, { since: startWords(ev.startedAt, now, lang, s), title: ev.title })}</span>
      </li>
    );
    case 'run': {
      const since = startWords(ev.startedAt, now, lang, s);
      const text = ev.source === 'this-tab' ? (ev.startedAt === null ? s.startUnknown : fmt(s.runTab, { agent: agentName, time: clockTime(ev.startedAt) }))
        : ev.source === 'task' ? fmt(s.runTask, { since, title: ev.title ?? '' })
          : ev.stalled ? fmt(s.runStalled, { since })
            : ev.title ? fmt(s.runSubTask, { since, task: ev.title }) : fmt(s.runSub, { since });
      return (
        <li className={'n-lanes__ev n-lanes__ev--run' + (ev.stalled ? ' n-lanes__ev--stalled' : '')} data-ev="run" data-source={ev.source} data-stub={ev.stub ? 'true' : undefined} data-start={ev.startedAt === null ? 'unknown' : undefined}
          style={{ left: `${position(model, ev.since)}%`, width: `${Math.max(0.8, position(model, now) - position(model, ev.since))}%` }}>
          {ev.stub && ev.startedAt !== null && <span className="n-lanes__stub">{sinceWords(ev.startedAt, now, lang)}</span>}
          <span className="n-lanes__sr">{text}</span>
        </li>
      );
    }
    default: return (
      <li className="n-lanes__ev n-lanes__ev--tick" style={{ left: `${position(model, ev.at)}%` }} data-ev="tick">
        <span className="n-lanes__sr">{fmt(s.tick, { time: clockTime(ev.at) })}</span>
      </li>
    );
  }
}

export interface TimelineProps { hub: HubSnapshot; lang: Lang | string; demo: boolean; clock: Date; navigate: (path: string) => void; turns: readonly TabTurn[] }

export function Timeline({ hub, lang, demo, clock, turns }: TimelineProps) {
  const s: S = pick(TIMELINE_STRINGS, lang);
  const live = !demo;
  // the shared readings (signals/hooks.ts): the same requests the running foot and the day read
  const today = useAway({ enabled: live });
  const beats = useHeartbeats({ enabled: live });
  const observer = useObserver({ enabled: live });
  const kill = useKillSwitchReading({ enabled: live });
  const blockedLite = useBlockedTasks({ enabled: live });
  const runningLite = useRunningTasks({ enabled: live });
  const subsLite = useSubagents({ enabled: live });
  // the same paths with the fields the lanes need and the shared parsers leave out (a start time)
  const blocked = useBlockedFeed({ enabled: live });
  const running = useRunningFeed({ enabled: live });
  const subs = useSubagentsFeed({ enabled: live });
  const now = clock.getTime();
  const cloudConfigured = hub.trust ? hub.trust.cloudAvailable || hub.trust.claudeAvailable : null;
  const usable = <T,>(r: { state: string; value: T | null }): T | null => (r.state === 'live' || r.state === 'stale' || r.state === 'empty' ? r.value ?? ([] as unknown as T) : null);

  const states = useMemo(() => agentsByException({
    roster: hub.agents, rosterKnown: hub.sources.agents, blocked: blockedLite, running: runningLite, subagents: subsLite, turns,
    today, heartbeats: beats, trust: hub.trust, killSwitch: kill, slots: hub.slots, now,
  }, lang).agents, [hub.agents, hub.sources, hub.trust, hub.slots, blockedLite, runningLite, subsLite, turns, today, beats, kill, now, lang]);
  const observerProblems = usable(observer);
  const model = useMemo(() => buildTimeline({
    now, roster: hub.agents, done: today.state === 'disabled' ? null : usable(today) ? doneActions(usable(today)) : null,
    blocked: usable(blocked), running: usable(running), subagents: usable(subs)?.runs ?? null, turns,
    beats: usable(beats)?.heartbeats ?? null,
    observer: observerProblems && observerProblems.unhealthy ? observerProblems.unhealthy.map((p) => ({ key: p.key, detail: p.detail, since: p.since })) : null,
    states, cloudConfigured,
  }), [now, hub.agents, today, blocked, running, subs, turns, beats, observerProblems, states, cloudConfigured]);

  const open = (id: number) => (event: React.MouseEvent) => { event.preventDefault(); openDocketEntry(id); };
  const hourMarks = [0, 6, 12, 18, 24];
  const sources: Array<[string, Parameters<typeof SourceLabel>[0]['reading'], string]> = [
    [s.srcToday, today, 'today'], [s.srcDocket, blocked, 'docket'], [s.srcRunning, running, 'running'],
    [s.srcSubagents, subs, 'subagents'], [s.srcHeartbeats, beats, 'heartbeats'], [s.srcObserver, observer, 'observer'],
  ];
  const hidden = sources.filter(([, r]) => !drawable(r)).map(([name]) => name);

  if (demo) {
    return (
      <Register title={s.title} register="timeline" meta={<SourceLabel reading={{ state: 'demo', lastGoodAt: null }} lang={lang} />}>
        <p className="n-pgnote" data-demo-note="">{s.demoNote}</p>
      </Register>
    );
  }

  const row = (lane: Lane) => {
    const word = stateWords(lane, s, lang);
    return (
      <div className={'n-lanes__row' + (lane.dashed ? ' n-lanes__row--dashed' : '')} role="row" key={lane.id} data-lane={lane.id}>
        <div className="n-lanes__who" role="rowheader">{lane.id === NO_AGENT ? s.noAgent : lane.name}</div>
        <div className="n-lanes__track" role="cell">
          <ol className="n-lanes__events">
            {lane.events.map((ev, i) => <Event key={i} ev={ev} model={model} s={s} lang={lang} agentName={lane.name} open={open} />)}
          </ol>
          {lane.dashed && <span className="n-lanes__note">{s.dashed}</span>}
        </div>
        <div className="n-lanes__now" role="cell">{lane.state && <Mark kind={lane.state.mark} size="sm" />} {word}</div>
      </div>
    );
  };

  return (
    <Register title={s.title} register="timeline"
      meta={<SourceLabel reading={today} lang={lang} />}
      foot={(
        <div className="n-lanes__sources" data-timeline-sources="">
          <b>{s.sources}</b>
          {sources.map(([name, reading]) => <span key={name}>{name} <SourceLabel reading={reading} lang={lang} showTime={false} /></span>)}
          {hidden.length > 0 && <span className="n-lanes__hidden">{fmt(s.hidden, { which: hidden.join(', ') })}</span>}
        </div>
      )}>
      <div className="n-lanes" role="table" aria-label={s.laneLabel}>
        <div className="n-lanes__axis" role="row">
          <span role="columnheader" className="n-lanes__who">{s.hours}</span>
          <span role="columnheader" className="n-lanes__track n-lanes__hours">
            {hourMarks.map((h) => <span key={h} className="n-lanes__hour" style={{ left: `${(h / 24) * 100}%` }}>{String(h % 24).padStart(2, '0')}:00</span>)}
            <span className="n-lanes__nowline" style={{ left: `${position(model, now)}%` }} data-now="">{s.nowLabel} {clockTime(now)}</span>
          </span>
          <span role="columnheader" className="n-lanes__now">{s.nowLabel}</span>
        </div>
        {model.lanes.map(row)}
        <div className="n-lanes__row n-lanes__row--system" role="row" data-lane="system">
          <div className="n-lanes__who" role="rowheader">{s.system}</div>
          <div className="n-lanes__track" role="cell">
            {model.system === null ? <span className="n-lanes__note">{s.systemUnknown}</span>
              : model.system.length === 0 ? <span className="n-lanes__note">{s.systemNone}</span>
                : (
                  <ol className="n-lanes__events">
                    {model.system.map((p) => (
                      <li key={p.key} className="n-lanes__ev n-lanes__ev--system" data-ev="system" data-stub={p.stub ? 'true' : undefined} data-start={p.startedAt === null ? 'unknown' : undefined} style={{ left: `${position(model, p.since ?? now)}%`, width: `${Math.max(0.8, position(model, now) - position(model, p.since ?? now))}%` }}>
                        <Mark kind="problem" size="sm" />
                        {p.stub && p.startedAt !== null && <span className="n-lanes__stub">{sinceWords(p.startedAt, now, lang)}</span>}
                        <span className="n-lanes__sr"><code style={IDENT}>{p.key}</code>{p.detail ? ` — ${p.detail}` : ''}{' · '}{p.startedAt !== null ? fmt(s.systemSince, { when: stamp(p.startedAt, now, lang) }) : s.systemSinceUnknown}</span>
                      </li>
                    ))}
                  </ol>
                )}
          </div>
          <div className="n-lanes__now" role="cell" />
        </div>
      </div>
      {model.folded.length > 0 && <p className="n-pgnote n-lanes__folded" data-folded="">{plural(lang, s.folded, model.folded.length, { names: model.folded.join(', ') })}</p>}
    </Register>
  );
}
