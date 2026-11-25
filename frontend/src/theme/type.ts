/**
 * Typography helpers for React inline styles (contract v1, §4–5).
 *
 * Inline styles cannot use CSS classes, so they reach the theme through these helpers:
 *   fontSize: fs('ui')            -> 'var(--n-fs-ui)'
 *   ...LABEL                      -> the theme's label voice (font, case, tracking, weight)
 *   ...MONO                       -> identifiers only: hashes, ids, addresses, code
 *   fsFromPx(10)                  -> the scale step a legacy pixel size maps to
 * Never write a numeric fontSize below 12 again; never hard-code uppercase or tracking on a label.
 */
import type { CSSProperties } from 'react';

export type FontStep = 'meta' | 'label' | 'ui' | 'own' | 'prose' | 'title' | 'verdict' | 'figure';

export const fs = (step: FontStep): string => `var(--n-fs-${step})`;
export const lh = (step: FontStep): string => `var(--n-lh-${step})`;

/** The scale step a legacy pixel size maps to (contract §4). */
export function stepFromPx(px: number): FontStep {
  if (px < 12) return 'meta';
  if (px < 13) return 'label';
  if (px < 14.5) return 'ui';
  if (px < 16.5) return 'own';
  if (px < 20) return 'prose';
  if (px < 28) return 'title';
  if (px < 40) return 'verdict';
  return 'figure';
}
export const fsFromPx = (px: number): string => fs(stepFromPx(px));

/** Small structural labels: section heads, badges, table heads, tabs. */
export const LABEL: CSSProperties = {
  fontFamily: 'var(--n-font-label)',
  textTransform: 'var(--n-label-case)' as CSSProperties['textTransform'],
  letterSpacing: 'var(--n-label-track)',
  fontWeight: 'var(--n-label-weight)' as CSSProperties['fontWeight'],
};

/** A heading drawn in the label voice (a panel's h2–h4, a strong lead-in): the label's face,
 *  case and tracking, at the semibold weight a heading needs in every theme. */
export const LABEL_STRONG: CSSProperties = {
  ...LABEL,
  fontWeight: 'var(--n-w-semi)' as CSSProperties['fontWeight'],
};

/** Identifiers only: hashes, ids, addresses, model and capability names, code, logs, JSON. */
export const MONO: CSSProperties = {
  fontFamily: 'var(--n-font-mono)',
  fontVariantNumeric: 'tabular-nums',
};

/** An identifier that sits inside a label (an id in a section head, a model name in a tag):
 *  mono, and immune to the label voice's case and tracking, because identifiers are
 *  case-sensitive. */
export const IDENT: CSSProperties = {
  ...MONO,
  textTransform: 'none',
  letterSpacing: 'normal',
};

/** Reading prose: replies, entries, long explanations. */
export const PROSE: CSSProperties = {
  fontFamily: 'var(--n-font-text)',
  fontSize: 'var(--n-fs-prose)',
  lineHeight: 'var(--n-lh-prose)',
};
