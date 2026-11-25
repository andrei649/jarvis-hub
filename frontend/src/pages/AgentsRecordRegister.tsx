/* The fourth Home register at 2200 px and wider (PHASE_B_PLAN.md §5.5; data-register="record"):
   the agents by exception, then the tail of the record.

   Each agent has one state, each from a named source (agent-states.ts): waiting on you, working,
   finished today, unavailable, halted, or "no activity reported", which is one line of names.
   The words idle, ready and active are never used: the hub does not record them. Replies running
   in another window or surface are counted without a name ("1 reply running elsewhere"), because
   the turn slots carry no agent. The tail shows only the fields the audit endpoint sends. */
import React from 'react';
import { Mark, Register, SecHead, SourceLabel, Total } from '../frame/kit';
import { defineStrings, fmt, pick, plural, type Lang } from '../frame/strings';
import type { AgentState, HubSnapshot, TabTurn } from '../signals/types';
import { agentsByException } from '../signals/agents-exception';
import { useAuditVerify, useAway, useBlockedTasks, useHeartbeats, useKillSwitchReading, useRunningTasks, useSubagents } from '../signals/hooks';
import { NoReading, PageLink, drawable, stamp } from './common';
import { shortHash } from './RecordTable';
import { useRecordFeed } from './sources';
import { IDENT } from '../theme/type';
import './pages.css';

export const AGENTS_RECORD_STRINGS = defineStrings({
  en: {
    agentsTitle: 'Agents',
    byException: 'by exception',
    recordTitle: 'The record',
    demoNote: 'Demo sample: no live agent state or record is drawn here.',
    waiting: { one: 'Waiting on you · {n}', few: 'Waiting on you · {n}', other: 'Waiting on you · {n}' },
    working: 'Working',
    finished: 'Finished today',
    unavailable: 'Unavailable',
    halted: 'Halted',
    none: { one: '{n} agent with no activity reported: {names}', few: '{n} agents with no activity reported: {names}', other: '{n} agents with no activity reported: {names}' },
    count: '{n}',
    elsewhere: { one: '{n} reply running elsewhere', few: '{n} replies running elsewhere', other: '{n} replies running elsewhere' },
    elsewhereUnknown: 'Replies running elsewhere: not reported',
    unknownSources: 'Not known: {which}.',
    srcDocket: 'decisions',
    srcRunning: 'running tasks',
    srcSubagents: 'sub-agents',
    srcToday: 'finished actions',
    recordEmpty: 'No entries in the record yet.',
    by: 'by {who}',
    chainIntact: 'Chain intact',
    chainBroken: 'Chain broken',
    chainUnknown: 'Chain not verified',
    openRecord: 'Open the record',
    sealed: 'Sealed',
    broken: 'Seal broken',
    entry: 'Entry',
  },
  ro: {
    agentsTitle: 'Agenți',
    byException: 'doar excepțiile',
    recordTitle: 'Registrul',
    demoNote: 'Mostră demo: aici nu se desenează nicio stare reală a agenților și niciun registru real.',
    waiting: { one: 'Te așteaptă · {n}', few: 'Te așteaptă · {n}', other: 'Te așteaptă · {n}' },
    working: 'Lucrează',
    finished: 'Terminat azi',
    unavailable: 'Indisponibil',
    halted: 'Oprit',
    none: { one: '{n} agent fără activitate raportată: {names}', few: '{n} agenți fără activitate raportată: {names}', other: '{n} de agenți fără activitate raportată: {names}' },
    count: '{n}',
    elsewhere: { one: '{n} răspuns rulează în altă parte', few: '{n} răspunsuri rulează în altă parte', other: '{n} de răspunsuri rulează în altă parte' },
    elsewhereUnknown: 'Răspunsuri care rulează în altă parte: neraportat',
    unknownSources: 'Necunoscut: {which}.',
    srcDocket: 'deciziile',
    srcRunning: 'sarcinile în lucru',
    srcSubagents: 'sub-agenții',
    srcToday: 'acțiunile terminate',
    recordEmpty: 'Încă nu există intrări în registru.',
    by: 'de {who}',
    chainIntact: 'Lanț intact',
    chainBroken: 'Lanț rupt',
    chainUnknown: 'Lanț neverificat',
    openRecord: 'Deschide registrul',
    sealed: 'Sigilat',
    broken: 'Sigiliu rupt',
    entry: 'Intrare',
  },
});

type S = typeof AGENTS_RECORD_STRINGS.en;

const GROUPS: ReadonlyArray<{ activity: AgentState['activity']; mark: AgentState['mark'] }> = [
  { activity: 'waitingOnYou', mark: 'seal-open' }, { activity: 'working', mark: 'work' }, { activity: 'finishedToday', mark: 'done' },
  { activity: 'unavailable', mark: 'blocked' }, { activity: 'halted', mark: 'held' },
];

function groupWord(activity: AgentState['activity'], agents: readonly AgentState[], s: S, lang: Lang | string): string {
  switch (activity) {
    case 'waitingOnYou': return plural(lang, s.waiting, agents.reduce((n, a) => n + (a.count ?? 0), 0));
    case 'working': return s.working;
    case 'finishedToday': return s.finished;
    case 'unavailable': return s.unavailable;
    default: return s.halted;
  }
}

