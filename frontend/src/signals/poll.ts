/* The shared poller (PHASE_B_PLAN.md §2.2, §5.6).

   usePolled(path, {admin, intervalMs, enabled}) returns a Reading of one hub GET:

     - requests are shared by path (and the admin flag): any number of components asking for
       the same path cause one request per interval, at the shortest interval any of them asked;
     - polling pauses while the document is hidden and catches up when it is shown again;
     - refused (401/403) is told apart from offline (no answer), from a switched-off feature
       (503), from an answer that could not be read (a 2xx whose body is not JSON) and from any
       other error, and a reading turns stale 2.5 intervals after its last good answer, so a
       stalled source can never pass for a live one;
     - demo and disabled never touch the network.

   The latest raw answer is shared; each caller parses it with its own `parse` (keep that
   function stable, at module level) and decides what `empty` means with `isEmpty`.
   `refresh()` (or refreshPolled(path) from outside React, e.g. after a decision) asks again
   now and resolves when that answer has landed; a refresh during a request asks once more when
   that request ends and resolves only when the second answer has landed, so an answer never
   predates the action that asked for it. resetPolling() is for tests. */
import { useCallback, useMemo, useSyncExternalStore } from 'react';
import { apiGet } from '../api/client';
import { STALE_FACTOR, isStale, type Reading, type ReadingReason } from './types';

export const DEFAULT_INTERVAL_MS = 30_000;
/** No caller may poll faster than this. */
export const MIN_INTERVAL_MS = 1_000;

export interface PollOptions<T> {
  /** Send the admin credential (the route is admin-guarded). */
  admin?: boolean;
  /** How often to ask; default 30 s. */
  intervalMs?: number;
  /** False: no request at all, the reading is 'disabled' (a page that does not show it). */
  enabled?: boolean;
  /** Demo mode: no request; the reading is 'demo' with `demoValue` (or null). */
  demo?: boolean;
  demoValue?: T;
  /** Shape and validate the raw answer; throw to mark it malformed. Keep it stable. */
  parse?: (raw: unknown) => T;
  /** When a current answer counts as empty ("nothing is waiting"). Keep it stable. */
  isEmpty?: (value: T) => boolean;
  /** Also ask again when the window regains focus (the docket does). */
  refreshOnFocus?: boolean;
}

/** A reading plus the way to ask again now. */
export type Polled<T> = Reading<T> & { readonly refresh: () => Promise<void> };

/** What the last attempt ended with. 'malformed': a 2xx whose body could not be read as JSON. */
export type PollOutcome = 'none' | 'ok' | 'refused' | 'offline' | 'unavailable' | 'http' | 'malformed';

/** The shared state of one path: the newest 2xx answer and how the latest attempt ended. */
export interface PollSnapshot {
  readonly outcome: PollOutcome;
  readonly hasRaw: boolean;
  readonly raw: unknown;
  readonly status: number | null;
  readonly checkedAt: number | null;
  readonly lastGoodAt: number | null;
  /** Bumped by the staleness timer and by the page becoming visible, to re-render on time. */
  readonly tick: number;
}

export const EMPTY_SNAPSHOT: PollSnapshot = Object.freeze({
  outcome: 'none', hasRaw: false, raw: undefined, status: null, checkedAt: null, lastGoodAt: null, tick: 0,
}) as PollSnapshot;

type Sub = { intervalMs: number; onFocus: boolean; listener: () => void };
/** A request asked for while another was in flight: it goes out when that one ends, and
 *  `done` resolves when its answer has landed. */
type Again = { done: Promise<void>; resolve: () => void };
type Entry = {
  key: string;
  path: string;
  admin: boolean;
  subs: Map<number, Sub>;
  snap: PollSnapshot;
  inflight: Promise<void> | null;
  again: Again | null;
  pollTimer: ReturnType<typeof setTimeout> | null;
  staleTimer: ReturnType<typeof setTimeout> | null;
};

const entries = new Map<string, Entry>();
let nextSub = 1;
let epoch = 0;
let listening = false;

const keyOf = (path: string, admin: boolean) => `${admin ? 'admin' : 'user'} ${path}`;
const hidden = () => typeof document !== 'undefined' && document.visibilityState === 'hidden';

function intervalOf(entry: Entry): number {
  let ms = Infinity;
  entry.subs.forEach((sub) => { ms = Math.min(ms, sub.intervalMs); });
  return Number.isFinite(ms) ? ms : DEFAULT_INTERVAL_MS;
}

function publish(entry: Entry, snap: PollSnapshot) {
  entry.snap = snap;
  entry.subs.forEach((sub) => { try { sub.listener(); } catch { /* a bad subscriber must not stop the others */ } });
}

/** How a failed request is read. apiGet attaches `status` to a non-2xx answer; an error without
 *  one is no answer at all (offline), except the SyntaxError of a 2xx body that is not JSON. */
