/* The docket (PHASE_B_PLAN.md §5.4): Home's register of what awaits the owner's signature.

   It reads the Decision Inbox's own feed (docket/useDocket.ts) and draws it as entries ordered
   by risk (docket/model.ts); one entry is open at a time and writes the decision out in full.
   The figure in the head is the number of entries, in the accent (the owner's hand) only while
   the feed is live; there is no "actions" figure, because the hub never groups distinct asks.

   States, each drawn as itself:
     checking   "Checking the decisions feed…"
     live       the entries
     empty      "Nothing is waiting for you." over a double rule reading "0 entries"; no figure
     refused    "Unknown — sign in as the owner to see what is waiting": on a networked origin a
                Sign in button (requireSignIn), on loopback where to set the credential. No "0",
                no "nothing waits".
     offline    "Unknown — the decisions feed did not answer · last good 10:44"; the previous
                entries stay, in the stale style, with signing disabled until a refresh, and the
                total says it is the last good reading
     stale      the same, said as stale: refresh before signing
     demo       the labelled demo sample, every decision control disabled

   Decisions. The register sends them (api/decisions.ts), one per request at a time, and keeps
   the last outcome of each request (docket/outcomes.ts): it is drawn in the entry that still holds
   the request, or else here in the register, with the title and the request — because the
   re-read that follows a decision often removes or re-keys the entry, and a refusal (expired,
   decided elsewhere, withdrawn) must never vanish like a success. An entry is keyed by its
   request too, so when a hub group promotes its next leader nothing typed, armed or edited for
   the previous one carries over; the open entry stays open while it holds a request it held.

   The hash #docket-entry-<id> on /v2/cockpit opens the entry holding request <id> and moves
   focus to it (also when <id> is a member of a group or a collapse); a request that is not on
   the docket is said so, with a link to it in Decisions.

   The open entry's signature is whole in the body's view as the docket first draws it (below,
   useSignatureInView), and nothing above it is cut to make it so. */
