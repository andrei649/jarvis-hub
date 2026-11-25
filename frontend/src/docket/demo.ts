/* The docket's demo sample (PHASE_B_PLAN.md §5.4): the six entries of the Ledger mockup
   (docs/design/hud-next/ledger/cockpit.html), written as the hub's own feed — tasks and a
   top-level groups[] — so the demo goes through the same model, ordering and friction as live
   data. It is drawn only under the "Demo sample" label, with every decision control disabled,
   and api/decisions.ts refuses to post while demo is on, so these ids can never reach the hub.

   Where the mockup and Phase B's rules differ, the rules win: the hub groups identical requests
   only (three restarts of the same service, not four different ones), and a group is signed one
   request at a time. Times are relative to now, so the sample reads the same any day. */
import { defineStrings, pick, type Lang } from '../frame/strings';
import { parseDocketFeed, parsePreview } from './model';
import type { DocketModel, DocketPreview, DocketSummary } from './types';

export const DEMO_STRINGS = defineStrings({
  en: {
    restart: 'Restart the local service lmstudio, which stopped responding',
    sweep: 'Sweep €4,200 of idle cash to the savings ladder',
    sweepUndo: 'A transfer back takes 1–2 working days.',
    logs: 'Delete logs older than 14 days',
    draftPost: 'Publish Veronica’s LinkedIn draft, which names a client flagged as sensitive',
    reply: 'Draft a reply to Raiffeisen with the QBR agenda',
    replyUndo: 'Delete the draft.',
    move: 'Move the research sync from 16:30 to 17:15',
    moveUndo: 'Move it back.',
  },
  ro: {
    restart: 'Repornește serviciul local lmstudio, care nu mai răspunde',
    sweep: 'Mută 4.200 € de bani nefolosiți în scara de economii',
    sweepUndo: 'Un transfer înapoi durează 1–2 zile lucrătoare.',
    logs: 'Șterge jurnalele mai vechi de 14 zile',
    draftPost: 'Publică ciorna LinkedIn a Veronicăi, care numește un client marcat ca sensibil',
    reply: 'Redactează un răspuns pentru Raiffeisen cu agenda QBR',
    replyUndo: 'Șterge ciorna.',
    move: 'Mută ședința de cercetare de la 16:30 la 17:15',
    moveUndo: 'Mut-o înapoi.',
  },
});

const MIN = 60_000;
const HOUR = 60 * MIN;
const iso = (at: number) => new Date(at).toISOString();
const ASK = { effective: 'ask', source: 'global', global: 'ask' };
const ASKED = { mode: 'ask', source: 'global', global: 'ask', by_mode: true };

/** The demo feed, as the hub would send it. */
export function demoFeed(lang: Lang | string = 'en', now: number = Date.now()): { tasks: unknown[]; groups: unknown[] } {
  const s = pick(DEMO_STRINGS, lang);
  const restart = (id: number, ago: number) => ({
    id, kind: 'restart_service', agent: 'steve', risk_tier: 3, tier_name: 'IRREVERSIBLE_OR_MONEY', status: 'blocked',
    title: s.restart, created_at: iso(now - ago), approval_deadline_at: iso(now - 2 * HOUR - 36 * MIN + 24 * HOUR),
    payload: { service: 'lmstudio', cmd: 'lms server restart' }, pushed: 0, approval_mode: ASK, asked_under: ASKED,
  });
  const logs = (id: number, ago: number) => ({
    id, kind: 'delete_file', agent: 'jarvis', risk_tier: 3, status: 'blocked', title: s.logs, created_at: iso(now - ago),
    payload: { path: 'logs/', older_than_days: 14 }, pushed: 0, approval_mode: ASK, asked_under: ASKED,
  });
  return {
    tasks: [
      restart(402, 2 * HOUR + 36 * MIN), restart(409, 2 * HOUR + 20 * MIN), restart(410, 2 * HOUR + 4 * MIN),
      { id: 371, kind: 'payment', agent: 'gecko', risk_tier: 3, status: 'blocked', title: s.sweep, created_at: iso(now - 2 * HOUR - 43 * MIN),
        payload: { amount: 4200, currency: 'EUR', to: 'savings ladder' }, pushed: 0, approval_mode: ASK,
        rollback: { description: s.sweepUndo, limitations: null } },
      logs(355, 3 * HOUR + 20 * MIN), logs(356, 3 * HOUR + 5 * MIN),
      { id: 349, kind: 'social.post', agent: 'ultron', risk_tier: 2, status: 'blocked', title: s.draftPost, created_at: iso(now - 3 * HOUR - 2 * MIN),
        payload: { channel: 'linkedin' }, pushed: 0, approval_mode: ASK, asked_under: ASKED },
      { id: 343, kind: 'draft_email', agent: 'stark', risk_tier: 1, status: 'blocked', title: s.reply, created_at: iso(now - 2 * HOUR - 45 * MIN),
        payload: { to: 'raiffeisen' }, pushed: 0, approval_mode: ASK, asked_under: ASKED, rollback: { description: s.replyUndo } },
      { id: 338, kind: 'calendar.move', agent: 'pepper', risk_tier: 1, status: 'blocked', title: s.move, created_at: iso(now - 3 * HOUR - 36 * MIN),
        payload: { event: 'research sync', to: '17:15' }, pushed: 0, approval_mode: ASK, asked_under: ASKED, rollback: { description: s.moveUndo } },
    ],
    groups: [{ id: 'demo-restart-lmstudio', leader_id: 402, member_ids: [402, 409, 410], count: 3, snapshot: 'demo0000000000000000000000000001' }],
  };
}

/** The demo docket (elsewhere: the mockup's "1 payment · 3 skill changes"). */
export function demoModel(lang: Lang | string = 'en', now: number = Date.now()): DocketModel {
  return { ...parseDocketFeed(demoFeed(lang, now)), elsewhere: { payments: 1, skillChanges: 3 } };
}

/** The demo docket's counts. */
export function demoSummary(): DocketSummary {
  return demoModel('en').summary;
}

const DEMO_PREVIEWS: Readonly<Record<number, unknown>> = {
  402: { target: '', effects: [{ field: 'cmd', value: 'lms server restart' }, { field: 'service', value: 'lmstudio' }], would_execute: false },
  371: { target: 'savings ladder', effects: [{ field: 'to', value: 'savings ladder' }, { field: 'amount', value: 4200 }], would_execute: false },
  355: { target: '', effects: [{ field: 'path', value: 'logs/' }], would_execute: false },
};

/** The dry run of a demo request (no request is made in demo), or null. */
export function demoPreview(taskId: number): DocketPreview | null {
  return taskId in DEMO_PREVIEWS ? parsePreview(DEMO_PREVIEWS[taskId]) : null;
}
