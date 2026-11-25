/* Trust · Overview (/v2/trust): the record, and the owner's authority (secondary.html parity;
   PHASE_B_PLAN.md §6). Replaces TrustMode under the Ledger frame.

   The record: the chain's verdict (a read-only "Verify again"), the newest entries as a ledger
   (RecordTable over /api/security/audit/intent) and the payments broker.
   Your authority: the emergency stop and its typed resume, the capability grants (live data only:
   the seeded list is drawn only in demo, labelled), and where work ran as a count with its basis.

   Honesty: every section carries its source label; refused, offline and unknown are said, never
   drawn as 0 or "intact"; demo disables every decision control. Money waits for the owner: a
   payment is approved by typing its amount, rejected in one click, settled in two steps. */
import React, { useMemo, useRef, useState } from 'react';
import { Consequence, Mark, Register, SecHead, SourceLabel, Total, basisWords, clockTime } from '../frame/kit';
import { useHeadRow } from '../frame/kit/Register';
import { hubReading } from '../frame/types';
import { defineStrings, fmt, pick, plural, type Lang } from '../frame/strings';
import { useApprovalMode, useAuditVerify } from '../signals/hooks';
import type { AuditVerify } from '../signals/wire';
import type { HubSnapshot, Reading } from '../signals/types';
import { useKillSwitch } from '../frame/useKillSwitch';
import { decidePayment, setKillSwitch } from '../api/actions';
import { refusalReason } from '../panel-kit';
import { V2 } from '../data';
import { TypedAction, TwoStepAction, type FrictionStrings } from './Friction';
import { RecordTable } from './RecordTable';
import { NoReading, PageLink, drawable } from './common';
import { LOCAL_ONLY_AGENTS, CLOUD_ONLY_AGENTS, rosterAgents } from './agent-states';
import {
  usePaymentsFeed, useRecordFeed, useRunningFeed, useSubagentsFeed,
  type PaymentRow, type RecordEntry, type RecordFeed,
} from './sources';
import { IDENT } from '../theme/type';
import './pages.css';

