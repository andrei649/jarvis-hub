/* Work · Overview (/v2/work): what needs you, what is running, what is scheduled, what is done
   (PHASE_B_PLAN.md §6; gap-2 §9C), composed in the browser from per-source readings. There is no
   server aggregate yet (B3), so there is no cross-source ordering: each section lists one source
   and carries that source's label.

   Honesty (§1.4): a source the owner is not allowed to read says "Refused", not "0"; one that did
   not answer says "Unknown"; a source that answered with nothing says so in words. Turn slots show
   surface and age, never an agent (the hub does not record one); an agent is named only where a
   named source proves it (a running task, a sub-agent, this tab's own turn). Titles are plain
   text. In demo no live list is drawn; the sections say so. */
import React from 'react';
import { Mark, Register, SourceLabel, TierGlyph, Total, clockTime } from '../frame/kit';
import { defineStrings, fmt, pick, plural, type Lang } from '../frame/strings';
import { docketHref, openDocketEntry, useDocketSummary } from '../docket/links';
import type { HubSnapshot, Reading, TabTurn } from '../signals/types';
import type { Question } from '../pending-question';
import { NoReading, PageLink, drawable, stamp } from './common';
import { rosterAgents } from './agent-states';
import { useAway, useHeartbeats, useSlots } from '../signals/hooks';
import {
  doneActions, startOfDay, topBlocked, useBlockedFeed, useJobsFeed, usePaymentsFeed, useRunningFeed,
  useSkillChangesFeed, useSubagentsFeed,
} from './sources';
import './pages.css';

