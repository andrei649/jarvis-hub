/* Agents by exception (PHASE_B_PLAN.md §5.5, §4.3): one state per agent, each from a named
   source the hub can prove. The words "idle", "ready" and "active" are retired: the hub keeps no
   per-agent activity stamps yet (B4), so an agent nothing vouches for is "no activity reported",
   which is what is true, not "idle".

   State, in the order that wins when more than one applies:

     halted         the global halt is on                          kill-switch
     waitingOnYou   it holds docket entries (the task's agent)     docket
     working        a running task                                 running-task
                    a running sub-agent (stalled drawn as stale)   sub-agent
                    this tab's in-flight turn ("Answering you")    this-tab
     unavailable    a cloud-only agent with no cloud model         cloud-policy
     finishedToday  an action of the day's feed under its name     dashboard-today
     scheduled      its heartbeat's next run                       heartbeat
     noActivity     everyone else                                  none

   Turns running on other surfaces are counted without a name ("1 reply running elsewhere"), from
   the hub's slot counts minus this tab's own turns. A source that did not answer is listed in
   `unread` so the page can say so ("Running work: unknown without the owner credential"), and
   never stands in for "nothing is running". Pure; words in one language. */
import { defineStrings, fmt, plural, pick, type Lang } from '../frame/strings';
import { clockTime } from '../frame/kit/strings';
import type { MarkKind } from '../frame/kit/marks';
import { isCloudOnlyAgent } from './agents-policy';
import { isCurrent } from './types';
import type { AgentActivity, AgentState, HubTrust, KillSwitchState, Reading, SlotUsage, TabTurn } from './types';
import type { HeartbeatStatus, SubagentsView, TaskLite, TodayFeed } from './wire';

export const AGENTS_STRINGS = defineStrings({
  en: {
    waitingOnYou: 'waiting on you',
    working: 'working',
    finishedToday: 'finished today',
    unavailable: 'unavailable',
    halted: 'halted',
    scheduled: 'scheduled',
    noActivity: 'no activity reported',
    sumWorking: { one: '{n} working', few: '{n} working', other: '{n} working' },
    sumWaitingOnYou: { one: '{n} waiting on you', few: '{n} waiting on you', other: '{n} waiting on you' },
    sumFinishedToday: { one: '{n} finished today', few: '{n} finished today', other: '{n} finished today' },
    sumUnavailable: { one: '{n} unavailable', few: '{n} unavailable', other: '{n} unavailable' },
    sumHalted: { one: '{n} halted', few: '{n} halted', other: '{n} halted' },
    sumNoActivity: { one: '{n} no activity reported', few: '{n} no activity reported', other: '{n} no activity reported' },
    agentsCount: 'Agents {n}',
    agentsNotReported: 'Agents: not reported',
    workingTab: 'Answering you (asked)',
    workingSub: 'Sub-agent running',
    workingSubStalled: 'Sub-agent running, quiet for a while',
    unavailableCloud: 'Needs a cloud model; none is configured',
    haltedDetail: 'Stopped by the global halt',
    scheduledNext: 'next check {time}',
    finishedDetail: { one: '{n} action finished today', few: '{n} actions finished today', other: '{n} actions finished today' },
    waitingDetail: { one: '{n} entry waits on the docket', few: '{n} entries wait on the docket', other: '{n} entries wait on the docket' },
    elsewhere: { one: '{n} reply running elsewhere', few: '{n} replies running elsewhere', other: '{n} replies running elsewhere' },
    unreadRunning: 'Running work: unknown without the owner credential',
    unreadDocket: 'Waiting entries: unknown without the owner credential',
    unreadSubagents: 'Sub-agents: could not be read',
    unreadToday: 'Finished today: could not be read',
  },
  ro: {
    waitingOnYou: 'așteaptă semnătura ta',
    working: 'lucrează',
    finishedToday: 'au terminat azi',
    unavailable: 'indisponibili',
    halted: 'opriți',
    scheduled: 'programați',
    noActivity: 'fără activitate raportată',
    sumWorking: { one: '{n} lucrează', few: '{n} lucrează', other: '{n} lucrează' },
    sumWaitingOnYou: { one: '{n} așteaptă semnătura ta', few: '{n} așteaptă semnătura ta', other: '{n} așteaptă semnătura ta' },
    sumFinishedToday: { one: '{n} a terminat azi', few: '{n} au terminat azi', other: '{n} au terminat azi' },
    sumUnavailable: { one: '{n} indisponibil', few: '{n} indisponibili', other: '{n} de indisponibili' },
    sumHalted: { one: '{n} oprit', few: '{n} opriți', other: '{n} de opriți' },
    sumNoActivity: { one: '{n} fără activitate raportată', few: '{n} fără activitate raportată', other: '{n} fără activitate raportată' },
    agentsCount: 'Agenți {n}',
    agentsNotReported: 'Agenți: neraportat',
    workingTab: 'Îți răspunde (întrebat)',
    workingSub: 'Subagent în lucru',
    workingSubStalled: 'Subagent în lucru, liniștit de o vreme',
    unavailableCloud: 'Are nevoie de un model cloud; niciunul nu este configurat',
    haltedDetail: 'Oprit de oprirea globală',
    scheduledNext: 'următoarea verificare la {time}',
    finishedDetail: { one: '{n} acțiune terminată azi', few: '{n} acțiuni terminate azi', other: '{n} de acțiuni terminate azi' },
    waitingDetail: { one: '{n} intrare așteaptă în registru', few: '{n} intrări așteaptă în registru', other: '{n} de intrări așteaptă în registru' },
    elsewhere: { one: '{n} răspuns rulează în altă parte', few: '{n} răspunsuri rulează în altă parte', other: '{n} de răspunsuri rulează în altă parte' },
    unreadRunning: 'Lucrări în curs: necunoscute fără credențialul proprietarului',
    unreadDocket: 'Intrări în așteptare: necunoscute fără credențialul proprietarului',
    unreadSubagents: 'Subagenți: nu au putut fi citiți',
    unreadToday: 'Terminate azi: nu au putut fi citite',
  },
});

