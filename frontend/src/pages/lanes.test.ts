import { describe, expect, it } from 'vitest';
import { buildTimeline, position, NO_AGENT, type TimelineInputs } from './lanes';
import { startOfDay } from './sources';
import type { AgentState } from '../signals/types';

const NOW = new Date(2026, 10, 23, 14, 30).getTime();
const DAY0 = startOfDay(NOW);
const HOUR = 3600_000;
const roster = [{ id: 'jarvis', name: 'Jarvis' }, { id: 'pepper', name: 'Pepper' }, { id: 'stark', name: 'Stark' }, { id: 'athena', name: 'Athena' }, { id: 'frigga', name: 'Frigga' }];
const st = (id: string, activity: AgentState['activity'] = 'noActivity'): AgentState => ({ id, name: id, activity, mark: 'idle', source: 'none' });
const base = (over: Partial<TimelineInputs> = {}): TimelineInputs => ({
  now: NOW, roster, done: [], blocked: [], running: [], subagents: [], turns: [], beats: [], observer: [],
  states: roster.map((a) => st(a.id)), cloudConfigured: null, ...over,
});

describe('buildTimeline: lanes only from real events', () => {
  it('has no lane for an agent with nothing today, and folds them into one named row', () => {
    const m = buildTimeline(base({ done: [{ id: 'a1', at: DAY0 + 9 * HOUR, title: 'Booked', agent: 'pepper' }] }));
    expect(m.lanes.map((l) => l.id)).toEqual(['pepper']);
    expect(m.folded).toEqual(['jarvis', 'stark', 'athena', 'frigga']);
  });

  it("draws yesterday's finished actions nowhere", () => {
    const m = buildTimeline(base({ done: [{ id: 'old', at: DAY0 - HOUR, title: 'Old', agent: 'pepper' }] }));
    expect(m.lanes).toEqual([]);
  });

  it('folds an agent with only a scheduled heartbeat: a schedule is not activity', () => {
    const m = buildTimeline(base({ beats: [{ agentId: 'stark', nextRun: NOW + 3 * HOUR }], states: roster.map((a) => st(a.id, a.id === 'stark' ? 'scheduled' : 'noActivity')) }));
    expect(m.lanes).toEqual([]);
    expect(m.folded).toContain('stark');
  });

  it('puts a tick, a start and a finish on the lane of the agent that has them', () => {
    const m = buildTimeline(base({
      done: [{ id: 'a1', at: DAY0 + 8 * HOUR, title: 'Index', agent: 'stark' }],
      running: [{ id: 3, title: 'Reindex', agent: 'stark', since: NOW - HOUR, tier: 0 }],
      beats: [{ agentId: 'stark', nextRun: NOW + 2 * HOUR }],
    }));
    expect(m.lanes).toHaveLength(1);
    expect(m.lanes[0].events.map((e) => e.kind).sort()).toEqual(['done', 'run', 'tick']);
  });

  it("keeps a run's real start for the words and flags one older than today; an unknown start is null at now", () => {
    const m = buildTimeline(base({ running: [
      { id: 1, title: 'Old', agent: 'stark', since: DAY0 - 5 * HOUR, tier: 0 },
      { id: 2, title: 'Unknown', agent: 'stark', since: null, tier: 0 },
    ] }));
    const runs = m.lanes[0].events.filter((e) => e.kind === 'run') as any[];
    expect(runs.find((r) => r.title === 'Old')).toMatchObject({ since: DAY0, startedAt: DAY0 - 5 * HOUR, stub: true });
    expect(runs.find((r) => r.title === 'Unknown')).toMatchObject({ since: NOW, startedAt: null, stub: false });
  });

  it('ignores a heartbeat that is not today, and a null time', () => {
    const m = buildTimeline(base({ done: [{ id: 'a', at: DAY0 + HOUR, title: 'x', agent: 'stark' }], beats: [{ agentId: 'stark', nextRun: NOW + 30 * HOUR }, { agentId: 'stark', nextRun: null }] }));
    expect(m.lanes[0].events.some((e) => e.kind === 'tick')).toBe(false);
  });

  it("draws this tab's turn as a run by the agent asked", () => {
    const m = buildTimeline(base({ turns: [{ turnId: 1, agent: 'Jarvis', askedAt: NOW - 3 * 60_000, startedAt: null, firstTokenAt: null }] }));
    expect(m.lanes[0].id).toBe('jarvis');
    expect(m.lanes[0].events[0]).toMatchObject({ kind: 'run', source: 'this-tab', since: NOW - 3 * 60_000 });
  });
});

