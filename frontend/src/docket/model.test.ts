/* The docket model (PHASE_B_PLAN.md §5.4, §9.4 E4): ordering, hub groups, the identical
   collapse, phrases, special kinds that open in Decisions, optional rows only when the hub sent
   their field, titles kept as plain text; and every table of words complete in both languages. */
import { describe, expect, it } from 'vitest';
import { stringProblems } from '../frame/strings';
import { RETENTION_KIND as PANEL_RETENTION_KIND } from '../panels/retention';
import { VOICE_COMMAND_KIND as PANEL_VOICE_KIND } from '../panels/voice-commands';
import { DEMO_STRINGS, demoFeed, demoModel, demoPreview } from './demo';
import { KIND_STRINGS, amountDigits, isMoney, kindWords, runsOnlyInAuto } from './kinds';
import {
  canonicalJson, commandOf, compareEntries, docketIsEmpty, entryHolding, normaliseConsentOffer, normaliseWhy, parseDocketFeed,
  parsePreview, summaryOf, validGroups,
} from './model';
import { PHRASE_STRINGS, phraseFor, phraseWord } from './phrases';
import { editedPhrase } from './PayloadEditor';
import {
  LOOSE_SHOWN, RECORDS_KEPT, decisionIds, isRefusal, outcomeOfDecision, outcomeOfEach, placeRecords, withRecord,
  type DecisionRecord,
} from './outcomes';
import { aboutWords, outcomeWords } from './Outcome';
import { RETENTION_KIND, VOICE_COMMAND_KIND, specialKindOf } from './special';
import { DOCKET_STRINGS } from './strings';
import type { DocketTask } from './types';

const HOUR = 3_600_000;
const T0 = Date.UTC(2026, 10, 23, 8, 0);
const iso = (at: number) => new Date(at).toISOString();
const task = (id: number, more: Record<string, unknown> = {}): DocketTask =>
  ({ id, title: `Task ${id}`, kind: 'k', agent: 'jarvis', risk_tier: 1, created_at: iso(T0 + id * 60_000), ...more }) as DocketTask;
const feed = (tasks: unknown[], groups?: unknown[]) => ({ tasks, ...(groups ? { groups } : {}) });
const SNAP = 's'.repeat(32);

describe('reading the feed', () => {
  it('throws on an answer that is not the decisions feed (the poller then says malformed)', () => {
    for (const bad of [null, 'x', [], {}, { tasks: 'no' }]) expect(() => parseDocketFeed(bad)).toThrow();
  });

  it('keeps only rows with a task id, once each, and is empty with none', () => {
    const model = parseDocketFeed(feed([task(1), { id: 0 }, { id: -3 }, { id: 1.5 }, { title: 'no id' }, task(1, { title: 'dup' }), 'junk']));
    expect(model.entries.map((e) => e.taskId)).toEqual([1]);
    expect(model.entries[0].title).toBe('Task 1');
    expect(docketIsEmpty(parseDocketFeed(feed([])))).toBe(true);
    expect(parseDocketFeed(feed([])).summary).toEqual({ entries: 0, requests: 0, friction: { typed: 0, twoStep: 0, click: 0, inDecisions: 0 } });
    expect(parseDocketFeed(feed([task(1)])).elsewhere).toEqual({ payments: null, skillChanges: null });
  });
});

