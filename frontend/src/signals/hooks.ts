/* The signal hooks every Phase B engineer imports from here (PHASE_B_PLAN.md §2.2, §5.6).

   Each is a Reading of one hub GET through the shared poller (signals/poll.ts): identical paths
   share one request, polling pauses while the document is hidden, refused (401/403) is told apart
   from offline, and a reading turns stale 2.5 intervals after its last good answer. The cadence
   is §5.6's: approval mode, interrupts and the observer every 60 s, the audit chain every 5 min,
   the kill switch, the slots, the sub-agents and the running tasks every 30 s, the day's feed
   every 60 s, the heartbeat every 5 min. `enabled: false` is for a page that does not show it (the
   reading is 'disabled' and nothing is asked); `demo: true` never touches the network.

   Parsers are in signals/wire.ts and are fail-closed: an answer that is not the hub's shape is
   `unknown` / `malformed`, never an empty list or an all-clear. Where a 200 holds nothing usable
   (an interrupt budget with no counts) the reading is `unknown` / `not-reported`.

   useVerdict() is the one place the day's verdict is computed: DayRegister, DayBand and Glance all
   call it, so Home and Glance cannot disagree. useAttention() is the masthead's and the contents
   column's notes. */
import { useEffect, useState } from 'react';
import { docketHref, useDocketSummary } from '../docket/links';
import { DOCKET_FEED_PATH, type DocketSummary } from '../docket/types';
import type { Lang } from '../frame/strings';
import { usePolled, type Polled } from './poll';
import {
  noPressure, pressureFrom,
  demoReading, type Attention, type HubSnapshot, type KillSwitchState, type PressureReading, type Verdict,
} from './types';
import { attentionFrom } from './attention';
import { verdict as deriveVerdict } from './verdict';
import { readLastSeen, writeLastSeen } from './away';
import {
  noTasks, parseApprovalMode, parseAuditVerify, parseComponents, parseEgress, parseHeartbeats, parseInterrupts,
  parseKillSwitch, parseObserver, parsePaymentsWaiting, parseSlots, parseSubagents, parseTasks, parseTodayFeed,
  interruptsKnown,
  type ApprovalModeReading, type AuditVerify, type ComponentsHealth, type EgressLedger, type HeartbeatStatus,
  type InterruptBudget, type ObserverStatus, type SlotsView, type SubagentsView, type TaskLite, type TodayFeed,
} from './wire';

/** What every hook takes. */
export interface HookOptions {
  /** Demo mode: no request; the reading is 'demo'. */
  readonly demo?: boolean;
  /** False: the page does not show it; the reading is 'disabled' and nothing is asked. */
  readonly enabled?: boolean;
}

const S30 = 30_000;
const S60 = 60_000;
const M5 = 300_000;

/** A live answer that holds nothing usable is unknown ("not reported"), not an empty success. */
function notReportedUnless<T>(r: Polled<T>, usable: (value: T) => boolean): Polled<T> {
  if (r.state !== 'live' || r.value === null || usable(r.value)) return r;
  return { ...r, state: 'unknown', reason: 'not-reported', value: null };
}

// ---- the running head ---------------------------------------------------------------------------------

/** GET /autonomy/mode (admin), 60 s: auto · ask · off. Refused when the browser has no owner credential. */
export function useApprovalMode(opts: HookOptions = {}): Polled<ApprovalModeReading> {
  return usePolled('/autonomy/mode', { admin: true, intervalMs: S60, parse: parseApprovalMode, demo: opts.demo, enabled: opts.enabled });
}

/** GET /autonomy/interrupts (admin), 60 s: "1 of 4 used today", or unknown when the hub has no budget wired. */
export function useInterrupts(opts: HookOptions = {}): Polled<InterruptBudget> {
  return notReportedUnless(
    usePolled('/autonomy/interrupts', { admin: true, intervalMs: S60, parse: parseInterrupts, demo: opts.demo, enabled: opts.enabled }),
    interruptsKnown,
  );
}