import React, { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import { Mark, Register, SourceLabel, Total, clockTime as clock, reasonWords, stateWord } from '../frame/kit';
import { fmt, pick, plural, type Lang } from '../frame/strings';
import { routeHref } from '../hud-routing';
import { isNetworkedOrigin, requireSignIn } from '../api/owner-session';
import { decide, rejectEach, rejectGroup } from '../api/decisions';
import { areaById, pageForPanel, textOf } from '../nav/areas';
import { DocketEntryView, type EntryMode } from './DocketEntry';
import { DECISIONS_PATH, HUD_ROUTE_EVENT, decisionsHref, docketTaskFromHash, openDecisionsCard } from './links';
import { entryHolding } from './model';
import { OutcomeLine } from './Outcome';
import {
  decisionIds, outcomeOfDecision, outcomeOfEach, placeRecords, withRecord,
  type DecisionRecord, type EntryDecision, type Outcome,
} from './outcomes';
import { DOCKET_STRINGS } from './strings';
import { fillNodes } from './text';
import type { DocketEntry } from './types';
import { useDocket, useDocketSummary } from './useDocket';
import './docket.css';

const PAYMENTS_PAGE = '/v2/console/payments';
const TRUST_OPS_PAGE = '/v2/console/trust-ops';

function subscribeHash(update: () => void): () => void {
  window.addEventListener('hashchange', update);
  window.addEventListener('popstate', update);
  window.addEventListener(HUD_ROUTE_EVENT, update);
  return () => {
    window.removeEventListener('hashchange', update);
    window.removeEventListener('popstate', update);
    window.removeEventListener(HUD_ROUTE_EVENT, update);
  };
}
const hashNow = () => (typeof window === 'undefined' ? '' : window.location.hash);

/** The location's hash, following in-app navigation (openDocketEntry pushes history without a
 *  hashchange, then tells the router). */
export function useLocationHash(): string {
  return useSyncExternalStore(subscribeHash, hashNow, () => '');
}

/** The scroll that brings the open entry's signature whole into the docket body's view: just enough
 *  for its bottom to reach the view's bottom, and only where that cuts nothing the body draws above it.
 *  `firstLine` is where the body's first text begins: the docket's state line ("Demo sample — signing is
 *  disabled.", "Unknown — …"), an outcome, the column heads, or the open entry's own tier word when
 *  nothing stands above it. The scroll may take away only the blank above that line (the state line's
 *  own top padding, 12px; 9px in the compact density); where the signature needs more, it scrolls
 *  nothing, and the signature stays where the layout put it. A phone (the signature hundreds of pixels
 *  down) and Classic at 1100×800 (21-22px, which cut "Demo sample — signing is disabled." under the
 *  register head's rule) therefore scroll nothing. `signBottom` and `firstLine` are measured from the top
 *  of the body's content (as if it were not scrolled); `view` is the height the body shows. */
export function signatureScroll(view: number, signBottom: number, firstLine: number): number {
  const want = Math.ceil(signBottom - view);
  return want > 0 && want <= Math.floor(firstLine) ? want : 0;
}

/** Where the first text (or mark) the body draws begins, in the viewport: the top of the content box of
 *  the element that holds the first text node that is drawn (an svg mark counts as drawn too). Words that
 *  are visually hidden or not drawn are skipped. Null when the body draws nothing. */
function firstLineTop(body: HTMLElement): number | null {
  const walker = document.createTreeWalker(body, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    let el: Element | null;
    if (node.nodeType === Node.TEXT_NODE) {
      if (!node.textContent || !node.textContent.trim()) continue;
      el = node.parentElement;
    } else {
      el = (node as Element).localName === 'svg' ? node as Element : null;
    }
    if (!el || el.closest('[data-visually-hidden], [hidden]')) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    return r.top + (el.clientTop || 0) + (parseFloat(cs.paddingTop) || 0);
  }
  return null;
}

/** The signature the docket draws in its open entry: the typed line, or the row with Sign where the
 *  request takes one or two steps (an entry that signs in Decisions draws neither). */
const SIGNATURE = '.n-entry--open :is(.n-signline, .n-entry__signrow)';

/** The open entry's signature whole in the body's view as the docket first draws it (PHASE_B_PLAN.md
 *  §9.5: at 1280×800 "the open entry's SignLine is fully visible"; §5.1: from 1340px the open entry
 *  is shown in full). The layout gives it that room in every look, with one exception measured: in
 *  Classic, in Romanian, at 1280×800, the label voice (mono capitals, tracked) breaks the open entry's
 *  risk line and the docket's total onto second lines, and 3px of the demo sample's sign line lie
 *  below what the body shows. There, and wherever the owner's own data does the same, the body is
 *  scrolled down by what is hidden, if that takes away only the blank above the body's first line (the
 *  docket's state line, or the column heads, or the entry's tier word), so nothing the docket says is cut
 *  and the whole entry, the decision and the signature are all in view; where it would cut anything (below
 *  760px the signature lies far below the view; Classic at 1100×800 needs 21-22px, which cut the demo's
 *  state line under the head's rule) nothing is scrolled. It acts on the entry first drawn open, when
 *  it is drawn and whenever the body or what it holds changes size (a font arriving, the window
 *  resized), until the owner scrolls the body or another entry opens; where nothing is hidden it
 *  scrolls nothing, and it scrolls nothing but the body. */
function useSignatureInView(table: React.RefObject<HTMLDivElement | null>, openKey: string | null) {
  const first = useRef<string | null>(null);
  const over = useRef(false);
  useLayoutEffect(() => {
    if (over.current || openKey === null) return undefined;
    if (first.current === null) first.current = openKey;
    if (openKey !== first.current) { over.current = true; return undefined; }
    const root = table.current;
    const body = root?.closest<HTMLElement>('.n-register__body') ?? null;
    if (!root || !body) return undefined;
    let wrote: number | null = null;   // the scrollTop written here, until its scroll event arrives
    const fit = () => {
      if (over.current) return;
      const sign = root.querySelector<HTMLElement>(SIGNATURE);
      const entry = root.querySelector<HTMLElement>('.n-entry--open');
      if (!sign || !entry || body.clientHeight <= 0) return;
      const top = body.getBoundingClientRect().top + body.clientTop - body.scrollTop;
      const first = firstLineTop(body) ?? entry.getBoundingClientRect().top;
      const want = signatureScroll(body.clientHeight, sign.getBoundingClientRect().bottom - top, first - top);
      if (Math.abs(body.scrollTop - want) < 1) return;
      wrote = want;
      body.scrollTop = want;
    };
    const stop = () => { over.current = true; detach(); };
    // a scroll that is not this hook's own is the owner's: it is never undone
    const onScroll = () => {
      if (wrote !== null && Math.abs(body.scrollTop - wrote) < 1) { wrote = null; return; }
      stop();
    };
    const resized = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => fit());
    function detach() {
      body?.removeEventListener('scroll', onScroll);
      resized?.disconnect();
    }
    fit();
    body.addEventListener('scroll', onScroll, { passive: true });
    resized?.observe(body);
    resized?.observe(root);
    return detach;
  }, [openKey]); // eslint-disable-line react-hooks/exhaustive-deps
}

