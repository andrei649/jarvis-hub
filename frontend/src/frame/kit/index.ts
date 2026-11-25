/* frame/kit — the building blocks every Phase B engineer draws with (PHASE_B_PLAN.md §2.2).
   Import from 'frame/kit' (this file). The primitives (n-btn, n-seg, n-field, n-link, n-kbd,
   n-tag, n-row, n-state, n-card) stay Phase A's, in src/theme/kit.css; the classes here are
   Phase B's: n-mk, n-tier, n-src, n-register, n-sec, n-total, n-consequence, n-disclosure, n-key.
   Importing the kit also loads frame.css (the shared breakpoints' visibility helpers). */
import '../frame.css';
export { Mark, TierGlyph, type MarkProps, type TierGlyphProps } from './Mark';
export { SourceLabel, type SourceLabelProps } from './SourceLabel';
export { Register, SecHead, Total, type RegisterProps, type SecHeadProps, type TotalProps } from './Register';
export { Consequence, type ConsequenceRow } from './Consequence';
export { Disclosure, placeInside, unplace, type DisclosureProps } from './Disclosure';
export { MarksKey, KEY_MARKS, type MarksKeyProps } from './MarksKey';
export {
  MARK_KINDS, MARK_STRINGS, HAND_MARKS, TIER_STRINGS, markWord, tierKey, tierBars, tierWord,
  type MarkKind, type TierKey,
} from './marks';
export { KIT_STRINGS, clockTime, stateWord, reasonWords, basisWords } from './strings';
