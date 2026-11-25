/* While you were away (PHASE_B_PLAN.md §5.2): what the hub did since this browser last looked.

   Three sources, merged oldest first:
     - the day's feed (`/api/dashboard/today`): completed actions are "done", follow-ups are
       listed as other; learned facts are not listed (they are not something that happened to the
       owner's work, and the count would then claim more than the list shows);
     - docket entries raised since: awaiting the owner's signature, an exception;
     - problems that are current and began inside the window (the verdict's causes): a cause
       whose start the hub did not report is listed at the time it was checked, marked as such
       (`atKind: 'checked'`), never as an event time.
   "Since" is this browser's last visit (localStorage `nerva.home.lastSeenAt`, written when the
   page is hidden), else the start of today, and never earlier than the feed's 24-hour window.
   Titles are the hub's plain text. Exceptions (held, blocked, raised, problems) are drawn in
   semibold. Pure; words in one language. */
import { defineStrings, fmt, plural, pick, type Lang } from '../frame/strings';
import { clockTime } from '../frame/kit/strings';
import { sinceStamp } from './trust-signals';
import { isCurrent } from './types';
import type { AwayEntry, Cause, Reading } from './types';
import type { TaskLite, TodayFeed } from './wire';

export const AWAY_STRINGS = defineStrings({
  en: {
    sinceVisit: 'since {time} (this browser)',
    sinceStartOfDay: 'since {time} (start of today)',
    sinceLast24h: 'since {time} (the record keeps 24 hours)',
    entries: { one: '{n} entry', few: '{n} entries', other: '{n} entries' },
    done: '{n} done',
    heldOrBlocked: '{n} held or blocked',
    problems: { one: '{n} problem', few: '{n} problems', other: '{n} problems' },
    empty: 'Nothing recorded since {time}.',
    checkedAt: 'checked {time}',
    unreadToday: 'The day\'s record could not be read.',
    unreadDocket: 'Entries raised on the docket are unknown without the owner credential.',
    unreadProblems: 'Problems that began meanwhile are unknown: the service probes could not be read.',
    unreadCount: { one: '{n} source not read', few: '{n} sources not read', other: '{n} sources not read' },
    emptyPartial: 'Nothing recorded since {time} in the sources that answered.',
    docketEntry: 'Docket entry {n}',
    doneUnknown: 'done: unknown',
    heldOrBlockedUnknown: 'held or blocked: unknown',
    problemsUnknown: 'problems: unknown',
  },
  ro: {
    sinceVisit: 'din {time} (acest browser)',
    sinceStartOfDay: 'din {time} (începutul zilei)',
    sinceLast24h: 'din {time} (registrul păstrează 24 de ore)',
    entries: { one: '{n} intrare', few: '{n} intrări', other: '{n} de intrări' },
    done: '{n} terminate',
    heldOrBlocked: '{n} reținute sau blocate',
    problems: { one: '{n} problemă', few: '{n} probleme', other: '{n} de probleme' },
    empty: 'Nimic înregistrat din {time}.',
    checkedAt: 'verificat la {time}',
    unreadToday: 'Registrul zilei nu a putut fi citit.',
    unreadDocket: 'Intrările ridicate în registrul de semnături sunt necunoscute fără credențialul proprietarului.',
    unreadProblems: 'Problemele apărute între timp sunt necunoscute: sondele de servicii nu au putut fi citite.',
    unreadCount: { one: '{n} sursă necitită', few: '{n} surse necitite', other: '{n} de surse necitite' },
    emptyPartial: 'Nimic înregistrat din {time} în sursele care au răspuns.',
    docketEntry: 'Intrarea {n} din registrul de semnături',
    doneUnknown: 'terminate: necunoscut',
    heldOrBlockedUnknown: 'reținute sau blocate: necunoscut',
    problemsUnknown: 'probleme: necunoscut',
  },
});

export const LAST_SEEN_KEY = 'nerva.home.lastSeenAt';
const DAY_MS = 24 * 60 * 60 * 1000;

export interface AwaySince {
  /** Epoch ms: the window starts here. */
  readonly at: number;
  readonly basis: 'lastVisit' | 'startOfDay' | 'last24h';
}

/** The window's start: the last visit if one is stored (and not in the future), else the start of
 *  today; never earlier than the feed's 24 hours. */
