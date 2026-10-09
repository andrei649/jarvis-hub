import { describe, expect, it } from '@jest/globals';
import { buildBriefingField, fieldEnergy } from '../briefingField';

describe('native briefing neural field', () => {
  const agents = [
    { id: 'a', tier: 'TEC', status: 'busy' },
    { id: 'b', tier: 'BUS', status: 'idle' },
    { id: 'c', tier: 'TEC', status: 'active' },
  ];
  const tasks = [
    { owner: 'A', state: 'running' },
    { owner: 'b', state: 'queued' },
    { owner: 'nobody', state: 'running' },
  ];

  it('uses real tier, agent activity, and exact running-task ownership counts', () => {
    const field = buildBriefingField(agents, tasks);
    expect(field.regions.map(region => [region.key, region.count, region.busy, region.running]))
      .toEqual([['bus', 1, 0, 0], ['tec', 2, 2, 1]]);
    expect(field.totalAgents).toBe(3);
    expect(field.runningTasks).toBe(2);
    expect(field.unassignedRunningTasks).toBe(1);
    expect(field.markers).toHaveLength(3);
    expect(buildBriefingField([...agents].reverse(), [...tasks].reverse())).toEqual(field);
  });

  it('leaves the field empty with no roster and never invents tier or ownership', () => {
    const field = buildBriefingField([], [{ owner: 'ghost', state: 'running' }]);
    expect(field.regions).toEqual([]);
    expect(field.markers).toEqual([]);
    expect(field.edges).toEqual([]);
    expect(field.unassignedRunningTasks).toBe(1);
  });

  it('does not attribute a task when reported agent IDs collide across tiers', () => {
    const collision = [
      { id: 'same', tier: 'TEC', status: 'idle' },
      { id: 'same', tier: 'BUS', status: 'idle' },
    ];
    const running = [{ owner: 'same', state: 'running' }];
    const field = buildBriefingField(collision, running);
    expect(field.regions.map(region => region.running)).toEqual([0, 0]);
    expect(field.unassignedRunningTasks).toBe(1);
    expect(buildBriefingField([...collision].reverse(), running)).toEqual(field);
  });

  it('caps geometry and groups excess tiers without changing actual counts', () => {
    const huge = Array.from({ length: 360 }, (_, index) => ({
      id: `agent-${index}`, tier: `T${index % 20}`, status: index % 3 ? 'idle' : 'busy',
    }));
    const field = buildBriefingField(huge, []);
    expect(field.regions.length).toBeLessThanOrEqual(8);
    expect(field.regions.reduce((total, region) => total + region.count, 0)).toBe(360);
    expect(field.regions.some(region => region.key === 'other')).toBe(true);
    expect(field.markers.length).toBeLessThanOrEqual(96);
    expect(field.edges.length).toBeLessThanOrEqual(192);
    expect(field.markers.every(point => point.x >= 0 && point.x <= 1 && point.y >= 0 && point.y <= 1)).toBe(true);
    expect(field.regions.reduce((total, region) => total + region.markerCount, 0)).toBe(field.markers.length);
  });

  it('keeps a literal other tier separate from overflow tiers and their task owners', () => {
    const tiers = ['a', 'b', 'c', 'd', 'e', 'f', 'other', 'y', 'z'];
    const field = buildBriefingField(tiers.map(tier => ({ id: tier, tier, status: 'idle' })), [
      { owner: 'other', state: 'running' }, { owner: 'y', state: 'running' },
    ]);
    expect(field.regions).toHaveLength(8);
    expect(field.regions.find(region => region.key === 'other'))
      .toMatchObject({ label: 'other', count: 1, running: 1 });
    expect(field.regions.find(region => region.label === 'Other reported tiers'))
      .toMatchObject({ count: 2, running: 1 });
    expect(field.regions.reduce((total, region) => total + region.count, 0)).toBe(9);
  });

  it('reports only supported energy sources and rejects invalid mic samples', () => {
    expect(fieldEnergy(agents, tasks, { status: 'listening', level: 0.4 }).source).toBe('measured mic level');
    expect(fieldEnergy(agents, tasks, { status: 'listening', level: NaN })).toMatchObject({ source: 'voice state, no measured level', level: 0 });
    expect(fieldEnergy(agents, tasks, { status: 'speaking', level: 1 }).source).toBe('voice state');
    expect(fieldEnergy(agents, tasks, { status: 'transcribing' }).source).toBe('voice state');
    expect(fieldEnergy(agents, tasks, { status: 'idle' }).source).toBe('reported work');
    expect(fieldEnergy([], [], { status: 'idle' })).toMatchObject({ source: 'idle', level: 0 });
  });
});