export const TRUST_STRINGS = defineStrings({
  en: {
    recordTitle: 'The record',
    recordMeta: 'Audit chain · every action, sealed',
    authorityTitle: 'Your authority',
    approvalMode: 'Approval mode {mode}',
    modeAuto: 'Auto',
    modeAsk: 'Ask',
    modeOff: 'Off',
    chainIntact: 'Intact',
    chainBroken: 'Broken',
    chainUnknown: 'Not verified',
    chainDemo: 'Demo sample',
    verifiedAt: 'verified {time}',
    verifyAgain: 'Verify again',
    verifyNote: 'verifying is read only',
    chainLine: { one: 'Chain intact: {n} sealed entry', few: 'Chain intact: {n} sealed entries', other: 'Chain intact: {n} sealed entries' },
    chainLineNoCount: 'Chain intact',
    brokenLine: 'Chain broken at entry {n}',
    brokenLineNoId: 'Chain broken: an entry no longer matches its seal',
    unknownLine: 'The chain has not been verified',
    demoLine: 'A demo sample: this is not a real chain',
    explain: 'Every action is an entry. Each entry is sealed with the hash of the one before it, so changing any entry would break every seal after it.',
    unkeyed: 'Unkeyed: this proves integrity only, not tamper evidence. Anyone with file access could recompute the chain.',
    keyed: 'Keyed: an edit cannot be recomputed without the audit key.',
    entriesEmpty: 'No entries in the record yet.',
    recordShown: '{shown} shown · {total} in the record',
    recordShownOnly: '{shown} shown',
    openChain: 'Open the audit panels',
    paymentsTitle: 'Payments',
    paymentsAside: 'money always waits for you',
    paymentsEmpty: 'No payments.',
    paymentWaiting: 'Waiting for approval',
    paymentApproved: 'Approved, not yet settled',
    paymentRejected: 'Rejected',
    paymentSettled: 'Settled',
    paymentOther: 'State: {state}',
    approve: 'Approve',
    approveConfirm: 'Approve payment',
    approvePrompt: 'Type {amount} to approve this payment to {payee}.',
    approveField: 'Type {amount} to approve the payment of {amount} to {payee}',
    amountMissing: 'Amount not reported',
    reject: 'Reject',
    settle: 'Settle',
    settleConfirm: 'Settle payment',
    settlePrompt: 'Settle the approved payment to {payee}?',
    cancel: 'Cancel',
    working: 'Working…',
    refusedAction: 'The hub did not accept this. Nothing changed.',
    payRefused: 'The hub refused: {why}',
    payUnanswered: 'The hub did not answer. The payment may or may not have changed; check the list.',
    resumeUnanswered: 'The hub did not answer. It may or may not have resumed; check the stop state.',
    payCount: { one: '{n} payment', few: '{n} payments', other: '{n} payments' },
    payWaiting: 'Waiting {amounts}',
    payNoneWaiting: 'Nothing waits for approval',
    stopTitle: 'Emergency stop',
    stopArmed: 'Armed',
    stopHalted: 'Halted',
    stopUnknown: 'Unknown',
    stopArmedNote: 'one click, no confirmation',
    stopHaltedNote: 'every agent and the job queue are held',
    stopUnknownNote: 'the stop is still offered',
    stopScoped: { one: '{n} agent-scoped halt is in force; the global stop is armed and halts everything.', few: '{n} agent-scoped halts are in force; the global stop is armed and halts everything.', other: '{n} agent-scoped halts are in force; the global stop is armed and halts everything.' },
    stopButton: 'Stop all agents',
    stopNote: 'One click. Halts every agent and the job queue until you resume.',
    stopFailed: 'The stop was not confirmed: {why}',
    wouldHalt: 'Would halt now',
    wouldHaltNames: '{names}, who are working, and the job queue.',
    wouldHaltNone: 'No agent is working now; the job queue would stop.',
    toUndo: 'To undo',
    toUndoText: 'Resume. Nothing restarts on its own.',
    resume: 'Resume',
    resumeConfirm: 'Resume all agents',
    resumePrompt: 'Type DISENGAGE to resume every agent. Scoped halts may remain.',
    resumeField: 'Type DISENGAGE to resume the agents',
    capsTitle: 'Capabilities',
    capsAside: 'what agents may do without asking',
    capsNotReported: 'The hub does not report capability grants here. Open Capabilities to read them.',
    capsOpen: 'Open Capabilities',
    capsColumns: 'Capability, what it allows, grant',
    capName: 'Capability',
    capAllows: 'What it allows',
    capGrant: 'Grant',
    grantAllow: 'Allow',
    grantScoped: 'Scoped',
    grantGated: 'Gated',
    grantApproval: 'Approval',
    whereTitle: 'Where work ran',
    whereAside: 'all time',
    whereFigure: '{local} of {total} runs',
    whereWhat: 'sent to local runners',
    whereBasisLine: 'by route',
    whereCloud: '{cloud} sent to the cloud',
    whereUnclassified: '{n} not classified',
    whereNone: 'No run has been counted yet.',
    whereUnknown: 'Where work ran is unknown: the hub did not report it.',
    whereDemo: 'No figure is drawn for a demo sample.',
    splitLabel: '{local} local, {cloud} cloud, {unknown} not classified',
    basis: 'Basis',
    ladder: 'How the figure is known',
    rungUnknown: 'Unknown',
    rungDerived: 'Derived',
    rungRoute: 'By route',
    rungVerified: 'Verified',
    rungLater: 'not available yet',
    basisNote: 'Counted from the route each run used, local or cloud. Not a network measurement: a verified figure needs one, and the hub does not take it yet.',
    egress: 'Egress',
    egressNone: 'No cloud model configured',
    egressSome: 'A cloud model is configured',
    egressUnknown: 'Not reported',
    egressDeclared: 'a setting, not a measurement',
    localOnly: 'Local only, by code',
    cloudOnly: 'Cloud only',
    athenaBlocked: 'Athena — unavailable while no cloud model is configured',
    athenaOpen: 'Athena',
    names: '{names}',
    namesAnd: '{head} and {last}',
    demoNotice: 'Demo sample. Every decision control is off.',
    demoOff: 'Off in demo',
    needsLive: 'Needs a live reading of the hub',
  },
  ro: {
    recordTitle: 'Registrul',
    recordMeta: 'Lanț de audit · fiecare acțiune, sigilată',
    authorityTitle: 'Autoritatea ta',
    approvalMode: 'Mod de aprobare {mode}',
    modeAuto: 'Automat',
    modeAsk: 'Întreabă',
    modeOff: 'Oprit',
    chainIntact: 'Intact',
    chainBroken: 'Rupt',
    chainUnknown: 'Neverificat',
    chainDemo: 'Mostră demo',
    verifiedAt: 'verificat la {time}',
    verifyAgain: 'Verifică din nou',
    verifyNote: 'verificarea este doar citire',
    chainLine: { one: 'Lanț intact: {n} intrare sigilată', few: 'Lanț intact: {n} intrări sigilate', other: 'Lanț intact: {n} de intrări sigilate' },
    chainLineNoCount: 'Lanț intact',
    brokenLine: 'Lanț rupt la intrarea {n}',
    brokenLineNoId: 'Lanț rupt: o intrare nu se mai potrivește cu sigiliul ei',
    unknownLine: 'Lanțul nu a fost verificat',
    demoLine: 'O mostră demo: acesta nu este un lanț real',
    explain: 'Fiecare acțiune este o intrare. Fiecare intrare este sigilată cu hash-ul celei dinaintea ei, deci modificarea oricărei intrări ar rupe toate sigiliile de după ea.',
    unkeyed: 'Fără cheie: dovedește doar integritatea, nu și protecția la modificare. Oricine are acces la fișier ar putea recalcula lanțul.',
    keyed: 'Cu cheie: o modificare nu poate fi recalculată fără cheia de audit.',
    entriesEmpty: 'Încă nu există intrări în registru.',
    recordShown: '{shown} afișate · {total} în registru',
    recordShownOnly: '{shown} afișate',
    openChain: 'Deschide panourile de audit',
    paymentsTitle: 'Plăți',
    paymentsAside: 'banii te așteaptă mereu',
    paymentsEmpty: 'Nicio plată.',
    paymentWaiting: 'Așteaptă aprobarea',
    paymentApproved: 'Aprobată, încă nedecontată',
    paymentRejected: 'Respinsă',
    paymentSettled: 'Decontată',
    paymentOther: 'Stare: {state}',
    approve: 'Aprobă',
    approveConfirm: 'Aprobă plata',
    approvePrompt: 'Scrie {amount} pentru a aproba această plată către {payee}.',
    approveField: 'Scrie {amount} pentru a aproba plata de {amount} către {payee}',
    amountMissing: 'Suma nu este raportată',
    reject: 'Respinge',
    settle: 'Decontează',
    settleConfirm: 'Decontează plata',
    settlePrompt: 'Decontezi plata aprobată către {payee}?',
    cancel: 'Anulează',
    working: 'Se lucrează…',
    refusedAction: 'Hubul nu a acceptat acest lucru. Nimic nu s-a schimbat.',
    payRefused: 'Hubul a refuzat: {why}',
    payUnanswered: 'Hubul nu a răspuns. Plata s-ar putea să fi fost schimbată sau nu; verifică lista.',
    resumeUnanswered: 'Hubul nu a răspuns. S-ar putea să fi reluat sau nu; verifică starea opririi.',
    payCount: { one: '{n} plată', few: '{n} plăți', other: '{n} de plăți' },
    payWaiting: 'În așteptare {amounts}',
    payNoneWaiting: 'Nimic nu așteaptă aprobarea',
    stopTitle: 'Oprire de urgență',
    stopArmed: 'Armată',
    stopHalted: 'Oprit',
    stopUnknown: 'Necunoscut',
    stopArmedNote: 'un clic, fără confirmare',
    stopHaltedNote: 'toți agenții și coada de joburi sunt ținuți pe loc',
    stopUnknownNote: 'oprirea rămâne disponibilă',
    stopScoped: { one: '{n} oprire pe agent este în vigoare; oprirea globală e armată și oprește totul.', few: '{n} opriri pe agent sunt în vigoare; oprirea globală e armată și oprește totul.', other: '{n} de opriri pe agent sunt în vigoare; oprirea globală e armată și oprește totul.' },
    stopButton: 'Oprește toți agenții',
    stopNote: 'Un clic. Oprește toți agenții și coada de joburi până reiei.',
    stopFailed: 'Oprirea nu a fost confirmată: {why}',
    wouldHalt: 'Ar opri acum',
    wouldHaltNames: '{names}, care lucrează, și coada de joburi.',
    wouldHaltNone: 'Niciun agent nu lucrează acum; coada de joburi s-ar opri.',
    toUndo: 'Pentru a anula',
    toUndoText: 'Reia. Nimic nu repornește singur.',
    resume: 'Reia',
    resumeConfirm: 'Reia toți agenții',
    resumePrompt: 'Scrie DISENGAGE pentru a relua toți agenții. Pot rămâne opriri pe agent.',
    resumeField: 'Scrie DISENGAGE pentru a relua agenții',
    capsTitle: 'Capacități',
    capsAside: 'ce pot face agenții fără să întrebe',
    capsNotReported: 'Hubul nu raportează aici acordările de capacități. Deschide Capacități pentru a le citi.',
    capsOpen: 'Deschide Capacități',
    capsColumns: 'Capacitate, ce permite, acordare',
    capName: 'Capacitate',
    capAllows: 'Ce permite',
    capGrant: 'Acordare',
    grantAllow: 'Permis',
    grantScoped: 'Limitat',
    grantGated: 'Condiționat',
    grantApproval: 'Aprobare',
    whereTitle: 'Unde a rulat munca',
    whereAside: 'tot timpul',
    whereFigure: '{local} din {total} rulări',
    whereWhat: 'trimise către runnere locale',
    whereBasisLine: 'după rută',
    whereCloud: '{cloud} trimise în cloud',
    whereUnclassified: '{n} neclasificate',
    whereNone: 'Nicio rulare nu a fost numărată încă.',
    whereUnknown: 'Unde a rulat munca este necunoscut: hubul nu a raportat.',
    whereDemo: 'Pentru o mostră demo nu se desenează nicio cifră.',
    splitLabel: '{local} locale, {cloud} în cloud, {unknown} neclasificate',
    basis: 'Bază',
    ladder: 'Cum este cunoscută cifra',
    rungUnknown: 'Necunoscut',
    rungDerived: 'Dedus',
    rungRoute: 'După rută',
    rungVerified: 'Verificat',
    rungLater: 'încă indisponibil',
    basisNote: 'Numărat după ruta folosită de fiecare rulare, locală sau cloud. Nu este o măsurătoare de rețea: o cifră verificată ar avea nevoie de una, iar hubul nu o face încă.',
    egress: 'Ieșire în rețea',
    egressNone: 'Niciun model cloud configurat',
    egressSome: 'Un model cloud este configurat',
    egressUnknown: 'Neraportat',
    egressDeclared: 'o setare, nu o măsurătoare',
    localOnly: 'Doar local, prin cod',
    cloudOnly: 'Doar cloud',
    athenaBlocked: 'Athena — indisponibilă cât timp niciun model cloud nu este configurat',
    athenaOpen: 'Athena',
    names: '{names}',
    namesAnd: '{head} și {last}',
    demoNotice: 'Mostră demo. Toate comenzile de decizie sunt oprite.',
    demoOff: 'Oprit în demo',
    needsLive: 'Necesită o citire în direct a hubului',
  },
});

