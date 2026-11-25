/* Shared signal types for Phase B (PHASE_B_PLAN.md §1.4, §2.2, §4.2–4.3, §5.2–5.5, §3.9).

   These are the shapes every engineer passes between the hub readers (signals/*), the frame
   (running head and foot), Home's registers and the pages. The honesty rules decide them:
     - every reading has a state; unknown is never 0, a default or an all-clear;
     - every locality readout carries its basis;
     - a row is drawn only if its field exists, so optional fields stay optional here.

   Types, a few pure constructors so every module builds readings the same way, and the pure
   parsers of hub answers more than one module reads (slots, residency, pressure). No React, no
   fetch: signals/poll.ts is the reader, the derivations live beside it. */
import type { LlmLiveState, StatusSys } from '../api/types';
import type { StatusChrome } from '../api/status-chrome';
import type { SafeModeState } from '../safe-mode-banner';
import type { MarkKind } from '../frame/kit/marks';

export type { MarkKind } from '../frame/kit/marks';

// ---- readings ------------------------------------------------------------------------------

/** What is known about a reading right now.
 *  live      the source answered within 2.5 × its polling interval
 *  stale     the last answer is older than that (draw it in the stale style, say how old)
 *  unknown   no usable answer: not yet asked ('checking'), switched off, malformed, an error
 *  refused   the hub refused the request (401/403): it needs the owner credential
 *  offline   the hub did not answer at all
 *  demo      a seeded sample (demo mode); every decision control is disabled while shown
 *  empty     the source answered, and the answer holds nothing ("nothing is waiting")
 *  disabled  the reading is switched off on purpose (not polled on this page, a feature off) */
export type ReadingState = 'live' | 'stale' | 'unknown' | 'refused' | 'offline' | 'demo' | 'empty' | 'disabled';
export const READING_STATES: readonly ReadingState[] = ['live', 'stale', 'unknown', 'refused', 'offline', 'demo', 'empty', 'disabled'];

/** Why a reading is not live, as a code; words come from the strings tables (frame/kit).
 *  checking      no answer yet (the first poll is in flight): "Checking…"
 *  unavailable   the hub answered 503: the feature is off or not ready
 *  http          another non-2xx answer (see `status`)
 *  malformed     an answer that could not be read
 *  not-measured  the hub never measures this (latency p50)
 *  not-reported  the source answered without this field
 *  credential    refused: needs the owner credential (401/403)
 *  network       offline: no answer at all */
export type ReadingReason = 'checking' | 'unavailable' | 'http' | 'malformed' | 'not-measured' | 'not-reported' | 'credential' | 'network';

/** Where a locality figure comes from (gap-5 §7): measured (observed by the hub), declared
 *  (a setting or policy, not a measurement), derived (inferred from other facts), seeded (the
 *  demo sample), unknown. Every locality readout carries one. */
export type Basis = 'measured' | 'declared' | 'derived' | 'seeded' | 'unknown';
export const BASES: readonly Basis[] = ['measured', 'declared', 'derived', 'seeded', 'unknown'];

/** A reading is stale when its last good answer is older than this many polling intervals. */
export const STALE_FACTOR = 2.5;

/** One value read from the hub (or derived from such values), with what is known about it.
 *  `value` is the newest usable answer and may be old: read `state` before trusting it. It is
 *  null before the first answer, after a refusal and when disabled. Times are epoch ms. */
export interface Reading<T> {
  readonly state: ReadingState;
  readonly value: T | null;
  /** When the latest attempt finished, whatever its outcome. */
  readonly checkedAt: number | null;
  /** When the newest usable answer arrived ("checked 10:50", "last good reading 10:44"). */
  readonly lastGoodAt: number | null;
  readonly reason?: ReadingReason;
  /** The HTTP status of the latest non-2xx answer. */
  readonly status?: number;
  /** Locality readouts only. */
  readonly basis?: Basis;
  /** The path or name it was read from, for the disclosure ("from /autonomy/mode"). */
  readonly source?: string;
  /** The polling interval the staleness was judged against. */
  readonly intervalMs?: number;
}

/** How long a reading stays live after its last good answer. */
export function staleAfter(intervalMs: number): number {
  return intervalMs * STALE_FACTOR;
}