export const WORK_STRINGS = defineStrings({
  en: {
    needsTitle: 'Needs you',
    runningTitle: 'Running now',
    scheduledTitle: 'Scheduled',
    doneTitle: 'Done today',
    demoNote: 'Demo sample: no live work is listed here.',
    docketWaiting: { one: '{n} decision awaits your signature', few: '{n} decisions await your signature', other: '{n} decisions await your signature' },
    docketRequests: { one: '{n} request behind them', few: '{n} requests behind them', other: '{n} requests behind them' },
    friction: '{typed} typed · {twoStep} two-step · {click} one click',
    docketNone: 'Nothing waits on the docket.',
    docketUnknown: 'Decisions: not known.',
    openDocket: 'Open the docket',
    paymentsWaiting: { one: '{n} payment waits for your approval', few: '{n} payments wait for your approval', other: '{n} payments wait for your approval' },
    paymentsNone: 'No payment waits for approval.',
    paymentsUnknown: 'Payments: not known.',
    openPayments: 'Open Trust',
    skillChanges: { one: '{n} skill change is pending review', few: '{n} skill changes are pending review', other: '{n} skill changes are pending review' },
    skillChangesNone: 'No skill change is pending.',
    skillChangesUnknown: 'Skill changes: not known.',
    openDecisions: 'Open Decisions',
    questionOpen: 'A question is open in this conversation: {question}',
    openConversation: 'Answer it in the conversation',
    topHeading: 'The strictest first',
    by: 'by {agent}',
    turnsRunning: { one: '{n} turn is running now', few: '{n} turns are running now', other: '{n} turns are running now' },
    turnsRunningCap: 'of {cap} allowed',
    turnsIdle: 'No turn is running.',
    turnsUnknown: 'Turns running: not reported.',
    holdersHeading: 'Where they run (the hub does not record an agent)',
    holder: '{surface} · {age}',
    ageSeconds: 'under a minute',
    ageMinutes: '{n} min',
    ageHours: '{n} h',
    tasksHeading: 'Running tasks',
    tasksNone: 'No task is running.',
    tasksUnknown: 'Running tasks: not known.',
    subagentsHeading: 'Sub-agents',
    subagentsNone: 'No sub-agent is running.',
    subagentsUnknown: 'Sub-agents: not known.',
    subCap: '{active} of {cap} in use',
    stalled: 'stalled',
    forParent: 'for {parent}',
    thisTab: 'This tab',
    askedAgent: 'Asked {agent} at {time}',
    heartbeatsHeading: 'Next checks',
    heartbeatsNone: 'No heartbeat is scheduled.',
    heartbeatsUnknown: 'Heartbeats: not known.',
    nextCheck: 'next check {when}',
    lastNotRecorded: 'The last check is not recorded.',
    jobsHeading: 'Your jobs',
    jobsNone: 'No job is set up.',
    jobsUnknown: 'Jobs: not known.',
    jobRunsAt: 'runs {when}',
    jobNoNext: 'next run not reported',
    jobPaused: 'paused',
    jobNotRunnable: 'cannot run now',
    jobLast: 'last run {when}',
    doneNone: 'Nothing has finished today.',
    doneUnknown: 'Today’s actions: not known.',
    doneCount: { one: '{n} action finished today', few: '{n} actions finished today', other: '{n} actions finished today' },
    more: 'Missions and sessions are on their own pages:',
    missions: 'Missions',
    sessions: 'Sessions',
  },
  ro: {
    needsTitle: 'Te așteaptă',
    runningTitle: 'În lucru acum',
    scheduledTitle: 'Programat',
    doneTitle: 'Terminat azi',
    demoNote: 'Mostră demo: aici nu este listată nicio muncă reală.',
    docketWaiting: { one: '{n} decizie așteaptă semnătura ta', few: '{n} decizii așteaptă semnătura ta', other: '{n} de decizii așteaptă semnătura ta' },
    docketRequests: { one: '{n} cerere în spatele lor', few: '{n} cereri în spatele lor', other: '{n} de cereri în spatele lor' },
    friction: '{typed} cu text scris · {twoStep} în doi pași · {click} cu un clic',
    docketNone: 'Nimic nu așteaptă pe listă.',
    docketUnknown: 'Decizii: necunoscut.',
    openDocket: 'Deschide lista',
    paymentsWaiting: { one: '{n} plată așteaptă aprobarea ta', few: '{n} plăți așteaptă aprobarea ta', other: '{n} de plăți așteaptă aprobarea ta' },
    paymentsNone: 'Nicio plată nu așteaptă aprobarea.',
    paymentsUnknown: 'Plăți: necunoscut.',
    openPayments: 'Deschide Încredere',
    skillChanges: { one: '{n} modificare de abilitate așteaptă revizuirea', few: '{n} modificări de abilități așteaptă revizuirea', other: '{n} de modificări de abilități așteaptă revizuirea' },
    skillChangesNone: 'Nicio modificare de abilitate nu este în așteptare.',
    skillChangesUnknown: 'Modificări de abilități: necunoscut.',
    openDecisions: 'Deschide Decizii',
    questionOpen: 'O întrebare este deschisă în această conversație: {question}',
    openConversation: 'Răspunde în conversație',
    topHeading: 'Cele mai stricte întâi',
    by: 'de {agent}',
    turnsRunning: { one: '{n} tură rulează acum', few: '{n} ture rulează acum', other: '{n} de ture rulează acum' },
    turnsRunningCap: 'din {cap} permise',
    turnsIdle: 'Nicio tură nu rulează.',
    turnsUnknown: 'Ture în desfășurare: neraportat.',
    holdersHeading: 'Unde rulează (hubul nu înregistrează un agent)',
    holder: '{surface} · {age}',
    ageSeconds: 'sub un minut',
    ageMinutes: '{n} min',
    ageHours: '{n} h',
    tasksHeading: 'Sarcini în lucru',
    tasksNone: 'Nicio sarcină nu rulează.',
    tasksUnknown: 'Sarcini în lucru: necunoscut.',
    subagentsHeading: 'Sub-agenți',
    subagentsNone: 'Niciun sub-agent nu rulează.',
    subagentsUnknown: 'Sub-agenți: necunoscut.',
    subCap: '{active} din {cap} folosiți',
    stalled: 'blocat',
    forParent: 'pentru {parent}',
    thisTab: 'Această filă',
    askedAgent: 'L-ai întrebat pe {agent} la {time}',
    heartbeatsHeading: 'Următoarele verificări',
    heartbeatsNone: 'Nicio verificare periodică nu este programată.',
    heartbeatsUnknown: 'Verificări periodice: necunoscut.',
    nextCheck: 'următoarea verificare {when}',
    lastNotRecorded: 'Ultima verificare nu este înregistrată.',
    jobsHeading: 'Joburile tale',
    jobsNone: 'Niciun job nu este configurat.',
    jobsUnknown: 'Joburi: necunoscut.',
    jobRunsAt: 'rulează {when}',
    jobNoNext: 'următoarea rulare nu este raportată',
    jobPaused: 'în pauză',
    jobNotRunnable: 'nu poate rula acum',
    jobLast: 'ultima rulare {when}',
    doneNone: 'Nimic nu s-a terminat azi.',
    doneUnknown: 'Acțiunile de azi: necunoscut.',
    doneCount: { one: '{n} acțiune terminată azi', few: '{n} acțiuni terminate azi', other: '{n} de acțiuni terminate azi' },
    more: 'Misiunile și sesiunile sunt pe paginile lor:',
    missions: 'Misiuni',
    sessions: 'Sesiuni',
  },
});

