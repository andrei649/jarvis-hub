/* Mark and TierGlyph: state as a shape plus a word, risk as three bars plus a word.
   Drawn inline (no sprite to mount), in currentColor; only the owner's hand (seal-open, seal)
   takes the accent, and the chain's seal on every record entry is ink. */
import React from 'react';
import type { Lang } from '../strings';
import { HAND_MARKS, markWord, tierBars, tierKey, tierWord, type MarkKind } from './marks';
import './kit.css';

const RING = { cx: 8, cy: 8, r: 5.6, fill: 'none', stroke: 'currentColor', strokeWidth: 1.6 } as const;
const ROUND = { strokeLinecap: 'round', strokeLinejoin: 'round' } as const;

function shape(kind: MarkKind): React.ReactNode {
  switch (kind) {
    case 'ok': return <circle cx="8" cy="8" r="3.4" fill="currentColor" />;
    case 'attn': return <><circle {...RING} /><path d="M8 2.4a5.6 5.6 0 0 0 0 11.2z" fill="currentColor" /></>;
    case 'problem': return <rect x="2.5" y="2.5" width="11" height="11" fill="currentColor" />;
    case 'unknown': return <circle {...RING} strokeDasharray="2.4 2" />;
    case 'stale': return <><circle {...RING} /><path d="M8 4.8V8l2.3 1.4" fill="none" stroke="currentColor" strokeWidth="1.6" {...ROUND} /></>;
    case 'held': return <path d="M5.2 3v10M10.8 3v10" fill="none" stroke="currentColor" strokeWidth="2.4" />;
    case 'blocked': return <><circle {...RING} /><path d="M4.1 11.9l7.8-7.8" stroke="currentColor" strokeWidth="1.6" /></>;
    case 'work': return <path d="M4 2.5l9.5 5.5L4 13.5z" fill="currentColor" />;
    case 'done': return <path d="M3 8.6l3.3 3.3L13 4.6" fill="none" stroke="currentColor" strokeWidth="1.9" {...ROUND} />;
    case 'idle': return <circle cx="8" cy="8" r="3.1" fill="none" stroke="currentColor" strokeWidth="1.5" />;
    case 'seal-open': return <><circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.4" /><path d="M5.6 10.7V5.3l4.8 5.4V5.3" fill="none" stroke="currentColor" strokeWidth="1.3" {...ROUND} /></>;
    case 'seal':
    case 'chain':
      // a solid disc with the N knocked out; --mk-knock is the ground it sits on (the page by default)
      return <><circle cx="8" cy="8" r="7.25" fill="currentColor" /><path d="M5.4 10.9V5.1l5.2 5.8V5.1" fill="none" style={{ stroke: 'var(--mk-knock, var(--n-bg))' }} strokeWidth="1.5" {...ROUND} /></>;
    case 'here': return <><rect x="2.75" y="2.75" width="10.5" height="10.5" fill="none" stroke="currentColor" strokeWidth="1.5" /><rect x="6" y="6" width="4" height="4" fill="currentColor" /></>;
    case 'key': return <path d="M8 2.2l5.8 5.8L8 13.8 2.2 8z" fill="currentColor" />;
    default: return null;
  }
}

export interface MarkProps {
  kind: MarkKind;
  lang?: Lang | string;
  size?: 'sm' | 'md' | 'lg';
  /** Write the mark's word after it. */
  word?: boolean;
  /** No word beside it: the mark carries its word as its accessible name. */
  label?: boolean;
  className?: string;
}

/** A state mark. Hidden from assistive tech by default, because a word always stands beside
 *  it; pass `word` to write that word, or `label` when the mark stands alone. */
export function Mark({ kind, lang = 'en', size = 'md', word = false, label = false, className }: MarkProps) {
  const name = markWord(kind, lang);
  const classes = ['n-mk', `n-mk--${size}`, `n-mk--${kind}`];
  if (HAND_MARKS.has(kind)) classes.push('n-mk--hand');
  if (kind === 'chain') classes.push('n-mk--chain');
  if (className) classes.push(className);
  const named = label && !word;
  const svg = (
    <svg className={classes.join(' ')} viewBox="0 0 16 16" data-mark={kind} focusable="false"
      {...(named ? { role: 'img', 'aria-label': name } : { 'aria-hidden': true })}>
      {shape(kind)}
    </svg>
  );
  if (!word) return svg;
  return <span className="n-mk-word" data-mark-word={kind}>{svg}<span>{name}</span></span>;
}

export interface TierGlyphProps {
  /** The hub's risk tier (0–3); anything else is drawn as unknown, with every bar filled. */
  tier: unknown;
  /** Tier 3 with an amount or a money kind. */
  money?: boolean;
  /** Write the tier's name after the glyph; otherwise the glyph carries it as its name. */
  word?: boolean;
  lang?: Lang | string;
  className?: string;
}

const FILLED_X = [0, 7.5, 15];
const OUTLINE_X = [0.6, 8.1, 15.6];

/** The three-bar risk glyph: ▯▯▯ read only, ▮▯▯ reversible, ▮▮▯ external, ▮▮▮ irreversible or money. */
export function TierGlyph({ tier, money = false, word = false, lang = 'en', className }: TierGlyphProps) {
  const key = tierKey(tier, money);
  const bars = tierBars(key);
  const name = tierWord(key, lang);
  return (
    <span className={['n-tier', className].filter(Boolean).join(' ')} data-tier={String(key)} data-bars={bars}>
      <svg className="n-tier__glyph" viewBox="0 0 20 12" focusable="false"
        {...(word ? { 'aria-hidden': true } : { role: 'img', 'aria-label': name })}>
        {[0, 1, 2].map((i) => i < bars
          ? <rect key={i} x={FILLED_X[i]} y="0" width="5" height="12" fill="currentColor" />
          : <rect key={i} x={OUTLINE_X[i]} y="0.6" width="3.8" height="10.8" fill="none" stroke="currentColor" strokeWidth="1.2" />)}
      </svg>
      {word && <span className="n-tier__word">{name}</span>}
    </span>
  );
}
