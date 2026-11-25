/* Consequence: what happens, written out (If you sign · To undo · If you wait …), as a
   description list. A row is drawn only if its field exists (honesty rule §1.4): pass the
   hub's value or null, never a placeholder; with no row left, nothing is drawn. */
import React from 'react';
import './kit.css';

export interface ConsequenceRow {
  /** Stable key (defaults to the term when it is a string). */
  key?: string;
  term: React.ReactNode;
  /** The consequence; null, undefined, false or '' leaves the row out. */
  detail: React.ReactNode;
}

const present = (detail: React.ReactNode) => detail !== null && detail !== undefined && detail !== false && detail !== '';

export function Consequence({ rows, className, ariaLabel }: { rows: readonly ConsequenceRow[]; className?: string; ariaLabel?: string }) {
  const shown = rows.filter((row) => present(row.detail));
  if (!shown.length) return null;
  return (
    <dl className={['n-consequence', className].filter(Boolean).join(' ')} aria-label={ariaLabel}>
      {shown.map((row, i) => (
        <React.Fragment key={row.key ?? (typeof row.term === 'string' ? row.term : i)}>
          <dt>{row.term}</dt>
          <dd>{row.detail}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}