/** True when an answer from `lastGoodAt` is too old to call live. */
export function isStale(lastGoodAt: number | null, intervalMs: number, now: number = Date.now()): boolean {
  return lastGoodAt !== null && now - lastGoodAt > staleAfter(intervalMs);
}

/** True when a reading may be drawn as current fact (live, or answered empty). Demo is drawn
 *  too, but only under its "Demo sample" label and with decisions disabled. */
export function isCurrent(reading: Pick<Reading<unknown>, 'state'>): boolean {
  return reading.state === 'live' || reading.state === 'empty';
}

type Extra = Partial<Pick<Reading<unknown>, 'reason' | 'status' | 'basis' | 'source' | 'intervalMs' | 'checkedAt'>>;

/** Before the first answer: drawn as "Checking…". */
export function checkingReading<T>(extra: Extra = {}): Reading<T> {
  return { state: 'unknown', value: null, checkedAt: null, lastGoodAt: null, reason: 'checking', ...extra };
}
/** Not known, with the reason. */
export function unknownReading<T>(reason: ReadingReason, extra: Extra = {}): Reading<T> {
  return { state: 'unknown', value: null, checkedAt: null, lastGoodAt: null, reason, ...extra };
}
/** A current answer read at `at`. */
export function liveReading<T>(value: T, at: number, extra: Extra = {}): Reading<T> {
  return { state: 'live', value, checkedAt: at, lastGoodAt: at, ...extra };
}
/** A seeded sample (demo mode). */
export function demoReading<T>(value: T, extra: Extra = {}): Reading<T> {
  return { state: 'demo', value, checkedAt: null, lastGoodAt: null, basis: 'seeded', ...extra };
}
/** Switched off on purpose. */
export function disabledReading<T>(extra: Extra = {}): Reading<T> {
  return { state: 'disabled', value: null, checkedAt: null, lastGoodAt: null, ...extra };
}

// ---- the hub snapshot (App's loader, every 30 s) ---------------------------------------------

/** /api/trust/status, parsed fail-closed. Null in the snapshot when it did not answer. */
export interface HubTrust {
  readonly mic: 'on' | 'off' | 'unknown';
  readonly strictLocal: boolean;
  readonly cloudAvailable: boolean;
  readonly claudeAvailable: boolean;
}

/** /api/analytics/locality: run counts by route label. `local_pct` is null until a routed run. */
export interface LocalityCounts {
  readonly local_pct: number | null;
  readonly local: number;
  readonly cloud: number;
  readonly unknown: number;
  readonly total: number;
  readonly [field: string]: unknown;
}

/** /status `slots` (routers/status.py `_slot_usage`, H019), also the `slots` of
 *  GET /api/status/slots: turns, chat lanes and sub-agents in use against what is allowed. Wire
 *  names. A count the hub could not read is null — unknown, never 0. */
export interface TurnSlots {
  /** Turns holding a session's lease now, on every surface (this tab's included). */
  readonly running: number;
  readonly per_session: number | null;
  readonly cap: number | null;
}
export interface LaneSlots {
  readonly channel: string;
  readonly running: number | null;
  readonly queued: number | null;
  readonly lanes: number | null;
  readonly cap: number | null;
}
export interface SubagentSlots {
  readonly running: number;
  readonly cap: number;
}
export interface SlotUsage {
  /** Null when the hub cannot count turns. */
  readonly turns: TurnSlots | null;
  /** One row per running channel that holds chat lanes; [] when none does. */
  readonly lanes: readonly LaneSlots[];
  /** Null when no sub-agent manager is wired. */
  readonly subagents: SubagentSlots | null;
}

/** /status `residency_state` (local_model_inventory.py): known (each runner said what it holds),
 *  unknown (a runner answered but could not say), offline (no runner answered). */
export type ResidencyState = 'known' | 'unknown' | 'offline';
export const RESIDENCY_STATES: readonly ResidencyState[] = ['known', 'unknown', 'offline'];

/** What App's loader knew at its latest commit (frame/types.ts `hubSnapshotFrom`). The frame,
 *  the day register and the running head and foot read the hub through this, never through
 *  App's individual state variables.
 *  state: 'unknown' (reason 'checking') before the first commit, 'live' when /status answered,
 *  'offline' when it did not, 'demo' in demo. Stale is judged by readers with
 *  hubReading() (frame/types.ts) against `lastGoodAt`, because a stalled loader commits nothing.
 *  The /status fields below are null when /status did not answer or did not send them (or sent
 *  something unreadable): a reader says "not reported", never a default. */