describe('order', () => {
  it('puts the strictest tier first, then the soonest deadline, then the oldest, then the lowest id', () => {
    const model = parseDocketFeed(feed([
      task(1, { risk_tier: 0, created_at: iso(T0 - 9 * HOUR) }),
      task(2, { risk_tier: 2, created_at: iso(T0) }),
      task(3, { risk_tier: 3, created_at: iso(T0) }),
      task(4, { risk_tier: 3, created_at: iso(T0 - HOUR) }),
      task(5, { risk_tier: 3, created_at: iso(T0), approval_deadline_at: iso(T0 + 2 * HOUR) }),
      task(6, { risk_tier: 3, created_at: iso(T0), approval_deadline_at: iso(T0 + HOUR) }),
      task(7, { risk_tier: undefined, created_at: iso(T0 + HOUR) }),
      task(8, { risk_tier: 1 }),
    ]));
    expect(model.entries.map((e) => e.taskId)).toEqual([6, 5, 4, 3, 7, 2, 8, 1]);
    expect(model.entries.find((e) => e.taskId === 7)!.tier).toBe('unknown');
    expect(compareEntries(model.entries[0], model.entries[1])).toBeLessThan(0);
  });

  it('grades friction by tier: 0 one click, 1 two steps, 2–3 and an unknown tier typed', () => {
    const model = parseDocketFeed(feed([task(1, { risk_tier: 0 }), task(2, { risk_tier: 1 }), task(3, { risk_tier: 2 }),
      task(4, { risk_tier: 3 }), task(5, { risk_tier: null }), task(6, { risk_tier: '1' }), task(7, { risk_tier: 4 })]));
    const by = Object.fromEntries(model.entries.map((e) => [e.taskId, e.friction]));
    expect(by).toEqual({ 1: 'click', 2: 'two-step', 3: 'typed', 4: 'typed', 5: 'typed', 6: 'typed', 7: 'typed' });
    expect(model.summary.friction).toEqual({ typed: 5, twoStep: 1, click: 1, inDecisions: 0 });
    expect(model.entries.find((e) => e.taskId === 2)!.phrase).toBeNull();
    expect(model.entries.find((e) => e.taskId === 3)!.phrase).toBe('sign');
  });
});

describe('hub groups', () => {
  const members = [task(41, { title: 'Same', kind: 'delete_file', risk_tier: 3 }), task(42, { title: 'Same', kind: 'delete_file', risk_tier: 3 })];
  const group = { id: 'g1', leader_id: 41, member_ids: [41, 42], count: 2, snapshot: SNAP };

  it('become one entry, signed one request (the leader) at a time, carrying the group exactly as sent', () => {
    const model = parseDocketFeed(feed([...members, task(43)], [group]));
    const entry = model.entries[0];
    expect(entry).toMatchObject({ key: 'group:g1', kind: 'group', taskId: 41, memberIds: [41, 42] });
    expect(entry.group).toEqual(group);
    expect(entry.verbs).toEqual(['sign', 'preview', 'edit', 'defer', 'reject', 'rejectGroup']);
    expect(model.summary).toMatchObject({ entries: 2, requests: 3 });
    expect(entryHolding(model, 42)?.key).toBe('group:g1');
  });

  it('are refused when the inbox would refuse them, or without a 32-character snapshot', () => {
    const tasks = new Map(members.map((t) => [t.id, t]));
    const bad = [
      { ...group, leader_id: 99 }, { ...group, count: 3 }, { ...group, member_ids: [41, 41] }, { ...group, member_ids: [41] },
      { ...group, member_ids: [41, 77] }, { ...group, snapshot: 'short' }, { ...group, snapshot: undefined }, { ...group, id: '' },
    ];
    for (const g of bad) expect(validGroups([g], tasks), JSON.stringify(g)).toEqual([]);
    expect(validGroups([group, { ...group, id: 'g2' }], tasks).map((g) => g.id)).toEqual(['g1']);   // a task joins one group
    const model = parseDocketFeed(feed(members, [{ ...group, snapshot: 'short' }]));
    expect(model.entries.map((e) => e.kind)).toEqual(['identical']);     // drawn as a collapse instead
  });
});

describe('the identical collapse', () => {
  const same = (id: number, more: Record<string, unknown> = {}) =>
    task(id, { title: 'Restart lmstudio', kind: 'restart_service', agent: 'steve', risk_tier: 3, payload: { service: 'lmstudio', n: { b: 1, a: 2 } }, ...more });

  it('folds requests with the same kind, title, agent, tier, deadline and payload, the oldest leading', () => {
    const model = parseDocketFeed(feed([same(12, { created_at: iso(T0 + HOUR) }), same(10, { created_at: iso(T0) }),
      same(11, { payload: { n: { a: 2, b: 1 }, service: 'lmstudio' }, created_at: iso(T0 + 2 * HOUR) })]));
    expect(model.entries).toHaveLength(1);
    expect(model.entries[0]).toMatchObject({ key: 'same:10', kind: 'identical', taskId: 10, memberIds: [10, 12, 11], group: null });
    expect(model.entries[0].verbs).toContain('rejectAllIdentical');
    expect(model.entries[0].memberTargets).toEqual(['lmstudio', 'lmstudio', 'lmstudio']);
    expect(canonicalJson({ b: 1, a: [{ d: 1, c: 2 }] })).toBe('{"a":[{"c":2,"d":1}],"b":1}');
  });

  it('keeps apart what differs, and never folds a special kind', () => {
    const model = parseDocketFeed(feed([same(1), same(2, { payload: { service: 'qdrant' } }), same(3, { agent: 'jarvis' }),
      same(4, { risk_tier: 2 }), same(5, { approval_deadline_at: iso(T0 + HOUR) }), same(6, { title: 'Other' }),
      task(7, { kind: RETENTION_KIND, title: 'Same', created_at: iso(T0) }), task(8, { kind: RETENTION_KIND, title: 'Same', created_at: iso(T0) })]));
    expect(model.entries.every((e) => e.kind === 'single')).toBe(true);
    expect(model.entries).toHaveLength(8);
  });
});

