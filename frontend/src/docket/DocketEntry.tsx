/* One line of the docket (PHASE_B_PLAN.md §5.4, "Entry anatomy").

   Closed, an entry is one ruled line: Risk (the tier glyph and word, who raised it and when),
   the title with what signing does, and Your hand (the control its friction takes). Open — one
   entry at a time — it writes the decision out: why it waits, its members, what happens if you
   sign, how to undo it, what happens if you wait, any caution and the model's opinion, then the
   signature and the other verbs. Every optional row is drawn only when the hub sent its field.

   No verb is bound to a key, and the page says so beside the verbs; a held key or the second
   click of a double-click never sends a decision (ConfirmAction repeatConfirms={false}, and the
   one-click verbs ignore a click that is not the first of its sequence), so a decision cannot
   land on the entry that moved in under the pointer. Decisions are sent by the register
   (Docket.tsx, through api/decisions.ts), which keeps their outcome by request id: the entry
   only asks (`onDecide`) and draws the outcome it is handed, so an outcome survives the entry
   (the re-read after a decision often removes or re-keys it). While the docket is stale, offline
   or a demo sample, every decision control is disabled. */
import React, { useEffect, useId, useRef, useState } from 'react';
import { ConfirmAction } from '../confirm';
import { Consequence, TierGlyph, reasonWords, type ConsequenceRow } from '../frame/kit';
import { fmt, pick, plural, type Lang } from '../frame/strings';
import { hubWords, preview as previewRequest } from '../api/decisions';
import { demoPreview } from './demo';
import { kindSentence, KIND_STRINGS, runsOnlyInAuto, unknownKindParts } from './kinds';
import { decisionsHref, docketAnchorId, openDecisionsCard } from './links';
import { commandOf, parsePreview } from './model';
import { OutcomeLine, refusalWords } from './Outcome';
import type { DecisionRecord, EntryDecision } from './outcomes';
import { PayloadEditor } from './PayloadEditor';
import { FILLED_SIGN, OUTLINE_SIGN, SealWord, SignControl } from './SignLine';
import { DOCKET_STRINGS } from './strings';
import { agentOf, fillNodes, formatWhen, wholeDays } from './text';
import type { DocketEntry, DocketPreview, DocketWhy } from './types';
import './docket.css';

type S = typeof DOCKET_STRINGS.en;

/** How the docket stands: decisions are possible only on a live, non-demo reading. */
export type EntryMode = 'live' | 'stale' | 'demo';

type PreviewState =
  | { status: 'idle' } | { status: 'loading' } | { status: 'ok'; preview: DocketPreview }
  | { status: 'none' } | { status: 'failed'; words: string };

/** A click that is the first of its sequence (or came from the keyboard, detail 0). The second
 *  click of a double-click is not a decision: by then another entry may sit under the pointer. */
export const firstClick = (ev: React.MouseEvent): boolean => ev.detail <= 1;

/** Why it waits (H484), worded as approvalModeNote() reads it, plus "not sent to your phone". */
export function whySentences(why: DocketWhy | null | undefined, pushed: boolean | null | undefined, s: S): string[] {
  const out: string[] = [];
  const now = (m: 'auto' | 'ask' | 'off') => (m === 'auto' ? s.whyNowAuto : m === 'ask' ? s.whyNowAsk : s.whyNowOff);
  const drift = (m: 'auto' | 'ask' | 'off') => (m === 'auto' ? s.whyDriftAuto : m === 'ask' ? s.whyDriftAsk : s.whyDriftOff);
  if (why?.askedUnder) {
    const { mode, byMode, source } = why.askedUnder;
    const held = byMode && mode !== 'auto';
    out.push(held ? (mode === 'ask' ? s.whyHeldAsk : s.whyHeldOff)
      : mode === 'auto' ? s.whyQueuedAuto : mode === 'ask' ? s.whyQueuedAsk : s.whyQueuedOff);
    if (held && why.modeNow && why.modeNow !== mode) out.push(drift(why.modeNow));
    if (source === 'agent') out.push(s.whyAgentMode);
  } else if (why?.modeNow) {
    out.push(now(why.modeNow));
    if (why.modeNowSource === 'agent') out.push(s.whyAgentMode);
  }
  if (pushed === false) out.push(s.notPushed);
  return out;
}

