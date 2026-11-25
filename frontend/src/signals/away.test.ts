import { describe, expect, it } from 'vitest';
import { stringProblems } from '../frame/strings';
import { AWAY_STRINGS, LAST_SEEN_KEY, awayEntries, awaySince, awayWords, readLastSeen, writeLastSeen, type AwayInput } from './away';
import { T0, at, checking, empty, live, refused } from './test-support';
import type { Cause } from './types';
import type { TaskLite, TodayItem } from './wire';

const SINCE = awaySince(at(6), T0);
const item = (id: string, h: number, m: number, kind: TodayItem['kind'], title: string, agent: string | null = null): TodayItem => ({ id, at: at(h, m), kind, title, agent });
const task = (id: number, h: number, m: number, title = `Entry ${id}`): TaskLite => ({ id, kind: 'send_email', title, agent: 'ultron', createdAt: at(h, m), service: null });
const cause = (key: string, detail: string, since: number | null): Cause => ({ key, detail, mark: 'problem', consequence: null, since, source: 'observer' });
const input = (over: Partial<AwayInput> = {}): AwayInput => ({
  today: live({ items: [] }), blocked: empty([]), causes: [], checkedAt: T0, since: SINCE, now: T0,
  docketHref: (id) => `/v2/cockpit#docket-entry-${id}`, recordHref: '/v2/console/today', ...over,
});

describe('away strings', () => {
  it('are complete in English and Romanian', () => expect(stringProblems(AWAY_STRINGS)).toEqual([]));
});

describe('awaySince', () => {
  it('is this browser\'s last visit when one is stored', () => {
    expect(awaySince(at(6), T0)).toEqual({ at: at(6), basis: 'lastVisit' });
  });
  it('is the start of today when nothing is stored, or the value is not usable', () => {
    for (const stored of [null, 0, -5, NaN, T0 + 3_600_000]) expect(awaySince(stored, T0), String(stored)).toEqual({ at: at(0), basis: 'startOfDay' });
  });
  it('is never earlier than the feed\'s 24 hours', () => {
    expect(awaySince(at(7, 0, 20), T0)).toEqual({ at: T0 - 24 * 3_600_000, basis: 'last24h' });
  });
});