type T = typeof TRUST_STRINGS.en;

const DEMO_RECORD: RecordFeed = {
  chainOk: null,
  entries: (V2.AUDIT_CHAIN as Array<{ verb: string; x: string; hash: string }>).map((b, i): RecordEntry => ({
    seq: i + 1, at: null, actor: null, action: b.verb, why: b.x, hash: b.hash, tier: null,
  })),
};

const demoPayments = (): readonly PaymentRow[] => (V2.PAYMENTS as Array<{ pcap: string; desc: string; amt: string; state: string }>).map((p, i) => ({
  id: `demo-${i}`, payee: p.pcap, memo: p.desc, amount: Number(String(p.amt).replace(/[^0-9.]/g, '')) || null, currency: /€/.test(p.amt) ? 'EUR' : null,
  state: p.state === 'pending' ? 'pending' : p.state === 'cleared' ? 'settled' : 'other', stateWord: p.state, createdAt: null,
}));

export function money(amount: number, currency: string | null, lang: Lang | string): string {
  if (currency) {
    try { return new Intl.NumberFormat(lang === 'ro' ? 'ro-RO' : 'en-GB', { style: 'currency', currency }).format(amount); } catch { /* fall through */ }
    return `${amount} ${currency}`;
  }
  return String(amount);
}