export interface AgentsRecordRegisterProps { hub: HubSnapshot; lang: Lang | string; demo: boolean; navigate: (path: string) => void; turns: readonly TabTurn[] }

export function AgentsRecordRegister({ hub, lang, demo, navigate, turns }: AgentsRecordRegisterProps) {
  const s: S = pick(AGENTS_RECORD_STRINGS, lang);
  const live = !demo;
  // the same shared readings the running foot reads: one derivation, so the two cannot disagree
  const blocked = useBlockedTasks({ enabled: live });
  const running = useRunningTasks({ enabled: live });
  const subs = useSubagents({ enabled: live });
  const today = useAway({ enabled: live });
  const beats = useHeartbeats({ enabled: live });
  const kill = useKillSwitchReading({ enabled: live });
  const record = useRecordFeed({ demo });
  const chain = useAuditVerify({ demo });
  const now = Date.now();

  if (demo) {
    return (
      <Register title={s.agentsTitle} register="record" meta={<SourceLabel reading={{ state: 'demo', lastGoodAt: null }} lang={lang} />}>
        <p className="n-pgnote" data-demo-note="">{s.demoNote}</p>
      </Register>
    );
  }

  const states = agentsByException({
    roster: hub.agents, rosterKnown: hub.sources.agents, blocked, running, subagents: subs, turns, today, heartbeats: beats,
    trust: hub.trust, killSwitch: kill, slots: hub.slots, now,
  }, lang);
  const groups = GROUPS.map((g) => ({ ...g, agents: states.agents.filter((a) => a.activity === g.activity) })).filter((g) => g.agents.length > 0);
  // a scheduled heartbeat is not activity: the Timeline and the Agents page show it, Home does not
  const quiet = states.agents.filter((a) => a.activity === 'noActivity' || a.activity === 'scheduled');
  const unknownWords: Record<string, string> = { docket: s.srcDocket, running: s.srcRunning, subagents: s.srcSubagents, today: s.srcToday };
  const elsewhere = states.elsewhere;
  const tail = (record.value?.entries ?? []).slice(0, 5);
  const chainOk = record.value?.chainOk ?? null;
  const chainWord = !demo && chain.value && (chain.state === 'live' || chain.state === 'stale') ? (chain.value.valid ? s.chainIntact : s.chainBroken) : s.chainUnknown;

  return (
    <Register title={s.agentsTitle} register="record" meta={<span>{s.byException}</span>}
      foot={<Total aside={<PageLink path="/v2/trust" navigate={navigate}>{s.openRecord}</PageLink>}><b>{chainWord}</b></Total>}>
      <div className="n-agents" data-agents-by-exception="">
        {groups.map((g) => (
          <div className="n-agents__group" key={g.activity} data-activity={g.activity}>
            <h3 className="n-agents__head"><Mark kind={g.mark} size="sm" /> {groupWord(g.activity, g.agents, s, lang)}</h3>
            <ul className="n-agents__list">
              {g.agents.map((a) => (
                <li key={a.id} data-agent={a.id} data-source={a.source}>
                  <b>{a.name}</b>
                  {a.activity === 'waitingOnYou' && a.count ? <span className="n-agents__n"> · {fmt(s.count, { n: a.count })}</span> : null}
                  {a.detail && a.activity !== 'waitingOnYou' && <span className="n-agents__detail">{a.detail}</span>}
                </li>
              ))}
            </ul>
          </div>
        ))}
        {quiet.length > 0 && <p className="n-agents__quiet" data-activity="noActivity">{plural(lang, s.none, quiet.length, { names: quiet.map((a) => a.name).join(', ') })}</p>}
        {(elsewhere === null || elsewhere > 0) && <p className="n-pgnote" data-elsewhere="">{elsewhere === null ? s.elsewhereUnknown : plural(lang, s.elsewhere, elsewhere)}</p>}
        {states.unread.length > 0 && <p className="n-pgnote" data-unknown-sources="">{fmt(s.unknownSources, { which: states.unread.map((k) => unknownWords[k]).join(', ') })}</p>}
      </div>

      <SecHead title={s.recordTitle} aside={<SourceLabel reading={record} lang={lang} />} />
      {drawable(record)
        ? tail.length > 0
          ? (
            <ol className="n-chaintail" data-record-tail="">
              {tail.map((e) => (
                <li key={e.seq}>
                  <time>{e.at !== null ? stamp(e.at, now, lang) : '—'}</time>
                  <span className="n-chaintail__what">{e.why ?? e.action ?? s.entry}{e.actor && <small> · {fmt(s.by, { who: e.actor })}</small>}</span>
                  <span className="n-chaintail__seal">
                    {chainOk === true && <Mark kind="chain" size="sm" label lang={lang} />}
                    {chainOk === false && <Mark kind="problem" size="sm" label lang={lang} />}
                    {shortHash(e.hash) && <code style={IDENT}>{shortHash(e.hash)}</code>}
                  </span>
                </li>
              ))}
            </ol>
          )
          : <p className="n-pgnote">{s.recordEmpty}</p>
        : <NoReading reading={record} lang={lang} />}
    </Register>
  );
}