export interface HubSnapshot {
  readonly state: ReadingState;
  readonly reason?: ReadingReason;
  readonly demo: boolean;
  readonly serverUp: boolean;
  /** The latest loader commit (epoch ms). */
  readonly checkedAt: number | null;
  /** The latest commit where /status answered. */
  readonly lastGoodAt: number | null;
  /** The loader's cadence (30 s). */
  readonly intervalMs: number;
  readonly llm: LlmLiveState;
  /** /status `llm_backend`: the backend the router sends to ('ollama', 'lmstudio', …), as the hub
   *  names it; the hub's own 'none' (no backend configured) is kept. The running head's
   *  "<model id> · <backend>" and the verdict's "Not blocking: replies are served by <backend>". */
  readonly backend: string | null;
  /** /status `configured_model`: the model id the router is set to use — a setting (declared),
   *  not a measurement; `llm.model` is the one the hub found loaded. */
  readonly configuredModel: string | null;
  /** /status `residency_state`. */
  readonly residency: ResidencyState | null;
  /** /status `slots`: the Work overview's turn-slot counts (§6) and the fourth register's
   *  "1 reply running elsewhere" (§5.5; this tab's own turns are among `turns.running`). */
  readonly slots: SlotUsage | null;
  readonly sys: StatusSys | null;
  readonly safeMode: SafeModeState;
  readonly chrome: StatusChrome;
  /** Null when /api/trust/status did not answer (never the loader's 'on' default). */
  readonly trust: HubTrust | null;
  /** Null when /api/analytics/locality did not answer or was not asked (demo). */
  readonly locality: LocalityCounts | null;
  readonly agents: readonly any[];
  readonly ticker: readonly any[];
  readonly weather: any | null;
  readonly calendar: readonly any[];
  readonly tasks: readonly any[];
  /** Which loader sources answered in the latest cycle (agents, weather, calendar, tasks,
   *  ticker, decisions, trust …): absence of evidence is not evidence of absence. */
  readonly sources: Readonly<Record<string, boolean>>;
}

const isCount = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v) && v >= 0;
const countOrNull = (v: unknown): number | null => (isCount(v) ? v : null);
const isRecord = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);

/** /status.slots (or /api/status/slots `.slots`) read fail-closed: null unless it has the hub's
 *  shape (an object with a `lanes` list). Inside it, a part the hub could not count stays null,
 *  an unreadable count is null, and a lane row without a channel name is left out. */
export function slotUsageFrom(raw: unknown): SlotUsage | null {
  if (!isRecord(raw) || !Array.isArray(raw.lanes)) return null;
  const t = raw.turns;
  const turns = isRecord(t) && isCount(t.running)
    ? { running: t.running, per_session: countOrNull(t.per_session), cap: countOrNull(t.cap) } : null;
  const s = raw.subagents;
  const subagents = isRecord(s) && isCount(s.running) && isCount(s.cap) ? { running: s.running, cap: s.cap } : null;
  const lanes = raw.lanes.flatMap((row): LaneSlots[] => (isRecord(row) && typeof row.channel === 'string' && row.channel.trim()
    ? [{ channel: row.channel.trim().slice(0, 80), running: countOrNull(row.running), queued: countOrNull(row.queued),
      lanes: countOrNull(row.lanes), cap: countOrNull(row.cap) }]
    : []));
  return { turns, lanes, subagents };
}

/** /status `residency_state`: one of the three words, else null. */
export function residencyFrom(raw: unknown): ResidencyState | null {
  return typeof raw === 'string' && (RESIDENCY_STATES as readonly string[]).includes(raw) ? raw as ResidencyState : null;
}

// ---- memory and disk pressure (§5.2 verdict rules 7–8; §4.4 notices) --------------------------

/** The hub's conditions, worst first (agents/core/resource_pressure.py CONDITIONS). */
export type PressureCondition = 'disk_critical' | 'memory_critical' | 'oom_restart_suspected' | 'disk_elevated' | 'memory_elevated';
export const PRESSURE_CONDITIONS: readonly PressureCondition[] = ['disk_critical', 'memory_critical', 'oom_restart_suspected', 'disk_elevated', 'memory_elevated'];