describe('special kinds open in Decisions', () => {
  const offer = { revision: 'a'.repeat(64), count: 2, choices: ['session', 'always', 'deny'], categories: [{ description: 'reviewed', permanent: false }] };
  const image = { kind: 'plugin.egress', payload: { plugin: 'cloud-image', method: 'POST', url: 'https://api.openai.com/v1/images/generations', image: { body: { prompt: 'p', model: 'm' } } } };

  it.each([
    ['image', image],
    ['image', { kind: 'toolrpc.image_generate', payload: { tool: 'image_generate', args: { prompt: 'p' } } }],
    ['image', { kind: 'plugin.egress', payload: { plugin: 'cloud-image-krea', method: 'POST', url: 'https://evil.invalid/x', image: { body: {} } } }],
    ['consent', { kind: 'toolrpc.terminal_run', consent_offer: offer }],
    ['retention', { kind: RETENTION_KIND }],
    ['voice', { kind: VOICE_COMMAND_KIND }],
    ['guardian', { kind: 'toolrpc.terminal_run', judge: { advisory: false, decision: 'deny' } }],
  ])('%s', (special, fields) => {
    const entry = parseDocketFeed(feed([task(9, fields)])).entries[0];
    expect(entry).toMatchObject({ special: true, specialKind: special, verbs: ['openInDecisions'] });
  });

  it('only those: an advisory opinion, a malformed offer, an ordinary tool call stay signable here', () => {
    for (const fields of [{ judge: { advisory: true, score: 80 } }, { consent_offer: { ...offer, revision: 'stale' } },
      { kind: 'tool.rpc', payload: { tool: 'other', target: 'other' } }]) {
      expect(parseDocketFeed(feed([task(9, fields)])).entries[0].special, JSON.stringify(fields)).toBe(false);
    }
    expect(specialKindOf(task(1), false)).toBeNull();
  });

  it('mirror the panels\' kind names', () => {
    expect(RETENTION_KIND).toBe(PANEL_RETENTION_KIND);
    expect(VOICE_COMMAND_KIND).toBe(PANEL_VOICE_KIND);
  });

  it('are counted apart from the signing mix: they are not signed here', () => {
    const model = parseDocketFeed(feed([task(1, { kind: RETENTION_KIND, risk_tier: 3 }), task(2, { risk_tier: 0 }),
      task(3, { kind: 'toolrpc.terminal_run', risk_tier: 1, judge: { advisory: false, decision: 'deny' } })]));
    expect(model.summary).toEqual({ entries: 3, requests: 3, friction: { typed: 0, twoStep: 0, click: 1, inDecisions: 2 } });
  });
});

