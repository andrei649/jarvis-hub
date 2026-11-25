import { describe, expect, it } from 'vitest';
import { stringProblems } from '../frame/strings';
import { AGENTS_STRINGS, agentsByException, agentsSummary, type AgentsInput } from './agents-exception';
import { CLOUD_ONLY_AGENTS, LOCAL_ONLY_AGENTS, isCloudOnlyAgent, isLocalOnlyAgent } from './agents-policy';
import { T0, at, empty, live, refused } from './test-support';
import type { AgentState, TabTurn } from './types';
import type { TaskLite } from './wire';

const ROSTER = ['jarvis', 'pepper', 'stark', 'steve', 'ultron', 'athena', 'frigga', 'howard', 'hestia'].map((id) => ({ id, name: id[0].toUpperCase() + id.slice(1), role: `${id} role` }));
const task = (id: number, agent: string | null, extra: Partial<TaskLite> = {}): TaskLite => ({ id, kind: 'send_email', title: `Task ${id}`, agent, createdAt: null, service: null, ...extra });
const trust = (cloud: boolean) => ({ mic: 'on' as const, strictLocal: !cloud, cloudAvailable: cloud, claudeAvailable: false });
const turn = (agent: string): TabTurn => ({ turnId: 1, agent, askedAt: T0, startedAt: T0, firstTokenAt: null });
const base = (over: Partial<AgentsInput> = {}): AgentsInput => ({ roster: ROSTER, now: T0, trust: trust(true), ...over });
const state = (input: AgentsInput, id: string, lang = 'en'): AgentState => agentsByException(input, lang).agents.find((a) => a.id === id) as AgentState;

describe('agent policy', () => {
  it('lists the hub\'s local-only agents (hestia included) and its cloud-only one', () => {
    expect([...LOCAL_ONLY_AGENTS].sort()).toEqual(['frigga', 'hestia', 'howard', 'ultron']);
    expect([...CLOUD_ONLY_AGENTS]).toEqual(['athena']);
    expect(isLocalOnlyAgent('Hestia')).toBe(true);
    expect(isLocalOnlyAgent('jarvis')).toBe(false);
    expect(isCloudOnlyAgent(' ATHENA ')).toBe(true);
    expect(isCloudOnlyAgent(null)).toBe(false);
  });
});