type Source = AgentState['source'];

const MARK: Readonly<Record<AgentActivity, MarkKind>> = {
  waitingOnYou: 'seal-open', working: 'work', finishedToday: 'done', unavailable: 'blocked', halted: 'held', scheduled: 'idle', noActivity: 'idle',
};
export const ACTIVITY_ORDER: readonly AgentActivity[] = ['working', 'waitingOnYou', 'finishedToday', 'unavailable', 'halted', 'scheduled', 'noActivity'];

export interface AgentsInput {
  /** hub.agents: the roster as the hub sent it ({id, name, role}). */
  readonly roster: readonly any[];
  /** hub.sources.agents: the roster arrived this cycle. False reads as "not reported", not "no agents". */
  readonly rosterKnown?: boolean;
  /** The docket's blocked tasks (their `agent` field). */
  readonly blocked?: Reading<readonly TaskLite[]> | null;
  /** GET /autonomy/tasks?status=running (admin). */
  readonly running?: Reading<readonly TaskLite[]> | null;
  readonly subagents?: Reading<SubagentsView> | null;
  /** This tab's in-flight turns: the agent asked, never the routed one. */
  readonly turns?: readonly TabTurn[];
  readonly today?: Reading<TodayFeed> | null;
  readonly heartbeats?: Reading<HeartbeatStatus> | null;
  /** /api/trust/status: null when it did not answer (nothing is claimed unavailable then). */
  readonly trust?: HubTrust | null;
  readonly killSwitch?: Reading<KillSwitchState> | null;
  /** /status `slots`: the turn count behind "N replies running elsewhere". */
  readonly slots?: SlotUsage | null;
  readonly now?: number;
}

export type UnreadSource = 'docket' | 'running' | 'subagents' | 'today';