describe('optional rows exist only when the hub sent their field', () => {
  it('leaves every optional key out of a bare request', () => {
    const entry = parseDocketFeed(feed([{ id: 3 }])).entries[0];
    for (const key of ['why', 'delegatedBy', 'pushed', 'rollback', 'tainted', 'opinion', 'consentOffer', 'memberTargets']) {
      expect(entry, key).not.toHaveProperty(key);
    }
    expect(entry).toMatchObject({ title: '', nativeKind: null, agent: null, createdAt: null, deadlineAt: null, tier: 'unknown', friction: 'typed' });
  });

  it('reads each one fail-closed', () => {
    const entry = parseDocketFeed(feed([task(4, {
      approval_mode: { effective: 'auto', source: 'global' }, asked_under: { mode: 'ask', source: 'agent', by_mode: true },
      delegated_by: { spawn_id: 'sp-1', parent: 'pepper', label: 'English goal text' }, pushed: 0,
      rollback: { description: 'Move it back.', limitations: '' }, payload: { untrusted_source: 'web page' },
      judge: { advisory: true, score: 72, flags: ['x'], judge: { provider: 'ollama', model: 'qwen3', local: true } },
      approval_deadline_at: iso(T0 + HOUR),
    })])).entries[0];
    expect(entry.why).toEqual({ modeNow: 'auto', modeNowSource: 'global', askedUnder: { mode: 'ask', source: 'agent', byMode: true } });
    expect(entry.delegatedBy).toEqual({ parent: 'pepper', spawnId: 'sp-1' });
    expect(entry.pushed).toBe(false);
    expect(entry.rollback).toEqual({ description: 'Move it back.', limitations: null });
    expect(entry.tainted).toBe(true);
    expect(entry.opinion).toMatchObject({ score: 72, provider: 'ollama', model: 'qwen3', local: true, advisory: true, flagged: true, truncated: false });
    expect(entry.deadlineAt).toBe(T0 + HOUR);
  });

  it('says nothing about a mode it cannot read, and nothing for rows sent empty', () => {
    expect(normaliseWhy({ effective: 'yolo' }, { mode: 'ASK' })).toBeNull();
    expect(normaliseWhy(null, { mode: 'off', by_mode: true })).toEqual({ modeNow: null, modeNowSource: null, askedUnder: { mode: 'off', source: 'global', byMode: true } });
    const entry = parseDocketFeed(feed([task(5, { approval_mode: 'ask', delegated_by: { parent: ' ' }, rollback: { description: '' },
      payload: { injection_flags: [] }, judge: 'nope', pushed: 'yes' })])).entries[0];
    for (const key of ['why', 'delegatedBy', 'rollback', 'tainted', 'opinion', 'pushed']) expect(entry, key).not.toHaveProperty(key);
    expect(normaliseConsentOffer({ revision: 'a'.repeat(64), count: 0, choices: ['session', 'always', 'deny'], categories: [] })).toBeNull();
  });

  it('marks a guardian verdict apart from an advisory opinion', () => {
    const entry = parseDocketFeed(feed([task(6, { kind: 'toolrpc.terminal_run', judge: { advisory: false, decision: 'escalate' } })])).entries[0];
    expect(entry.opinion).toMatchObject({ advisory: false, verdict: 'escalate' });
  });
});

describe('titles are the hub\'s plain text', () => {
  it('kept verbatim: markup and Markdown are characters, not structure', () => {
    const title = '<img src=x onerror=alert(1)> **bold** [link](javascript:x) ‮evil';
    expect(parseDocketFeed(feed([task(1, { title })])).entries[0].title).toBe(title);
    expect(parseDocketFeed(feed([task(2, { title: 42 })])).entries[0].title).toBe('');
  });
});