/** "Trust › Payments": a page's place in the navigation registry, in the owner's language. */
function crumb(panelId: string, lang: Lang): string | null {
  const page = pageForPanel(panelId);
  if (!page) return null;
  const area = areaById(page.area);
  return area ? `${textOf(area.label, lang)} › ${textOf(page.label, lang)}` : textOf(page.label, lang);
}

/** An entry as one request stands for it: its key plus the request it signs. A hub group keeps its
 *  key when it promotes its next leader; this does not, so that entry is drawn afresh. */
const uidOf = (entry: DocketEntry) => `${entry.key}|${entry.taskId}`;

/** Send one decision about an entry (api/decisions.ts) and say what it came to. */
async function send(entry: DocketEntry, decision: EntryDecision): Promise<Outcome> {
  const reason = decision.reason ?? '';
  switch (decision.verb) {
    case 'sign': return outcomeOfDecision(await decide(entry.taskId, 'accept', { reason }), 'sign');
    case 'edit': return outcomeOfDecision(await decide(entry.taskId, 'edit', { payload: decision.payload, reason }), 'edit');
    case 'defer': return outcomeOfDecision(await decide(entry.taskId, 'defer', { reason }), 'defer');
    case 'reject': return outcomeOfDecision(await decide(entry.taskId, 'reject', { reason }), 'reject');
    case 'rejectGroup':
      if (!entry.group) return { kind: 'notSent' };
      return outcomeOfDecision(await rejectGroup(entry.group, reason), 'rejectGroup', entry.memberIds.length);
    case 'rejectAll': return outcomeOfEach(await rejectEach(entry.memberIds, { reason }), entry.memberIds.length);
    default: return { kind: 'notSent' };
  }
}

/** The register's decisions: the requests in flight, and the last outcome of each request. */
function useDecisions(live: boolean) {
  const inflight = useRef(new Set<number>());
  const seq = useRef(0);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const [pending, setPending] = useState<ReadonlySet<number>>(() => new Set());
  const [records, setRecords] = useState<ReadonlyMap<number, DecisionRecord>>(() => new Map());

  const decideEntry = async (entry: DocketEntry, decision: EntryDecision): Promise<boolean> => {
    if (!live) return false;
    const ids = decisionIds(entry, decision.verb);
    if (ids.some((id) => inflight.current.has(id))) return false;     // one decision per request at a time
    ids.forEach((id) => inflight.current.add(id));
    setPending(new Set(inflight.current));
    let outcome: Outcome;
    try {
      outcome = await send(entry, decision);
    } catch {
      outcome = { kind: 'notSent' };     // the client would not send it as asked: nothing was posted
    } finally {
      ids.forEach((id) => inflight.current.delete(id));
    }
    if (mounted.current) {
      setPending(new Set(inflight.current));
      seq.current += 1;
      const record: DecisionRecord = { seq: seq.current, verb: decision.verb, taskId: entry.taskId, ids, title: entry.title, outcome };
      setRecords((previous) => withRecord(previous, record));
    }
    return outcome.kind === 'done';
  };
  return { pending, records, decideEntry };
}

export interface DocketProps {
  lang: Lang;
  demo: boolean;
  /** navigateHud: logical paths only. */
  navigate: (path: string) => void;
}

