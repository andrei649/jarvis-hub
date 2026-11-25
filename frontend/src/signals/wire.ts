/* The hub's answers, parsed fail-closed (PHASE_B_PLAN.md §5.6, §4.2).

   One pure parser per endpoint the signal hooks read (signals/hooks.ts). Each takes the raw JSON
   and returns the small shape the derivations need, or THROWS when the answer is not the hub's
   shape: usePolled then reports the reading as `unknown` / `malformed`, never as an empty or
   "all clear" value. A field the hub did not send is null ("not reported"), never 0 or false.

   Kept apart from the hooks so the derivations (verdict, away, agents-exception …) can name these
   shapes without importing React or the poller. */
import { slotUsageFrom, type KillSwitchState, type SlotUsage } from './types';

const isRecord = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const isCount = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v) && v >= 0;
const countOrNull = (v: unknown): number | null => (isCount(v) ? v : null);
const text = (v: unknown, max = 400): string | null => (typeof v === 'string' && v.trim() ? v.trim().slice(0, max) : null);

/** An ISO string or an epoch (seconds or ms) as epoch ms; null when it is neither. */
export function epochMs(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v) && v > 0) return v < 1e11 ? Math.round(v * 1000) : Math.round(v);
  if (typeof v === 'string' && v.trim()) {
    const at = Date.parse(v);
    return Number.isNaN(at) ? null : at;
  }
  return null;
}

/** A stamp without a zone ("2026-11-23 10:40:00") is the hub's SQLite UTC; one with a zone is read as written. */
function naiveUtcMs(v: unknown): number | null {
  if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(v.trim())) return epochMs(`${v.trim().replace(' ', 'T')}Z`);
  return epochMs(v);
}

function mustBeRecord(raw: unknown, what: string): Record<string, unknown> {
  if (!isRecord(raw)) throw new Error(`not a ${what} answer`);
  return raw;
}

// ---- GET /autonomy/mode (admin) -----------------------------------------------------------------

export type ApprovalModeValue = 'auto' | 'ask' | 'off';
export const APPROVAL_MODE_VALUES: readonly ApprovalModeValue[] = ['auto', 'ask', 'off'];
export interface ApprovalModeReading { readonly mode: ApprovalModeValue }

/** Only the three exact words count (as approvalModeNote() reads them). */
export function parseApprovalMode(raw: unknown): ApprovalModeReading {
  const r = mustBeRecord(raw, 'approval mode');
  if (!(APPROVAL_MODE_VALUES as readonly unknown[]).includes(r.mode)) throw new Error('unknown approval mode');
  return { mode: r.mode as ApprovalModeValue };
}

// ---- GET /autonomy/interrupts (admin) -----------------------------------------------------------

/** The interrupt budget. Every count is null when the hub has no budget wired ("Unknown"). */
export interface InterruptBudget {
  readonly used: number | null;
  readonly perDay: number | null;
  readonly remaining: number | null;
}
export function parseInterrupts(raw: unknown): InterruptBudget {
  const r = mustBeRecord(raw, 'interrupts');
  return { used: countOrNull(r.used), perDay: countOrNull(r.per_day), remaining: countOrNull(r.remaining) };
}
/** "1 of 4 used today" needs both counts. */
export function interruptsKnown(b: InterruptBudget): boolean {
  return b.used !== null && b.perDay !== null;
}

// ---- GET /api/security/audit/verify (user) ---------------------------------------------------------

export interface AuditVerify {
  /** The chain verifies. */
  readonly valid: boolean;
  /** The first entry that does not (valid false). */
  readonly firstInvalidId: number | null;
  /** Entries sealed. */
  readonly entries: number | null;
  /** Keyed and fully verifying: the only chain that is tamper evidence. Null when not reported. */
  readonly tamperEvident: boolean | null;
}
export function parseAuditVerify(raw: unknown): AuditVerify {
  const r = mustBeRecord(raw, 'audit verify');
  if (typeof r.valid !== 'boolean') throw new Error('audit verdict missing');
  return {
    valid: r.valid,
    firstInvalidId: typeof r.first_invalid_id === 'number' && Number.isInteger(r.first_invalid_id) ? r.first_invalid_id : null,
    entries: countOrNull(r.entries),
    tamperEvident: typeof r.tamper_evident === 'boolean' ? r.tamper_evident : null,
  };
}

// ---- GET /autonomy/observer (admin) ------------------------------------------------------------------