describe('phrases (a fixed map)', () => {
  const typed = (fields: Record<string, unknown>) => {
    const entry = parseDocketFeed(feed([task(1, { risk_tier: 3, ...fields })])).entries[0];
    return entry.phrase;
  };
  it.each([
    [{ kind: 'restart_service' }, 'restart'],
    [{ kind: 'delete_file' }, 'delete'],
    [{ kind: 'toolrpc.file_delete' }, 'delete'],
    [{ kind: 'payment', payload: { amount: 4200 } }, '4200'],
    [{ kind: 'transfer', payload: { amount: '12.50' } }, '12.50'],
    [{ kind: 'payment' }, 'sign'],
    [{ kind: 'k', payload: { amount: 99 } }, '99'],
    [{ kind: 'comms.send' }, 'send'],
    [{ kind: 'social.post' }, 'send'],
    [{ kind: 'chat.message' }, 'send'],
    [{ kind: 'channel.reply' }, 'sign'],          // only send, post and message kinds (§5.4)
    [{ kind: 'draft_email' }, 'sign'],            // a draft sends nothing
    [{ kind: 'draft_message' }, 'sign'],
    [{ kind: 'mail.dm' }, 'sign'],
    [{ kind: 'release.deploy' }, 'deploy'],
    [{ kind: 'travel.book' }, 'book'],
    [{ kind: 'design.review' }, 'sign'],
    [{ kind: 'postpone' }, 'sign'],
  ])('%j → %s', (fields, phrase) => {
    expect(typed(fields)).toBe(phrase);
  });

  it('only for typed friction, the same words in both languages, and the edited amount for an edit', () => {
    const t = task(1, { kind: 'payment', risk_tier: 3, payload: { amount: 200 } });
    expect(phraseFor(t, 'money', 'two-step')).toBeNull();
    expect(phraseFor(t, 'money', 'typed', 'ro', { amount: 50 })).toBe('50');
    expect(PHRASE_STRINGS.ro).toEqual(PHRASE_STRINGS.en);
    expect(phraseWord(undefined)).toBe('sign');
    expect(amountDigits(-3)).toBeNull();
    expect(amountDigits('1e9')).toBeNull();
  });

  it('types an amount only as digits: a number JavaScript writes with an exponent is no phrase', () => {
    expect(amountDigits(4200)).toBe('4200');
    expect(amountDigits(12.5)).toBe('12.5');
    expect(amountDigits(' 99 ')).toBe('99');
    expect(amountDigits(1e21)).toBeNull();
    expect(amountDigits(1e-7)).toBeNull();
    expect(phraseFor(task(1, { kind: 'payment', risk_tier: 3 }), 'money', 'typed', 'en', { amount: 1e21 })).toBe('sign');
  });

  it('an edit is signed with what the edited request is: an amount added to a tier-3 request is typed', () => {
    const plain = task(1, { kind: 'k', risk_tier: 3, payload: { a: 1 } });
    expect(editedPhrase(plain, 3, 'typed', 'en', { a: 1 })).toBe('sign');
    expect(editedPhrase(plain, 3, 'typed', 'en', { a: 1, amount: 75 })).toBe('75');
    expect(editedPhrase(plain, 3, 'typed', 'en', null)).toBe('sign');                  // not JSON yet: the request as it is
    const pay = task(2, { kind: 'payment', risk_tier: 3, payload: { amount: 200 } });
    expect(editedPhrase(pay, 'money', 'typed', 'en', { amount: 50 })).toBe('50');
    expect(editedPhrase(pay, 'money', 'typed', 'en', {})).toBe('sign');                // still money by kind, no amount to type
    expect(editedPhrase(task(3, { kind: 'k', risk_tier: 1 }), 1, 'two-step', 'en', { amount: 5 })).toBeNull();
  });
});