type T = typeof WORK_STRINGS.en;

export function ageWords(seconds: number, lang: Lang | string): string {
  const s = pick(WORK_STRINGS, lang);
  if (seconds < 60) return s.ageSeconds;
  if (seconds < 3600) return fmt(s.ageMinutes, { n: Math.floor(seconds / 60) });
  return fmt(s.ageHours, { n: Math.floor(seconds / 3600) });
}

/** A line of a section: a mark and its sentence, then optional extras. */
function Line({ mark, children, id }: { mark: React.ComponentProps<typeof Mark>['kind']; children: React.ReactNode; id?: string }) {
  return <li className="n-work__line" data-line={id}><Mark kind={mark} size="md" /><span className="n-work__text">{children}</span></li>;
}

/** The sentence for a count whose source may not be current: the count only when the reading is
 *  live or stale; a word for an empty answer; the reading's own words (never 0) otherwise. */
function Counted({ reading, count, one, none, unknown, lang }: {
  reading: Pick<Reading<unknown>, 'state' | 'reason' | 'status' | 'lastGoodAt'>; count: number | null;
  one: Parameters<typeof plural>[1]; none: string; unknown: string; lang: Lang | string;
}) {
  if (reading.state === 'empty' || ((reading.state === 'live' || reading.state === 'stale') && count === 0)) return <>{none}</>;
  if ((reading.state === 'live' || reading.state === 'stale') && count !== null) return <>{plural(lang, one, count)}</>;
  return <>{unknown} <SourceLabel reading={reading} lang={lang} /></>;
}

export interface WorkOverviewProps {
  hub: HubSnapshot; lang: Lang | string; demo: boolean; navigate: (path: string) => void;
  turns: readonly TabTurn[]; question: Question | null;
}

