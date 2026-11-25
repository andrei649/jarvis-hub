/* The composer head's "Mode": the approval mode that applies to the recipient, in the hub's own
   words (agents/core/autonomy/mode.py), so the owner sees before sending whether a side effect will
   wait for them (PHASE_B_PLAN.md §5.3).

   The composer never asks the hub itself: whoever renders it passes the reading. The Ledger's
   TalkRegister resolves the recipient's mode (home/talk/recipient-mode.ts): the agent's own
   override when it has one — said as "<Agent>'s own setting" — else the global mode, which a
   global Off makes a floor for everyone. Without a reading it says so: "Mode unknown — not read on
   this page", never a guessed mode. A value the hub stopped confirming keeps its source label
   (stale, offline · last good reading), and a demo value is labelled as one. */
import React from 'react';
import { Mark, SourceLabel } from '../../frame/kit';
import { reasonWords } from '../../frame/kit/strings';
import { fmt } from '../../frame/strings';
import type { Reading } from '../../signals/types';
import type { ApprovalModeReading, ApprovalModeValue } from '../../signals/wire';
import { talkStrings } from './strings';

/** The mode that applies to the recipient; `source` says whether it is the agent's own override
 *  ('agent') or the global mode ('global'). Absent source reads as the global mode. */
export interface RecipientModeValue extends ApprovalModeReading { readonly source?: 'agent' | 'global' }

/** A Reading of the recipient's mode (home/talk/recipient-mode.ts, or signals/hooks useApprovalMode
 *  for the global one); its state, value and last good time are required. */
export type ApprovalModeInput = Pick<Reading<RecipientModeValue>, 'state' | 'value' | 'lastGoodAt'> & Partial<Reading<RecipientModeValue>>;

const SHOWN = new Set(['live', 'stale', 'offline', 'demo']);

export function ComposerMode({ reading, agentName, lang }: { reading?: ApprovalModeInput | null; agentName?: string; lang: string }) {
  const s = talkStrings(lang);
  const mode: ApprovalModeValue | null = reading && SHOWN.has(reading.state) && reading.value ? reading.value.mode : null;
  if (!mode && reading && (reading.state === 'demo' || (reading.state === 'unknown' && reading.reason === 'checking'))) {
    // demo mode reads nothing from the hub (the section says it is a sample); before the first
    // answer the mode is being checked, not unknown
    return (
      <span className="n-composer__mode" data-mode={reading.state === 'demo' ? 'demo' : 'checking'} data-source-state={reading.state}>
        <span className="n-composer__k">{s.mode}</span> <SourceLabel reading={reading} lang={lang} />
      </span>
    );
  }
  if (!mode) {
    const why = !reading ? s.modeNotRead
      : reasonWords(reading.state === 'refused' ? 'credential' : reading.reason, lang, reading.status) ?? s.modeNotRead;
    return (
      <span className="n-composer__mode" data-mode="unknown" data-source-state={reading ? reading.state : 'disabled'} title={`${s.modeUnknown} — ${why}`}>
        <Mark kind="unknown" size="sm" lang={lang} />
        <span>{s.modeUnknown}</span>
        <span className="n-composer__why-mode"> — {why}</span>
      </span>
    );
  }
  const word = mode === 'auto' ? s.modeAuto : mode === 'ask' ? s.modeAsk : s.modeOff;
  const means = mode === 'auto' ? s.modeAutoMeans : mode === 'ask' ? s.modeAskMeans : s.modeOffMeans;
  const full = mode === 'auto' ? s.modeAutoFull : mode === 'ask' ? s.modeAskFull : s.modeOffFull;
  const own = reading!.value!.source === 'agent' && !!agentName;
  return (
    <span className="n-composer__mode" data-mode={mode} data-mode-source={reading!.value!.source ?? 'global'} data-source-state={reading!.state}
      title={own ? `${fmt(s.modeOwnTitle, { agent: agentName! })} ${full}` : full}>
      <span className="n-composer__k">{s.mode}</span> <b>{word}</b><span className="n-composer__means"> — {means}</span>
      {own && <span className="n-composer__own"> · {fmt(s.modeOwn, { agent: agentName! })}</span>}
      {reading!.state !== 'live' && <> <SourceLabel reading={reading!} lang={lang} /></>}
    </span>
  );
}