export interface AgentsException {
  /** Every roster agent with its one state. */
  readonly agents: readonly AgentState[];
  /** The roster size; null when the roster was not reported. */
  readonly total: number | null;
  readonly counts: Readonly<Record<AgentActivity, number>>;
  /** Sources that did not answer: absence of evidence, never "nothing is running". */
  readonly unread: readonly UnreadSource[];
  /** Replies running on other surfaces (hub turn slots minus this tab's); null when unknown. */
  readonly elsewhere: number | null;
}

const lower = (v: unknown): string => (typeof v === 'string' ? v.trim().toLowerCase() : '');
const startOfDay = (now: number): number => { const d = new Date(now); d.setHours(0, 0, 0, 0); return d.getTime(); };

export function agentsByException(input: AgentsInput, langIn: Lang | string = 'en'): AgentsException {
  const lang: Lang = langIn === 'ro' ? 'ro' : 'en';
  const s = pick(AGENTS_STRINGS, lang);
  const now = input.now ?? Date.now();
  const rosterKnown = input.rosterKnown !== false && input.roster.length > 0;
  const halted = input.killSwitch?.value?.halted === true;
  // The router gates Athena on the cloud adapter alone (hybrid_router._cloud_available; trust
  // status cloud_available): a Claude-only install cannot answer her either.
  const noCloud = !!input.trust && !input.trust.cloudAvailable;

  const waiting = new Map<string, number>();
  (input.blocked?.value ?? []).forEach((t) => { const id = lower(t.agent); if (id) waiting.set(id, (waiting.get(id) ?? 0) + 1); });

  const working = new Map<string, { source: Source; detail: string | null; stale?: boolean }>();
  (input.running?.value ?? []).forEach((t) => {
    const id = lower(t.agent);
    if (id && !working.has(id)) working.set(id, { source: 'running-task', detail: t.title || null });
  });
  const ids = new Set(input.roster.map((a) => lower(a?.id)));
  (input.subagents?.value?.spawns ?? []).filter((r) => r.status === 'running').forEach((r) => {
    // the sub-agent's own id when the roster knows it, else the agent that spawned it
    const id = r.agent && ids.has(r.agent) ? r.agent : r.parent && ids.has(r.parent) ? r.parent : '';
    if (!id) return;
    const prior = working.get(id);
    if (prior && prior.source !== 'sub-agent') return;
    working.set(id, { source: 'sub-agent', detail: r.stalled ? s.workingSubStalled : s.workingSub, stale: r.stalled && (prior?.stale ?? true) });
  });
  (input.turns ?? []).forEach((t) => {
    const id = lower(t.agent);
    if (id && !working.has(id)) working.set(id, { source: 'this-tab', detail: s.workingTab });
  });

  const finished = new Map<string, number>();
  const dayStart = startOfDay(now);
  (input.today?.value?.items ?? []).forEach((it) => {
    if (it.kind === 'action' && it.agent && it.at !== null && it.at >= dayStart) finished.set(it.agent, (finished.get(it.agent) ?? 0) + 1);
  });

  const next = new Map<string, number>();
  (input.heartbeats?.value?.heartbeats ?? []).forEach((h) => { if (h.nextRun !== null && h.nextRun >= now) next.set(h.agentId, h.nextRun); });

  const agents: AgentState[] = input.roster.flatMap((a): AgentState[] => {
    const id = lower(a?.id);
    if (!id) return [];
    const base = { id, name: typeof a.name === 'string' && a.name.trim() ? a.name.trim() : id, role: typeof a.role === 'string' && a.role.trim() ? a.role.trim() : null };
    const state = (activity: AgentActivity, source: Source, extra: Partial<AgentState> = {}): AgentState => ({ ...base, activity, mark: MARK[activity], source, ...extra });
    if (halted) return [state('halted', 'kill-switch', { detail: s.haltedDetail })];
    const w = waiting.get(id);
    if (w) return [state('waitingOnYou', 'docket', { count: w, detail: plural(lang, s.waitingDetail, w) })];
    const work = working.get(id);
    if (work) return [state('working', work.source, { detail: work.detail, ...(work.stale ? { stale: true } : {}) })];
    if (noCloud && isCloudOnlyAgent(id)) return [state('unavailable', 'cloud-policy', { detail: s.unavailableCloud })];
    const done = finished.get(id);
    if (done) return [state('finishedToday', 'dashboard-today', { count: done, detail: plural(lang, s.finishedDetail, done) })];
    const at = next.get(id);
    if (at !== undefined) return [state('scheduled', 'heartbeat', { detail: fmt(s.scheduledNext, { time: clockTime(at) }), since: null })];
    return [state('noActivity', 'none')];
  });

  const counts = Object.fromEntries(ACTIVITY_ORDER.map((k) => [k, 0])) as Record<AgentActivity, number>;
  agents.forEach((a) => { counts[a.activity] += 1; });

  const unread: UnreadSource[] = [];
  if (input.blocked && !isCurrent(input.blocked)) unread.push('docket');
  if (input.running && !isCurrent(input.running)) unread.push('running');
  if (input.subagents && !isCurrent(input.subagents)) unread.push('subagents');
  if (input.today && !isCurrent(input.today)) unread.push('today');

  const turns = input.slots?.turns ?? null;
  const elsewhere = turns ? Math.max(0, turns.running - (input.turns?.length ?? 0)) : null;

  return { agents: rosterKnown ? agents : [], total: rosterKnown ? agents.length : null, counts, unread, elsewhere };
}