export function WorkOverview({ hub, lang, demo, navigate, turns, question }: WorkOverviewProps) {
  const s: T = pick(WORK_STRINGS, lang);
  const now = Date.now();
  const live = !demo;
  const docket = useDocketSummary();
  const blocked = useBlockedFeed({ enabled: live });
  const payments = usePaymentsFeed({ enabled: live });
  const skills = useSkillChangesFeed({ enabled: live });
  const slots = useSlots({ enabled: live });
  const running = useRunningFeed({ enabled: live });
  const subs = useSubagentsFeed({ enabled: live });
  const beats = useHeartbeats({ enabled: live });
  const jobs = useJobsFeed({ enabled: live });
  const today = useAway({ enabled: live });
  const names = new Map(rosterAgents(hub.agents).map((a) => [a.id, a.name]));
  const nameOf = (id: string | null) => (id ? names.get(id) ?? id.charAt(0).toUpperCase() + id.slice(1) : '');
  const open = (id: number) => (event: React.MouseEvent) => { event.preventDefault(); openDocketEntry(id); };

  const waitingPayments = (payments.value ?? []).filter((p) => p.state === 'pending').length;
  const turnSlots = hub.slots?.turns ?? null;
  const slotReading: Pick<Reading<unknown>, 'state' | 'reason' | 'status' | 'lastGoodAt'> = turnSlots
    ? { state: hub.state === 'live' ? 'live' : hub.state === 'offline' ? 'offline' : 'stale', lastGoodAt: hub.lastGoodAt }
    : { state: 'unknown', reason: 'not-reported', lastGoodAt: null };
  const doneToday = doneActions(today.value).filter((d) => d.at >= startOfDay(now));
  const nextBeats = [...(beats.value?.heartbeats ?? [])].filter((b) => b.nextRun !== null).sort((a, b) => (a.nextRun as number) - (b.nextRun as number)).slice(0, 5);
  const nextJobs = [...(jobs.value ?? [])].filter((j) => j.enabled !== false).sort((a, b) => (a.runAt ?? Infinity) - (b.runAt ?? Infinity) || a.name.localeCompare(b.name)).slice(0, 5);

  const demoNote = <p className="n-pgnote" data-demo-note="">{s.demoNote}</p>;

  return (
    <div className="n-work" data-page="work" data-demo={demo ? 'true' : undefined}>
      <Register title={s.needsTitle} register="work-needs"
        meta={demo ? <SourceLabel reading={{ state: 'demo', lastGoodAt: null }} lang={lang} /> : <SourceLabel reading={docket} lang={lang} />}>
        {demo ? demoNote : (
          <>
            <ul className="n-work__lines">
              <Line mark={docket.value && docket.value.entries > 0 ? 'seal-open' : docket.state === 'empty' ? 'ok' : 'unknown'} id="docket">
                <Counted reading={docket} count={docket.value ? docket.value.entries : null} one={s.docketWaiting} none={s.docketNone} unknown={s.docketUnknown} lang={lang} />
                {docket.value && docket.value.entries > 0 && (
                  <small className="n-work__sub">
                    {plural(lang, s.docketRequests, docket.value.requests)} · {fmt(s.friction, { typed: docket.value.friction.typed, twoStep: docket.value.friction.twoStep, click: docket.value.friction.click })}
                    {' · '}<PageLink path="/v2/cockpit" navigate={navigate}>{s.openDocket}</PageLink>
                  </small>
                )}
              </Line>
              <Line mark={waitingPayments > 0 ? 'seal-open' : payments.state === 'unknown' || payments.state === 'refused' || payments.state === 'offline' ? 'unknown' : 'ok'} id="payments">
                <Counted reading={payments} count={payments.value ? waitingPayments : null} one={s.paymentsWaiting} none={s.paymentsNone} unknown={s.paymentsUnknown} lang={lang} />
                {waitingPayments > 0 && <small className="n-work__sub"><PageLink path="/v2/trust" navigate={navigate}>{s.openPayments}</PageLink></small>}
              </Line>
              <Line mark={(skills.value?.count ?? 0) > 0 ? 'attn' : skills.state === 'unknown' || skills.state === 'refused' || skills.state === 'offline' ? 'unknown' : 'ok'} id="skills">
                <Counted reading={skills} count={skills.value ? skills.value.count : null} one={s.skillChanges} none={s.skillChangesNone} unknown={s.skillChangesUnknown} lang={lang} />
                {(skills.value?.count ?? 0) > 0 && <small className="n-work__sub"><PageLink path="/v2/console/decision-inbox" navigate={navigate}>{s.openDecisions}</PageLink></small>}
              </Line>
              {question && (
                <Line mark="attn" id="question">
                  {fmt(s.questionOpen, { question: question.question })}
                  <small className="n-work__sub"><PageLink path="/v2/cockpit" navigate={navigate}>{s.openConversation}</PageLink></small>
                </Line>
              )}
            </ul>
            {drawable(blocked) && (blocked.value?.length ?? 0) > 0 && (
              <>
                <h3 className="n-work__sub-head">{s.topHeading}</h3>
                <ol className="n-work__top" data-top-entries="">
                  {topBlocked(blocked.value ?? [], 3).map((row) => (
                    <li key={row.id} data-docket-ref={row.id}>
                      <TierGlyph tier={row.tier} lang={lang} />
                      <a className="n-link" href={docketHref(row.id)} onClick={open(row.id)}>{row.title}</a>
                      {row.agent && <small>{fmt(s.by, { agent: nameOf(row.agent) })}</small>}
                    </li>
                  ))}
                </ol>
              </>
            )}
            {!drawable(blocked) && <NoReading reading={blocked} lang={lang} />}
          </>
        )}
      </Register>

      <Register title={s.runningTitle} register="work-running"
        meta={demo ? <SourceLabel reading={{ state: 'demo', lastGoodAt: null }} lang={lang} /> : <SourceLabel reading={slotReading} lang={lang} />}>
        {demo ? demoNote : (
          <>
            <ul className="n-work__lines">
              <Line mark={turnSlots && turnSlots.running > 0 ? 'work' : turnSlots ? 'idle' : 'unknown'} id="turns">
                {turnSlots
                  ? turnSlots.running > 0
                    ? <>{plural(lang, s.turnsRunning, turnSlots.running)}{turnSlots.cap !== null ? ` · ${fmt(s.turnsRunningCap, { cap: turnSlots.cap })}` : ''}</>
                    : s.turnsIdle
                  : <>{s.turnsUnknown} <SourceLabel reading={slotReading} lang={lang} /></>}
              </Line>
              {turns.map((t) => (
                <Line mark="work" id="this-tab" key={t.turnId}>
                  <b>{s.thisTab}</b> · {fmt(s.askedAgent, { agent: nameOf(t.agent.toLowerCase()), time: clockTime(t.askedAt) })}
                </Line>
              ))}
            </ul>
            {slots.state !== 'disabled' && drawable(slots) && slots.value?.holders && slots.value.holders.length > 0 && (
              <>
                <h3 className="n-work__sub-head">{s.holdersHeading}</h3>
                <ul className="n-work__plain" data-slot-holders="">
                  {slots.value.holders.map((h, i) => <li key={i}>{fmt(s.holder, { surface: typeof h.surface === 'string' ? h.surface : '—', age: typeof h.age_s === 'number' ? ageWords(h.age_s, lang) : '—' })}</li>)}
                </ul>
              </>
            )}

            <h3 className="n-work__sub-head">{s.tasksHeading} <SourceLabel reading={running} lang={lang} /></h3>
            {drawable(running)
              ? (running.value?.length ?? 0) > 0
                ? <ul className="n-work__plain" data-running-tasks="">
                  {(running.value ?? []).map((t) => <li key={t.id}><Mark kind="work" size="sm" /> {t.agent && <b>{nameOf(t.agent)} </b>}{t.title}</li>)}
                </ul>
                : <p className="n-pgnote">{s.tasksNone}</p>
              : <NoReading reading={running} lang={lang} />}

            <h3 className="n-work__sub-head">{s.subagentsHeading} <SourceLabel reading={subs} lang={lang} /></h3>
            {drawable(subs)
              ? (subs.value?.runs.length ?? 0) > 0
                ? <>
                  <ul className="n-work__plain" data-subagents="">
                    {(subs.value?.runs ?? []).map((r) => (
                      <li key={r.id}>
                        <Mark kind={r.stalled ? 'stale' : 'work'} size="sm" /> <b>{nameOf(r.agent)}</b>
                        {r.parent && ` ${fmt(s.forParent, { parent: nameOf(r.parent) })}`}
                        {r.stalled && ` · ${s.stalled}`}
                      </li>
                    ))}
                  </ul>
                  {subs.value && subs.value.active !== null && subs.value.cap !== null && <p className="n-pgnote">{fmt(s.subCap, { active: subs.value.active, cap: subs.value.cap })}</p>}
                </>
                : <p className="n-pgnote">{s.subagentsNone}</p>
              : <NoReading reading={subs} lang={lang} />}
          </>
        )}
      </Register>

      <Register title={s.scheduledTitle} register="work-scheduled"
        meta={demo ? <SourceLabel reading={{ state: 'demo', lastGoodAt: null }} lang={lang} /> : <SourceLabel reading={beats} lang={lang} />}>
        {demo ? demoNote : (
          <>
            <h3 className="n-work__sub-head">{s.heartbeatsHeading}</h3>
            {drawable(beats)
              ? nextBeats.length > 0
                ? <ul className="n-work__plain" data-heartbeats="">
                  {nextBeats.map((b) => <li key={b.agentId}><b>{nameOf(b.agentId)}</b> · {fmt(s.nextCheck, { when: stamp(b.nextRun as number, now, lang) + (new Date(b.nextRun as number).toDateString() === new Date(now).toDateString() ? '' : ` ${clockTime(b.nextRun as number)}`) })}</li>)}
                </ul>
                : <p className="n-pgnote">{s.heartbeatsNone}</p>
              : <NoReading reading={beats} lang={lang} />}
            {drawable(beats) && nextBeats.length > 0 && <p className="n-pgnote">{s.lastNotRecorded}</p>}
            <h3 className="n-work__sub-head">{s.jobsHeading} <SourceLabel reading={jobs} lang={lang} /></h3>
            {drawable(jobs)
              ? nextJobs.length > 0
                ? <ul className="n-work__plain" data-jobs="">
                  {nextJobs.map((j) => {
                    const when = (t: number) => `${stamp(t, now, lang)} ${clockTime(t)}`;
                    const schedule = j.scheduleText ?? j.cron;
                    const bits = [
                      j.runAt !== null ? fmt(s.jobRunsAt, { when: when(j.runAt) }) : schedule,
                      j.runAt === null ? s.jobNoNext : null,
                      j.pausedReason ? `${s.jobPaused}: ${j.pausedReason}` : j.runnable === false ? s.jobNotRunnable : null,
                      j.lastRunAt !== null ? `${fmt(s.jobLast, { when: when(j.lastRunAt) })}${j.lastStatus ? ` (${j.lastStatus})` : ''}` : null,
                    ].filter((b): b is string => !!b);
                    return <li key={j.id}><b>{j.name}</b> · {bits.join(' · ')}</li>;
                  })}
                </ul>
                : <p className="n-pgnote">{s.jobsNone}</p>
              : <NoReading reading={jobs} lang={lang} />}
          </>
        )}
      </Register>

      <Register title={s.doneTitle} register="work-done"
        meta={demo ? <SourceLabel reading={{ state: 'demo', lastGoodAt: null }} lang={lang} /> : <SourceLabel reading={today} lang={lang} />}
        foot={!demo && drawable(today) && doneToday.length > 0 ? <Total><b>{plural(lang, s.doneCount, doneToday.length)}</b></Total> : undefined}>
        {demo ? demoNote : drawable(today)
          ? doneToday.length > 0
            ? <ul className="n-work__done" data-done-today="">
              {doneToday.slice(0, 8).map((d) => (
                <li key={d.id}><time dateTime={new Date(d.at).toISOString()}>{clockTime(d.at)}</time><Mark kind="done" size="sm" />
                  <span>{d.agent && <b>{nameOf(d.agent)} </b>}{d.title}</span></li>
              ))}
            </ul>
            : <p className="n-pgnote">{s.doneNone}</p>
          : <NoReading reading={today} lang={lang} />}
        <p className="n-pgnote n-work__more">{s.more}{' '}
          <PageLink path="/v2/console/missions" navigate={navigate}>{s.missions}</PageLink>{' · '}
          <PageLink path="/v2/console/sessions" navigate={navigate}>{s.sessions}</PageLink></p>
      </Register>
    </div>
  );
}
