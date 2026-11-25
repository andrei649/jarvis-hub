/* The hub readings the Phase B pages draw from (PHASE_B_PLAN.md §5.5, §6, §5.6). The day's feed, the
   turn slots, the heartbeats, the observer and the chain's verdict are E3's hooks (signals/hooks.ts);
   this file keeps only the feeds that need fields those parsers leave out (a running task's start, a
   sub-agent's start and task, a decision's tier) and the ones no one else reads (jobs, skill changes,
   the payments list, the record's entries). Identical paths share one request with E3's hooks.

   Every feed is one usePolled call (requests are shared by path, paused while the tab is hidden,
   refused told apart from offline), with a parser at module level that keeps only the fields a
   page may draw and throws on an answer that is not the hub's shape. A field the hub did not send
   stays null here: a page draws a row only when its field exists (§1.4), and "unknown" is never
   turned into 0. Titles are the hub's plain text and are only ever rendered as text.

   Cadence (§5.6): the day's actions and the audit tail 60 s, the work feeds (running tasks,
   sub-agents, slots, payments, docket feed) 30 s, heartbeats and the audit verdict 5 min. The
   caller says `enabled` so a feed is asked only while a page that shows it is mounted. */
import { usePolled, type Polled } from '../signals/poll';
import { DOCKET_FEED_PATH, type DocketTask } from '../docket/types';
import type { TodayFeed } from '../signals/wire';

// ---- small readers ---------------------------------------------------------------------------

const isRecord = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown, max = 200): string | null => (typeof v === 'string' && v.trim() ? v.trim().slice(0, max) : null);
const count = (v: unknown): number | null => (typeof v === 'number' && Number.isInteger(v) && v >= 0 ? v : null);
const finite = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** An ISO string or epoch (seconds or milliseconds) as epoch ms; null when it is neither. */
export function toEpochMs(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v) && v > 0) return v < 1e11 ? Math.round(v * 1000) : Math.round(v);
  if (typeof v === 'string' && v.trim()) {
    const t = Date.parse(v);
    return Number.isNaN(t) ? null : t;
  }
  return null;
}

/** A finished action of the day (from the day's feed, signals/wire.ts TodayFeed). */
export interface DoneAction { readonly id: string; readonly at: number; readonly title: string; readonly agent: string | null }

/** The actions of the day's feed (kind "action") as finished work, newest first. Learnings and follow-ups are not work. */
export function doneActions(feed: TodayFeed | null | undefined): readonly DoneAction[] {
  return (feed?.items ?? []).flatMap((i): DoneAction[] => (i.kind === 'action' && i.at !== null ? [{ id: i.id, at: i.at, title: i.title, agent: i.agent }] : []))
    .sort((a, b) => b.at - a.at);
}

export const startOfDay = (at: number): number => { const d = new Date(at); d.setHours(0, 0, 0, 0); return d.getTime(); };

// ---- running tasks (/autonomy/tasks?status=running, admin) -----------------------------------

export interface RunningTask { readonly id: number; readonly title: string; readonly agent: string | null; readonly since: number | null; readonly tier: number | null }
export const RUNNING_PATH = '/autonomy/tasks?status=running';

export function parseRunning(raw: unknown): readonly RunningTask[] {
  if (!isRecord(raw) || !Array.isArray(raw.tasks)) throw new Error('not a task list');
  return raw.tasks.flatMap((t): RunningTask[] => (isRecord(t) && typeof t.id === 'number' && text(t.title, 300)
    ? [{ id: t.id, title: text(t.title, 300) as string, agent: text(t.agent, 60)?.toLowerCase() ?? null,
      since: toEpochMs(t.updated_at) ?? toEpochMs(t.created_at), tier: typeof t.risk_tier === 'number' ? t.risk_tier : null }]
    : []));
}
export const noRows = (v: readonly unknown[]): boolean => v.length === 0;
export function useRunningFeed(opts: { enabled?: boolean; demo?: boolean } = {}): Polled<readonly RunningTask[]> {
  return usePolled<readonly RunningTask[]>(RUNNING_PATH, { admin: true, intervalMs: 30_000, parse: parseRunning, isEmpty: noRows, ...opts });
}

// ---- sub-agents (/api/subagents) ---------------------------------------------------------------

export interface SubagentRun {
  readonly id: string; readonly agent: string; readonly parent: string | null; readonly status: string;
  readonly stalled: boolean; readonly since: number | null; readonly task: string | null;
}
export interface SubagentsFeed { readonly runs: readonly SubagentRun[]; readonly active: number | null; readonly cap: number | null }