/** GET /api/security/audit/verify (user), 5 min. `refresh()` is "Verify again". */
export function useAuditVerify(opts: HookOptions = {}): Polled<AuditVerify> {
  return usePolled('/api/security/audit/verify', { intervalMs: M5, parse: parseAuditVerify, demo: opts.demo, enabled: opts.enabled });
}

/** GET /autonomy/observer (admin), 60 s: the unhealthy probes, each with its `since` (B2). */
export function useObserver(opts: HookOptions = {}): Polled<ObserverStatus> {
  return usePolled('/autonomy/observer', { admin: true, intervalMs: S60, parse: parseObserver, demo: opts.demo, enabled: opts.enabled });
}

/** GET /api/admin/network/calls (admin, optional), 60 s: requests that left this machine, models' share. */
export function useEgressLedger(opts: HookOptions = {}): Polled<EgressLedger> {
  return usePolled('/api/admin/network/calls', { admin: true, intervalMs: S60, parse: parseEgress, demo: opts.demo, enabled: opts.enabled });
}

/** GET /api/system/pressure (user), 60 s: every raised memory and disk condition, dismissed or not.
 *  'empty' when nothing is raised; unknown, refused or offline when it did not answer: never "no pressure". */
export function usePressureReading(opts: HookOptions = {}): Polled<PressureReading> {
  return usePolled('/api/system/pressure', { intervalMs: S60, parse: pressureFrom, isEmpty: noPressure, demo: opts.demo, enabled: opts.enabled });
}

// ---- the day ---------------------------------------------------------------------------------------------------

/** GET /api/dashboard/today?days=1&limit=50 (user), 60 s: what the hub did and learned today. */
export function useAway(opts: HookOptions = {}): Polled<TodayFeed> {
  return usePolled('/api/dashboard/today?days=1&limit=50', { intervalMs: S60, parse: parseTodayFeed, demo: opts.demo, enabled: opts.enabled });
}

/** GET /heartbeat/status, 5 min: each agent's next scheduled check. */
export function useHeartbeats(opts: HookOptions = {}): Polled<HeartbeatStatus> {
  return usePolled('/heartbeat/status', { intervalMs: M5, parse: parseHeartbeats, demo: opts.demo, enabled: opts.enabled });
}

// ---- who is working: only while a page that shows them is mounted ----------------------------------------------

/** GET /api/status/slots (user), 30 s: who holds the turn, lane and sub-agent slots. */
export function useSlots(opts: HookOptions = {}): Polled<SlotsView> {
  return usePolled('/api/status/slots', { intervalMs: S30, parse: parseSlots, demo: opts.demo, enabled: opts.enabled });
}

/** GET /api/subagents (user), 30 s: spawned sub-agents (a silent one is `stalled`). */
export function useSubagents(opts: HookOptions = {}): Polled<SubagentsView> {
  return usePolled('/api/subagents', { intervalMs: S30, parse: parseSubagents, demo: opts.demo, enabled: opts.enabled });
}

/** GET /autonomy/tasks?status=running (admin), 30 s: filtered in SQL, unlike /tasks?view=running (B10).
 *  Refused without the owner credential: "Running work: unknown", never an empty list. */
export function useRunningTasks(opts: HookOptions = {}): Polled<readonly TaskLite[]> {
  return usePolled('/autonomy/tasks?status=running', {
    admin: true, intervalMs: S30, parse: parseTasks, isEmpty: noTasks, demo: opts.demo, enabled: opts.enabled,
  });
}

/** The docket's own feed (GET /autonomy/tasks?status=blocked&limit=200, admin), 30 s, as a short
 *  list of tasks. The same request the docket reads (identical paths share one). */
export function useBlockedTasks(opts: HookOptions = {}): Polled<readonly TaskLite[]> {
  return usePolled(DOCKET_FEED_PATH, {
    admin: true, intervalMs: S30, parse: parseTasks, isEmpty: noTasks, demo: opts.demo, enabled: opts.enabled, refreshOnFocus: true,
  });
}