export interface AgentsSummaryPart {
  readonly activity: AgentActivity;
  readonly mark: MarkKind;
  readonly count: number;
  /** "1 working", "11 no activity reported". */
  readonly text: string;
}

/** The foot's count phrase for each state: a plural form per activity, never a number glued to a
 *  translated fragment (Romanian: "1 indisponibil", "3 indisponibili", "20 de indisponibili"). */
const SUMMARY_FORMS = (s: ReturnType<typeof pick<typeof AGENTS_STRINGS.en>>) => ({
  working: s.sumWorking, waitingOnYou: s.sumWaitingOnYou, finishedToday: s.sumFinishedToday,
  unavailable: s.sumUnavailable, halted: s.sumHalted, noActivity: s.sumNoActivity, scheduled: s.sumNoActivity,
} as const);

/** The foot's line: "Agents 18 · ▶ 1 working · ⊛ 2 waiting on you · ✓ 3 finished today · ⊘ 1 unavailable ·
 *  11 no activity reported". Scheduled agents are counted with the rest (Home does not show
 *  "scheduled" as a state, §5.5). Parts with a zero count are left out. */
export function agentsSummary(result: AgentsException, langIn: Lang | string = 'en'): { label: string; parts: readonly AgentsSummaryPart[]; elsewhere: string | null; unread: readonly string[] } {
  const lang: Lang = langIn === 'ro' ? 'ro' : 'en';
  const s = pick(AGENTS_STRINGS, lang);
  const c = result.counts;
  const partOf = (activity: AgentActivity, count: number): AgentsSummaryPart | null =>
    count > 0 ? { activity, mark: MARK[activity], count, text: plural(lang, SUMMARY_FORMS(s)[activity], count) } : null;
  const parts = [
    partOf('working', c.working), partOf('waitingOnYou', c.waitingOnYou), partOf('finishedToday', c.finishedToday),
    partOf('unavailable', c.unavailable), partOf('halted', c.halted), partOf('noActivity', c.noActivity + c.scheduled),
  ].filter((p): p is AgentsSummaryPart => p !== null);
  const unreadWords: Record<UnreadSource, string> = { docket: s.unreadDocket, running: s.unreadRunning, subagents: s.unreadSubagents, today: s.unreadToday };
  return {
    label: result.total === null ? s.agentsNotReported : fmt(s.agentsCount, { n: result.total }),
    parts,
    elsewhere: result.elsewhere !== null && result.elsewhere > 0 ? plural(lang, s.elsewhere, result.elsewhere) : null,
    unread: result.unread.map((u) => unreadWords[u]),
  };
}