describe('awayEntries', () => {
  it('lists the day\'s actions oldest first with their agent and no exception', () => {
    const today = live({ items: [item('b', 9, 40, 'action', 'Indexed 17 sources', 'vision'), item('a', 7, 14, 'action', 'Calendar synced', 'pepper')] });
    const s = awayEntries(input({ today }));
    expect(s.entries.map((e) => [e.id, e.kind, e.mark, e.exception, e.agent, e.source])).toEqual([
      ['a', 'done', 'done', false, 'pepper', 'dashboard-today'], ['b', 'done', 'done', false, 'vision', 'dashboard-today']]);
    expect(s.totals).toEqual({ entries: 2, done: 2, heldOrBlocked: 0, problems: 0 });
  });

  it('leaves out what happened before the window, in the future, and what was learned', () => {
    const today = live({ items: [
      item('old', 5, 0, 'action', 'Before'), item('learn', 8, 0, 'learning', 'A fact'), item('ok', 8, 1, 'action', 'In'),
      { id: 'future', at: T0 + 3_600_000, kind: 'action' as const, title: 'Tomorrow', agent: null }, { id: 'nostamp', at: null, kind: 'action' as const, title: 'No stamp', agent: null },
    ] });
    expect(awayEntries(input({ today })).entries.map((e) => e.id)).toEqual(['ok']);
  });

  it('lists a follow-up as other, not as done', () => {
    const s = awayEntries(input({ today: live({ items: [item('f', 8, 0, 'followup', 'Ask about the lease')] }) }));
    expect(s.entries[0]).toMatchObject({ kind: 'other', mark: 'attn', nativeKind: 'followup' });
    expect(s.totals.done).toBe(0);
  });

  it('lists a blocked_task follow-up once: the docket entry for the same task wins, and a failed_task is an exception', () => {
    const followup = (id: string, reason: string, taskId: number | null, title: string): TodayItem => ({ id, at: at(7, 48), kind: 'followup', title, agent: 'steve', reason, taskId });
    const today = live({ items: [
      followup('followup:blocked_task:task:7', 'blocked_task', 7, 'Restart ollama?'),
      followup('followup:blocked_task:task:9', 'blocked_task', 9, 'Not on the docket'),
      followup('followup:failed_task:task:11', 'failed_task', 11, 'Backup failed'),
    ] });
    const s = awayEntries(input({ today, blocked: live([task(7, 7, 48, 'Restart ollama?')]) }));
    expect(s.entries.map((e) => [e.id, e.kind, e.exception, e.nativeKind])).toEqual([
      ['docket:7', 'raised', true, 'send_email'],
      ['followup:blocked_task:task:9', 'blocked', true, 'blocked_task'],
      ['followup:failed_task:task:11', 'problem', true, 'failed_task'],
    ]);
    expect(s.totals).toMatchObject({ entries: 3, heldOrBlocked: 2, problems: 1 });
    // with the docket unread there is nothing to dedupe against: the follow-up is kept
    expect(awayEntries(input({ today, blocked: refused() })).entries.map((e) => e.id)).toContain('followup:blocked_task:task:7');
  });

  it('marks the probes unread when they did not answer, and a tally whose source did not answer is unknown, never 0', () => {
    const s = awayEntries(input({ problemsRead: false }));
    expect(s.unread).toEqual(['problems']);
    expect(s.known).toEqual({ done: true, heldOrBlocked: true, problems: false });
    const w = awayWords(s);
    expect(w.totals.problems).toBe('problems: unknown');
    expect(w.totals.done).toBe('0 done');
    expect(w.unreadCount).toBe('1 source not read');
    expect(w.unread).toEqual(['Problems that began meanwhile are unknown: the service probes could not be read.']);
    const docket = awayEntries(input({ blocked: refused() }));
    expect(docket.unread).toEqual(['docket']);
    expect(awayWords(docket).totals.heldOrBlocked).toBe('held or blocked: unknown');
    expect(awayEntries(input()).unread).toEqual([]);
    expect(awayWords(awayEntries(input())).unreadCount).toBeNull();
  });

  it('adds docket entries raised since, as an exception that links to the entry', () => {
    const s = awayEntries(input({ blocked: live([task(7, 7, 48, 'Send the redacted report'), task(3, 5, 0)]) }));
    expect(s.entries).toHaveLength(1);
    expect(s.entries[0]).toMatchObject({ id: 'docket:7', kind: 'raised', mark: 'seal-open', exception: true, title: 'Send the redacted report', href: '/v2/cockpit#docket-entry-7', source: 'docket' });
    expect(s.totals.heldOrBlocked).toBe(1);
  });

  it('adds current problems that began in the window, at the time they began', () => {
    const s = awayEntries(input({ causes: [cause('service.qdrant', 'qdrant not responding on 127.0.0.1:6333', at(8, 14)), cause('service.neo4j', 'neo4j not responding', at(4, 0))] }));
    expect(s.entries).toHaveLength(1);
    expect(s.entries[0]).toMatchObject({ id: 'problem:service.qdrant', kind: 'problem', mark: 'problem', exception: true, at: at(8, 14), atKind: 'event', title: 'qdrant not responding on 127.0.0.1:6333' });
    expect(s.totals.problems).toBe(1);
  });

  it('lists a problem whose start the hub did not report at the time it was checked, and says so', () => {
    const s = awayEntries(input({ causes: [cause('service.n8n', 'n8n not responding', null), cause('audit-chain', 'Chain broken at entry 4', null)] }));
    expect(s.entries.map((e) => [e.at, e.atKind])).toEqual([[T0, 'checked'], [T0, 'checked']]);
    expect(s.entries[1].title).toBe('audit-chain: Chain broken at entry 4');
    expect(awayWords(s).checked(T0)).toBe('checked 10:50');
    expect(awayEntries(input({ causes: [cause('service.n8n', 'n8n down', null)], checkedAt: null })).entries).toEqual([]);
  });

  it('keeps titles as plain text exactly as the hub wrote them', () => {
    const nasty = '<img src=x onerror=alert(1)> **bold** [link](http://x)';
    const s = awayEntries(input({ today: live({ items: [item('x', 8, 0, 'action', nasty)] }) }));
    expect(s.entries[0].title).toBe(nasty);
  });

  it('keeps only the newest N entries', () => {
    const items = Array.from({ length: 8 }, (_, i) => item(`i${i}`, 7, i, 'action', `A${i}`));
    expect(awayEntries(input({ today: live({ items }), limit: 3 })).entries.map((e) => e.id)).toEqual(['i5', 'i6', 'i7']);
  });

  it('totals: entries, done, held or blocked, problems', () => {
    const s = awayEntries(input({
      today: live({ items: [item('a', 7, 0, 'action', 'A'), item('b', 7, 1, 'action', 'B')] }),
      blocked: live([task(1, 8, 0), task(2, 8, 1)]), causes: [cause('service.x', 'x down', at(9))],
    }));
    expect(s.totals).toEqual({ entries: 5, done: 2, heldOrBlocked: 2, problems: 1 });
  });

  it('says which sources did not answer, so an empty list cannot read as "nothing happened"', () => {
    const s = awayEntries(input({ today: refused(), blocked: checking() }));
    expect(s.entries).toEqual([]);
    expect(s.unread).toEqual(['today', 'docket']);
    expect(awayWords(s).unread).toEqual(['The day\'s record could not be read.', 'Entries raised on the docket are unknown without the owner credential.']);
    expect(awayEntries(input()).unread).toEqual([]);
  });
});

