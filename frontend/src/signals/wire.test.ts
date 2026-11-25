import { describe, expect, it } from 'vitest';
import {
  epochMs, interruptsKnown, noTasks, parseApprovalMode, parseAuditVerify, parseComponents, parseEgress, parseHeartbeats, parseInterrupts,
  parseKillSwitch, parseObserver, parsePaymentsWaiting, parseSlots, parseSubagents, parseTasks, parseTodayFeed,
} from './wire';

describe('epochMs', () => {
  it('reads ISO strings and epochs in seconds or milliseconds, and nothing else', () => {
    expect(epochMs('2026-11-23T10:40:05+00:00')).toBe(Date.UTC(2026, 10, 23, 10, 40, 5));
    expect(epochMs(1_795_000_000)).toBe(1_795_000_000_000);
    expect(epochMs(1_795_000_000_000)).toBe(1_795_000_000_000);
    for (const v of [null, undefined, '', 'yesterday', 0, -3, NaN, {}]) expect(epochMs(v), String(v)).toBeNull();
  });
});

describe('the approval mode and the interrupt budget', () => {
  it('accepts only the three exact mode words', () => {
    expect(parseApprovalMode({ mode: 'ask' })).toEqual({ mode: 'ask' });
    for (const raw of [{ mode: 'ASK' }, { mode: 'live' }, {}, null, 'ask']) expect(() => parseApprovalMode(raw), JSON.stringify(raw)).toThrow();
  });
  it('reads the budget, and leaves an unwired one unknown rather than 0', () => {
    const b = parseInterrupts({ remaining: 3, per_day: 4, used: 1 });
    expect(b).toEqual({ used: 1, perDay: 4, remaining: 3 });
    expect(interruptsKnown(b)).toBe(true);
    const none = parseInterrupts({ remaining: null, per_day: null, used: null });
    expect(none).toEqual({ used: null, perDay: null, remaining: null });
    expect(interruptsKnown(none)).toBe(false);
    expect(parseInterrupts({ remaining: -1, per_day: 'x', used: 1.5 })).toEqual({ used: null, perDay: null, remaining: null });
    expect(() => parseInterrupts([])).toThrow();
  });
});

describe('the audit chain', () => {
  it('needs a boolean verdict', () => {
    expect(parseAuditVerify({ valid: true, first_invalid_id: null, entries: 921, tamper_evident: false, reason: 'x' }))
      .toEqual({ valid: true, firstInvalidId: null, entries: 921, tamperEvident: false });
    expect(parseAuditVerify({ valid: false, first_invalid_id: 412, entries: 3 })).toEqual({ valid: false, firstInvalidId: 412, entries: 3, tamperEvident: null });
    for (const raw of [{}, { valid: 'true' }, null, { entries: 3 }]) expect(() => parseAuditVerify(raw), JSON.stringify(raw)).toThrow();
  });
});

describe('the observer', () => {
  it('reads each unhealthy probe with its since (B2)', () => {
    const o = parseObserver({ enabled: true, probes: 2, tracked: 7, unhealthy: [
      { key: 'service.lmstudio', detail: 'lmstudio not responding on 127.0.0.1:1234', severity: 'CRITICAL', since: '2026-11-23T08:14:00+00:00' },
      { key: 'resource.ram', detail: 'RAM at 91%', severity: 'warn' },
      { detail: 'no key' }, null, 3,
    ] });
    expect(o.enabled).toBe(true);
    expect(o.unhealthy).toEqual([
      { key: 'service.lmstudio', detail: 'lmstudio not responding on 127.0.0.1:1234', severity: 'CRITICAL', since: Date.UTC(2026, 10, 23, 8, 14) },
      { key: 'resource.ram', detail: 'RAM at 91%', severity: 'WARN', since: null },
    ]);
  });
  it('says unknown, not healthy, when the observer is off or its answer is not a list', () => {
    expect(parseObserver({ enabled: false, reason: 'observer not initialized' })).toEqual({ enabled: false, probes: null, tracked: null, unhealthy: null });
    expect(() => parseObserver({ probes: 1, tracked: 1 })).toThrow();
    expect(() => parseObserver({ enabled: true, unhealthy: 'none' })).toThrow();
    expect(parseObserver({ enabled: true, probes: 1, tracked: 0, unhealthy: [] }).unhealthy).toEqual([]);
  });
});

