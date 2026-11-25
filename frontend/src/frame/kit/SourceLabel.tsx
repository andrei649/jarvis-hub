/* SourceLabel: where a section's data comes from and how current it is, from a Reading.
     live      ● Live · checked 10:50
     empty     Empty · checked 10:50
     stale     ◷ Stale · checked 10:44
     unknown   ◌ Checking…   or   ◌ Unknown — <reason>
     refused   ⊘ Refused — needs the owner credential
     offline   ◌ Offline · last good reading 10:44
     demo      [Demo sample] in a dashed frame
     disabled  ○ Off
   A stale or unknown section can never pass for a live one: the label says so in words. */
import React from 'react';
import type { Lang } from '../strings';
import { fmt, pick } from '../strings';
import type { Reading } from '../../signals/types';
import { Mark } from './Mark';
import type { MarkKind } from './marks';
import { KIT_STRINGS, clockTime, reasonWords, stateWord } from './strings';
import './kit.css';

export interface SourceLabelProps {
  reading: Pick<Reading<unknown>, 'state' | 'reason' | 'status' | 'lastGoodAt'>;
  lang?: Lang | string;
  /** "checked 10:50" (default) or "verified 10:50" (the audit chain). */
  verb?: 'checked' | 'verified';
  /** Write the time beside the state (default true). */
  showTime?: boolean;
  className?: string;
}

const MARKS: Record<Reading<unknown>['state'], MarkKind | null> = {
  live: 'ok', empty: null, stale: 'stale', unknown: 'unknown', refused: 'blocked', offline: 'unknown', demo: null, disabled: 'idle',
};

export function SourceLabel({ reading, lang = 'en', verb = 'checked', showTime = true, className }: SourceLabelProps) {
  const s = pick(KIT_STRINGS, lang);
  const { state, reason, status, lastGoodAt } = reading;
  const time = showTime && typeof lastGoodAt === 'number' ? clockTime(lastGoodAt) : null;
  let word = stateWord(state, lang);
  let after: string | null = null;
  let why: string | null = null;
  if (state === 'unknown' && reason === 'checking') word = s.checking;
  else if (state === 'live' || state === 'empty' || state === 'stale') after = time ? fmt(verb === 'verified' ? s.verifiedAt : s.checkedAt, { time }) : null;
  else if (state === 'offline') after = time ? fmt(s.lastGoodAt, { time }) : null;
  else if (state === 'unknown' || state === 'refused') why = reasonWords(reason, lang, status);
  const mark = MARKS[state];
  return (
    <span className={['n-src', `n-src--${state}`, className].filter(Boolean).join(' ')} data-source-state={state}>
      {mark && <Mark kind={mark} size="sm" lang={lang} />}
      <span className="n-src__word">{word}</span>
      {after && <span className="n-src__asof">{` · ${after}`}</span>}
      {why && <span className="n-src__why">{` — ${why}`}</span>}
    </span>
  );
}
