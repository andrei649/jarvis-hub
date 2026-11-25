/* MarksKey: every mark the page uses, with its word, and the source labels (the Trust page
   carries it at the foot of its contents column; secondary.html "Key"). */
import React, { useId } from 'react';
import { pick, type Lang } from '../strings';
import { Mark } from './Mark';
import { markWord, type MarkKind } from './marks';
import { SourceLabel } from './SourceLabel';
import { KIT_STRINGS } from './strings';
import './kit.css';

/** The key's default rows, as the Trust page draws them; the owner's hand gets a full row. */
export const KEY_MARKS: readonly MarkKind[] = ['ok', 'attn', 'problem', 'unknown', 'stale', 'held', 'blocked', 'chain', 'seal-open', 'seal'];
const WIDE: ReadonlySet<MarkKind> = new Set<MarkKind>(['seal-open', 'seal']);

export interface MarksKeyProps {
  lang?: Lang | string;
  /** The marks to explain (default KEY_MARKS). */
  kinds?: readonly MarkKind[];
  /** Also explain the source labels: Live, Demo sample, Empty (default true). */
  sources?: boolean;
  className?: string;
}

export function MarksKey({ lang = 'en', kinds = KEY_MARKS, sources = true, className }: MarksKeyProps) {
  const id = `n-key-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`;
  return (
    <section className={['n-key', className].filter(Boolean).join(' ')} aria-labelledby={id}>
      <h3 className="n-key__title" id={id}>{pick(KIT_STRINGS, lang).key}</h3>
      <ul className="n-key__list">
        {kinds.map((kind) => (
          <li key={kind} className={['n-key__item', WIDE.has(kind) ? 'n-key__item--wide' : ''].filter(Boolean).join(' ')} data-mark-key={kind}>
            <Mark kind={kind} lang={lang} />{markWord(kind, lang)}
          </li>
        ))}
        {sources && (
          <li className="n-key__item n-key__item--wide n-key__sources">
            <SourceLabel reading={{ state: 'live', lastGoodAt: null }} lang={lang} showTime={false} />
            <SourceLabel reading={{ state: 'demo', lastGoodAt: null }} lang={lang} showTime={false} />
            <SourceLabel reading={{ state: 'empty', lastGoodAt: null }} lang={lang} showTime={false} />
          </li>
        )}
      </ul>
    </section>
  );
}
