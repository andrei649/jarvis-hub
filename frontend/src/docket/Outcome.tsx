/* A decision's outcome, drawn (PHASE_B_PLAN.md §5.4, "After a decision"; the records are kept by
   the register, docket/outcomes.ts). A mark and the words, always both:

     done      ⬤ Signed. · ✓ Rejected. · ‖ Deferred. …   the seal (the owner's hand) for a signature
     refused   ⊘ Refused — <the hub's own words>          or "the hub did not answer"
     partial   ◐ Rejected 2 of 3; 1 refused: <words>
     notSent   ⊘ Not sent — …

   In an entry the line stands alone; in the register it also says what it was about — the title
   (plain text, verbatim) and the request — so a request that left the docket after a refusal
   cannot pass for one that was signed. A refusal is an alert, a success a status. */
import React from 'react';
import { Mark } from '../frame/kit';
import type { MarkKind } from '../frame/kit/marks';
import { fmt, pick, plural, type Lang } from '../frame/strings';
import { isRefusal, type DecisionRecord, type Outcome } from './outcomes';
import { DOCKET_STRINGS } from './strings';
import './docket.css';

type S = typeof DOCKET_STRINGS.en;

/** The hub's words for a refusal, or ours for no answer (and for the demo sample). */
export function refusalWords(outcome: { status: number | null; reason: string | null; demo?: true }, s: S): string {
  if (outcome.demo) return s.demoOn;
  if (outcome.reason) return outcome.reason;
  return outcome.status ? fmt(s.hubAnswered, { status: outcome.status }) : s.noAnswer;
}

/** An outcome in words, in a language. */
export function outcomeWords(outcome: Outcome, lang: Lang): string {
  const s = pick(DOCKET_STRINGS, lang);
  switch (outcome.kind) {
    case 'done':
      switch (outcome.verb) {
        case 'sign': return s.doneSign;
        case 'edit': return s.doneEdit;
        case 'defer': return s.doneDefer;
        case 'reject': return s.doneReject;
        default: return plural(lang, s.rejectedAll, outcome.n);
      }
    case 'refused': return fmt(s.refusedBy, { reason: refusalWords(outcome, s) });
    case 'partial': return fmt(s.rejectedSome, { done: outcome.done, total: outcome.total, failed: outcome.failed, reason: refusalWords(outcome, s) });
    default: return s.notSent;
  }
}

function markOf(outcome: Outcome): MarkKind {
  if (outcome.kind === 'done') return outcome.verb === 'sign' || outcome.verb === 'edit' ? 'seal' : outcome.verb === 'defer' ? 'held' : 'done';
  return outcome.kind === 'partial' ? 'attn' : 'blocked';
}

/** The data-outcome hook: sending, done, refused, partial or not-sent. */
export function outcomeHook(outcome: Outcome): string {
  return outcome.kind === 'notSent' ? 'not-sent' : outcome.kind;
}

/** What the record was about: "<title> · request 27", or "<title> · 3 requests". */
export function aboutWords(record: DecisionRecord, lang: Lang): string {
  const s = pick(DOCKET_STRINGS, lang);
  const title = record.title || s.noTitle;
  return record.ids.length > 1
    ? plural(lang, s.outcomeAboutMany, record.ids.length, { title })
    : fmt(s.outcomeAbout, { title, id: record.taskId });
}

export interface OutcomeLineProps {
  lang: Lang;
  /** The decision in flight: "Sending your decision…" (it wins over an older record). */
  sending?: boolean;
  record?: DecisionRecord | null;
  /** In the register: say what it was about. */
  about?: boolean;
  className: string;
}

/** One outcome line, or nothing. */
export function OutcomeLine({ lang, sending = false, record = null, about = false, className }: OutcomeLineProps) {
  const s = pick(DOCKET_STRINGS, lang);
  // Keyed, so each outcome is a new element: a refusal is inserted as an alert (and announced),
  // not a "Sending…" status whose role is changed in place.
  if (sending) return <p key="sending" className={className} role="status" data-outcome="sending">{s.sending}</p>;
  if (!record) return null;
  const { outcome } = record;
  const what = about ? aboutWords(record, lang) : null;
  return (
    <p key={`outcome-${record.seq}`} className={className} role={isRefusal(outcome) ? 'alert' : 'status'} data-outcome={outcomeHook(outcome)}
      data-outcome-request={record.taskId}>
      <Mark kind={markOf(outcome)} lang={lang} />
      <span className="n-docket__outcome-words">{outcomeWords(outcome, lang)}</span>
      {/* the space is for reading aloud and copying; a flex row does not draw it. The line is cut
          short on screen, so the whole of it is also its tooltip (plain text). */}
      {what && <>{' '}<span className="n-docket__outcome-about" title={what}>{what}</span></>}
    </p>
  );
}