export function awaySince(stored: number | null, now: number): AwaySince {
  const d = new Date(now);
  d.setHours(0, 0, 0, 0);
  if (typeof stored === 'number' && Number.isFinite(stored) && stored > 0 && stored <= now) {
    return stored < now - DAY_MS ? { at: now - DAY_MS, basis: 'last24h' } : { at: stored, basis: 'lastVisit' };
  }
  return { at: Math.max(d.getTime(), now - DAY_MS), basis: 'startOfDay' };
}

export interface AwayInput {
  readonly today: Reading<TodayFeed> | null;
  /** The docket's blocked tasks (entries raised since). */
  readonly blocked: Reading<readonly TaskLite[]> | null;
  /** The verdict's current causes. */
  readonly causes: readonly Cause[];
  /** When the causes were read (the verdict's `checkedAt`). */
  readonly checkedAt: number | null;
  readonly since: AwaySince;
  readonly now: number;
  /** A ready href for a docket entry (docket/links.ts docketHref). */
  readonly docketHref?: (taskId: number) => string;
  /** Where the day's record lives. */
  readonly recordHref?: string;
  /** At most this many entries are kept (the newest). */
  readonly limit?: number;
  /** False when the service probes (the observer) could not be read, so the list says nothing
   *  about problems that began meanwhile. Default true. */
  readonly problemsRead?: boolean;
}

export interface AwayTotals {
  readonly entries: number;
  readonly done: number;
  readonly heldOrBlocked: number;
  readonly problems: number;
}

export interface AwaySummary {
  readonly since: AwaySince;
  /** Oldest first. */
  readonly entries: readonly AwayEntry[];
  readonly totals: AwayTotals;
  /** Sources that did not answer, so the list cannot be read as complete. */
  readonly unread: readonly ('today' | 'docket' | 'problems')[];
  /** Whether each tally was counted from a source that answered: an unread source's tally is
   *  Unknown, never 0. Done comes from the day's record; held, blocked and raised from the docket
   *  and the day's follow-ups; problems from the probes. */
  readonly known: { readonly done: boolean; readonly heldOrBlocked: boolean; readonly problems: boolean };
}

const nameOf = (key: string): string => key.replace(/^service\./, '');

export function awayEntries(input: AwayInput): AwaySummary {
  const { since, now } = input;
  const out: AwayEntry[] = [];

  // The docket first: a `blocked_task` follow-up in the day's feed is the same task as its
  // docket entry, and is listed once, as the docket entry.
  const listedOnDocket = new Set<number>();
  (input.blocked?.value ?? []).forEach((t) => {
    if (t.createdAt === null || t.createdAt < since.at) return;
    listedOnDocket.add(t.id);
    out.push({
      id: `docket:${t.id}`, at: t.createdAt, mark: 'seal-open', kind: 'raised', nativeKind: t.kind, title: t.title,
      agent: t.agent, exception: true, href: input.docketHref ? input.docketHref(t.id) : null, source: 'docket',
    });
  });

  (input.today?.value?.items ?? []).forEach((it) => {
    if (it.at === null || it.at < since.at || it.at > now + 60_000) return;
    if (it.kind === 'action') {
      out.push({ id: it.id, at: it.at, mark: 'done', kind: 'done', nativeKind: 'action', title: it.title, agent: it.agent, exception: false, href: input.recordHref ?? null, source: 'dashboard-today' });
    } else if (it.kind === 'followup') {
      const href = input.recordHref ?? null;
      if (it.reason === 'blocked_task' && it.taskId != null && listedOnDocket.has(it.taskId)) return;
      if (it.reason === 'failed_task') {
        out.push({ id: it.id, at: it.at, mark: 'problem', kind: 'problem', nativeKind: it.reason, title: it.title, agent: it.agent, exception: true, href, source: 'dashboard-today' });
      } else if (it.reason === 'blocked_task') {
        out.push({ id: it.id, at: it.at, mark: 'blocked', kind: 'blocked', nativeKind: it.reason, title: it.title, agent: it.agent, exception: true, href, source: 'dashboard-today' });
      } else {
        out.push({ id: it.id, at: it.at, mark: 'attn', kind: 'other', nativeKind: it.reason ?? 'followup', title: it.title, agent: it.agent, exception: false, href, source: 'dashboard-today' });
      }
    }
  });

  input.causes.forEach((c) => {
    const known = typeof c.since === 'number';
    if (known && (c.since as number) < since.at) return;
    const name = nameOf(c.key);
    const at = known ? (c.since as number) : input.checkedAt;
    if (at === null) return;
    out.push({
      id: `problem:${c.key}`, at, mark: 'problem', kind: 'problem', nativeKind: c.key,
      title: c.detail.toLowerCase().includes(name.toLowerCase()) ? c.detail : `${name}: ${c.detail}`,
      agent: null, exception: true, href: null, source: 'problem', atKind: known ? 'event' : 'checked',
    });
  });

  out.sort((a, b) => a.at - b.at);
  const limit = input.limit ?? 50;
  const entries = out.length > limit ? out.slice(out.length - limit) : out;
  const unread: ('today' | 'docket' | 'problems')[] = [];
  if (input.today && !isCurrent(input.today)) unread.push('today');
  if (input.blocked && !isCurrent(input.blocked)) unread.push('docket');
  if (input.problemsRead === false) unread.push('problems');
  const count = (kind: AwayEntry['kind']) => entries.filter((e) => e.kind === kind).length;
  return {
    since, entries, unread,
    known: {
      done: !unread.includes('today'),
      heldOrBlocked: !unread.includes('docket') && !unread.includes('today'),
      problems: !unread.includes('problems') && !unread.includes('today'),
    },
    totals: { entries: entries.length, done: count('done'), heldOrBlocked: count('held') + count('blocked') + count('raised'), problems: count('problem') },
  };
}

