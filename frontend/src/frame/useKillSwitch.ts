/* The emergency stop, read and pressed (PHASE_B_PLAN.md §4.1, §5.6).

   GET /api/security/kill-switch is public and content-free: { global, any_halted, halted_count }.
   It is read through the shared poller every 30 s (one request however many components ask), so
   the masthead's Stop, the attention note and the pages read the same answer. Anything that is
   not the hub's exact shape is unknown (the poller says 'malformed'), never "armed".

   stop() is the one click: POST /api/security/kill-switch {engage: true, scope: 'global',
   reason: 'hud'} with the admin credential, then the state is read again. An unknown state still
   offers the stop, because stopping is the safe direction. Resume is not here: it is typed
   DISENGAGE on Trust › Emergency stop.

   What the press says is decided by the state read again, not by the POST's own answer (§1.4):

     read again   the POST was …          result
     halted       anything                ok: the stop is in effect, nothing to report
     armed        refused (an answer)     "Stop was refused — {the hub's words}. Nothing was halted."
     armed        unanswered              no answer, and the hub still reports no halt
     armed        accepted                accepted, yet the hub still reports no halt
     unknown      any of the three        said so: whether anything is halted is unknown

   "Unanswered" is what the shared poller calls offline (signals/poll.ts outcomeOf): no answer at
   all, status 0, or a gateway's 502 / 504, after which the hub may still act on the request. A
   504 whose re-read says halted is therefore a stop that worked, not a refusal.

   The press also owns the failure the API client records for its POST (api/client.ts sink): the
   stop's own notice reports it, worded from the re-read, so the notices' failed-actions line
   leaves it out (isStopPressFailure) rather than say "the change did not happen" beside
   "Halted". */
import { useCallback, useMemo } from 'react';
import { isKillSwitchState, setKillSwitch } from '../api/actions';
import type { ActionFailure } from '../api/client';
import { refusalReason } from '../panel-kit';
import { outcomeOf, pollSnapshot, refreshPolled, usePolled } from '../signals/poll';
import type { KillSwitchState, Reading } from '../signals/types';
import { STOP_STRINGS } from './frame-strings';
import { pick, type Lang } from './strings';

export const KILL_SWITCH_PATH = '/api/security/kill-switch';
export const KILL_SWITCH_INTERVAL_MS = 30_000;

/** The public status as the frame keeps it; throws on anything else (read as malformed). With the
 *  global switch off, agent-scoped halts still in force are counted (`scoped`, present only when
 *  there are some), so a page can say the stop is armed while some agent is held. */
export function killSwitchFrom(raw: unknown): KillSwitchState {
  if (!isKillSwitchState(raw)) throw new Error('not a kill-switch status');
  const scoped = !raw.global && raw.any_halted ? raw.halted_count : 0;
  return scoped > 0 ? { halted: raw.global, scoped } : { halted: raw.global };
}

/** How the hub answered the stop's POST. */
export type StopAnswer = 'accepted' | 'refused' | 'unanswered';
/** The kill switch as read again after the press; only a current answer counts. */
export type StopAfter = 'halted' | 'armed' | 'unknown';

/** What a press came to. `ok` is true only when the switch reads halted afterwards. `reason` is
 *  the hub's own words when it refused (or a gateway's, for an unanswered POST), else a short
 *  phrase in the hook's language saying why the stop is not confirmed. */
export type StopResult =
  | { readonly ok: true; readonly answer: StopAnswer; readonly after: 'halted' }
  | {
    readonly ok: false; readonly answer: StopAnswer; readonly after: 'armed' | 'unknown';
    readonly reason: string; readonly unanswered?: true;
  };

export type KillSwitch = Reading<KillSwitchState> & {
  readonly stop: () => Promise<StopResult>;
  readonly refresh: () => Promise<void>;
};

/** True only for a current reading that says a global halt is on. */
export function isHalted(reading: Pick<Reading<KillSwitchState>, 'state' | 'value'>): boolean {
  return (reading.state === 'live' || reading.state === 'stale') && reading.value?.halted === true;
}

/** The presses, from the moment the POST leaves to the moment it settles (the latest few). */
const presses: Array<{ from: number; to: number }> = [];
const MAX_PRESSES = 20;

/** Whether a failure the API client recorded is a stop press's own POST (its notice says it). */
export function isStopPressFailure(failure: Pick<ActionFailure, 'method' | 'path' | 'at'>): boolean {
  return failure.method === 'POST' && failure.path === KILL_SWITCH_PATH
    && presses.some((press) => failure.at >= press.from && failure.at <= press.to);
}

/** The switch as the shared poller's latest attempt read it: only a current, well-formed answer. */
function stateNow(): StopAfter {
  const snap = pollSnapshot(KILL_SWITCH_PATH);
  if (snap.outcome !== 'ok' || !snap.hasRaw) return 'unknown';
  try { return killSwitchFrom(snap.raw).halted ? 'halted' : 'armed'; } catch { return 'unknown'; }
}

async function pressStop(lang: Lang | string): Promise<StopResult> {
  const s = pick(STOP_STRINGS, lang);
  const press = { from: Date.now(), to: Number.POSITIVE_INFINITY };
  presses.push(press);
  if (presses.length > MAX_PRESSES) presses.shift();
  let answer: StopAnswer = 'accepted';
  let said = '';
  try {
    await setKillSwitch(true);
  } catch (err) {
    const { outcome } = outcomeOf(err);
    // a 2xx whose body could not be read is still the hub's acceptance
    answer = outcome === 'offline' ? 'unanswered' : outcome === 'malformed' ? 'accepted' : 'refused';
    said = answer === 'refused' ? refusalReason(err) : answer === 'unanswered' ? refusalReason(err, s.reasonNoAnswer) : '';
  } finally {
    press.to = Date.now();
  }
  // Read the state again either way: the stop's own answer is not the stop's state.
  try { await refreshPolled(KILL_SWITCH_PATH); } catch { /* the reading says what is known */ }
  const after = stateNow();
  if (after === 'halted') return { ok: true, answer, after };
  const reason = said || (after === 'armed' ? s.reasonStillArmed : s.reasonUnread);
  return { ok: false, answer, after, reason, ...(answer === 'unanswered' ? { unanswered: true as const } : {}) };
}

/** The kill switch and the stop. `lang` words the short reason a page shows beside its own
 *  sentence ("The stop was not confirmed: {reason}"); the masthead words its notice itself. */
export function useKillSwitch(lang: Lang | string = 'en'): KillSwitch {
  const polled = usePolled<KillSwitchState>(KILL_SWITCH_PATH, {
    intervalMs: KILL_SWITCH_INTERVAL_MS, parse: killSwitchFrom, refreshOnFocus: true,
  });
  const stop = useCallback(() => pressStop(lang), [lang]);
  const { refresh, ...reading } = polled;
  return useMemo(() => ({ ...reading, stop, refresh }),
    // the reading's fields are the identity of the result
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [reading.state, reading.value, reading.checkedAt, reading.lastGoodAt, reading.reason, reading.status, reading.intervalMs, stop, refresh]);
}