export function outcomeOf(error: unknown): { outcome: PollOutcome; status: number | null } {
  const status = typeof (error as { status?: unknown })?.status === 'number' ? (error as { status: number }).status : null;
  if (status === null && (error as { name?: unknown })?.name === 'SyntaxError') return { outcome: 'malformed', status };
  if (status === 401 || status === 403) return { outcome: 'refused', status };
  if (status === null || status === 0 || status === 502 || status === 504) return { outcome: 'offline', status };
  if (status === 503) return { outcome: 'unavailable', status };
  return { outcome: 'http', status };
}

function clearTimers(entry: Entry) {
  if (entry.pollTimer) clearTimeout(entry.pollTimer);
  if (entry.staleTimer) clearTimeout(entry.staleTimer);
  entry.pollTimer = null;
  entry.staleTimer = null;
}

function schedule(entry: Entry) {
  if (entry.pollTimer) clearTimeout(entry.pollTimer);
  entry.pollTimer = null;
  if (!entry.subs.size || hidden() || entries.get(entry.key) !== entry) return;
  const interval = intervalOf(entry);
  const due = entry.snap.checkedAt === null ? 0 : entry.snap.checkedAt + interval - Date.now();
  entry.pollTimer = setTimeout(() => { entry.pollTimer = null; void fetchEntry(entry); }, Math.max(0, due));
}

function scheduleStale(entry: Entry) {
  if (entry.staleTimer) clearTimeout(entry.staleTimer);
  entry.staleTimer = null;
  const at = entry.snap.lastGoodAt;
  if (at === null || !entry.subs.size) return;
  const wait = at + intervalOf(entry) * STALE_FACTOR - Date.now() + 1;
  if (wait <= 0) return;
  entry.staleTimer = setTimeout(() => {
    entry.staleTimer = null;
    publish(entry, { ...entry.snap, tick: entry.snap.tick + 1 });
  }, wait);
}

function fetchEntry(entry: Entry): Promise<void> {
  if (entry.inflight) {
    // One follow-up, however many ask: it resolves when its own answer lands, not this one's.
    if (!entry.again) {
      let resolve!: () => void;
      const done = new Promise<void>((r) => { resolve = r; });
      entry.again = { done, resolve };
    }
    return entry.again.done;
  }
  const started = epoch;
  const run = apiGet<unknown>(entry.path, entry.admin ? { admin: true } : undefined).then(
    (raw) => {
      if (started !== epoch) return;
      const now = Date.now();
      publish(entry, { outcome: 'ok', hasRaw: true, raw, status: null, checkedAt: now, lastGoodAt: now, tick: entry.snap.tick });
    },
    (error) => {
      if (started !== epoch) return;
      const { outcome, status } = outcomeOf(error);
      publish(entry, { ...entry.snap, outcome, status, checkedAt: Date.now() });
    },
  ).then(() => {
    if (started !== epoch) return;
    entry.inflight = null;
    scheduleStale(entry);
    const again = entry.again;
    if (again) {
      entry.again = null;
      void fetchEntry(entry).then(again.resolve, again.resolve);
      return;
    }
    schedule(entry);
  });
  entry.inflight = run;
  return run;
}

function onVisibility() {
  if (hidden()) { entries.forEach((entry) => { if (entry.pollTimer) clearTimeout(entry.pollTimer); entry.pollTimer = null; }); return; }
  entries.forEach((entry) => {
    if (!entry.subs.size) return;
    // the clock moved while hidden: re-render with the right age before the new answer lands
    publish(entry, { ...entry.snap, tick: entry.snap.tick + 1 });
    scheduleStale(entry);
    if (!entry.inflight) schedule(entry);
  });
}

function onFocus() {
  entries.forEach((entry) => {
    let wants = false;
    entry.subs.forEach((sub) => { wants = wants || sub.onFocus; });
    if (wants && !hidden()) void fetchEntry(entry);
  });
}

function listen() {
  if (listening || typeof window === 'undefined') return;
  listening = true;
  document.addEventListener('visibilitychange', onVisibility);
  window.addEventListener('focus', onFocus);
}

function entryFor(path: string, admin: boolean): Entry {
  const key = keyOf(path, admin);
  let entry = entries.get(key);
  if (!entry) {
    entry = { key, path, admin, subs: new Map(), snap: EMPTY_SNAPSHOT, inflight: null, again: null, pollTimer: null, staleTimer: null };
    entries.set(key, entry);
  }
  listen();
  return entry;
}

function subscribeTo(path: string, admin: boolean, sub: Sub): () => void {
  const entry = entryFor(path, admin);
  const id = nextSub++;
  entry.subs.set(id, sub);
  if (!entry.inflight) {
    const fresh = entry.snap.checkedAt !== null && Date.now() - entry.snap.checkedAt < intervalOf(entry);
    if (!fresh && !hidden()) void fetchEntry(entry);
    else schedule(entry);
  }
  scheduleStale(entry);
  return () => {
    entry.subs.delete(id);
    if (!entry.subs.size) clearTimers(entry);
    else { if (!entry.inflight) schedule(entry); scheduleStale(entry); }
  };
}