export interface AwayWords {
  /** "since 06:00 (this browser)". */
  readonly since: string;
  /** The total line, in parts: "7 entries" · "4 done" · "2 held or blocked" · "1 problem". */
  readonly totals: { readonly entries: string; readonly done: string; readonly heldOrBlocked: string; readonly problems: string };
  /** "Nothing recorded since 06:00." */
  readonly empty: string;
  /** "checked 10:50", for a problem whose start the hub did not report. */
  readonly checked: (at: number) => string;
  readonly unread: readonly string[];
  /** "Nothing recorded since 06:00 in the sources that answered." */
  readonly emptyPartial: string;
  /** "1 source not read"; null when every source answered. */
  readonly unreadCount: string | null;
  /** "Docket entry 12": the title of a docket entry the hub sent without one. */
  readonly docketEntry: (id: string) => string;
}

export function awayWords(summary: AwaySummary, langIn: Lang | string = 'en', now: number = Date.now()): AwayWords {
  const lang: Lang = langIn === 'ro' ? 'ro' : 'en';
  const s = pick(AWAY_STRINGS, lang);
  const time = sinceStamp(summary.since.at, now, lang);
  const t = summary.totals;
  const sinceKey = summary.since.basis === 'lastVisit' ? s.sinceVisit : summary.since.basis === 'last24h' ? s.sinceLast24h : s.sinceStartOfDay;
  return {
    since: fmt(sinceKey, { time }),
    emptyPartial: fmt(s.emptyPartial, { time }),
    unreadCount: summary.unread.length ? plural(lang, s.unreadCount, summary.unread.length) : null,
    docketEntry: (id: string) => fmt(s.docketEntry, { n: id.replace(/^docket:/, '') }),
    totals: {
      entries: plural(lang, s.entries, t.entries),
      done: summary.known.done ? fmt(s.done, { n: t.done }) : s.doneUnknown,
      heldOrBlocked: summary.known.heldOrBlocked ? fmt(s.heldOrBlocked, { n: t.heldOrBlocked }) : s.heldOrBlockedUnknown,
      problems: summary.known.problems ? plural(lang, s.problems, t.problems) : s.problemsUnknown,
    },
    empty: fmt(s.empty, { time }),
    checked: (at: number) => fmt(s.checkedAt, { time: clockTime(at) }),
    unread: summary.unread.map((u) => (u === 'today' ? s.unreadToday : u === 'docket' ? s.unreadDocket : s.unreadProblems)),
  };
}

/** The stored last visit (epoch ms), or null when absent, unreadable or storage is unavailable. */
export function readLastSeen(storage: Pick<Storage, 'getItem'> | null = safeStorage()): number | null {
  try {
    const raw = storage?.getItem(LAST_SEEN_KEY);
    const n = raw ? Number(raw) : NaN;
    return Number.isFinite(n) && n > 0 ? n : null;
  } catch { return null; }
}

export function writeLastSeen(at: number, storage: Pick<Storage, 'setItem'> | null = safeStorage()): void {
  try { storage?.setItem(LAST_SEEN_KEY, String(Math.round(at))); } catch { /* storage unavailable: the window falls back to the start of today */ }
}

function safeStorage(): Storage | null {
  try { return typeof window !== 'undefined' ? window.localStorage : null; } catch { return null; }
}