const GRANT: Record<string, { word: 'grantAllow' | 'grantScoped' | 'grantGated' | 'grantApproval'; mark: 'ok' | 'held' | 'seal-open'; kind: 'allow' | 'scoped' | 'gated' | 'approval' }> = {
  ALLOW: { word: 'grantAllow', mark: 'ok', kind: 'allow' },
  SCOPED: { word: 'grantScoped', mark: 'ok', kind: 'scoped' },
  GATED: { word: 'grantGated', mark: 'held', kind: 'gated' },
  APPROVAL: { word: 'grantApproval', mark: 'seal-open', kind: 'approval' },
};

export function joinNames(names: readonly string[], lang: Lang | string): string {
  const s = pick(TRUST_STRINGS, lang);
  if (names.length <= 1) return names[0] ?? '';
  return fmt(s.namesAnd, { head: names.slice(0, -1).join(', '), last: names[names.length - 1] });
}

// ---- the record ----------------------------------------------------------------------------------

function ChainVerdict({ lang, demo, reading, refresh, s }: { lang: Lang | string; demo: boolean; reading: Reading<AuditVerify>; refresh: () => Promise<void>; s: T }) {
  const value = reading.value;
  const usable = !demo && value !== null && (reading.state === 'live' || reading.state === 'stale');
  let mark: 'chain' | 'problem' | 'unknown' | 'idle' = 'unknown';
  let word = s.chainUnknown;
  let line = s.unknownLine;
  if (demo) { mark = 'idle'; word = s.chainDemo; line = s.demoLine; }
  else if (usable && value) {
    if (value.valid) {
      mark = 'chain'; word = s.chainIntact;
      line = value.entries !== null ? plural(lang, s.chainLine, value.entries) : s.chainLineNoCount;
    } else {
      mark = 'problem'; word = s.chainBroken;
      line = value.firstInvalidId !== null ? fmt(s.brokenLine, { n: value.firstInvalidId }) : s.brokenLineNoId;
    }
  }
  return (
    <section className="n-chainverdict n-chainverdict--trust" aria-labelledby="trust-chain-line" data-chain-state={demo ? 'demo' : usable && value ? (value.valid ? 'intact' : 'broken') : 'unknown'}>
      <p className="n-chainverdict__state">
        <Mark kind={mark} size="md" lang={lang} />
        <span><b>{word}</b>{usable && reading.lastGoodAt !== null ? ` · ${fmt(s.verifiedAt, { time: clockTime(reading.lastGoodAt) })}` : ''}</span>
        <button type="button" className="n-btn n-btn--sm" disabled={demo} title={demo ? s.demoOff : undefined}
          onClick={() => { void refresh(); }}>{s.verifyAgain}</button>
        <span className="n-chainverdict__note">{s.verifyNote}</span>
      </p>
      <h3 className="n-chainverdict__line" id="trust-chain-line">{line}</h3>
      {usable && value && value.valid && <p className="n-chainverdict__explain">{s.explain}</p>}
      {usable && value && value.valid && value.tamperEvident !== null && <p className="n-chainverdict__explain" data-chain-keyed={String(value.tamperEvident)}>{value.tamperEvident ? s.keyed : s.unkeyed}</p>}
      {!demo && !usable && <NoReading reading={reading} lang={lang} />}
    </section>
  );
}