describe('what decisions came to (the register keeps them by request)', () => {
  const rec = (seq: number, ids: number[], outcome: DecisionRecord['outcome'] = { kind: 'done', verb: 'sign', n: 1 }): DecisionRecord =>
    ({ seq, verb: 'sign', taskId: ids[0], ids, title: `Task ${ids[0]}`, outcome });
  const refused = { kind: 'refused', status: 409, reason: 'approval expired' } as const;

  it('are about the leader, or every member for Reject group and Reject all N', () => {
    const entry = { taskId: 21, memberIds: [21, 22, 23] };
    expect(decisionIds(entry, 'sign')).toEqual([21]);
    expect(decisionIds(entry, 'reject')).toEqual([21]);
    expect(decisionIds(entry, 'rejectGroup')).toEqual([21, 22, 23]);
    expect(decisionIds(entry, 'rejectAll')).toEqual([21, 22, 23]);
  });

  it('are facts from the client\'s answers: done, refused (the hub\'s words), partial, demo', () => {
    expect(outcomeOfDecision({ ok: true, status: null, reason: null }, 'defer')).toEqual({ kind: 'done', verb: 'defer', n: 1 });
    expect(outcomeOfDecision({ ok: false, status: 409, reason: 'approval group changed' }, 'rejectGroup', 3))
      .toEqual({ kind: 'refused', status: 409, reason: 'approval group changed' });
    expect(outcomeOfDecision({ ok: false, status: null, reason: null, demo: true }, 'sign')).toMatchObject({ kind: 'refused', demo: true });
    expect(outcomeOfEach({ rejected: [1, 2], refused: [] }, 2)).toEqual({ kind: 'done', verb: 'rejectAll', n: 2 });
    expect(outcomeOfEach({ rejected: [1], refused: [{ id: 2, status: 409, reason: 'task is not waiting' }, { id: 3, status: null, reason: null }] }, 3))
      .toEqual({ kind: 'partial', done: 1, total: 3, failed: 2, status: 409, reason: 'task is not waiting' });
    expect(outcomeOfEach({ rejected: [], refused: [], demo: true }, 2)).toMatchObject({ kind: 'refused', demo: true });
    expect(isRefusal({ kind: 'done', verb: 'sign', n: 1 })).toBe(false);
    expect(isRefusal({ kind: 'notSent' })).toBe(true);
  });

  it('are worded when drawn, in either language, the hub\'s own words kept', () => {
    expect(outcomeWords({ kind: 'done', verb: 'sign', n: 1 }, 'en')).toBe('Signed.');
    expect(outcomeWords({ kind: 'done', verb: 'rejectAll', n: 3 }, 'en')).toBe('Rejected all 3.');
    expect(outcomeWords(refused, 'ro')).toBe('Refuzată — approval expired');
    expect(outcomeWords({ kind: 'refused', status: null, reason: null }, 'en')).toBe('Refused — the hub did not answer');
    expect(outcomeWords({ kind: 'partial', done: 12, total: 14, failed: 2, status: 409, reason: 'task is not waiting' }, 'en'))
      .toBe('Rejected 12 of 14; 2 refused: task is not waiting');
    expect(aboutWords(rec(1, [27]), 'en')).toBe('Task 27 · request 27');
    expect(aboutWords({ ...rec(1, [21, 22, 23]), title: '' }, 'ro')).toBe('(fără titlu) · 3 cereri');
  });

  it('keep the last outcome of each request', () => {
    const all = withRecord(new Map(), rec(1, [21, 22, 23], refused));
    const next = withRecord(all, rec(2, [22]));
    expect([...next.entries()].map(([id, r]) => [id, r.seq])).toEqual([[21, 1], [22, 2], [23, 1]]);
    let many = new Map<number, DecisionRecord>();
    for (let i = 1; i <= RECORDS_KEPT + 5; i += 1) many = withRecord(many, rec(i, [i]));
    expect(many.size).toBe(RECORDS_KEPT);
    expect(many.has(1)).toBe(false);
    expect(many.has(RECORDS_KEPT + 5)).toBe(true);
  });

  it('are drawn in the entry that still holds a request, else in the register — never twice, never lost', () => {
    const records = withRecord(withRecord(withRecord(new Map(), rec(1, [27], refused)), rec(2, [21, 22, 23], refused)), rec(3, [5]));
    // 27 and 5 left the docket; of the collapse only 22 is left, as a single entry
    const placed = placeRecords([{ memberIds: [30] }, { memberIds: [22] }], records);
    expect(placed.inEntry.map((r) => r?.seq ?? null)).toEqual([null, 2]);
    expect(placed.loose.map((r) => r.seq)).toEqual([3, 1]);                             // newest first
    // a record that lost its entry's place to a newer one is not drawn in the register as well
    const newer = withRecord(records, rec(4, [22]));
    const again = placeRecords([{ memberIds: [21, 22] }], newer);
    expect(again.inEntry.map((r) => r?.seq ?? null)).toEqual([4]);
    expect(again.loose.map((r) => r.seq)).toEqual([3, 1]);
    // at most LOOSE_SHOWN in the register
    let many = new Map<number, DecisionRecord>();
    for (let i = 1; i <= LOOSE_SHOWN + 2; i += 1) many = withRecord(many, rec(i, [100 + i]));
    expect(placeRecords([], many).loose.map((r) => r.seq)).toEqual([LOOSE_SHOWN + 2, LOOSE_SHOWN + 1, LOOSE_SHOWN]);
  });
});

