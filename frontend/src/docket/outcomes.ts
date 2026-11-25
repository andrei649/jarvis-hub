/* What the owner's decisions came to (PHASE_B_PLAN.md §5.4, "After a decision").

   A decision resolves only once the decisions feed has been read again (api/decisions.ts), and
   that re-read often moves the request: it leaves the docket (signed, rejected, deferred — or
   refused because it expired, was decided elsewhere or was withdrawn), or its entry is keyed
   anew (a hub group promotes its next leader; a collapse loses its leader). So the outcome is not
   kept by the entry that sent it. The docket register keeps the last outcome per request id
   (DecisionRecord) and draws it

     in the entry that still holds the request    next to the decision, as before
     in the register itself, otherwise            with the title and the request it was about,
                                                  so a refusal never looks like a success

   Pure: no React, no fetch, no words (docket/Outcome.tsx words them from the docket's tables). */
import type { DecisionOutcome, EachOutcome } from '../api/decisions';
import type { DocketEntry } from './types';

/** The decisions an entry can send (its verbs, less the read-only and navigating ones). */
export type DecisionVerb = 'sign' | 'edit' | 'defer' | 'reject' | 'rejectGroup' | 'rejectAll';

/** One decision as an entry asks for it; the docket register sends it. */
export type EntryDecision =
  | { readonly verb: 'sign' | 'defer' | 'reject' | 'rejectGroup' | 'rejectAll'; readonly reason?: string }
  | { readonly verb: 'edit'; readonly payload: Record<string, unknown>; readonly reason?: string };

/** What a decision came to, as facts (worded when drawn, in the language then in force).
 *    done      the hub took it; `n` requests were decided (a group's or a collapse's members)
 *    refused   the hub refused it (`reason`: its own words, or null) or did not answer
 *              (`status` null); `demo`: not sent because the demo sample is on
 *    partial   "Reject all N": `done` of `total` rejected, `failed` refused, the first refusal's
 *              status and words
 *    notSent   the decision client would not send it as asked (a defect, never the hub's word) */
export type Outcome =
  | { readonly kind: 'done'; readonly verb: DecisionVerb; readonly n: number }
  | { readonly kind: 'refused'; readonly status: number | null; readonly reason: string | null; readonly demo?: true }
  | { readonly kind: 'partial'; readonly done: number; readonly total: number; readonly failed: number;
      readonly status: number | null; readonly reason: string | null }
  | { readonly kind: 'notSent' };

/** One decision, remembered by the register. */
export interface DecisionRecord {
  /** Order of arrival: the newest is the highest. */
  readonly seq: number;
  readonly verb: DecisionVerb;
  /** The request the entry signs (its leader): what "request N" names. */
  readonly taskId: number;
  /** Every request the decision was about: the leader alone, or all members for Reject group
   *  and Reject all N. */
  readonly ids: readonly number[];
  /** The entry's title when it was sent: the hub's plain text, verbatim ('' when none). */
  readonly title: string;
  readonly outcome: Outcome;
}

/** The requests a decision is about: one request, or every member for the group verbs. */
export function decisionIds(entry: Pick<DocketEntry, 'taskId' | 'memberIds'>, verb: DecisionVerb): number[] {
  return verb === 'rejectGroup' || verb === 'rejectAll' ? [...entry.memberIds] : [entry.taskId];
}

/** A single decision's answer (api/decisions.ts decide or rejectGroup) as an outcome. */
export function outcomeOfDecision(result: DecisionOutcome, verb: DecisionVerb, n = 1): Outcome {
  if (result.ok) return { kind: 'done', verb, n };
  return { kind: 'refused', status: result.status, reason: result.reason, ...(result.demo ? { demo: true as const } : {}) };
}

/** "Reject all N" (api/decisions.ts rejectEach) as an outcome: all rejected, or what was and why
 *  the rest was refused. */
export function outcomeOfEach(result: EachOutcome, total: number): Outcome {
  if (result.demo) return { kind: 'refused', status: null, reason: null, demo: true };
  if (!result.refused.length) return { kind: 'done', verb: 'rejectAll', n: result.rejected.length };
  const first = result.refused[0];
  return { kind: 'partial', done: result.rejected.length, total, failed: result.refused.length, status: first.status, reason: first.reason };
}

/** True when the outcome needs the owner's eyes: the hub (or the client) did not do it all. */
export function isRefusal(outcome: Outcome): boolean {
  return outcome.kind !== 'done';
}

/** At most this many requests are remembered; the oldest records go first. */
export const RECORDS_KEPT = 200;

/** The records with `record` as the last outcome of each of its requests. */
export function withRecord(records: ReadonlyMap<number, DecisionRecord>, record: DecisionRecord): Map<number, DecisionRecord> {
  const next = new Map(records);
  for (const id of record.ids) next.set(id, record);
  if (next.size > RECORDS_KEPT) {
    const oldest = [...next.entries()].sort((a, b) => a[1].seq - b[1].seq);
    for (const [id] of oldest.slice(0, next.size - RECORDS_KEPT)) next.delete(id);
  }
  return next;
}

/** Records drawn in the register, newest first, at most this many. */
export const LOOSE_SHOWN = 3;

/** Where each record is drawn.
 *    in an entry     each entry shows the newest record that is still the last outcome of one of
 *                    its requests (a record is drawn in one entry at most: the first, in docket
 *                    order)
 *    in the register a record none of whose requests is on the docket any more (`loose`, newest
 *                    first, at most `max`)
 *  A record that is still the last outcome of a request on the docket, but lost its place there
 *  to a newer one, is not drawn twice: it is left out. */
export function placeRecords(entries: readonly Pick<DocketEntry, 'memberIds'>[], records: ReadonlyMap<number, DecisionRecord>,
  max: number = LOOSE_SHOWN): { inEntry: (DecisionRecord | null)[]; loose: DecisionRecord[] } {
  const placed = new Set<DecisionRecord>();
  const onDocket = new Set<number>();
  const inEntry = entries.map((entry) => {
    let best: DecisionRecord | null = null;
    for (const id of entry.memberIds) {
      onDocket.add(id);
      const record = records.get(id);
      if (record && !placed.has(record) && (!best || record.seq > best.seq)) best = record;
    }
    if (best) placed.add(best);
    return best;
  });
  const held = new Set<DecisionRecord>();
  records.forEach((record, id) => { if (onDocket.has(id)) held.add(record); });
  const loose = [...new Set(records.values())].filter((r) => !placed.has(r) && !held.has(r))
    .sort((a, b) => b.seq - a.seq).slice(0, Math.max(0, max));
  return { inEntry, loose };
}
