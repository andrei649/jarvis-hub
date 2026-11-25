import { describe, expect, it } from 'vitest';
import {
  doneActions, parseBlocked, parseJobs, parsePayments, parseRecord, parseRunning, parseSkillChanges, parseSubagents,
  toEpochMs, topBlocked,
} from './sources';

describe('toEpochMs', () => {
  it('reads ISO strings and epoch seconds or milliseconds, and nothing else', () => {
    expect(toEpochMs('2026-11-23T10:00:00Z')).toBe(Date.UTC(2026, 10, 23, 10));
    expect(toEpochMs(1_764_000_000)).toBe(1_764_000_000_000);
    expect(toEpochMs(1_764_000_000_000)).toBe(1_764_000_000_000);
    for (const v of ['', 'soon', null, undefined, 0, -5, NaN, {}]) expect(toEpochMs(v as unknown)).toBeNull();
  });
});

describe('parsers fail closed on answers that are not the hub\'s', () => {
  it.each([
    ['running', parseRunning], ['subagents', parseSubagents], ['jobs', parseJobs], ['blocked', parseBlocked],
    ['payments', parsePayments], ['skill changes', parseSkillChanges], ['record', parseRecord],
  ])('%s throws on a proxy page, a string and a list', (_name, parse) => {
    for (const raw of [null, 'not json', [], 42, { unrelated: true }]) expect(() => (parse as (r: unknown) => unknown)(raw)).toThrow();
  });
});

describe('parseRunning and parseBlocked', () => {
  it('keep plain-text titles and the fields a row has, and leave out a row with no id or title', () => {
    const rows = parseRunning({ tasks: [
      { id: 1, title: ' <b>Index</b> ', agent: 'Stark', risk_tier: 1, updated_at: '2026-11-23T10:00:00Z' },
      { id: 'x', title: 'no numeric id' }, { id: 3 }, null,
    ] });
    expect(rows).toEqual([{ id: 1, title: '<b>Index</b>', agent: 'stark', since: Date.UTC(2026, 10, 23, 10), tier: 1 }]);
  });

  it('orders the docket\'s top rows strictest first, then oldest, then lowest id', () => {
    const rows = parseBlocked({ tasks: [
      { id: 5, title: 'a', risk_tier: 1, created_at: '2026-11-20T00:00:00Z' },
      { id: 6, title: 'b', risk_tier: 3, created_at: '2026-11-22T00:00:00Z' },
      { id: 7, title: 'c', risk_tier: 3, created_at: '2026-11-21T00:00:00Z' },
      { id: 8, title: 'd' },
    ] });
    expect(topBlocked(rows.filter((r) => r.id !== 8), 3).map((r) => r.id)).toEqual([7, 6, 5]);
    // a tier the hub did not send sorts as the strictest: unknown is never treated as safe
    expect(topBlocked(rows, 4)[0].id).toBe(8);
  });
});

describe('parseSubagents', () => {
  it('keeps only work in flight and carries the stall flag', () => {
    const feed = parseSubagents({ spawns: [
      { id: 'a', agent: 'Scout', parent: 'Jarvis', status: 'running', stalled: true, created_at: '2026-11-23T10:00:00Z', task: 'look' },
      { id: 'b', agent: 'x', status: 'done' }, { id: 'c', agent: 'y', status: 'failed' }, { id: 'd', agent: 'z', status: 'stopping' },
    ], stats: { active: 1, cap: 3 } });
    expect(feed.runs.map((r) => [r.id, r.agent, r.stalled])).toEqual([['a', 'scout', true], ['d', 'z', false]]);
    expect(feed.active).toBe(1);
    expect(feed.cap).toBe(3);
  });

  it('leaves a count the hub did not send null, never 0', () => {
    expect(parseSubagents({ spawns: [] })).toMatchObject({ active: null, cap: null });
  });
});

describe('parsePayments', () => {
  it('reads the broker\'s rows, naming a state it does not know, and leaves a missing amount null', () => {
    const rows = parsePayments({ payments: [
      { id: 'p1', payee: 'Gecko', amount: 4200, currency: 'eur', memo: 'x', status: 'pending', created_at: 1_764_000_000 },
      { id: 'p2', mandate_id: 'm', status: 'frozen' }, { payee: 'no id' },
    ] });
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({ id: 'p1', payee: 'Gecko', amount: 4200, currency: 'EUR', state: 'pending' });
    expect(rows[1]).toMatchObject({ state: 'other', stateWord: 'frozen', amount: null, currency: null, payee: 'm' });
  });
});

describe('parseSkillChanges', () => {
  it('adds the proposals past the page to the ones shown, and needs a count', () => {
    expect(parseSkillChanges({ count: 3, more: 2 })).toEqual({ count: 5 });
    expect(parseSkillChanges({ count: 0 })).toEqual({ count: 0 });
    expect(() => parseSkillChanges({ proposals: [] })).toThrow();
  });
});

describe('parseRecord', () => {
  it('reads the log\'s entries and its own verdict, a tier only from metadata, and no invented field', () => {
    const feed = parseRecord({ verify: { ok: true, n: 2 }, entries: [
      { seq: 2, ts: 1_764_000_000, actor: 'ultron', action: 'redact', why: 'PII', entry_hash: 'abcdef0123456789', metadata: { risk_tier: 2 } },
      { seq: 1, ts: 1_763_999_000, actor: 'jarvis', action: 'route', why: 'q', entry_hash: 'f', metadata: { tier: 9 } },
      { actor: 'no seq' },
    ] });
    expect(feed.chainOk).toBe(true);
    expect(feed.entries).toHaveLength(2);
    expect(feed.entries[0]).toMatchObject({ seq: 2, actor: 'ultron', tier: 2, at: 1_764_000_000_000 });
    expect(feed.entries[1].tier).toBeNull();
  });

  it('has no verdict when the hub sent none, and a false one when the log says so', () => {
    expect(parseRecord({ entries: [] }).chainOk).toBeNull();
    expect(parseRecord({ verify: { ok: false }, entries: [] }).chainOk).toBe(false);
  });
});

describe('doneActions', () => {
  it('keeps actions only, newest first, with a time', () => {
    const items = [
      { id: 'a', at: 100, kind: 'action', title: 'one', agent: 'pepper' }, { id: 'b', at: 300, kind: 'action', title: 'two', agent: null },
      { id: 'c', at: 200, kind: 'learning', title: 'x', agent: null }, { id: 'd', at: null, kind: 'action', title: 'no time', agent: null },
    ];
    expect(doneActions({ items } as never).map((d) => d.id)).toEqual(['b', 'a']);
    expect(doneActions(null)).toEqual([]);
  });
});
