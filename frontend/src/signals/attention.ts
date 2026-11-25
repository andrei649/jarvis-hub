/* The attention notes beside an area or a page (PHASE_B_PLAN.md §3.9): the pure part of
   useAttention() (signals/hooks.ts).

   A note exists only when its provider returned a LIVE, positive value: an unknown, refused,
   offline or stale count is no note at all, never a 0 and never "nothing waits". The stop is the
   exception: its word (Armed, Halted, Unknown) is always drawn, and Unknown is a word, not a guess.

     docket      the docket's entries, from the docket summary           "N need you"
     payments    payments waiting, from /api/payments (admin)            "N waits"
     services    unhealthy probes: the observer if it answered, else the situation ticker's
                 WARNING/ALERT items (only ever a positive count: an empty ticker proves nothing)
     record      the audit chain is invalid                              "■ record broken"
     killSwitch  armed · halted · unknown */
import type { DocketSummary } from '../docket/types';
import type { Attention, HubSnapshot, KillSwitchState, Reading } from './types';
import type { AuditVerify, ObserverStatus } from './wire';

export interface AttentionInput {
  readonly docket: Reading<DocketSummary>;
  /** Payments waiting (count of pending). */
  readonly payments: Reading<number>;
  readonly observer: Reading<ObserverStatus>;
  readonly audit: Reading<AuditVerify>;
  readonly killSwitch: Reading<KillSwitchState>;
  /** The loader's ticker, the fallback for `services` when the observer cannot be read. */
  readonly hub?: Pick<HubSnapshot, 'ticker'> | null;
}

/** A count that may be drawn: the source answered now and the number is positive. */
const live = (r: Reading<unknown>): boolean => r.state === 'live';

export function tickerWarnings(ticker: readonly any[] | null | undefined): number {
  return (ticker ?? []).filter((item) => {
    const verb = String(item?.verb ?? '').toUpperCase();
    return (verb === 'WARNING' || verb === 'ALERT') && typeof item?.text === 'string' && item.text.trim() !== '';
  }).length;
}

export function attentionFrom(input: AttentionInput): Attention {
  const out: { -readonly [K in keyof Attention]: Attention[K] } = {};

  const docket = input.docket;
  if (live(docket) && docket.value && docket.value.entries > 0) out.docket = { key: 'docket', count: docket.value.entries };

  if (live(input.payments) && typeof input.payments.value === 'number' && input.payments.value > 0) {
    out.payments = { key: 'payments', count: input.payments.value };
  }

  const obs = input.observer.value;
  const observerAnswered = live(input.observer) && !!obs && obs.enabled && obs.unhealthy !== null;
  const down = observerAnswered ? (obs as ObserverStatus).unhealthy!.length : tickerWarnings(input.hub?.ticker);
  if (down > 0) out.services = { key: 'services', count: down };

  const audit = input.audit.value;
  if (live(input.audit) && audit && !audit.valid) out.record = { key: 'record', brokenAt: audit.firstInvalidId };

  const stop = input.killSwitch;
  out.killSwitch = {
    key: 'killSwitch',
    state: live(stop) && stop.value ? (stop.value.halted ? 'halted' : 'armed') : 'unknown',
  };
  return out;
}