/** One raised condition. */
export interface PressureEntry {
  readonly condition: PressureCondition;
  /** From the condition: critical → verdict rule 7 (Problem), elevated → rule 8 (Degraded);
   *  suspected is the out-of-memory restart (today's banner raises it as an alarm, like critical). */
  readonly level: 'critical' | 'elevated' | 'suspected';
  /** The owner dismissed its banner for this boot. The condition is still raised. */
  readonly dismissed: boolean;
  /** Memory in use, or the fullest disk, 0–100; null when the hub did not report it. */
  readonly percent: number | null;
  /** Disks near or over the threshold, fullest first (disk conditions only). */
  readonly paths: readonly { readonly path: string; readonly percent: number }[];
}

/** GET /api/system/pressure (user-guarded; routers/pressure.py), read with usePolled every 60 s
 *  as a Reading<PressureReading> (signals/hooks.ts usePressureReading): 'empty' when nothing is
 *  raised, unknown/refused/offline when it did not answer — never "no pressure" by default. */
export interface PressureReading {
  readonly bootId: string;
  /** Every raised condition, worst first, dismissed or not. The verdict reads these: dismissing
   *  the banner does not make a full disk normal. */
  readonly conditions: readonly PressureEntry[];
  /** The worst condition not dismissed: what the notices' banner shows. */
  readonly worst: PressureEntry | null;
}

const pct = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? Math.max(0, Math.min(100, Math.round(v))) : null);

/** The pressure answer as a PressureReading; throws when it is not the hub's shape (usePolled
 *  then says 'malformed'). Unknown conditions are left out; `worst` is recomputed from the
 *  conditions (the first one not dismissed), so the two can never disagree. */
export function pressureFrom(raw: unknown): PressureReading {
  if (!isRecord(raw) || typeof raw.boot_id !== 'string' || !raw.boot_id || !Array.isArray(raw.conditions)) {
    throw new Error('not a pressure answer');
  }
  const conditions = raw.conditions.flatMap((c): PressureEntry[] => {
    if (!isRecord(c) || typeof c.condition !== 'string' || !(PRESSURE_CONDITIONS as readonly string[]).includes(c.condition)) return [];
    const condition = c.condition as PressureCondition;
    const level = condition.endsWith('_critical') ? 'critical' : condition.endsWith('_elevated') ? 'elevated' : 'suspected';
    const paths = Array.isArray(c.paths)
      ? c.paths.flatMap((p) => (isRecord(p) && typeof p.path === 'string' && pct(p.percent) !== null
        ? [{ path: p.path.slice(0, 120), percent: pct(p.percent) as number }] : [])).slice(0, 4)
      : [];
    return [{ condition, level, dismissed: c.dismissed === true, percent: pct(c.percent), paths }];
  }).sort((a, b) => PRESSURE_CONDITIONS.indexOf(a.condition) - PRESSURE_CONDITIONS.indexOf(b.condition));
  return { bootId: raw.boot_id.slice(0, 80), conditions, worst: conditions.find((c) => !c.dismissed) ?? null };
}

/** usePolled's `isEmpty` for pressure: nothing is raised. */
export function noPressure(reading: PressureReading): boolean {
  return reading.conditions.length === 0;
}

// ---- the running head (§4.2) ---------------------------------------------------------------

/** The six trust signals, in running-head order. */
export type SignalId = 'egress' | 'localRoute' | 'microphone' | 'model' | 'data' | 'chain';
export const SIGNAL_IDS: readonly SignalId[] = ['egress', 'localRoute', 'microphone', 'model', 'data', 'chain'];

/** One running-head item, already in words (signals/trust-signals.ts builds it for a language).
 *  The running head shows `long` at ≥ 1680px, `short` at 1340–1679px and below, and `marks`
 *  (a mark and at most a word or two) at ≤ 759px and in the floating window. */
export interface SignalView {
  readonly id: SignalId;
  readonly state: ReadingState;
  readonly mark: MarkKind;
  readonly label: { readonly long: string; readonly short: string };
  readonly value: { readonly long: string; readonly short: string; readonly marks: string };
  /** An identifier drawn in mono after the value (the model id). */
  readonly ident?: string | null;
  readonly basis?: Basis;
  /** The disclosure: one sentence per line — what it means, its basis, when it was checked. */
  readonly detail: readonly string[];
  readonly checkedAt: number | null;
  /** A page that explains or acts on it (Trust › Emergency stop, Settings › Model setup). */
  readonly href?: string;
}