describe('money and kinds', () => {
  it('money is tier 3 with an amount or a money kind', () => {
    expect(isMoney(task(1, { risk_tier: 3, kind: 'payment' }))).toBe(true);
    expect(isMoney(task(1, { risk_tier: 3, kind: 'x', payload: { amount: 5 } }))).toBe(true);
    expect(isMoney(task(1, { risk_tier: 2, kind: 'payment' }))).toBe(false);
    expect(isMoney(task(1, { risk_tier: 3, kind: 'delete_file' }))).toBe(false);
    expect(parseDocketFeed(feed([task(1, { risk_tier: 3, kind: 'payment' })])).entries[0].tier).toBe('money');
  });

  it('words kinds only through the fixed table; an unknown kind is said as itself', () => {
    expect(kindWords('restart_service', 'en')).toBe('Restarts a local service.');
    expect(kindWords('restart_service', 'ro')).toBe('Repornește un serviciu local.');
    expect(kindWords('calendar.sync', 'en')).toBe('Runs a request of kind calendar.sync.');
    expect(kindWords(null, 'ro')).toBe('Rulează o cerere fără tip declarat.');
  });

  it('knows the kinds whose approval runs only in Auto (mode.py RECEIPT_NOTE)', () => {
    for (const kind of ['toolrpc.terminal_run', 'terminal.exec', 'toolrpc.browser_run', 'browser.step', 'checkpoint.restore', 'provider.selection']) {
      expect(runsOnlyInAuto(kind), kind).toBe(true);
    }
    for (const kind of ['restart_service', 'toolrpc.file_write', 'payment', null]) expect(runsOnlyInAuto(kind), String(kind)).toBe(false);
  });
});

describe('the preview', () => {
  it('keeps target, effects (cmd after B1), would_execute and a pending question — not its own reversibility', () => {
    const preview = parsePreview({ summary: "Would run 'x'; IRREVERSIBLE", irreversible: true, target: 'lmstudio', would_execute: false,
      effects: [{ field: 'cmd', value: 'lms server restart' }, { field: 'amount', value: 200 }, { nope: 1 }],
      prompt: { available: true, text: 'Which one?', choices: ['A', 7, 'B'] } });
    expect(preview).toEqual({ target: 'lmstudio', wouldExecute: false,
      effects: [{ field: 'cmd', value: 'lms server restart' }, { field: 'amount', value: '200' }],
      prompt: { available: true, text: 'Which one?', choices: ['A', 'B'] } });
    expect(commandOf(preview)).toBe('lms server restart');
    expect(commandOf(parsePreview({ effects: [{ field: 'command', value: 'ls' }] }))).toBe('ls');
    expect(parsePreview('x')).toBeNull();
    expect(parsePreview({ prompt: { available: false } })!.prompt).toEqual({ available: false });
  });
});

describe('the demo sample', () => {
  it('is the hub\'s own shape, through the same model: six entries, a hub group, a collapse, money, typed and two-step', () => {
    const model = demoModel('en', T0);
    expect(model.entries).toHaveLength(6);
    expect(model.entries.map((e) => e.kind)).toEqual(['group', 'identical', 'single', 'single', 'single', 'single']);
    expect(model.entries.map((e) => e.friction)).toEqual(['typed', 'typed', 'typed', 'typed', 'two-step', 'two-step']);
    expect(model.entries.find((e) => e.tier === 'money')?.phrase).toBe('4200');
    expect(model.summary).toEqual({ entries: 6, requests: 9, friction: { typed: 4, twoStep: 2, click: 0, inDecisions: 0 } });
    expect(model.elsewhere).toEqual({ payments: 1, skillChanges: 3 });
    expect(demoModel('ro', T0).entries[0].title).toBe(DEMO_STRINGS.ro.restart);
    expect(commandOf(demoPreview(402))).toBe('lms server restart');
    expect((demoFeed('en', T0).groups[0] as { snapshot: string }).snapshot).toHaveLength(32);
  });
});

describe('the docket\'s words', () => {
  it('are complete in English and Romanian', () => {
    expect(stringProblems(DOCKET_STRINGS)).toEqual([]);
    expect(stringProblems(KIND_STRINGS)).toEqual([]);
    expect(stringProblems(PHRASE_STRINGS)).toEqual([]);
    expect(stringProblems(DEMO_STRINGS)).toEqual([]);
  });

  it('never call unknown "0" or "nothing waits", and never "Dismiss"', () => {
    const all = [...Object.values(DOCKET_STRINGS.en), ...Object.values(DOCKET_STRINGS.ro)]
      .flatMap((v) => (typeof v === 'string' ? [v] : [v.one, v.few, v.other]));
    expect(all.filter((t) => /dismiss|all clear|^0 /i.test(t))).toEqual([]);
    expect(DOCKET_STRINGS.en.refused).toMatch(/^Unknown — /);
    expect(summaryOf([])).toEqual({ entries: 0, requests: 0, friction: { typed: 0, twoStep: 0, click: 0, inDecisions: 0 } });
  });
});
