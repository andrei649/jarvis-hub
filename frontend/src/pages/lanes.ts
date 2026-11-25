/* The Timeline's model (PHASE_B_PLAN.md §6): one lane per agent with something today, built only
   from real events. Pure, so it is tested without a page.

   Events and where they come from:
     done   an action the hub recorded as finished today (/api/dashboard/today)
     hold   a request waiting for the owner: from max(created, start of day) to now, with a stub
            ("since 2 Jul") when it is older, and a pin that numbers it (links to the docket entry)
     run    a running task, a sub-agent, or this tab's own turn ("asked <agent>")
     tick   the agent's next heartbeat (a scheduled time, never a result)
   Problems the observer reports name no agent, so they live on a separate System lane. The
   cloud-only agent with no cloud model is a dashed lane. Agents with nothing today fold into one
   row, named. A source that did not answer contributes nothing and is listed as unknown. */
import type { AgentState, TabTurn } from '../signals/types';
import { rosterAgents, CLOUD_ONLY_AGENTS } from './agent-states';
import type { BlockedRow, DoneAction, RunningTask, SubagentRun } from './sources';
import { startOfDay } from './sources';

export type LaneEvent =
  | { kind: 'done'; id: string; at: number; title: string }
  | { kind: 'hold'; id: number; since: number; startedAt: number | null; stub: boolean; olderThan: number | null; title: string; pin: number }
  | { kind: 'run'; source: 'task' | 'sub-agent' | 'this-tab'; since: number; startedAt: number | null; stub: boolean; title: string | null; stalled: boolean }
  | { kind: 'tick'; at: number };

export interface Lane { readonly id: string; readonly name: string; readonly events: readonly LaneEvent[]; readonly dashed: boolean; readonly state: AgentState | null }

/** `since` places the bar (clamped to today); `startedAt` is the hub's own time, for the words and
 *  the stub; null when the hub sent none. */
export interface SystemEvent { readonly key: string; readonly detail: string | null; readonly since: number | null; readonly startedAt: number | null; readonly stub: boolean }

/** A heartbeat's next run, as signals/wire.ts HeartbeatEntry reads it. */
export interface BeatLite { readonly agentId: string; readonly nextRun: number | null }
/** An unhealthy observer probe, as signals/wire.ts ObserverProbe reads it. */
export interface ProblemLite { readonly key: string; readonly detail: string | null; readonly since: number | null }

export interface TimelineInputs {
  readonly now: number;
  readonly roster: readonly unknown[];
  readonly done: readonly DoneAction[] | null;
  readonly blocked: readonly BlockedRow[] | null;
  readonly running: readonly RunningTask[] | null;
  readonly subagents: readonly SubagentRun[] | null;
  readonly turns: readonly TabTurn[];
  readonly beats: readonly BeatLite[] | null;
  readonly observer: readonly ProblemLite[] | null;
  /** One state per agent, from signals/agents-exception.ts (the same derivation the foot reads). */
  readonly states: readonly AgentState[];
  readonly cloudConfigured: boolean | null;
}

export interface TimelineModel {
  readonly dayStart: number;
  readonly dayEnd: number;
  readonly now: number;
  readonly lanes: readonly Lane[];
  /** null when the observer did not answer. */
  readonly system: readonly SystemEvent[] | null;
  /** Agents with no lane and no activity reported today. */
  readonly folded: readonly string[];
  /** Sources that did not answer. */
  readonly unknown: readonly string[];
  readonly states: readonly AgentState[];
}

const DAY = 24 * 3600 * 1000;
export const NO_AGENT = '_none';