describe('agents by exception', () => {
  it('has complete strings', () => expect(stringProblems(AGENTS_STRINGS)).toEqual([]));

  it('never produces "idle", "ready" or "active": an agent nothing vouches for has no activity reported', () => {
    const result = agentsByException(base({
      blocked: live([task(1, 'pepper')]), running: live([task(2, 'stark')]), turns: [turn('jarvis')],
      today: live({ items: [{ id: 'a', at: at(9), kind: 'action', title: 't', agent: 'steve' }] }),
      heartbeats: live({ schedulerRunning: true, heartbeats: [{ agentId: 'ultron', nextRun: at(18) }], blocked: 0 }),
    }), 'en');
    const summary = agentsSummary(result);
    // the words a person can read: states, details, the foot's line (a mark's id is not a word)
    const words = [...result.agents.flatMap((a) => [a.activity, a.detail ?? '']), summary.label, ...summary.parts.map((p) => p.text), summary.elsewhere ?? '', ...summary.unread].join(' | ');
    expect(words).not.toMatch(/\b(idle|ready|active)\b/i);
    const table = (t: Record<string, unknown>) => Object.values(t).flatMap((v) => (typeof v === 'string' ? [v] : [(v as any).one, (v as any).other])).join(' ');
    expect(table(AGENTS_STRINGS.en)).not.toMatch(/\b(idle|ready|active)\b/i);
    expect(table(AGENTS_STRINGS.ro)).not.toMatch(/\b(idle|inactiv)\b/i);
    expect(state(base(), 'jarvis').activity).toBe('noActivity');
    expect(result.agents.map((a) => a.activity)).toEqual(expect.arrayContaining(['waitingOnYou', 'working', 'finishedToday', 'scheduled', 'noActivity']));
  });

  it('names the source that proves each state', () => {
    const input = base({
      blocked: live([task(1, 'pepper'), task(2, 'pepper')]),
      running: live([task(3, 'stark', { title: 'Index the filings' })]),
      subagents: live({ spawns: [{ id: 's1', parent: 'jarvis', agent: 'sub', status: 'running', stalled: false }], active: 1, cap: 4 }),
      turns: [turn('steve')],
      today: live({ items: [{ id: 'a', at: at(9), kind: 'action', title: 'Done thing', agent: 'ultron' }, { id: 'b', at: at(10), kind: 'action', title: 'Another', agent: 'ultron' }] }),
      heartbeats: live({ schedulerRunning: true, heartbeats: [{ agentId: 'frigga', nextRun: at(18) }], blocked: 0 }),
    });
    expect(state(input, 'pepper')).toMatchObject({ activity: 'waitingOnYou', source: 'docket', count: 2, mark: 'seal-open' });
    expect(state(input, 'stark')).toMatchObject({ activity: 'working', source: 'running-task', detail: 'Index the filings', mark: 'work' });
    expect(state(input, 'jarvis')).toMatchObject({ activity: 'working', source: 'sub-agent', detail: 'Sub-agent running' });
    expect(state(input, 'steve')).toMatchObject({ activity: 'working', source: 'this-tab', detail: 'Answering you (asked)' });
    expect(state(input, 'ultron')).toMatchObject({ activity: 'finishedToday', source: 'dashboard-today', count: 2, mark: 'done' });
    expect(state(input, 'frigga')).toMatchObject({ activity: 'scheduled', source: 'heartbeat', detail: 'next check 18:00' });
    expect(state(input, 'howard')).toMatchObject({ activity: 'noActivity', source: 'none' });
  });

  it('draws a stalled sub-agent as the stale variant of working', () => {
    const input = base({ subagents: live({ spawns: [{ id: 's1', parent: null, agent: 'stark', status: 'running', stalled: true }], active: 1, cap: 4 }) });
    expect(state(input, 'stark')).toMatchObject({ activity: 'working', source: 'sub-agent', stale: true, detail: 'Sub-agent running, quiet for a while' });
    const two = base({ subagents: live({ spawns: [
      { id: 's1', parent: null, agent: 'stark', status: 'running', stalled: true }, { id: 's2', parent: null, agent: 'stark', status: 'running', stalled: false }], active: 2, cap: 4 }) });
    expect(state(two, 'stark').stale).toBeUndefined();
    expect(state(base({ subagents: live({ spawns: [{ id: 's3', parent: null, agent: 'stark', status: 'done', stalled: false }], active: 0, cap: 4 }) }), 'stark').activity).toBe('noActivity');
  });

  it('a sub-agent no roster agent owns counts for its parent; an unknown one counts for nobody', () => {
    const owned = base({ subagents: live({ spawns: [{ id: 's1', parent: 'pepper', agent: 'sub', status: 'running', stalled: false }], active: 1, cap: 4 }) });
    expect(state(owned, 'pepper').activity).toBe('working');
    const orphan = base({ subagents: live({ spawns: [{ id: 's1', parent: 'nobody', agent: 'sub', status: 'running', stalled: false }], active: 1, cap: 4 }) });
    expect(agentsByException(orphan).counts.working).toBe(0);
  });

  it('marks the cloud-only agent unavailable when no cloud model is configured, and only then', () => {
    expect(state(base({ trust: trust(false) }), 'athena')).toMatchObject({ activity: 'unavailable', source: 'cloud-policy', mark: 'blocked' });
    expect(state(base({ trust: trust(true) }), 'athena').activity).toBe('noActivity');
    expect(state(base({ trust: null }), 'athena').activity).toBe('noActivity');   // nothing is claimed unavailable on an unanswered trust status
    expect(state(base({ trust: trust(false) }), 'frigga').activity).not.toBe('unavailable');
    // the router gates her on the cloud adapter alone: Claude alone does not make her available
    expect(state(base({ trust: { mic: 'on', strictLocal: false, cloudAvailable: false, claudeAvailable: true } }), 'athena').activity).toBe('unavailable');
  });

  it('halts every agent while the global halt is on', () => {
    const result = agentsByException(base({ killSwitch: live({ halted: true }), blocked: live([task(1, 'pepper')]), turns: [turn('steve')] }));
    expect(result.agents.every((a) => a.activity === 'halted' && a.source === 'kill-switch')).toBe(true);
    expect(result.counts.halted).toBe(ROSTER.length);
  });

  it('prefers waiting on you over working, and a running task over a sub-agent', () => {
    const input = base({
      blocked: live([task(1, 'stark')]), running: live([task(2, 'stark'), task(3, 'steve')]),
      subagents: live({ spawns: [{ id: 's', parent: null, agent: 'steve', status: 'running', stalled: false }], active: 1, cap: 2 }),
    });
    expect(state(input, 'stark').activity).toBe('waitingOnYou');
    expect(state(input, 'steve').source).toBe('running-task');
  });

  it('counts finished only from today\'s actions', () => {
    const items = [
      { id: 'a', at: at(9), kind: 'action' as const, title: 't', agent: 'stark' },
      { id: 'b', at: at(9, 0, 22), kind: 'action' as const, title: 'yesterday', agent: 'steve' },
      { id: 'c', at: at(9), kind: 'learning' as const, title: 'learned', agent: 'ultron' },
      { id: 'd', at: null, kind: 'action' as const, title: 'no stamp', agent: 'jarvis' },
    ];
    const input = base({ today: live({ items }) });
    expect([state(input, 'stark').activity, state(input, 'steve').activity, state(input, 'ultron').activity, state(input, 'jarvis').activity])
      .toEqual(['finishedToday', 'noActivity', 'noActivity', 'noActivity']);
  });

  it('lists a source that did not answer as unread, and never turns it into "nothing is running"', () => {
    const result = agentsByException(base({ running: refused(), blocked: refused(), subagents: live({ spawns: [], active: 0, cap: 4 }) }));
    expect(result.unread).toEqual(['docket', 'running']);
    const summary = agentsSummary(result);
    expect(summary.unread).toEqual(['Waiting entries: unknown without the owner credential', 'Running work: unknown without the owner credential']);
    expect(agentsByException(base({ running: empty([]), blocked: empty([]) })).unread).toEqual([]);
  });

  it('counts replies running elsewhere without a name', () => {
    const slots = { turns: { running: 3, per_session: 1, cap: 4 }, lanes: [], subagents: null };
    expect(agentsByException(base({ slots, turns: [turn('steve')] })).elsewhere).toBe(2);
    expect(agentsByException(base({ slots: { ...slots, turns: { running: 1, per_session: 1, cap: 4 } }, turns: [turn('steve')] })).elsewhere).toBe(0);
    expect(agentsByException(base({ slots: { ...slots, turns: null } })).elsewhere).toBeNull();
    expect(agentsByException(base()).elsewhere).toBeNull();
    expect(agentsSummary(agentsByException(base({ slots, turns: [turn('steve')] }))).elsewhere).toBe('2 replies running elsewhere');
    expect(agentsSummary(agentsByException(base({ slots: { ...slots, turns: { running: 2, per_session: 1, cap: 4 } }, turns: [turn('steve')] }))).elsewhere).toBe('1 reply running elsewhere');
  });

  it('reports a roster that was not reported as not reported, not as no agents', () => {
    const result = agentsByException({ roster: [], now: T0 });
    expect([result.total, result.agents]).toEqual([null, []]);
    expect(agentsSummary(result).label).toBe('Agents: not reported');
    expect(agentsByException(base({ rosterKnown: false })).total).toBeNull();
  });

  it('writes the foot line: working, waiting, finished, unavailable, halted, then the rest', () => {
    const input = base({
      trust: trust(false),
      blocked: live([task(1, 'pepper'), task(2, 'stark')]), running: live([task(3, 'steve')]),
      today: live({ items: [{ id: 'a', at: at(9), kind: 'action', title: 't', agent: 'ultron' }] }),
      heartbeats: live({ schedulerRunning: true, heartbeats: [{ agentId: 'frigga', nextRun: at(18) }], blocked: 0 }),
    });
    const s = agentsSummary(agentsByException(input));
    expect(s.label).toBe('Agents 9');
    expect(s.parts.map((p) => p.text)).toEqual(['1 working', '2 waiting on you', '1 finished today', '1 unavailable', '4 no activity reported']);
    expect(s.parts.map((p) => p.mark)).toEqual(['work', 'seal-open', 'done', 'blocked', 'idle']);
    const ro = agentsSummary(agentsByException(input), 'ro');
    expect(ro.label).toBe('Agenți 9');
    expect(ro.parts[0].text).toBe('1 lucrează');
  });

  it('writes Romanian counts with the right plural form, never a number glued to a fragment', () => {
    const one = agentsSummary(agentsByException(base({ trust: trust(false), today: live({ items: [{ id: 'a', at: at(9), kind: 'action', title: 't', agent: 'ultron' }] }), killSwitch: live({ halted: false }) })), 'ro');
    expect(one.parts.map((p) => p.text)).toEqual(expect.arrayContaining(['1 indisponibil', '1 a terminat azi']));
    expect(one.parts.map((p) => p.text).join('|')).not.toMatch(/1 indisponibili|1 au terminat/);
    const halted = agentsSummary(agentsByException(base({ killSwitch: live({ halted: true }) })), 'ro');
    expect(halted.parts[0].text).toBe(ROSTER.length + ' ' + (ROSTER.length >= 20 ? 'de ' : '') + 'opriți');
    const en = agentsSummary(agentsByException(base({ killSwitch: live({ halted: true }) })));
    expect(en.parts[0].text).toBe(ROSTER.length + ' halted');
  });
});