// ---- the verdict (§5.2) ----------------------------------------------------------------------

/** The verdict's state word. First matching rule wins (signals/verdict.ts). */
export type VerdictState = 'demo' | 'checking' | 'offline' | 'halted' | 'degraded' | 'problem' | 'normal' | 'unknown';

/** One cause under the verdict: the key (mono) and the probe's own detail, plus a consequence
 *  only where code supports one (a fixed map, never generated copy). */
export interface Cause {
  readonly key: string;
  readonly detail: string;
  readonly mark: MarkKind;
  readonly severity?: string | null;
  /** "Not blocking: replies are served by ollama" — only from the fixed map. */
  readonly consequence?: string | null;
  /** When the key turned unhealthy (observer `since`, backend item B2); null when not reported. */
  readonly since?: number | null;
  readonly source: 'observer' | 'ticker' | 'components' | 'pressure' | 'kill-switch' | 'audit' | 'status';
}

/** The day register's one sentence about the hub. */
export interface Verdict {
  readonly state: VerdictState;
  /** The rule that fired (1–13 in the spec's table), for tests and the disclosure. */
  readonly rule: number;
  readonly mark: MarkKind;
  /** The headline, in words, for the language it was built for. */
  readonly headline: string;
  readonly causes: readonly Cause[];
  /** A link to the docket entry that fixes a cause (a restart_service entry naming a down key). */
  readonly remedy?: { readonly taskId: number; readonly href: string; readonly text: string } | null;
  /** A page that explains or acts on the state (Trust › Emergency stop, Settings › Model setup). */
  readonly link?: { readonly href: string; readonly text: string } | null;
  /** Which readings did not answer (rule 13: "Unknown — <which readings> did not answer"). */
  readonly missing?: readonly string[];
  /** The same readings by name (hub, stop, pressure, audit, probes, components, model; the
   *  words are `missing`): lets a neighbour ask "were the probes read?" without matching words. */
  readonly missingKeys?: readonly string[];
  readonly checkedAt: number | null;
  /** Since when the state holds; null until the backend reports it (B2). */
  readonly since: number | null;
}

// ---- agents by exception (§5.5, §4.3) --------------------------------------------------------

/** The states the hub can prove for an agent. "idle", "ready" and "active" are retired. */
export type AgentActivity = 'waitingOnYou' | 'working' | 'finishedToday' | 'unavailable' | 'halted' | 'scheduled' | 'noActivity';

/** One agent's state, with the source that proves it. */
export interface AgentState {
  readonly id: string;
  readonly name: string;
  readonly role?: string | null;
  readonly activity: AgentActivity;
  readonly mark: MarkKind;
  readonly source: 'docket' | 'running-task' | 'sub-agent' | 'this-tab' | 'dashboard-today' | 'cloud-policy' | 'kill-switch' | 'heartbeat' | 'none';
  /** Working, but the sub-agent reported `stalled` (drawn as the stale variant). */
  readonly stale?: boolean;
  /** What it is doing, or "next check 18:00", in words. */
  readonly detail?: string | null;
  /** Entries waiting on the owner, or things finished today. */
  readonly count?: number | null;
  readonly since?: number | null;
}

// ---- the machine (§4.3, §5.2 This machine) -----------------------------------------------------

/** One machine reading from /status.sys. A reading with no total is unknown, never 0; the
 *  latency p50 is never measured by the hub, so it is always unknown ('not-measured'). */
export interface MachineReading {
  readonly key: 'ram' | 'vram' | 'gpu' | 'latency';
  readonly state: ReadingState;
  readonly reason?: ReadingReason;
  /** 0–100 when known. */
  readonly pct: number | null;
  readonly used?: number | null;
  readonly total?: number | null;
  readonly unit?: 'GB' | 'ms' | '%';
  /** The device or backend name it was read from, when the hub names one. */
  readonly detail?: string | null;
}

// ---- while you were away (§5.2) --------------------------------------------------------------

/** One line of "While you were away": an action the hub recorded, a docket entry raised since,
 *  or a current problem. Titles are plain text from the hub; never markup. */