export type ProbeSeverity = 'INFO' | 'WARN' | 'CRITICAL';
export interface ObserverProbe {
  /** e.g. `service.lmstudio`, `resource.ram`. */
  readonly key: string;
  /** The probe's own words (English, from the hub): shown verbatim. */
  readonly detail: string;
  readonly severity: ProbeSeverity | null;
  /** When the key flipped to unhealthy (B2); null when the hub did not report it. */
  readonly since: number | null;
}
export interface ObserverStatus {
  /** `system.observer_enabled`. When false the hub samples nothing: `unhealthy` is null. */
  readonly enabled: boolean;
  readonly probes: number | null;
  readonly tracked: number | null;
  /** Null when the observer is off or not initialised: unknown, not "no problems". */
  readonly unhealthy: readonly ObserverProbe[] | null;
}
export function parseObserver(raw: unknown): ObserverStatus {
  const r = mustBeRecord(raw, 'observer');
  if (r.enabled === false) return { enabled: false, probes: null, tracked: null, unhealthy: null };
  if (!Array.isArray(r.unhealthy)) throw new Error('observer list missing');
  const unhealthy = r.unhealthy.flatMap((row): ObserverProbe[] => {
    if (!isRecord(row)) return [];
    const key = text(row.key, 120);
    if (!key) return [];
    const sev = typeof row.severity === 'string' ? row.severity.toUpperCase() : '';
    return [{
      key,
      detail: text(row.detail, 300) ?? key,
      severity: sev === 'INFO' || sev === 'WARN' || sev === 'CRITICAL' ? sev : null,
      since: epochMs(row.since),
    }];
  });
  return { enabled: true, probes: countOrNull(r.probes), tracked: countOrNull(r.tracked), unhealthy };
}

// ---- GET /api/dashboard/today (user) ---------------------------------------------------------------

export type TodayKind = 'action' | 'learning' | 'followup' | 'other';
export interface TodayItem {
  readonly id: string;
  /** Epoch ms; null when the hub's stamp could not be read. */
  readonly at: number | null;
  readonly kind: TodayKind;
  /** The hub's title, plain text. */
  readonly title: string;
  readonly agent: string | null;
  /** A follow-up's reason (`blocked_task`, `failed_task`, `open_concern`, `upcoming_date`); null
   *  for the other kinds. */
  readonly reason?: string | null;
  /** The autonomy task a follow-up or action is about, when the hub named one. */
  readonly taskId?: number | null;
}
export interface TodayFeed {
  readonly items: readonly TodayItem[];
}
export function parseTodayFeed(raw: unknown): TodayFeed {
  const r = mustBeRecord(raw, 'today feed');
  if (!Array.isArray(r.items)) throw new Error('today items missing');
  const items = r.items.flatMap((row, index): TodayItem[] => {
    if (!isRecord(row)) return [];
    const title = text(row.title, 300);
    if (!title) return [];
    const kind: TodayKind = row.kind === 'action' || row.kind === 'learning' || row.kind === 'followup' ? row.kind : 'other';
    const agent = text(row.agent, 64);
    return [{
      id: text(row.entry_id, 160) ?? `${kind}:${index}`,
      // `epoch` first: it is unambiguous seconds. A memory-derived `ts` is a naive SQLite stamp
      // ("YYYY-MM-DD HH:MM:SS", UTC) that Date.parse would read as local time.
      at: epochMs(row.epoch) ?? naiveUtcMs(row.ts),
      kind,
      title,
      agent: agent ? agent.toLowerCase() : null,
      reason: text(row.reason, 40),
      taskId: typeof row.id === 'number' && Number.isSafeInteger(row.id) && (row.source === 'task' || kind === 'action') ? row.id : null,
    }];
  });
  return { items };
}

// ---- GET /heartbeat/status -------------------------------------------------------------------------

export interface HeartbeatEntry { readonly agentId: string; readonly nextRun: number | null }
export interface HeartbeatStatus {
  readonly schedulerRunning: boolean;
  readonly heartbeats: readonly HeartbeatEntry[];
  /** HEARTBEAT files the injection scan refused at load. */
  readonly blocked: number;
}
export function parseHeartbeats(raw: unknown): HeartbeatStatus {
  const r = mustBeRecord(raw, 'heartbeat status');
  if (typeof r.scheduler_running !== 'boolean' || !Array.isArray(r.heartbeats)) throw new Error('heartbeat shape');
  const heartbeats = r.heartbeats.flatMap((row): HeartbeatEntry[] => {
    if (!isRecord(row)) return [];
    const agentId = text(row.agent_id, 64);
    return agentId ? [{ agentId: agentId.toLowerCase(), nextRun: epochMs(row.next_run) }] : [];
  });
  return { schedulerRunning: r.scheduler_running, heartbeats, blocked: Array.isArray(r.blocked) ? r.blocked.length : 0 };
}

// ---- GET /api/status/slots (user) -----------------------------------------------------------------

export interface SlotsView {
  readonly slots: SlotUsage;
  /** One row per holder (surface, session, age) as the hub sends them; null when it could not list. */
  readonly holders: readonly Readonly<Record<string, unknown>>[] | null;
  readonly holdersTotal: number | null;
}
export function parseSlots(raw: unknown): SlotsView {
  const r = mustBeRecord(raw, 'slots');
  const slots = slotUsageFrom(r.slots);
  if (!slots) throw new Error('slots shape');
  const holders = Array.isArray(r.holders) ? r.holders.filter(isRecord).slice(0, 50) : null;
  return { slots, holders, holdersTotal: countOrNull(r.holders_total) };
}