/** What a kind does, from the fixed table; a kind it does not know is named as itself. */
export function KindSentence({ kind, lang }: { kind: string | null; lang: Lang }) {
  const known = kindSentence(kind, lang);
  if (known) return <>{known}</>;
  if (!kind) return <>{pick(KIND_STRINGS, lang).noKind}</>;
  const [before, after] = unknownKindParts(lang);
  return <>{before}<code className="n-entry__ident">{kind}</code>{after}</>;
}

function IfYouSign({ entry, preview, lang, s }: { entry: DocketEntry; preview: DocketPreview | null; lang: Lang; s: S }) {
  const cmd = commandOf(preview);
  const others = preview ? preview.effects.filter((e) => e.field !== 'cmd' && e.field !== 'command') : [];
  const mode = entry.why?.modeNow;
  const onlyInAuto = runsOnlyInAuto(entry.nativeKind) && (mode === 'ask' || mode === 'off')
    ? (mode === 'ask' ? s.onlyInAutoAsk : s.onlyInAutoOff) : null;
  return (
    <>
      <span className="n-entry__sentence">
        {cmd ? fillNodes(s.wouldRun, { cmd: <code className="n-entry__ident">{cmd}</code> }) : <KindSentence kind={entry.nativeKind} lang={lang} />}
      </span>
      {others.length > 0 && (
        <span className="n-entry__sentence" data-row="effects">
          {fillNodes(s.dryRunReports, {
            effects: others.map((e, i) => (
              <React.Fragment key={`${e.field}-${i}`}>{i > 0 ? ' · ' : ''}<code className="n-entry__ident">{e.field}</code>{' '}
                <code className="n-entry__ident">{e.value}</code></React.Fragment>)),
          })}
        </span>
      )}
      {preview?.wouldExecute === false && <span className="n-entry__sentence">{s.queuedForWorker}</span>}
      {onlyInAuto && <span className="n-entry__sentence" data-row="only-in-auto">{onlyInAuto}</span>}
    </>
  );
}

function Opinion({ opinion, s }: { opinion: NonNullable<DocketEntry['opinion']>; s: S }) {
  const who = [opinion.provider, opinion.model].filter(Boolean).join('/');
  const where = opinion.local === null ? null : opinion.local ? s.opinionLocal : s.opinionRemote;
  const tail = (
    <>
      {who && <>{' · '}<code className="n-entry__ident">{who}</code></>}
      {where && <>{' · '}{where}</>}
    </>
  );
  if (opinion.advisory === false) {
    return <span className="n-entry__sentence">{opinion.verdict === 'deny' ? s.guardianDeny : s.guardianEscalate}{tail}</span>;
  }
  return (
    <>
      <span className="n-entry__sentence">
        {s.opinionAdvisory}{opinion.score !== null && <>{' · '}{fmt(s.opinionScore, { score: opinion.score })}</>}{tail}
      </span>
      {opinion.flagged && <span className="n-entry__sentence">{s.opinionFlagged}</span>}
      {opinion.truncated && <span className="n-entry__sentence">{s.opinionTruncated}</span>}
    </>
  );
}

const MEMBERS_SHOWN = 8;

export interface DocketEntryProps {
  entry: DocketEntry;
  open: boolean;
  lang: Lang;
  mode: EntryMode;
  /** Two steps: the confirmation of this entry's signature is open. */
  armed: boolean;
  /** A decision about one of this entry's requests is in flight. */
  busy: boolean;
  /** The last outcome the register drew here (docket/outcomes.ts placeRecords), or null. */
  outcome: DecisionRecord | null;
  /** Open this entry (and arm its two-step signature, or focus its signature box). */
  onOpen: (how?: { arm?: boolean; focus?: 'sign' | 'title' }) => void;
  /** Arm or disarm a two-step signature. */
  onArm: (armed: boolean) => void;
  /** Send a decision about this entry; resolves true when the hub took it, once the feed has
   *  been read again. The register keeps the outcome. */
  onDecide: (decision: EntryDecision) => Promise<boolean>;
  /** Where focus should go once this entry is open; cleared through onFocused. */
  focus?: 'sign' | 'title' | null;
  onFocused?: () => void;
  now: number;
}