export interface AwayEntry {
  readonly id: string;
  /** Epoch ms. */
  readonly at: number;
  readonly mark: MarkKind;
  readonly kind: 'done' | 'held' | 'blocked' | 'problem' | 'raised' | 'other';
  /** The hub's own kind word, unchanged, for the detail. */
  readonly nativeKind?: string | null;
  readonly title: string;
  readonly agent: string | null;
  /** Held, blocked, failed or a problem: drawn in semibold. */
  readonly exception: boolean;
  readonly href?: string | null;
  readonly source: 'dashboard-today' | 'docket' | 'problem';
  /** What `at` is: when the event happened (default), or when the hub was last asked, for a
   *  problem whose start the hub did not report: drawn as "checked 10:50", not as an event time. */
  readonly atKind?: 'event' | 'checked';
}

// ---- where a reply ran (§5.3; gap-5 §7.1) ------------------------------------------------------

/** cloud        the receipt's provider is a cloud adapter (measured, first hop)
 *  localRunner  Ollama or LM Studio and nothing more known: "where it ran is not verified"
 *  cloudName    the model id names a cloud model (`:cloud`, `-cloud`): a warning, whatever the route
 *  noModelCall  the turn's usage basis is measured_zero
 *  notReported  no receipt */
export type ReplyMarkerKind = 'cloud' | 'localRunner' | 'cloudName' | 'noModelCall' | 'notReported';

/** The reply footnote's "where it ran", for the least private of up to eight pairs. */
export interface ReplyMarker {
  readonly kind: ReplyMarkerKind;
  readonly basis: Basis;
  readonly provider: string | null;
  readonly model: string | null;
  /** How many other pairs the reply carried ("+N more" opens the provenance modal). */
  readonly more: number;
  /** Always false in Phase B: the hub cannot yet verify where a local runner computed. */
  readonly verified: boolean;
}

// ---- this tab's turns, and the stop ----------------------------------------------------------------

/** A turn this browser tab started and that has not ended (App builds it from its in-flight
 *  turns and the reply stamps, home/talk/types.ts). The only "working" fact the hub cannot
 *  report itself: it names the agent that was asked, not the agents it routed to. */
export interface TabTurn {
  /** runTurn's id: the key of App's textTurns and the reply bubble's `_turnId`. */
  readonly turnId: number;
  /** The agent asked (the recipient), never the routed one. */
  readonly agent: string;
  readonly askedAt: number;
  readonly startedAt: number | null;
  readonly firstTokenAt: number | null;
}

/** The emergency stop as GET /api/security/kill-switch reports it (frame/useKillSwitch.ts reads
 *  it as a Reading<KillSwitchState>: unknown when it did not answer; the stop is still offered
 *  then, because stopping is the safe direction). */
export interface KillSwitchState {
  /** A global halt is on: agents and the job queue wait until the owner resumes in Trust. */
  readonly halted: boolean;
  /** Agent-scoped halts in force while the global switch is off (frame/useKillSwitch.ts sets it
   *  only when there are some): the stop is armed, yet some agent is held. */
  readonly scoped?: number;
}

// ---- attention notes (§3.9) ----------------------------------------------------------------------

/** What feeds a note beside an area or a page. */
export type AttentionKey = 'docket' | 'payments' | 'services' | 'record' | 'killSwitch';
export const ATTENTION_KEYS: readonly AttentionKey[] = ['docket', 'payments', 'services', 'record', 'killSwitch'];

/** One note. A note exists only when its provider returned a live positive value (or, for the
 *  stop, a state word); an unknown count has no note at all, never a 0.
 *  docket      "N need you" (≥ 1680px) or "N", in the accent
 *  payments    "N waits", in the accent
 *  services    "■ N services down"
 *  record      "■ record broken" (at entry N when known)
 *  killSwitch  the contents column's word for the stop: Armed, Halted or Unknown */
export type AttentionNote =
  | { readonly key: 'docket'; readonly count: number }
  | { readonly key: 'payments'; readonly count: number }
  | { readonly key: 'services'; readonly count: number }
  | { readonly key: 'record'; readonly brokenAt: number | null }
  | { readonly key: 'killSwitch'; readonly state: 'armed' | 'halted' | 'unknown' };

/** What `useAttention()` returns (import it from signals/hooks.ts; the pure derivation behind it,
 *  `attentionFrom(…)`, lives in signals/attention.ts): a note per key, absent when there is
 *  nothing honest to say. nav/areas.ts says which keys feed which area and page. */
export type Attention = { readonly [K in AttentionKey]?: Extract<AttentionNote, { key: K }> };