/** `running` and `stopping` are work in flight; the rest (done, failed, stopped, lost) are over. */
export function parseSubagents(raw: unknown): SubagentsFeed {
  if (!isRecord(raw) || !Array.isArray(raw.spawns)) throw new Error('not a sub-agent list');
  const runs = raw.spawns.flatMap((s): SubagentRun[] => {
    if (!isRecord(s) || typeof s.id !== 'string') return [];
    const status = text(s.status, 20) ?? 'unknown';
    if (status !== 'running' && status !== 'stopping') return [];
    return [{ id: s.id.slice(0, 80), agent: (text(s.agent, 60) ?? 'sub').toLowerCase(), parent: text(s.parent, 60)?.toLowerCase() ?? null, status,
      stalled: s.stalled === true, since: toEpochMs(s.created_at), task: text(s.task, 200) }];
  });
  const stats = isRecord(raw.stats) ? raw.stats : {};
  return { runs, active: count(stats.active), cap: count(stats.cap) };
}
export const noSubagents = (v: SubagentsFeed): boolean => v.runs.length === 0;
export function useSubagentsFeed(opts: { enabled?: boolean; demo?: boolean } = {}): Polled<SubagentsFeed> {
  return usePolled<SubagentsFeed>('/api/subagents', { intervalMs: 30_000, parse: parseSubagents, isEmpty: noSubagents, ...opts });
}

// ---- owner jobs (/api/jobs, admin) -----------------------------------------------------------------

/** What `/api/jobs` rows carry (OwnerJob.as_dict): a schedule in words and as cron, a run time only
 *  for one-shot jobs, the last run, and whether the job can run. The hub sends no "next run" for a
 *  recurring job, so none is read or invented here. */
export interface OwnerJob {
  readonly id: string; readonly name: string; readonly enabled: boolean | null;
  readonly scheduleText: string | null; readonly cron: string | null;
  /** One-shot jobs only: when it runs (`run_at`). */
  readonly runAt: number | null; readonly oneShot: boolean;
  readonly lastRunAt: number | null; readonly lastStatus: string | null; readonly lastSummary: string | null;
  readonly pausedReason: string | null; readonly runnable: boolean | null;
}
export function parseJobs(raw: unknown): readonly OwnerJob[] {
  if (!isRecord(raw) || !Array.isArray(raw.jobs)) throw new Error('not a job list');
  return raw.jobs.flatMap((j): OwnerJob[] => {
    if (!isRecord(j)) return [];
    const name = text(j.name, 160);
    if (!name) return [];
    return [{ id: String(j.id ?? name).slice(0, 80), name, enabled: typeof j.enabled === 'boolean' ? j.enabled : null,
      scheduleText: text(j.schedule_text, 120), cron: text(j.cron, 80), runAt: toEpochMs(j.run_at), oneShot: j.one_shot === true,
      lastRunAt: toEpochMs(j.last_run_at), lastStatus: text(j.last_status, 40), lastSummary: text(j.last_summary, 200),
      pausedReason: text(j.paused_reason, 120), runnable: typeof j.runnable === 'boolean' ? j.runnable : null }];
  });
}
export function useJobsFeed(opts: { enabled?: boolean; demo?: boolean } = {}): Polled<readonly OwnerJob[]> {
  return usePolled<readonly OwnerJob[]>('/api/jobs', { admin: true, intervalMs: 60_000, parse: parseJobs, isEmpty: noRows, ...opts });
}

// ---- the decisions feed, only for its top rows (the docket owns the model; E4) -------------------

export interface BlockedRow { readonly id: number; readonly title: string; readonly agent: string | null; readonly tier: number | null; readonly createdAt: number | null }
export function parseBlocked(raw: unknown): readonly BlockedRow[] {
  if (!isRecord(raw) || !Array.isArray(raw.tasks)) throw new Error('not a decisions feed');
  return (raw.tasks as DocketTask[]).flatMap((t): BlockedRow[] => (isRecord(t) && typeof t.id === 'number' && text(t.title, 300)
    ? [{ id: t.id, title: text(t.title, 300) as string, agent: text(t.agent, 60)?.toLowerCase() ?? null,
      tier: typeof t.risk_tier === 'number' ? t.risk_tier : null, createdAt: toEpochMs(t.created_at) }] : []));
}
/** Strictest first, then the oldest: the order the docket asks for. */
export function topBlocked(rows: readonly BlockedRow[], n: number): readonly BlockedRow[] {
  return [...rows].sort((a, b) => (b.tier ?? 9) - (a.tier ?? 9) || (a.createdAt ?? Infinity) - (b.createdAt ?? Infinity) || a.id - b.id).slice(0, n);
}
export function useBlockedFeed(opts: { enabled?: boolean; demo?: boolean } = {}): Polled<readonly BlockedRow[]> {
  return usePolled<readonly BlockedRow[]>(DOCKET_FEED_PATH, { admin: true, intervalMs: 30_000, parse: parseBlocked, isEmpty: noRows, ...opts });
}