describe('awayWords', () => {
  const s = awayEntries(input({ today: live({ items: [item('a', 7, 0, 'action', 'A')] }), causes: [cause('service.x', 'x down', at(9))] }));
  // `now` is the fixtures' T0: a window that began on another day than `now` is dated, so the
  // wall-clock default would make these lines depend on the date the suite runs.
  it('writes the window and the total line in both languages', () => {
    const en = awayWords(s, 'en', T0);
    expect(en.since).toBe('since 06:00 (this browser)');
    expect(en.totals).toEqual({ entries: '2 entries', done: '1 done', heldOrBlocked: '0 held or blocked', problems: '1 problem' });
    expect(en.empty).toBe('Nothing recorded since 06:00.');
    const ro = awayWords(s, 'ro', T0);
    expect(ro.since).toBe('din 06:00 (acest browser)');
    expect(ro.totals.entries).toBe('2 intrări');
    expect(ro.totals.problems).toBe('1 problemă');
    expect(awayWords(awayEntries(input({ since: awaySince(null, T0) })), 'en', T0).since).toBe('since 00:00 (start of today)');
  });
  it('writes Romanian plurals with "de" from 20', () => {
    const many = awayEntries(input({ today: live({ items: Array.from({ length: 20 }, (_, i) => item(`i${i}`, 7, i, 'action', 'A')) }), limit: 50 }));
    expect(awayWords(many, 'ro').totals.entries).toBe('20 de intrări');
  });
});

describe('the last visit in storage', () => {
  const fake = () => { const m = new Map<string, string>(); return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v); } }; };
  it('is written and read back under nerva.home.lastSeenAt', () => {
    const store = fake();
    expect(readLastSeen(store)).toBeNull();
    writeLastSeen(at(10, 49), store);
    expect(LAST_SEEN_KEY).toBe('nerva.home.lastSeenAt');
    expect(readLastSeen(store)).toBe(at(10, 49));
  });
  it('reads nothing from garbage, and survives storage that throws', () => {
    const store = fake();
    store.setItem(LAST_SEEN_KEY, 'soon');
    expect(readLastSeen(store)).toBeNull();
    const broken = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } };
    expect(readLastSeen(broken)).toBeNull();
    expect(() => writeLastSeen(1, broken)).not.toThrow();
  });
});
