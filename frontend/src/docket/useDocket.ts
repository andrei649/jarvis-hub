/* The docket's readings (PHASE_B_PLAN.md §5.4, §5.6).

   useDocket({demo})   the docket itself: the decisions feed (GET /autonomy/tasks?status=blocked
                       &limit=200, admin) every 30 s, on window focus and after every decision,
                       through the shared poller; plus the counts of what waits elsewhere —
                       payments (GET /api/payments, admin, every 60 s: the cadence of the
                       masthead's own payments count, signals/hooks.ts, so Home does not quicken
                       that shared request) and skill changes (GET /api/skills/proposals, admin,
                       every 5 minutes: that route builds every proposal's whole diff and re-binds
                       its card on each read, so a count under the docket reads it rarely) — each
                       null unless its own feed is live. Neither cadence is in §5.6's table yet.
   useDocketSummary()  the counts the masthead, Glance and the Work overview read
   useDocketTitle(id)  the title of the entry holding request `id` (the conversation's slip)

   They share one request per path with every other reader of it (pages/sources.ts reads the
   same feed for its top rows). Demo never touches the network: it reads the labelled demo
   sample (docket/demo.ts). A refused feed (401/403) is `refused` with no value — never a 0 —
   and an offline or unreadable one keeps its last good value under its own state. */
import { useMemo } from 'react';
import { usePolled } from '../signals/poll';
import type { Reading } from '../signals/types';
import { readDemoMode } from '../demo-mode';
import type { Lang } from '../frame/strings';
import { demoModel, demoSummary } from './demo';
import { docketIsEmpty, entryHolding, parseDocketFeed, parseDocketSummary, summaryIsEmpty } from './model';
import { DOCKET_FEED_PATH, type DocketModel, type DocketSummary } from './types';

/** The docket's cadence (§5.6). */
export const DOCKET_INTERVAL_MS = 30_000;
export const PAYMENTS_PATH = '/api/payments';
export const SKILL_CHANGES_PATH = '/api/skills/proposals';
/** What waits elsewhere is read less often (see above). */
export const PAYMENTS_INTERVAL_MS = 60_000;
export const SKILL_CHANGES_INTERVAL_MS = 300_000;

type Rec = Record<string, unknown>;
const isRecord = (v: unknown): v is Rec => !!v && typeof v === 'object' && !Array.isArray(v);
const count = (v: unknown): number | null => (typeof v === 'number' && Number.isSafeInteger(v) && v >= 0 ? v : null);

/** Payments waiting for the owner: GET /api/payments rows whose status is "pending". */
export function pendingPayments(raw: unknown): number {
  if (!isRecord(raw) || !Array.isArray(raw.payments)) throw new Error('not a payments list');
  return raw.payments.filter((p) => isRecord(p) && p.status === 'pending').length;
}

/** Skill changes waiting: the proposals the hub sent plus the ones it only counted (`more`). */
export function skillChangeCount(raw: unknown): number {
  if (!isRecord(raw)) throw new Error('not a proposals answer');
  const shown = count(raw.count) ?? (Array.isArray(raw.proposals) ? raw.proposals.length : null);
  if (shown === null) throw new Error('no proposal count');
  return shown + (count(raw.more) ?? 0);
}

const none = (n: number) => n === 0;

/** Demo, unless the caller says otherwise: the URL's ?demo=1, which App's demo state follows. */
function demoNow(explicit: boolean | undefined): boolean {
  if (typeof explicit === 'boolean') return explicit;
  try { return typeof window !== 'undefined' && readDemoMode(window.location.search); } catch { return false; }
}

const feedOptions = { admin: true, intervalMs: DOCKET_INTERVAL_MS, refreshOnFocus: true } as const;

/** The docket, as a reading, with the way to read it again now. */
export function useDocket(opts: { demo: boolean; lang?: Lang }): Reading<DocketModel> & { refresh(): Promise<void> } {
  const demo = !!opts.demo;
  const lang = opts.lang ?? 'en';
  const sample = useMemo(() => (demo ? demoModel(lang) : null), [demo, lang]);
  const feed = usePolled<DocketModel>(DOCKET_FEED_PATH, {
    ...feedOptions, demo, demoValue: sample ?? undefined, parse: parseDocketFeed, isEmpty: docketIsEmpty,
  });
  const payments = usePolled<number>(PAYMENTS_PATH, { admin: true, intervalMs: PAYMENTS_INTERVAL_MS, demo, parse: pendingPayments, isEmpty: none });
  const skills = usePolled<number>(SKILL_CHANGES_PATH, { admin: true, intervalMs: SKILL_CHANGES_INTERVAL_MS, demo, parse: skillChangeCount, isEmpty: none });
  const current = (r: Reading<number>) => (r.state === 'live' || r.state === 'empty' ? r.value : null);
  const value = useMemo<DocketModel | null>(() => {
    if (!feed.value) return null;
    if (demo) return feed.value;                     // the sample carries its own counts
    return { ...feed.value, elsewhere: { payments: current(payments), skillChanges: current(skills) } };
  }, [feed.value, demo, payments.state, payments.value, skills.state, skills.value]); // eslint-disable-line react-hooks/exhaustive-deps
  return { ...feed, value };
}

/** The docket's counts, as a Reading: live (or empty) only when the decisions feed answered;
 *  refused when it needs the owner credential; unknown, offline or stale as the feed is; demo
 *  under the demo sample. Never a 0 for unknown: an unknown reading has no value. */
export function useDocketSummary(opts: { demo?: boolean } = {}): Reading<DocketSummary> {
  const demo = demoNow(opts.demo);
  const sample = useMemo(() => (demo ? demoSummary() : undefined), [demo]);
  const { refresh: _refresh, ...reading } = usePolled<DocketSummary>(DOCKET_FEED_PATH, {
    ...feedOptions, demo, demoValue: sample, parse: parseDocketSummary, isEmpty: summaryIsEmpty,
  });
  return reading;
}

/** The title of the docket entry holding request `id` — plain text, verbatim ('' when the hub
 *  sent none): `live` (or `stale`, `demo`) with the title when the docket holds it; `empty`
 *  when the feed answered and it does not (link to decisionsHref(id) instead); unknown, refused
 *  or offline as the feed is, with the last good title when there was one. */
export function useDocketTitle(id: number, opts: { demo?: boolean; lang?: Lang } = {}): Reading<string> {
  const demo = demoNow(opts.demo);
  const lang = opts.lang ?? 'en';
  const sample = useMemo(() => (demo ? demoModel(lang) : undefined), [demo, lang]);
  const { refresh: _refresh, ...feed } = usePolled<DocketModel>(DOCKET_FEED_PATH, {
    ...feedOptions, demo, demoValue: sample, parse: parseDocketFeed, isEmpty: docketIsEmpty,
  });
  const entry = entryHolding(feed.value, id);
  const title = entry ? entry.title : null;
  if ((feed.state === 'live' || feed.state === 'empty') && !entry) return { ...feed, state: 'empty', value: null };
  return { ...feed, value: title };
}