describe('the day\'s feed', () => {
  it('keeps titles as plain text and reads times from ts or epoch', () => {
    const f = parseTodayFeed({ items: [
      { entry_id: 'action:7', ts: '2026-11-23T07:14:00+00:00', kind: 'action', title: '  Calendar synced  ', agent: 'Pepper' },
      { entry_id: null, epoch: 1_795_000_000, kind: 'weird', title: 'x' },
      { kind: 'action', title: '' }, { kind: 'action' }, 'nope',
    ], counts: {} });
    expect(f.items).toEqual([
      { id: 'action:7', at: Date.UTC(2026, 10, 23, 7, 14), kind: 'action', title: 'Calendar synced', agent: 'pepper', reason: null, taskId: null },
      { id: 'other:1', at: 1_795_000_000_000, kind: 'other', title: 'x', agent: null, reason: null, taskId: null },
    ]);
    expect(() => parseTodayFeed({ error: 'not initialized' })).toThrow();
  });
});

describe('the day feed: stamps and follow-ups', () => {
  it('prefers epoch over ts, and reads a naive ts as the hub UTC (not local time)', () => {
    const f = parseTodayFeed({ items: [
      { entry_id: 'a', epoch: Date.UTC(2026, 10, 23, 10, 40) / 1000, ts: '2026-11-23 10:40:00', kind: 'followup', reason: 'open_concern', title: 'x' },
      { entry_id: 'b', ts: '2026-11-23 10:40:00', kind: 'followup', title: 'y' },
      { entry_id: 'c', ts: '2026-11-23T10:40:00+02:00', kind: 'followup', title: 'z' },
    ], counts: {} });
    expect(f.items.map((i) => i.at)).toEqual([Date.UTC(2026, 10, 23, 10, 40), Date.UTC(2026, 10, 23, 10, 40), Date.UTC(2026, 10, 23, 8, 40)]);
  });

  it('keeps a follow-up reason and the task it is about', () => {
    const f = parseTodayFeed({ items: [
      { entry_id: 'followup:blocked_task:task:12', epoch: 1_795_000_000, kind: 'followup', reason: 'blocked_task', source: 'task', id: 12, title: 'Restart ollama?' },
      { entry_id: 'followup:open_concern:learning:3', epoch: 1_795_000_000, kind: 'followup', reason: 'open_concern', source: 'memory', id: 3, title: 'c' },
    ], counts: {} });
    expect(f.items.map((i) => [i.reason, i.taskId])).toEqual([['blocked_task', 12], ['open_concern', null]]);
  });
});