/** The shared state of a path now (EMPTY_SNAPSHOT before anyone asked). */
export function pollSnapshot(path: string, opts: { admin?: boolean } = {}): PollSnapshot {
  return entries.get(keyOf(path, !!opts.admin))?.snap ?? EMPTY_SNAPSHOT;
}

/** Ask for a path again now (after a decision, "Verify again"). Resolves when an answer asked
 *  for after this call has landed: during a request, the follow-up's answer, not the one in
 *  flight. */
export function refreshPolled(path: string, opts: { admin?: boolean } = {}): Promise<void> {
  return fetchEntry(entryFor(path, !!opts.admin));
}

/** Tests only: forget every path, cancel every timer and ignore answers still in flight (a
 *  caller waiting on a follow-up is released). */
export function resetPolling(): void {
  epoch++;
  entries.forEach((entry) => { clearTimers(entry); entry.again?.resolve(); entry.again = null; });
  entries.clear();
  if (listening && typeof window !== 'undefined') {
    document.removeEventListener('visibilitychange', onVisibility);
    window.removeEventListener('focus', onFocus);
  }
  listening = false;
}

/** Turn a shared snapshot into one caller's reading (pure: the clock is passed in). */
export function readingFromSnapshot<T>(snap: PollSnapshot, opts: {
  path: string;
  intervalMs: number;
  parsed: { ok: true; value: T } | { ok: false } | null;
  isEmpty?: (value: T) => boolean;
  now: number;
}): Reading<T> {
  const { path, intervalMs, parsed, isEmpty, now } = opts;
  const base = { checkedAt: snap.checkedAt, lastGoodAt: snap.lastGoodAt, source: path, intervalMs };
  const lastGood = parsed && parsed.ok ? parsed.value : null;
  const status = snap.status ?? undefined;
  const unknown = (reason: ReadingReason, value: T | null): Reading<T> => ({ ...base, state: 'unknown', value, reason, ...(status !== undefined ? { status } : {}) });
  switch (snap.outcome) {
    case 'none':
      return unknown('checking', null);
    case 'refused':
      return { ...base, state: 'refused', value: null, reason: 'credential', ...(status !== undefined ? { status } : {}) };
    case 'offline':
      return { ...base, state: 'offline', value: lastGood, reason: 'network', ...(status !== undefined ? { status } : {}) };
    case 'unavailable':
      return unknown('unavailable', lastGood);
    case 'http':
      return unknown('http', lastGood);
    case 'malformed':
      return unknown('malformed', lastGood);
    case 'ok':
    default: {
      if (!parsed || !parsed.ok) return unknown('malformed', null);
      if (isStale(snap.lastGoodAt, intervalMs, now)) return { ...base, state: 'stale', value: parsed.value };
      let empty = false;
      try { empty = !!isEmpty?.(parsed.value); } catch { empty = false; }
      return { ...base, state: empty ? 'empty' : 'live', value: parsed.value };
    }
  }
}

const identity = (raw: unknown) => raw;

/** One hub GET as a Reading, shared, paused while hidden, with refused and offline told apart. */
export function usePolled<T = unknown>(path: string, opts: PollOptions<T> = {}): Polled<T> {
  const {
    admin = false, intervalMs: asked = DEFAULT_INTERVAL_MS, enabled = true, demo = false,
    demoValue, parse, isEmpty, refreshOnFocus = false,
  } = opts;
  const intervalMs = Math.max(MIN_INTERVAL_MS, Number.isFinite(asked) ? asked : DEFAULT_INTERVAL_MS);
  const active = enabled && !demo && !!path;
  const key = keyOf(path, admin);
  const subscribe = useCallback((listener: () => void) => (
    active ? subscribeTo(path, admin, { intervalMs, onFocus: refreshOnFocus, listener }) : () => {}
  ), [active, path, admin, intervalMs, refreshOnFocus]);
  const getSnapshot = useCallback(() => (active ? entries.get(key)?.snap ?? EMPTY_SNAPSHOT : EMPTY_SNAPSHOT), [active, key]);
  const snap = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const refresh = useCallback(() => (active ? refreshPolled(path, { admin }) : Promise.resolve()), [active, path, admin]);
  const parsed = useMemo(() => {
    if (!snap.hasRaw) return null;
    try { return { ok: true as const, value: (parse || identity)(snap.raw) as T }; } catch { return { ok: false as const }; }
  }, [snap.raw, snap.hasRaw, parse]);
  if (!enabled) return { state: 'disabled', value: null, checkedAt: null, lastGoodAt: null, source: path, refresh };
  if (demo) return { state: 'demo', value: demoValue ?? null, checkedAt: null, lastGoodAt: null, basis: 'seeded', source: path, refresh };
  // Staleness is judged against how often the path is really asked (the shortest interval).
  const entry = entries.get(key);
  const effective = entry && entry.subs.size ? intervalOf(entry) : intervalMs;
  return { ...readingFromSnapshot<T>(snap, { path, intervalMs: effective, parsed, isEmpty, now: Date.now() }), refresh };
}