function PaymentRows({ rows, lang, demo, live, onChanged, s }: { rows: readonly PaymentRow[]; lang: Lang | string; demo: boolean; live: boolean; onChanged: () => Promise<void>; s: T }) {
  const [error, setError] = useState<string | null>(null);
  const decide = async (id: string, action: 'approve' | 'reject' | 'settle'): Promise<boolean> => {
    try {
      await decidePayment(id, action);
      setError(null);
      await onChanged();
      return true;
    } catch (e) {
      setError(typeof (e as { status?: unknown })?.status === 'number' ? fmt(s.payRefused, { why: refusalReason(e) }) : s.payUnanswered);
      return false;
    }
  };
  const off = demo || !live;
  const offTitle = demo ? s.demoOff : !live ? s.needsLive : undefined;
  return (
    <>
      {error && <p className="n-pgnote n-pgnote--alert" role="alert">{error}</p>}
      <div className="n-pay" role="list">
        {rows.map((p) => {
          const shown = p.amount !== null ? money(p.amount, p.currency, lang) : null;
          const phrase = p.amount !== null ? String(p.amount) : null;
          const stateText = p.state === 'pending' ? s.paymentWaiting : p.state === 'approved' ? s.paymentApproved
            : p.state === 'rejected' ? s.paymentRejected : p.state === 'settled' ? s.paymentSettled : fmt(s.paymentOther, { state: p.stateWord });
          const approve: FrictionStrings = { label: s.approve, confirm: s.approveConfirm, cancel: s.cancel, busy: s.working, refused: s.refusedAction,
            prompt: fmt(s.approvePrompt, { amount: phrase ?? '', payee: p.payee }), inputLabel: fmt(s.approveField, { amount: phrase ?? '', payee: p.payee }) };
          const settle: FrictionStrings = { label: s.settle, confirm: s.settleConfirm, cancel: s.cancel, busy: s.working, refused: s.refusedAction, prompt: fmt(s.settlePrompt, { payee: p.payee }) };
          return (
            <div className="n-pay__row" role="listitem" key={p.id} data-payment-state={p.state}>
              <span className="n-pay__who">{p.payee}</span>
              <span className="n-pay__what">{p.memo ?? ''}</span>
              <span className="n-pay__amt">{shown ?? s.amountMissing}</span>
              <span className={'n-pay__state' + (p.state === 'pending' ? ' n-pay__state--hand' : '')}>
                <Mark kind={p.state === 'pending' ? 'seal-open' : p.state === 'settled' ? 'done' : p.state === 'rejected' ? 'blocked' : p.state === 'approved' ? 'attn' : 'unknown'} size="sm" lang={lang} />
                <span>{stateText}</span>
              </span>
              <span className="n-pay__acts">
                {p.state === 'pending' && (
                  <>
                    {phrase !== null
                      ? <TypedAction strings={approve} phrase={phrase} disabled={off} title={offTitle} onConfirm={() => decide(p.id, 'approve')} />
                      : <span className="n-pay__note">{s.amountMissing}</span>}
                    <button type="button" className="n-btn n-btn--sm n-btn--quiet" disabled={off} title={offTitle}
                      onClick={() => { void decide(p.id, 'reject'); }}>{s.reject}</button>
                  </>
                )}
                {p.state === 'approved' && <TwoStepAction strings={settle} disabled={off} title={offTitle} onConfirm={() => decide(p.id, 'settle')} />}
              </span>
            </div>
          );
        })}
      </div>
    </>
  );
}