export function DocketEntryView({ entry, open, lang, mode, armed, busy, outcome, onOpen, onArm, onDecide, focus = null, onFocused, now }: DocketEntryProps) {
  const s = pick(DOCKET_STRINGS, lang);
  const decidable = mode === 'live';
  const title = entry.title || s.noTitle;
  const [reason, setReason] = useState('');
  const [reasonOpen, setReasonOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [previewShown, setPreviewShown] = useState(false);
  const [previewState, setPreviewState] = useState<PreviewState>({ status: 'idle' });
  const mounted = useRef(true);
  const root = useRef<HTMLLIElement>(null);
  const auto = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const ids = { title: `n-entry-${auto}-title`, reason: `n-entry-${auto}-reason`, reasonField: `n-entry-${auto}-reason-field`, defer: `n-entry-${auto}-defer` };

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  // An edit belongs to the open entry: closing it ends the edit, so a later "Sign" from the
  // closed line signs the request as it is, never a draft left behind.
  useEffect(() => { if (!open) setEditing(false); }, [open]);

  const loadPreview = () => {
    if (mode === 'demo') {
      const sample = demoPreview(entry.taskId);
      setPreviewState(sample ? { status: 'ok', preview: sample } : { status: 'none' });
      return;
    }
    setPreviewState({ status: 'loading' });
    previewRequest(entry.taskId).then((raw) => {
      if (!mounted.current) return;
      const parsed = parsePreview(raw);
      setPreviewState(parsed ? { status: 'ok', preview: parsed } : { status: 'failed', words: reasonWords('malformed', lang) ?? s.noAnswer });
    }, (err) => {
      if (!mounted.current) return;
      const status = typeof err?.status === 'number' ? err.status : null;
      setPreviewState({ status: 'failed', words: refusalWords({ status, reason: hubWords(err) }, s) });
    });
  };

  // The open entry previews itself (read only); the others on request.
  useEffect(() => {
    if (open && !entry.special && previewState.status === 'idle') loadPreview();
  }, [open, entry.taskId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Focus asked for when the entry was opened: the signature box, or the title (a link's target).
  useEffect(() => {
    if (!open || !focus) return;
    const el = root.current;
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'nearest' });
    const target = focus === 'sign'
      ? el?.querySelector<HTMLElement>('.n-signline__input, .n-signline__sign')
      : el?.querySelector<HTMLElement>(`#${ids.title}`);
    target?.focus();
    onFocused?.();
  }, [open, focus]); // eslint-disable-line react-hooks/exhaustive-deps

  // The register sends the decision and keeps its outcome (one decision per request at a time).
  const ask = (decision: EntryDecision): Promise<boolean> => (decidable ? onDecide(decision) : Promise.resolve(false));
  const sign = () => ask({ verb: 'sign', reason });
  const signEdited = async (payload: Record<string, unknown>) => {
    const ok = await ask({ verb: 'edit', payload, reason });
    if (ok && mounted.current) setEditing(false);
    return ok;
  };
  const defer = () => ask({ verb: 'defer', reason });
  const reject = () => ask({ verb: 'reject', reason });
  const rejectWholeGroup = () => ask({ verb: 'rejectGroup', reason });
  const rejectAllIdentical = () => ask({ verb: 'rejectAll', reason });
  const togglePreview = () => {
    const next = !previewShown;
    setPreviewShown(next);
    if (next && (previewState.status === 'idle' || previewState.status === 'failed')) loadPreview();
  };

  const preview = previewState.status === 'ok' ? previewState.preview : null;
  const agent = agentOf(entry.agent);
  const raised = entry.createdAt !== null ? fmt(s.raisedAt, { time: formatWhen(entry.createdAt, lang, { now }) }) : null;
  const days = entry.createdAt !== null ? wholeDays(entry.createdAt, now) : 0;
  const n = entry.memberIds.length;
  const count = entry.kind === 'identical' ? plural(lang, s.identicalCount, n) : entry.kind === 'group' ? plural(lang, s.groupCount, n) : null;
  const parent = entry.delegatedBy ? (agentOf(entry.delegatedBy.parent)?.name ?? entry.delegatedBy.parent) : null;
  const how = entry.special ? s.howSpecial : entry.friction === 'click' ? s.howClick
    : entry.friction === 'two-step' ? s.howTwoStep : fmt(s.howTyped, { phrase: entry.phrase ?? '' });

  const risk = (
    <div className="n-entry__risk">
      <TierGlyph tier={entry.task.risk_tier} money={entry.tier === 'money'} word lang={lang} className="n-entry__lvl" />
      {agent && <span className="n-entry__who">{agent.name}</span>}
      {open && agent?.role && <span className="n-entry__role">{agent.role}</span>}
      {raised && <span className="n-entry__when">{raised}</span>}
      {days >= 1 && <span className="n-entry__age">{plural(lang, s.waitingDays, days)}</span>}
      {count && <span className="n-entry__count">{count}</span>}
      {parent && <span className="n-entry__sub">{fmt(s.subAgent, { parent })}</span>}
    </div>
  );

  const decisionsLink = mode === 'demo'
    ? <button type="button" className="n-btn n-btn--sm" data-verb="openInDecisions" disabled>{s.openInDecisions}</button>
    : <a className="n-btn n-btn--sm" data-verb="openInDecisions" href={decisionsHref(entry.taskId)} aria-label={fmt(s.openInDecisionsAria, { title })}
      onClick={(ev) => { ev.preventDefault(); openDecisionsCard(entry.taskId); }}>{s.openInDecisions}</a>;

  const outcomeLine = <OutcomeLine lang={lang} sending={busy} record={outcome} className="n-entry__outcome" />;

  const doesLine = (
    <p className="n-entry__line">
      <KindSentence kind={entry.nativeKind} lang={lang} />
      {entry.rollback && <span className="n-entry__undo">{fmt(s.undoLine, { what: entry.rollback.description })}</span>}
    </p>
  );

  const liProps = {
    ref: root,
    id: docketAnchorId(entry.taskId),
    'data-docket-entry': entry.taskId,
    'data-tier': String(entry.tier),
    'data-friction': entry.friction,
    'data-entry-kind': entry.kind,
    'data-entry-state': open ? 'open' : 'closed',
    ...(entry.special ? { 'data-special': entry.specialKind ?? '' } : {}),
    'aria-busy': busy || undefined,
  };

  if (!open) {
    let hand: React.ReactNode;
    if (entry.special) hand = decisionsLink;
    else if (entry.friction === 'click') {
      hand = <span data-verb="sign"><ConfirmAction tier={0} label={<SealWord word={s.sign} />} ariaLabel={fmt(s.signAria, { title })}
        className={`${FILLED_SIGN} n-btn--sm`} disabled={!decidable || busy} repeatConfirms={false} onConfirm={() => { void sign(); }} /></span>;
    } else if (entry.friction === 'two-step') {
      hand = <button type="button" className={`${OUTLINE_SIGN} n-btn--sm`} data-verb="sign" aria-label={fmt(s.signAria, { title })}
        disabled={!decidable || busy} onClick={() => onOpen({ arm: true })}><SealWord word={s.sign} /></button>;
    } else {
      hand = <button type="button" className="n-btn n-btn--sm" data-verb="open" aria-label={fmt(s.openToSignAria, { title })}
        onClick={() => onOpen({ focus: 'sign' })}>{s.openToSign}</button>;
    }
    return (
      <li className="n-entry" {...liProps}>
        {risk}
        <div className="n-entry__main">
          {/* one line below 1680px, cut with an ellipsis when it does not fit (docket.css): the whole
              title stays in the button's name and in its tooltip */}
          <h3 className="n-entry__title">
            <button type="button" className="n-entry__open" aria-expanded={false} aria-label={fmt(s.openEntry, { title })}
              title={title} onClick={() => onOpen()}>{title}</button>
          </h3>
          {doesLine}
          {outcomeLine}
        </div>
        <div className="n-entry__hand">{hand}<span className="n-entry__how">{how}</span></div>
      </li>
    );
  }

  const why = whySentences(entry.why, entry.pushed, s);
  const targets = entry.memberTargets ?? [];
  const rows: ConsequenceRow[] = [
    { key: 'sign', term: s.termIfSign, detail: <IfYouSign entry={entry} preview={preview} lang={lang} s={s} /> },
    { key: 'undo', term: s.termUndo, detail: entry.rollback
      ? <><span className="n-entry__sentence">{entry.rollback.description}</span>
        {entry.rollback.limitations && <span className="n-entry__sentence">{entry.rollback.limitations}</span>}</>
      : s.undoNotReported },
    { key: 'wait', term: s.termWait, detail: entry.deadlineAt !== null
      ? fmt(s.waitDeadline, { time: formatWhen(entry.deadlineAt, lang, { now, withTime: true }) }) : s.waitNothing },
    { key: 'caution', term: s.termCaution, detail: entry.tainted ? s.tainted : null },
    { key: 'opinion', term: s.termOpinion, detail: entry.opinion ? <Opinion opinion={entry.opinion} s={s} /> : null },
    { key: 'consent', term: s.termConsent, detail: entry.consentOffer ? plural(lang, s.consentOffered, entry.consentOffer.count) : null },
  ];

  const signature = entry.special ? (
    <div className="n-entry__special">
      <p className="n-entry__special-note">{s.specialNote}</p>
      {decisionsLink}
    </div>
  ) : editing ? (
    <PayloadEditor task={entry.task} title={title} tier={entry.tier} friction={entry.friction} lang={lang}
      disabled={!decidable} busy={busy} onSign={signEdited} onCancel={() => { onArm(false); setEditing(false); }}
      armed={armed} onArm={() => onArm(true)} onDisarm={() => onArm(false)} />
  ) : (
    <SignControl friction={entry.friction} phrase={entry.phrase} title={title} lang={lang}
      disabled={!decidable} busy={busy} onSign={sign}
      armed={armed} onArm={() => onArm(true)} onDisarm={() => onArm(false)}
      consequence={<IfYouSign entry={entry} preview={preview} lang={lang} s={s} />} />
  );

  const previewDetail = previewShown && (
    <div className="n-entry__preview" role="region" aria-label={s.previewTitle} data-preview={previewState.status}>
      <p className="n-entry__preview-title">{s.previewTitle}</p>
      {previewState.status === 'loading' && <p className="n-entry__preview-line">{s.previewLoading}</p>}
      {previewState.status === 'failed' && <p className="n-entry__preview-line" role="status">{fmt(s.previewFailed, { reason: previewState.words })}</p>}
      {(previewState.status === 'none' || (preview && !preview.target && !preview.effects.length && !preview.prompt)) && (
        <p className="n-entry__preview-line">{s.previewNoEffects}</p>
      )}
      {preview?.target && (
        <p className="n-entry__preview-line"><span className="n-entry__preview-term">{s.previewTarget}</span>{' '}
          <code className="n-entry__ident">{preview.target}</code></p>
      )}
      {preview && preview.effects.length > 0 && (
        <ul className="n-entry__effects">
          {preview.effects.map((e, i) => (
            <li key={`${e.field}-${i}`}><code className="n-entry__ident">{e.field}</code> <code className="n-entry__ident">{e.value}</code></li>
          ))}
        </ul>
      )}
      {preview?.prompt && (preview.prompt.available ? (
        <div className="n-entry__question">
          <p className="n-entry__preview-term">{s.previewQuestion}</p>
          <p className="n-entry__question-text">{preview.prompt.text}</p>
          {preview.prompt.choices.length > 0 && <ol>{preview.prompt.choices.map((c, i) => <li key={i}>{c}</li>)}</ol>}
        </div>
      ) : <p className="n-entry__preview-line">{s.previewQuestionGone}</p>)}
    </div>
  );

  return (
    <li className="n-entry n-entry--open" {...liProps}>
      {risk}
      <div className="n-entry__main">
        <h3 className="n-entry__title" id={ids.title} tabIndex={-1}>{title}</h3>
        {why.length > 0 && <p className="n-entry__why">{why.join(' ')}</p>}
        {entry.kind !== 'single' && (
          <ul className="n-entry__members" aria-label={plural(lang, s.membersLabel, n)}>
            {entry.memberIds.slice(0, MEMBERS_SHOWN).map((id, i) => (
              <li key={id}><code className="n-entry__member-id">{id}</code>
                {targets[i] ? <code className="n-entry__member-target">{targets[i]}</code> : null}</li>
            ))}
            {n > MEMBERS_SHOWN && <li className="n-entry__members-more">{plural(lang, s.moreMembers, n - MEMBERS_SHOWN)}</li>}
          </ul>
        )}
        <Consequence rows={rows} className="n-entry__consequence" />
        {entry.kind !== 'single' && !entry.special && (
          <p className="n-entry__applies">{plural(lang, s.appliesTo, n - 1, { id: entry.taskId })}</p>
        )}
        {signature}
        {!entry.special && (
          <div className="n-entry__reason">
            <button type="button" className="n-btn n-btn--sm n-btn--bare n-entry__reason-toggle" aria-expanded={reasonOpen}
              aria-controls={ids.reason} onClick={() => setReasonOpen((v) => !v)}>{s.addReason}</button>
            <div id={ids.reason} className="n-entry__reason-body" hidden={!reasonOpen}>
              <label className="n-entry__reason-label" htmlFor={ids.reasonField}>{s.reasonLabel}</label>
              <textarea id={ids.reasonField} className="n-textarea n-entry__reason-field" maxLength={280} rows={2}
                value={reason} onChange={(ev) => setReason(ev.target.value)} />
              <p className="n-entry__reason-note">{s.reasonNote}</p>
            </div>
          </div>
        )}
        {!entry.special && (
          <div className="n-entry__acts">
            <button type="button" className="n-btn n-btn--sm" data-verb="preview" aria-expanded={previewShown} onClick={togglePreview}>
              {previewShown ? s.hidePreview : s.preview}</button>
            <button type="button" className="n-btn n-btn--sm" data-verb="edit" aria-expanded={editing} disabled={!decidable || busy}
              onClick={() => { onArm(false); setEditing((v) => !v); }}>{s.edit}</button>
            <button type="button" className="n-btn n-btn--sm" data-verb="defer" title={s.deferHint} aria-describedby={ids.defer}
              disabled={!decidable || busy} onClick={(ev) => { if (firstClick(ev)) void defer(); }}>{s.defer}</button>
            <span id={ids.defer} data-visually-hidden="">{s.deferHint}</span>
            <span className="n-entry__fine" data-no-shortcut="">
              <span data-show-from="m">{s.noShortcut}</span><span data-show-upto="s">{s.noShortcutShort}</span>
            </span>
            <button type="button" className="n-btn n-btn--sm" data-verb="reject" disabled={!decidable || busy}
              onClick={(ev) => { if (firstClick(ev)) void reject(); }}>{s.reject}</button>
            {entry.verbs.includes('rejectGroup') && entry.group && (
              <span data-verb="rejectGroup" className="n-entry__verb">
                <ConfirmAction tier={1} plain repeatConfirms={false} label={s.rejectGroup} className="n-btn n-btn--sm"
                  prompt={plural(lang, s.rejectGroupPrompt, n)} armedLabel={plural(lang, s.rejectGroupConfirm, n)} cancelLabel={s.cancel}
                  groupLabel={plural(lang, s.rejectGroupPrompt, n)} groupClassName="n-entry__confirm n-entry__confirm--inline"
                  confirmClassName="n-btn n-btn--sm n-btn--ink" disabled={!decidable || busy} busy={busy} onConfirm={rejectWholeGroup} />
              </span>
            )}
            {entry.verbs.includes('rejectAllIdentical') && (
              <span data-verb="rejectAllIdentical" className="n-entry__verb">
                <ConfirmAction tier={1} plain repeatConfirms={false} label={plural(lang, s.rejectAll, n)} className="n-btn n-btn--sm"
                  prompt={plural(lang, s.rejectAllPrompt, n)} armedLabel={plural(lang, s.rejectAllConfirm, n)} cancelLabel={s.cancel}
                  groupLabel={plural(lang, s.rejectAllPrompt, n)} groupClassName="n-entry__confirm n-entry__confirm--inline"
                  confirmClassName="n-btn n-btn--sm n-btn--ink" disabled={!decidable || busy} busy={busy} onConfirm={rejectAllIdentical} />
              </span>
            )}
          </div>
        )}
        {previewDetail}
        {outcomeLine}
      </div>
    </li>
  );
}