describe('buildTimeline: holds', () => {
  it('numbers holds oldest first, and stubs one older than today with how old it is', () => {
    const m = buildTimeline(base({ blocked: [
      { id: 12, title: 'New', agent: 'pepper', tier: 1, createdAt: NOW - HOUR },
      { id: 7, title: 'Old', agent: 'pepper', tier: 3, createdAt: DAY0 - 50 * HOUR },
    ] }));
    const holds = m.lanes[0].events.filter((e) => e.kind === 'hold') as any[];
    const byId = Object.fromEntries(holds.map((h) => [h.id, h]));
    expect(byId[7].pin).toBe(1);
    expect(byId[12].pin).toBe(2);
    expect(byId[7].stub).toBe(true);
    expect(byId[7].since).toBe(DAY0);
    expect(byId[7].olderThan).toBe(DAY0 - 50 * HOUR);
    expect(byId[12].stub).toBe(false);
    expect(byId[12].since).toBe(NOW - HOUR);
  });

  it('puts a hold whose age is not known at now, without a start time and without calling it old', () => {
    const m = buildTimeline(base({ blocked: [{ id: 1, title: 'x', agent: 'stark', tier: 0, createdAt: null }] }));
    expect(m.lanes[0].events[0]).toMatchObject({ kind: 'hold', since: NOW, startedAt: null, stub: false });
  });

  it('keeps a hold that names no agent on its own lane, last', () => {
    const m = buildTimeline(base({ blocked: [{ id: 1, title: 'x', agent: null, tier: 0, createdAt: NOW }], done: [{ id: 'a', at: NOW, title: 'y', agent: 'pepper' }] }));
    expect(m.lanes.map((l) => l.id)).toEqual(['pepper', NO_AGENT]);
  });

  it('puts the lanes that hold something for the owner first', () => {
    const m = buildTimeline(base({ done: [{ id: 'a', at: NOW, title: 'y', agent: 'frigga' }], blocked: [{ id: 1, title: 'x', agent: 'stark', tier: 2, createdAt: NOW }] }));
    expect(m.lanes.map((l) => l.id)).toEqual(['stark', 'frigga']);
  });
});

describe('buildTimeline: system and unknown sources', () => {
  it("keeps observer problems off the agents' lanes, with the bar clamped to today and the hub's own start kept", () => {
    const m = buildTimeline(base({ observer: [{ key: 'service.ollama', detail: 'down', since: DAY0 - 5 * HOUR }, { key: 'resource.ram', detail: null, since: null }] }));
    expect(m.lanes).toEqual([]);
    expect(m.system).toEqual([{ key: 'service.ollama', detail: 'down', since: DAY0, startedAt: DAY0 - 5 * HOUR, stub: true }, { key: 'resource.ram', detail: null, since: null, startedAt: null, stub: false }]);
  });

  it('says the System lane is unknown (null), not empty, when the observer did not answer', () => {
    expect(buildTimeline(base({ observer: null })).system).toBeNull();
    expect(buildTimeline(base({ observer: [] })).system).toEqual([]);
  });

  it('draws the cloud-only agent as a dashed, empty lane only when no cloud model is configured', () => {
    const none = buildTimeline(base({ cloudConfigured: false }));
    expect(none.lanes).toEqual([expect.objectContaining({ id: 'athena', dashed: true, events: [] })]);
    expect(none.folded).not.toContain('athena');
    expect(buildTimeline(base({ cloudConfigured: true })).lanes).toEqual([]);
    expect(buildTimeline(base({ cloudConfigured: null })).lanes).toEqual([]);
  });

  it('lists the sources that did not answer, and draws nothing from them', () => {
    const m = buildTimeline(base({ done: null, blocked: null, running: null, subagents: null, beats: null }));
    expect(m.unknown).toEqual(['today', 'docket', 'running', 'subagents', 'heartbeats']);
    expect(m.lanes).toEqual([]);
  });
});

describe('position', () => {
  it('maps the day onto 0–100 and clamps', () => {
    const m = buildTimeline(base());
    expect(position(m, m.dayStart)).toBe(0);
    expect(position(m, m.dayEnd)).toBe(100);
    expect(position(m, m.dayStart + 12 * HOUR)).toBeCloseTo(50, 5);
    expect(position(m, m.dayStart - HOUR)).toBe(0);
    expect(position(m, m.dayEnd + HOUR)).toBe(100);
  });
});