// ---- GET /api/subagents (user) --------------------------------------------------------------------

export interface SubagentRow {
  readonly id: string;
  readonly parent: string | null;
  readonly agent: string | null;
  /** The hub's word: running, done, failed, … */
  readonly status: string;
  /** Running but silent for too long (H400): drawn as the stale variant of working. */
  readonly stalled: boolean;
}
export interface SubagentsView {
  readonly spawns: readonly SubagentRow[];
  readonly active: number | null;
  readonly cap: number | null;
}
export function parseSubagents(raw: unknown): SubagentsView {
  const r = mustBeRecord(raw, 'sub-agents');
  if (!Array.isArray(r.spawns)) throw new Error('spawns missing');
  const spawns = r.spawns.flatMap((row): SubagentRow[] => {
    if (!isRecord(row)) return [];
    const id = text(row.id, 160);
    const status = text(row.status, 32);
    if (!id || !status) return [];
    const parent = text(row.parent, 64);
    const agent = text(row.agent, 64);
    return [{ id, status, parent: parent ? parent.toLowerCase() : null, agent: agent ? agent.toLowerCase() : null, stalled: row.stalled === true }];
  });
  const stats = isRecord(r.stats) ? r.stats : {};
  return { spawns, active: countOrNull(stats.active), cap: countOrNull(stats.cap) };
}

// ---- GET /autonomy/tasks?status=running|blocked (admin) -----------------------------------------------

export interface TaskLite {
  readonly id: number;
  readonly kind: string | null;
  /** The hub's title, plain text. */
  readonly title: string;
  readonly agent: string | null;
  readonly createdAt: number | null;
  /** `payload.service`, for the observer's restart_service proposals. */
  readonly service: string | null;
}
export function parseTasks(raw: unknown): readonly TaskLite[] {
  const r = mustBeRecord(raw, 'tasks');
  if (!Array.isArray(r.tasks)) throw new Error('tasks missing');
  return r.tasks.flatMap((row): TaskLite[] => {
    if (!isRecord(row) || typeof row.id !== 'number' || !Number.isSafeInteger(row.id)) return [];
    const agent = text(row.agent, 64);
    const payload = isRecord(row.payload) ? row.payload : {};
    return [{
      id: row.id,
      kind: text(row.kind, 80),
      title: text(row.title, 300) ?? '',
      agent: agent ? agent.toLowerCase() : null,
      createdAt: epochMs(row.created_at),
      service: text(payload.service, 80),
    }];
  });
}
/** usePolled's `isEmpty` for a task list. */
export const noTasks = (tasks: readonly TaskLite[]): boolean => tasks.length === 0;

// ---- GET /api/admin/network/calls (admin, optional) --------------------------------------------------

export interface EgressLedger {
  /** Requests that went to a non-local host, plugins and models together. */
  readonly external: number;
  /** The share of those made by model providers. */
  readonly models: number | null;
  /** When the ledger starts (epoch ms), when it said. */
  readonly since: number | null;
}
export function parseEgress(raw: unknown): EgressLedger {
  const r = mustBeRecord(raw, 'egress ledger');
  const external = countOrNull(r.external_egress_total);
  if (external === null) throw new Error('egress totals missing');
  const ledger = isRecord(r.ledger) ? r.ledger : {};
  return { external, models: countOrNull(r.model_egress_total), since: epochMs(ledger.since) };
}

// ---- GET /api/health/components -------------------------------------------------------------------------

export interface ComponentsHealth {
  /** The optional components that did not start; null when the registry was unavailable. */
  readonly failed: readonly string[] | null;
}
export function parseComponents(raw: unknown): ComponentsHealth {
  const r = mustBeRecord(raw, 'components');
  if (!Array.isArray(r.failed)) return { failed: null };
  return { failed: r.failed.filter((n): n is string => typeof n === 'string' && n.trim() !== '').map((n) => n.trim().slice(0, 80)) };
}

// ---- GET /api/security/kill-switch (public) --------------------------------------------------------------

/** The hub's own consistency rules (api/actions.ts isKillSwitchState): anything else is malformed. */
export function parseKillSwitch(raw: unknown): KillSwitchState {
  const r = mustBeRecord(raw, 'kill switch');
  const ok = typeof r.global === 'boolean' && typeof r.any_halted === 'boolean' && isCount(r.halted_count)
    && r.any_halted === (r.halted_count > 0) && (!r.global || r.any_halted);
  if (!ok) throw new Error('Invalid kill-switch status');
  return { halted: r.global === true };
}

// ---- GET /api/payments (admin) -----------------------------------------------------------------------------

/** Payments waiting for the owner: the broker's `pending` ones. */
export function parsePaymentsWaiting(raw: unknown): number {
  const r = mustBeRecord(raw, 'payments');
  if (!Array.isArray(r.payments)) throw new Error('payments missing');
  return r.payments.filter((p) => isRecord(p) && p.status === 'pending').length;
}