// ---- the verdict's other inputs ---------------------------------------------------------------------------------

/** GET /api/security/kill-switch (public), 30 s: halted when the global halt is on. Frame/useKillSwitch
 *  reads the same path, so there is one request. */
export function useKillSwitchReading(opts: HookOptions = {}): Polled<KillSwitchState> {
  return usePolled('/api/security/kill-switch', { intervalMs: S30, parse: parseKillSwitch, demo: opts.demo, enabled: opts.enabled });
}

/** GET /api/health/components (user), 5 min: the optional components that did not start. */
export function useComponentsHealth(opts: HookOptions = {}): Polled<ComponentsHealth> {
  return usePolled('/api/health/components', { intervalMs: M5, parse: parseComponents, demo: opts.demo, enabled: opts.enabled });
}

/** GET /api/payments (admin), 60 s: payments waiting for the owner (the broker's pending ones). */
export function usePaymentsWaiting(opts: HookOptions = {}): Polled<number> {
  return usePolled('/api/payments', { admin: true, intervalMs: S60, parse: parsePaymentsWaiting, isEmpty: (n: number) => n === 0, demo: opts.demo, enabled: opts.enabled });
}

// ---- the verdict and the attention notes ---------------------------------------------------------------------------

/** The day's verdict. DayRegister, DayBand and Glance all call this, so they cannot disagree. It
 *  gathers the hub snapshot, the stop, the audit chain, the observer, the component check and
 *  memory and disk pressure (every raised condition, dismissed or not), and runs the pure
 *  verdict(). Nobody passes App's PressureState: it starts at "none" and keeps the last state on a
 *  failure, which is exactly the all-clear the verdict must not assume. */
export function useVerdict(hub: HubSnapshot, lang: Lang | string, opts: { demo?: boolean } = {}): Verdict {
  const demo = !!opts.demo || hub.demo;
  const killSwitch = useKillSwitchReading({ demo });
  const audit = useAuditVerify({ demo });
  const observer = useObserver({ demo });
  const components = useComponentsHealth({ demo });
  const pressure = usePressureReading({ demo });
  const blocked = useBlockedTasks({ demo });
  return deriveVerdict({ hub, now: Date.now(), demo, killSwitch, audit, observer, components, pressure, blocked, docketHref }, lang);
}

/** The attention notes (§3.9) beside the areas and in the contents column: a note only for a live
 *  positive count; the stop's word always. `hub` adds the ticker's warnings as a fallback for
 *  "services down" when the observer cannot be read (the masthead may leave it out). */
export function useAttention(opts: { demo?: boolean; hub?: HubSnapshot | null } = {}): Attention {
  const demo = !!opts.demo || !!opts.hub?.demo;
  // in demo the docket's sample is not a count the masthead may show: its answer is not read
  const summary = useDocketSummary({ demo });
  const docket = demo ? demoReading<DocketSummary>(null) : summary;
  const payments = usePaymentsWaiting({ demo });
  const observer = useObserver({ demo });
  const audit = useAuditVerify({ demo });
  const killSwitch = useKillSwitchReading({ demo });
  return attentionFrom({ docket, payments, observer, audit, killSwitch, hub: opts.hub ?? null });
}

// ---- this browser's last visit ----------------------------------------------------------------------------------------

/** When this browser last looked (localStorage `nerva.home.lastSeenAt`), read when the page mounts
 *  and again when it becomes visible after being hidden, so a HUD left open overnight shows what
 *  happened since the owner last looked, not since it was opened; written when the page is hidden
 *  or closed. Null when never written or storage is unavailable. */
export function useLastSeenAt(): number | null {
  const [seen, setSeen] = useState<number | null>(() => readLastSeen());
  useEffect(() => {
    const write = () => writeLastSeen(Date.now());
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') write();
      else setSeen(readLastSeen());
    };
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pagehide', write);
    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pagehide', write);
    };
  }, []);
  return seen;
}