export function Docket({ lang, demo, navigate }: DocketProps) {
  const s = pick(DOCKET_STRINGS, lang);
  const docket = useDocket({ demo, lang });
  const { state } = docket;
  const model = state === 'refused' ? null : docket.value;
  const entries = model?.entries ?? [];
  const mode: EntryMode = demo || state === 'demo' ? 'demo' : state === 'live' ? 'live' : 'stale';
  const decisions = useDecisions(mode === 'live');
  // The open entry: the one chosen, by key, or the entry now holding a request it held.
  const [chosen, setChosen] = useState<{ key: string; ids: readonly number[] } | null>(null);
  const [armedUid, setArmedUid] = useState<string | null>(null);
  const [focusReq, setFocusReq] = useState<{ uid: string; focus: 'sign' | 'title' } | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const hash = useLocationHash();
  const hashTask = docketTaskFromHash(hash);
  const handled = useRef('');
  const open = (chosen && (entries.find((e) => e.key === chosen.key)
    ?? entries.find((e) => e.memberIds.some((id) => chosen.ids.includes(id))))) || entries[0] || null;
  const now = Date.now();
  const table = useRef<HTMLDivElement>(null);
  useSignatureInView(table, open?.key ?? null);

  const onOpen = (entry: DocketEntry, how: { arm?: boolean; focus?: 'sign' | 'title' } = {}) => {
    setChosen({ key: entry.key, ids: entry.memberIds });
    setArmedUid(how.arm ? uidOf(entry) : null);
    setFocusReq(how.focus ? { uid: uidOf(entry), focus: how.focus } : null);
  };

  // #docket-entry-<id>: open the entry holding the request, once per hash and entry.
  useEffect(() => {
    if (hashTask === null || !model) return;
    const entry = entryHolding(model, hashTask);
    const mark = `${hash}|${entry?.key ?? ''}`;
    if (handled.current === mark) return;
    handled.current = mark;
    if (entry) onOpen(entry, { focus: 'title' });
  }, [hash, hashTask, model]); // eslint-disable-line react-hooks/exhaustive-deps

  const go = (path: string) => (ev: React.MouseEvent) => { ev.preventDefault(); navigate(path); };
  const refresh = async () => {
    setRefreshing(true);
    try { await docket.refresh(); } finally { if (mounted.current) setRefreshing(false); }
  };
  const refreshButton = (
    <button type="button" className="n-btn n-btn--sm" data-docket-refresh="" onClick={() => { void refresh(); }} disabled={refreshing}>
      {refreshing ? s.refreshing : s.refresh}
    </button>
  );
  const lastGood = docket.lastGoodAt !== null ? fmt(s.offlineSince, { time: clock(docket.lastGoodAt) }) : s.offline;

  const elsewhere = model?.elsewhere;
  const other = [
    elsewhere?.payments ? { key: 'payments', what: plural(lang, s.otherPayments, elsewhere.payments), where: crumb('payments', lang) ?? PAYMENTS_PAGE, path: PAYMENTS_PAGE } : null,
    elsewhere?.skillChanges ? { key: 'skills', what: plural(lang, s.otherSkills, elsewhere.skillChanges), where: crumb('decision-inbox', lang) ?? DECISIONS_PATH, path: DECISIONS_PATH } : null,
  ].filter((o): o is { key: string; what: string; where: string; path: string } => o !== null);

  let notice: React.ReactNode = null;
  if (state === 'unknown' && docket.reason === 'checking') {
    notice = <p className="n-docket__state" data-docket-state="checking" role="status"><Mark kind="unknown" /> {s.checking}</p>;
  } else if (state === 'refused') {
    const where = crumb('trust-ops', lang) ?? TRUST_OPS_PAGE;
    notice = (
      <div className="n-docket__state" data-docket-state="refused" role="status">
        <p className="n-docket__state-line"><Mark kind="blocked" /><span>{s.refused}</span></p>
        {isNetworkedOrigin()
          ? <p className="n-docket__state-line"><button type="button" className="n-btn n-btn--sm" onClick={() => requireSignIn()}>{s.signIn}</button></p>
          : <p className="n-docket__state-line">{fillNodes(s.refusedLoopback, {
            link: <a className="n-link" href={routeHref(TRUST_OPS_PAGE)} onClick={go(TRUST_OPS_PAGE)}>{where}</a> })}</p>}
      </div>
    );
  } else if (state === 'offline' || (state === 'unknown') || state === 'stale' || state === 'disabled') {
    const words = state === 'offline' ? lastGood
      : state === 'stale' ? fmt(s.staleSince, { time: docket.lastGoodAt !== null ? clock(docket.lastGoodAt) : '—' })
      : fmt(s.unknownWhy, { reason: reasonWords(docket.reason, lang, docket.status) ?? stateWord(state, lang) });
    notice = (
      <div className="n-docket__state" data-docket-state={state === 'disabled' ? 'unknown' : state} role="status">
        <p className="n-docket__state-line"><Mark kind={state === 'stale' ? 'stale' : 'unknown'} /><span>{words}</span></p>
        {entries.length > 0 && <p className="n-docket__state-line"><span>{s.refreshBeforeSigning}</span>{refreshButton}</p>}
        {entries.length === 0 && state !== 'disabled' && <p className="n-docket__state-line">{refreshButton}</p>}
      </div>
    );
  } else if (state === 'demo') {
    notice = <p className="n-docket__state" data-docket-state="demo">{s.demo}</p>;
  } else if (state === 'empty') {
    // "Nothing is waiting for you" would contradict "Other things waiting" under it.
    notice = <p className="n-docket__state" data-docket-state="empty">{other.length > 0 ? s.emptyHere : s.empty}</p>;
  }

  const missing = hashTask !== null && model && (state === 'live' || state === 'empty') && !entryHolding(model, hashTask);
  const missingNotice = missing && (
    <p className="n-docket__state" data-docket-state="not-on-docket" role="status">
      {fmt(s.notOnDocket, { id: hashTask })}{' '}
      <a className="n-link" href={decisionsHref(hashTask)} onClick={(ev) => { ev.preventDefault(); openDecisionsCard(hashTask); }}>{s.openItInDecisions}</a>
    </p>
  );

  // Each outcome is drawn in the entry that still holds its request, or else here.
  const placed = placeRecords(entries, decisions.records);
  const outcomes = placed.loose.length > 0 && (
    <div className="n-docket__outcomes" data-docket-outcomes="">
      {placed.loose.map((record) => (
        <OutcomeLine key={record.seq} lang={lang} record={record} about className="n-docket__outcome" />
      ))}
    </div>
  );

  const hasEntries = entries.length > 0;
  const title = hasEntries
    ? <><span className="n-docket__figure" data-figure-state={state}>{entries.length}</span>{' '}
      <span className="n-docket__words">{plural(lang, s.awaitTitle, entries.length)}</span></>
    : s.name;

  const otherLine = other.length > 0 && (
    <p className="n-docket__other" data-docket-other="">
      <span className="n-docket__other-lead">{s.otherWaiting}</span>{' '}
      {other.map((o, i) => (
        <span key={o.key} className="n-docket__other-item">{i > 0 ? ' · ' : ''}
          {fillNodes(s.otherIn, { what: o.what, where: <a className="n-link" href={routeHref(o.path)} onClick={go(o.path)}>{o.where}</a> })}</span>
      ))}
    </p>
  );
  const summary = model?.summary;
  // Off a live reading the counts are the last good reading's, and the total says so.
  const current = state === 'live' || state === 'demo';
  const asOf = !current && (
    <span className="n-docket__total-asof"><Mark kind="stale" lang={lang} />
      <span>{fmt(s.totalLastGood, { time: docket.lastGoodAt !== null ? clock(docket.lastGoodAt) : '—' })}</span>{' · '}</span>
  );
  const inDecisions = summary?.friction.inDecisions ?? 0;
  const foot = hasEntries && summary ? (
    <>
      {otherLine}
      <Total className={current ? 'n-docket__total' : 'n-docket__total n-docket__total--stale'} aside={<>
        <span>{plural(lang, s.mixTyped, summary.friction.typed)}</span>
        <span>{plural(lang, s.mixTwoStep, summary.friction.twoStep)}</span>
        <span>{plural(lang, s.mixClick, summary.friction.click)}</span>
        {inDecisions > 0 && <span>{plural(lang, s.mixInDecisions, inDecisions)}</span>}
      </>}>
        {asOf}<b>{plural(lang, s.totalEntries, summary.entries)}</b>{' · '}<span>{plural(lang, s.totalRequests, summary.requests)}</span>
      </Total>
    </>
  ) : state === 'empty' ? (
    <>{otherLine}<Total className="n-docket__total"><b>{plural(lang, s.totalEntries, 0)}</b></Total></>
  ) : null;

  return (
    <Register title={title} id="docket" register="docket" className="n-docket"
      meta={<SourceLabel reading={docket} lang={lang} />} foot={foot}>
      {notice}
      {missingNotice}
      {outcomes}
      {hasEntries && (
        /* one grid for the column heads and every entry (docket.css): the columns line up across
           rows, and Risk is as wide as the widest tier word drawn in it */
        <div className="n-docket__table" ref={table}>
          <div className="n-docket__cols" aria-hidden="true">
            <span>{s.colRisk}</span><span>{s.colEntry}</span><span>{s.colHand}</span>
          </div>
          <ol className="n-docket__list" data-mode={mode}>
            {entries.map((entry, i) => {
              const uid = uidOf(entry);
              return (
                <DocketEntryView key={uid} entry={entry} open={open?.key === entry.key} lang={lang} mode={mode}
                  armed={armedUid === uid} busy={entry.memberIds.some((id) => decisions.pending.has(id))}
                  outcome={placed.inEntry[i]}
                  onOpen={(how) => onOpen(entry, how)} onArm={(on) => setArmedUid(on ? uid : null)}
                  onDecide={(decision) => decisions.decideEntry(entry, decision)}
                  focus={focusReq?.uid === uid ? focusReq.focus : null} onFocused={() => setFocusReq(null)} now={now} />
              );
            })}
          </ol>
        </div>
      )}
    </Register>
  );
}