// ---- the page --------------------------------------------------------------------------------------

export interface TrustOverviewProps { hub: HubSnapshot; lang: Lang | string; demo: boolean; navigate: (path: string) => void }

export function TrustOverview({ hub, lang, demo, navigate }: TrustOverviewProps) {
  const s = pick(TRUST_STRINGS, lang);
  const now = Date.now();
  const chain = useAuditVerify({ demo });
  const record = useRecordFeed({ demo, demoValue: DEMO_RECORD });
  const demoRows = useMemo(demoPayments, []);
  const payments = usePaymentsFeed({ demo, demoValue: demoRows });
  const mode = useApprovalMode({ demo });
  // `lang` words a refused stop's reason, which the sentence around it is in (frame-strings STOP_STRINGS)
  const kill = useKillSwitch(lang);
  const running = useRunningFeed({ enabled: !demo });
  const subs = useSubagentsFeed({ enabled: !demo });
  const [stopError, setStopError] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  // from 1340px the record and your authority stand side by side, each as tall as what it holds: their
  // heads take one height, so the rules under them lie on one line whatever wraps (the record's meta
  // drops under its title in Classic at 1340-1440px)
  const columns = useRef<HTMLDivElement>(null);
  useHeadRow(columns);

  const paymentRows = payments.value ?? [];
  const waiting = paymentRows.filter((p) => p.state === 'pending');
  const waitingByCurrency = new Map<string, number>();
  for (const p of waiting) if (p.amount !== null) waitingByCurrency.set(p.currency ?? '', (waitingByCurrency.get(p.currency ?? '') ?? 0) + p.amount);
  const waitingAmounts = [...waitingByCurrency.entries()].map(([c, n]) => money(n, c || null, lang)).join(' · ');

  const halted = (kill.state === 'live' || kill.state === 'stale') && kill.value ? kill.value.halted : null;
  const stopState = halted === true ? 'halted' : halted === false ? 'armed' : 'unknown';
  const workers = useMemo(() => {
    const answered = (r: { state: string }) => r.state === 'live' || r.state === 'stale' || r.state === 'empty';
    if (!answered(running) || !answered(subs)) return null;
    const names = new Map<string, string>();
    const roster = new Map(rosterAgents(hub.agents).map((a) => [a.id, a.name]));
    for (const t of running.value ?? []) if (t.agent) names.set(t.agent, roster.get(t.agent) ?? t.agent);
    for (const r of subs.value?.runs ?? []) names.set(r.agent, roster.get(r.agent) ?? r.agent);
    return [...names.values()];
  }, [running.state, running.value, subs.state, subs.value, hub.agents]);

  const hubState = hubReading(hub, now);
  const locality = hub.locality;
  const whereReading: Pick<Reading<unknown>, 'state' | 'reason' | 'status' | 'lastGoodAt'> = demo
    ? { state: 'demo', lastGoodAt: null }
    : locality ? { state: hubState.state, reason: hubState.reason, lastGoodAt: hub.lastGoodAt }
      : { state: 'unknown', reason: 'not-reported', lastGoodAt: null };
  /** The figure is the last good one while the hub is out of reach: drawn under its "Offline · last
   *  good" label, never as current. Only a live or stale reading makes the ladder's rung current. */
  const whereShown = !!locality && (whereReading.state === 'live' || whereReading.state === 'stale' || whereReading.state === 'offline');
  const whereCurrent = !!locality && (whereReading.state === 'live' || whereReading.state === 'stale');
  const cloudConfigured = hub.trust ? hub.trust.cloudAvailable || hub.trust.claudeAvailable : null;
  const roster = rosterAgents(hub.agents);
  const nameOf = (id: string) => roster.find((a) => a.id === id)?.name ?? id.charAt(0).toUpperCase() + id.slice(1);

  const stop = async () => {
    if (stopping) return;
    setStopping(true); setStopError(null);
    try {
      const result = await kill.stop();
      if (result.ok === false) setStopError(fmt(s.stopFailed, { why: result.reason }));
    } finally { setStopping(false); }
  };
  const resume = async (): Promise<boolean | string> => {
    try { await setKillSwitch(false); await kill.refresh(); return true; } catch (e) {
      void kill.refresh();
      return typeof (e as { status?: unknown })?.status === 'number' ? fmt(s.payRefused, { why: refusalReason(e) }) : s.resumeUnanswered;
    }
  };

  const entries = record.value?.entries ?? [];
  const capsLive = demo;
  const capsReading: Reading<unknown> = demo ? { state: 'demo', value: null, checkedAt: null, lastGoodAt: null } : { state: 'unknown', value: null, checkedAt: null, lastGoodAt: null, reason: 'not-reported' };

  return (
    <div ref={columns} className="n-trust" data-page="trust" data-demo={demo ? 'true' : undefined}>
      <div id="record" className="n-trust__col">
        <Register title={s.recordTitle} register="trust-record" meta={<><span>{s.recordMeta}</span><SourceLabel reading={chain} lang={lang} verb="verified" /></>}>
          <ChainVerdict lang={lang} demo={demo} reading={chain} refresh={chain.refresh} s={s} />
          {drawable(record) && entries.length > 0
            ? <RecordTable entries={entries} lang={lang} chainOk={demo ? null : record.value?.chainOk ?? null} limit={8} now={now} />
            : drawable(record) ? <p className="n-pgnote">{s.entriesEmpty}</p> : <NoReading reading={record} lang={lang} />}
          {drawable(record) && entries.length > 0 && (
            <Total aside={<PageLink path="/v2/console/audit-anchors" navigate={navigate}>{s.openChain}</PageLink>}>
              <b>{fmt(s.recordShownOnly, { shown: Math.min(entries.length, 8) })}</b>
            </Total>
          )}
          <div id="payments" className="n-trust__block">
            <SecHead title={s.paymentsTitle} aside={<><span>{s.paymentsAside}</span> <SourceLabel reading={payments} lang={lang} /></>} />
            {drawable(payments)
              ? paymentRows.length === 0 ? <p className="n-pgnote">{s.paymentsEmpty}</p>
                : <PaymentRows rows={paymentRows} lang={lang} demo={demo} live={payments.state === 'live'} onChanged={payments.refresh} s={s} />
              : <NoReading reading={payments} lang={lang} />}
            {drawable(payments) && paymentRows.length > 0 && (
              <Total>
                <b>{plural(lang, s.payCount, paymentRows.length)}</b>
                <span> · {waiting.length === 0 ? s.payNoneWaiting : fmt(s.payWaiting, { amounts: waitingAmounts || plural(lang, s.payCount, waiting.length) })}</span>
              </Total>
            )}
          </div>
        </Register>
      </div>

      <div className="n-trust__col">
        <Register title={s.authorityTitle} register="trust-authority"
          meta={mode.state === 'live' && mode.value ? <span>{fmt(s.approvalMode, { mode: mode.value.mode === 'auto' ? s.modeAuto : mode.value.mode === 'ask' ? s.modeAsk : s.modeOff })}</span> : undefined}>
          {demo && <p className="n-pgnote" role="note">{s.demoNotice}</p>}
          <section className="n-stopsheet" id="stop" aria-labelledby="trust-stop-h" data-stop-state={stopState}>
            <h3 className="n-stopsheet__head">
              <span id="trust-stop-h">{s.stopTitle}</span>
              <span className="n-stopsheet__state">
                <Mark kind={stopState === 'armed' ? 'ok' : stopState === 'halted' ? 'held' : 'unknown'} size="sm" lang={lang} />
                <b>{stopState === 'armed' ? s.stopArmed : stopState === 'halted' ? s.stopHalted : s.stopUnknown}</b>
                {` · ${stopState === 'armed' ? s.stopArmedNote : stopState === 'halted' ? s.stopHaltedNote : s.stopUnknownNote}`}
              </span>
            </h3>
            {/* armed, yet some agent is held by its own halt: said, not hidden behind "Armed" */}
            {stopState === 'armed' && kill.value && (kill.value.scoped ?? 0) > 0 && (
              <p className="n-pgnote" data-stop-scoped={kill.value.scoped}>
                <Mark kind="held" size="sm" lang={lang} />{plural(lang, s.stopScoped, kill.value.scoped ?? 0)}
              </p>
            )}
            <div className="n-stopsheet__row">
              {/* live in demo too: it acts on the real hub, and stopping is the safe direction (§4.1),
                  as the masthead's and Glance's do; the typed resume below stays off in demo */}
              <button type="button" className="n-btn n-btn--danger" disabled={stopping || stopState === 'halted'} onClick={() => { void stop(); }}>{s.stopButton}</button>
              <p className="n-stopsheet__note">{s.stopNote}</p>
            </div>
            {stopError && <p className="n-pgnote n-pgnote--alert" role="alert">{stopError}</p>}
            {stopState === 'halted' && (
              <div className="n-stopsheet__resume">
                <TypedAction strings={{ label: s.resume, confirm: s.resumeConfirm, cancel: s.cancel, busy: s.working, refused: s.refusedAction, prompt: s.resumePrompt, inputLabel: s.resumeField }}
                  phrase="DISENGAGE" disabled={demo} onConfirm={resume} />
              </div>
            )}
            <Consequence rows={[
              { term: s.wouldHalt, detail: workers !== null && stopState !== 'halted' ? (workers.length ? fmt(s.wouldHaltNames, { names: joinNames(workers, lang) }) : s.wouldHaltNone) : null },
              { term: s.toUndo, detail: s.toUndoText },
            ]} />
          </section>

          <div id="caps" className="n-trust__block">
            <SecHead title={s.capsTitle} aside={<><span>{s.capsAside}</span> <SourceLabel reading={capsReading} lang={lang} /></>} />
            {capsLive ? (
              <div className="n-caps" role="table" aria-label={s.capsColumns}>
                <div className="n-caps__cols" role="row"><span role="columnheader">{s.capName}</span><span role="columnheader">{s.capAllows}</span><span role="columnheader">{s.capGrant}</span></div>
                {(V2.CAPABILITIES as Array<{ cn: string; cd: string; tagLabel: string }>).map((c) => {
                  const g = GRANT[c.tagLabel] ?? GRANT.GATED;
                  return (
                    <div className="n-caps__row" role="row" key={c.cn} data-grant={g.kind}>
                      <code role="cell" style={IDENT}>{c.cn}</code>
                      <span role="cell">{c.cd}</span>
                      <span role="cell" className={'n-caps__grant' + (g.kind === 'approval' ? ' n-caps__grant--hand' : '')}><Mark kind={g.mark} size="sm" lang={lang} />{s[g.word]}</span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="n-pgnote" data-caps="not-reported">{s.capsNotReported} <PageLink path="/v2/console/capabilities" navigate={navigate}>{s.capsOpen}</PageLink></p>
            )}
          </div>

          <div id="where" className="n-trust__block n-loc">
            <SecHead title={s.whereTitle} aside={<><span>{s.whereAside}</span> <SourceLabel reading={whereReading} lang={lang} /></>} />
            {demo ? <p className="n-pgnote">{s.whereDemo}</p>
              : locality && whereShown ? (
                locality.total > 0 ? (
                  <>
                    <div className="n-loc__figure">
                      <span className="n-loc__big">{fmt(s.whereFigure, { local: locality.local, total: locality.total })}</span>
                      <span className="n-loc__what">{s.whereWhat}<small>{`${s.whereBasisLine}${locality.cloud > 0 ? ` · ${fmt(s.whereCloud, { cloud: locality.cloud })}` : ''}${locality.unknown > 0 ? ` · ${fmt(s.whereUnclassified, { n: locality.unknown })}` : ''}`}</small></span>
                    </div>
                    <div className="n-loc__split" role="img" aria-label={fmt(s.splitLabel, { local: locality.local, cloud: locality.cloud, unknown: locality.unknown })}>
                      <i className="n-loc__seg n-loc__seg--local" style={{ width: `${(locality.local / locality.total) * 100}%` }} />
                      <i className="n-loc__seg n-loc__seg--cloud" style={{ width: `${(locality.cloud / locality.total) * 100}%` }} />
                    </div>
                  </>
                ) : <p className="n-pgnote">{s.whereNone}</p>
              ) : <p className="n-pgnote">{s.whereUnknown}</p>}
            <dl className="n-facts">
              <div>
                <dt>{s.basis}</dt>
                <dd>
                  <ol className="n-ladder" aria-label={s.ladder}>
                    <li className={!demo && !whereCurrent ? 'is-now' : undefined} aria-current={!demo && !whereCurrent ? 'true' : undefined}>{s.rungUnknown}</li>
                    <li>{s.rungDerived}</li>
                    <li className={!demo && whereCurrent ? 'is-now' : undefined} aria-current={!demo && whereCurrent ? 'true' : undefined}>{s.rungRoute}</li>
                    <li className="is-later">{s.rungVerified} <small>({s.rungLater})</small></li>
                  </ol>
                  <small>{s.basisNote}</small>
                </dd>
              </div>
              <div>
                <dt>{s.egress}</dt>
                <dd>
                  <Mark kind={cloudConfigured === null ? 'unknown' : cloudConfigured ? 'attn' : 'ok'} size="sm" lang={lang} />
                  <b>{cloudConfigured === null ? s.egressUnknown : cloudConfigured ? s.egressSome : s.egressNone}</b>
                  {` · ${s.egressDeclared} (${basisWords('declared', lang)})`}
                </dd>
              </div>
              <div><dt>{s.localOnly}</dt><dd>{LOCAL_ONLY_AGENTS.map(nameOf).join(' · ')}</dd></div>
              <div>
                <dt>{s.cloudOnly}</dt>
                <dd>
                  {cloudConfigured === false
                    ? <><Mark kind="blocked" size="sm" lang={lang} />{s.athenaBlocked}</>
                    : CLOUD_ONLY_AGENTS.map(nameOf).join(' · ')}
                </dd>
              </div>
            </dl>
          </div>
        </Register>
      </div>
    </div>
  );
}