// ---- payments (/api/payments, admin) and skill changes (/api/skills/proposals, admin) -------------

export type PaymentState = 'pending' | 'approved' | 'rejected' | 'settled' | 'other';
export interface PaymentRow {
  readonly id: string; readonly payee: string; readonly memo: string | null; readonly amount: number | null;
  readonly currency: string | null; readonly state: PaymentState; readonly stateWord: string; readonly createdAt: number | null;
}
export function parsePayments(raw: unknown): readonly PaymentRow[] {
  if (!isRecord(raw) || !Array.isArray(raw.payments)) throw new Error('not a payments list');
  return raw.payments.flatMap((p): PaymentRow[] => {
    if (!isRecord(p) || typeof p.id !== 'string') return [];
    const status = text(p.status ?? p.state, 20) ?? 'unknown';
    const state: PaymentState = status === 'pending' || status === 'approved' || status === 'rejected' || status === 'settled' ? status : 'other';
    return [{ id: p.id.slice(0, 80), payee: text(p.payee, 80) ?? text(p.mandate_id, 80) ?? '—', memo: text(p.memo, 280),
      amount: finite(p.amount), currency: text(p.currency, 8)?.toUpperCase() ?? null, state, stateWord: status, createdAt: toEpochMs(p.created_at) }];
  });
}
export function usePaymentsFeed(opts: { enabled?: boolean; demo?: boolean; demoValue?: readonly PaymentRow[] } = {}): Polled<readonly PaymentRow[]> {
  return usePolled<readonly PaymentRow[]>('/api/payments', { admin: true, intervalMs: 30_000, parse: parsePayments, isEmpty: noRows, ...opts });
}

export interface SkillChanges { readonly count: number }
export function parseSkillChanges(raw: unknown): SkillChanges {
  if (!isRecord(raw)) throw new Error('not a proposals answer');
  const shown = count(raw.count);
  if (shown === null) throw new Error('no proposal count');
  return { count: shown + (count(raw.more) ?? 0) };
}
export const noSkillChanges = (v: SkillChanges): boolean => v.count === 0;
export function useSkillChangesFeed(opts: { enabled?: boolean; demo?: boolean } = {}): Polled<SkillChanges> {
  return usePolled<SkillChanges>('/api/skills/proposals', { admin: true, intervalMs: 60_000, parse: parseSkillChanges, isEmpty: noSkillChanges, ...opts });
}

// ---- the record (/api/security/audit/intent and /api/security/audit/verify) ------------------------

export interface RecordEntry {
  readonly seq: number; readonly at: number | null; readonly actor: string | null; readonly action: string | null;
  readonly why: string | null; readonly hash: string | null;
  /** From `metadata.risk_tier` / `metadata.tier` when the entry carries one; null otherwise. */
  readonly tier: number | null;
}
export interface RecordFeed { readonly entries: readonly RecordEntry[]; readonly chainOk: boolean | null }

export function parseRecord(raw: unknown): RecordFeed {
  if (!isRecord(raw) || !Array.isArray(raw.entries)) throw new Error('not an audit list');
  const entries = raw.entries.flatMap((e): RecordEntry[] => {
    if (!isRecord(e) || typeof e.seq !== 'number') return [];
    const meta = isRecord(e.metadata) ? e.metadata : {};
    const tier = [meta.risk_tier, meta.tier].find((v) => typeof v === 'number' && v >= 0 && v <= 3);
    return [{ seq: e.seq, at: toEpochMs(e.ts), actor: text(e.actor, 60), action: text(e.action, 80), why: text(e.why, 400),
      hash: text(e.entry_hash, 80), tier: typeof tier === 'number' ? tier : null }];
  });
  const verify = isRecord(raw.verify) ? raw.verify : null;
  return { entries, chainOk: verify && typeof verify.ok === 'boolean' ? verify.ok : null };
}
export const noRecord = (v: RecordFeed): boolean => v.entries.length === 0;
export const RECORD_PATH = '/api/security/audit/intent?limit=50';
export function useRecordFeed(opts: { enabled?: boolean; demo?: boolean; demoValue?: RecordFeed } = {}): Polled<RecordFeed> {
  return usePolled<RecordFeed>(RECORD_PATH, { intervalMs: 60_000, parse: parseRecord, isEmpty: noRecord, ...opts });
}