export interface DocketLineProps {
  lang: Lang;
  demo: boolean;
  /** The window's "Open in app" handoff; the line repeats it only when given one. */
  onOpenInApp?: () => void;
}

/** The floating window's one line (§5.1): "⊛ N await your signature — sign in the main window".
 *  No signing here. Nothing is drawn while the feed is first being read, or when it answered —
 *  just now — that nothing waits. When it cannot be read, or its last answer is too old, the line
 *  says so, even when that last answer was "nothing": unknown is never an all-clear. */
export function DocketLine({ lang, demo, onOpenInApp }: DocketLineProps) {
  const s = pick(DOCKET_STRINGS, lang);
  const summary = useDocketSummary({ demo });
  const { state } = summary;
  const n = summary.value?.entries ?? 0;
  if (state === 'empty' || state === 'disabled' || (state === 'unknown' && summary.reason === 'checking')) return null;
  if ((state === 'live' || state === 'demo') && n === 0) return null;
  // A count is shown only when there is one to show: a last good "0" is no count at all.
  const counted = n > 0;
  let words: React.ReactNode;
  if (counted) {
    words = <><Mark kind="seal-open" /><span>{plural(lang, s.lineAwait, n)}</span>{state !== 'live' && <SourceLabel reading={summary} lang={lang} showTime={false} />}</>;
  } else if (state === 'stale') {
    words = <><Mark kind="stale" /><span>{fmt(s.lineStale, { time: summary.lastGoodAt !== null ? clock(summary.lastGoodAt) : '—' })}</span></>;
  } else {
    words = <><Mark kind="unknown" /><span>{fmt(s.lineUnknown, { reason: reasonWords(summary.reason, lang, summary.status) ?? stateWord(state, lang) })}</span></>;
  }
  return (
    <p className="n-docket__line" data-docket-line={state}>
      {/* a flex row with a gap: no spaces between its parts */}
      {words}
      {onOpenInApp && <button type="button" className="n-btn n-btn--sm n-btn--quiet" onClick={onOpenInApp}>{s.openInApp}</button>}
    </p>
  );
}