export function buildTimeline(input: TimelineInputs): TimelineModel {
  const { now } = input;
  const dayStart = startOfDay(now);
  const dayEnd = dayStart + DAY;
  const roster = rosterAgents(input.roster);
  const names = new Map(roster.map((a) => [a.id, a.name]));
  const events = new Map<string, LaneEvent[]>();
  const add = (agent: string | null, event: LaneEvent) => {
    const key = agent ?? NO_AGENT;
    const list = events.get(key) ?? [];
    list.push(event);
    events.set(key, list);
  };

  for (const d of input.done ?? []) if (d.at >= dayStart) add(d.agent, { kind: 'done', id: d.id, at: d.at, title: d.title });

  const holds = [...(input.blocked ?? [])].sort((a, b) => (a.createdAt ?? now) - (b.createdAt ?? now) || a.id - b.id);
  holds.forEach((h, i) => {
    const created = h.createdAt;
    const stub = created !== null && created < dayStart;
    // an unknown age is not drawn as "since midnight": the mark sits at now and the words say so
    add(h.agent, { kind: 'hold', id: h.id, since: created === null ? now : Math.max(created, dayStart), startedAt: created, stub, olderThan: stub ? created : null, title: h.title, pin: i + 1 });
  });

  const run = (source: 'task' | 'sub-agent' | 'this-tab', startedAt: number | null, title: string | null, stalled: boolean): LaneEvent =>
    ({ kind: 'run', source, since: startedAt === null ? now : Math.max(startedAt, dayStart), startedAt, stub: startedAt !== null && startedAt < dayStart, title, stalled });
  for (const t of input.running ?? []) if (t.agent) add(t.agent, run('task', t.since, t.title, false));
  for (const r of input.subagents ?? []) add(r.agent, run('sub-agent', r.since, r.task, r.stalled));
  for (const t of input.turns) add(t.agent.toLowerCase(), run('this-tab', t.askedAt, null, false));

  const ticksOf = new Map<string, number>();
  for (const b of input.beats ?? []) if (b.nextRun !== null && b.nextRun >= dayStart && b.nextRun < dayEnd) ticksOf.set(b.agentId, b.nextRun);

  const stateOf = new Map(input.states.map((a) => [a.id, a]));

  const lanes: Lane[] = [];
  for (const [id, list] of events) {
    const tick = ticksOf.get(id);
    const all = tick !== undefined ? [...list, { kind: 'tick', at: tick } as LaneEvent] : list;
    const name = id === NO_AGENT ? '' : names.get(id) ?? id.charAt(0).toUpperCase() + id.slice(1);
    lanes.push({ id, name, events: all, dashed: false, state: stateOf.get(id) ?? null });
  }
  // the cloud-only agent with no cloud model: a dashed lane, with nothing on it
  if (input.cloudConfigured === false) {
    for (const id of CLOUD_ONLY_AGENTS) {
      if (lanes.some((l) => l.id === id)) continue;
      lanes.push({ id, name: names.get(id) ?? id.charAt(0).toUpperCase() + id.slice(1), events: [], dashed: true, state: stateOf.get(id) ?? null });
    }
  }
  const rank = (l: Lane) => (l.id === NO_AGENT ? 3 : l.dashed ? 2 : l.events.some((e) => e.kind === 'hold') ? 0 : 1);
  lanes.sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));

  const laneIds = new Set(lanes.map((l) => l.id));
  // nothing happened today, even if a heartbeat is scheduled: one folded row, named
  const folded = input.states.filter((a) => (a.activity === 'noActivity' || a.activity === 'scheduled') && !laneIds.has(a.id)).map((a) => a.name);

  const unknown: string[] = [];
  if (input.done === null) unknown.push('today');
  if (input.blocked === null) unknown.push('docket');
  if (input.running === null) unknown.push('running');
  if (input.subagents === null) unknown.push('subagents');
  if (input.beats === null) unknown.push('heartbeats');

  return {
    dayStart, dayEnd, now, lanes, folded, unknown, states: input.states,
    system: input.observer === null ? null : input.observer.map((p) => ({ key: p.key, detail: p.detail, since: p.since === null ? null : Math.max(p.since, dayStart), startedAt: p.since, stub: p.since !== null && p.since < dayStart })),
  };
}

/** A position along the day, 0–100. */
export function position(model: Pick<TimelineModel, 'dayStart' | 'dayEnd'>, at: number): number {
  return Math.max(0, Math.min(100, ((at - model.dayStart) / (model.dayEnd - model.dayStart)) * 100));
}