describe('heartbeats, slots and sub-agents', () => {
  it('reads the schedule and what was refused at load', () => {
    expect(parseHeartbeats({ scheduler_running: true, heartbeats: [{ agent_id: 'Pepper', next_run: '2026-11-23T16:00:00+00:00', trigger: 'cron' }, { next_run: null }], blocked: [{ x: 1 }] }))
      .toEqual({ schedulerRunning: true, heartbeats: [{ agentId: 'pepper', nextRun: Date.UTC(2026, 10, 23, 16) }], blocked: 1 });
    expect(() => parseHeartbeats({ heartbeats: [] })).toThrow();
  });
  it('reads /api/status/slots through the shared slot parser, and refuses an answer without it', () => {
    const v = parseSlots({ slots: { turns: { running: 1, per_session: 1, cap: 4 }, lanes: [], subagents: { running: 0, cap: 2 } }, holders: [{ surface: 'hud', age: 3 }, 'x'], holders_total: 1 });
    expect(v.slots.turns).toEqual({ running: 1, per_session: 1, cap: 4 });
    expect(v.holders).toEqual([{ surface: 'hud', age: 3 }]);
    expect(v.holdersTotal).toBe(1);
    expect(parseSlots({ slots: { turns: null, lanes: [], subagents: null }, holders: null, holders_total: null }).holders).toBeNull();
    expect(() => parseSlots({ error: 'not initialized' })).toThrow();
  });
  it('reads sub-agents with their stalled flag', () => {
    const v = parseSubagents({ spawns: [{ id: 's1', parent: 'Jarvis', agent: 'sub', status: 'running', stalled: true }, { status: 'running' }], stats: { active: 1, cap: 4 } });
    expect(v.spawns).toEqual([{ id: 's1', parent: 'jarvis', agent: 'sub', status: 'running', stalled: true }]);
    expect([v.active, v.cap]).toEqual([1, 4]);
    expect(parseSubagents({ spawns: [], stats: {} })).toEqual({ spawns: [], active: null, cap: null });
    expect(() => parseSubagents({})).toThrow();
  });
});

describe('tasks', () => {
  it('reads running and blocked tasks, with the service a restart names', () => {
    const t = parseTasks({ tasks: [
      { id: 12, kind: 'restart_service', title: 'Restart ollama?', agent: 'Steve', created_at: '2026-11-23T08:14:00+00:00', payload: { service: 'ollama', cmd: 'ollama serve' } },
      { id: 'x' }, { id: 5 },
    ] });
    expect(t).toEqual([
      { id: 12, kind: 'restart_service', title: 'Restart ollama?', agent: 'steve', createdAt: Date.UTC(2026, 10, 23, 8, 14), service: 'ollama' },
      { id: 5, kind: null, title: '', agent: null, createdAt: null, service: null },
    ]);
    expect(noTasks(t)).toBe(false);
    expect(noTasks(parseTasks({ tasks: [] }))).toBe(true);
    expect(() => parseTasks({ error: 'not initialized' })).toThrow();
  });
});

describe('egress, components, kill switch, payments', () => {
  it('reads the ledger totals and refuses an answer without them', () => {
    expect(parseEgress({ external_egress_total: 42, model_egress_total: 0, ledger: { since: '2026-11-23T10:20:10+00:00' } }))
      .toEqual({ external: 42, models: 0, since: Date.UTC(2026, 10, 23, 10, 20, 10) });
    expect(parseEgress({ external_egress_total: 3 })).toEqual({ external: 3, models: null, since: null });
    expect(() => parseEgress({ plugins: {} })).toThrow();
  });
  it('reads failed components, and a registry that was unavailable as not reported', () => {
    expect(parseComponents({ components: {}, failed: ['kg', ' ', 3], summary: 'x' })).toEqual({ failed: ['kg'] });
    expect(parseComponents({ components: {}, summary: 'registry unavailable' })).toEqual({ failed: null });
  });
  it('reads the kill switch under the hub\'s own consistency rules', () => {
    expect(parseKillSwitch({ global: true, any_halted: true, halted_count: 1 })).toEqual({ halted: true });
    expect(parseKillSwitch({ global: false, any_halted: false, halted_count: 0 })).toEqual({ halted: false });
    expect(parseKillSwitch({ global: false, any_halted: true, halted_count: 2 })).toEqual({ halted: false });
    for (const raw of [{ global: true, any_halted: false, halted_count: 0 }, { global: 'yes' }, {}, null, { global: false, any_halted: false, halted_count: 1 }]) {
      expect(() => parseKillSwitch(raw), JSON.stringify(raw)).toThrow();
    }
  });
  it('counts the payments waiting for the owner', () => {
    expect(parsePaymentsWaiting({ payments: [{ status: 'pending' }, { status: 'approved' }, { status: 'pending' }, null] })).toBe(2);
    expect(parsePaymentsWaiting({ payments: [] })).toBe(0);
    expect(() => parsePaymentsWaiting({})).toThrow();
  });
});
