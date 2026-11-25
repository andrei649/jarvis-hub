/* The marks vocabulary (PHASE_B_PLAN.md §1.3–1.4; ledger README §2 "Marks").

   State is a shape plus a word, never a hue. These are the only marks Phase B draws; each kind
   has its word in both languages, and a mark is never shown without its word nearby (in the
   same line, or as the mark's accessible name when it stands alone).

   Pure data, no React, so signals/ and docket/ can name a mark without importing UI. */
import { defineStrings, type Lang, langOf } from '../strings';

export const MARK_KINDS = [
  'ok', 'attn', 'problem', 'unknown', 'stale', 'held', 'blocked', 'work', 'done', 'idle',
  'seal-open', 'seal', 'chain', 'here', 'key',
] as const;
export type MarkKind = typeof MARK_KINDS[number];

/** The marks drawn in the accent, because they are the owner's hand (asked for, or given). */
export const HAND_MARKS: ReadonlySet<MarkKind> = new Set<MarkKind>(['seal-open', 'seal']);

/** Each mark's word. `idle` says what the hub can prove ("no activity reported"), never "idle". */
export const MARK_STRINGS = defineStrings({
  en: {
    ok: 'OK',
    attn: 'Attention',
    problem: 'Problem',
    unknown: 'Unknown',
    stale: 'Stale',
    held: 'Held',
    blocked: 'Blocked',
    work: 'Working',
    done: 'Done',
    idle: 'No activity reported',
    'seal-open': 'Awaits your signature',
    seal: 'Signed by you',
    chain: 'Sealed',
    here: 'This machine',
    key: 'Important',
  },
  ro: {
    ok: 'În regulă',
    attn: 'Atenție',
    problem: 'Problemă',
    unknown: 'Necunoscut',
    stale: 'Învechit',
    held: 'Reținut',
    blocked: 'Blocat',
    work: 'Lucrează',
    done: 'Gata',
    idle: 'Nicio activitate raportată',
    'seal-open': 'Așteaptă semnătura ta',
    seal: 'Semnat de tine',
    chain: 'Sigilat',
    here: 'Acest calculator',
    key: 'Important',
  },
});

/** The word a mark stands for, in a language. */
export function markWord(kind: MarkKind, lang: Lang | string = 'en'): string {
  return MARK_STRINGS[langOf(lang)][kind];
}

/* The risk tiers (agents/core/autonomy/policy.py RiskTier, confirm.tsx RISK_TIER), as a
   three-bar glyph plus a word. `money` is tier 3 with an amount or a money kind. A tier the
   table does not know is drawn with every bar filled (it is treated as the strictest) and says
   so in words, rather than borrowing tier 3's name. */
export type TierKey = 0 | 1 | 2 | 3 | 'money' | 'unknown';
export const TIER_STRINGS = defineStrings({
  en: {
    t0: 'Read only',
    t1: 'Reversible',
    t2: 'External',
    t3: 'Irreversible',
    money: 'Money',
    unknown: 'Unknown risk',
  },
  ro: {
    t0: 'Doar citire',
    t1: 'Reversibil',
    t2: 'Extern',
    t3: 'Ireversibil',
    money: 'Bani',
    unknown: 'Risc necunoscut',
  },
});

/** The tier key for a hub value: 0–3 as given, 'money' when asked, anything else 'unknown'. */
export function tierKey(tier: unknown, money = false): TierKey {
  if (tier === 3 && money) return 'money';
  return tier === 0 || tier === 1 || tier === 2 || tier === 3 ? tier : 'unknown';
}

/** The number of filled bars a tier draws: unknown draws all three (the strictest). */
export function tierBars(key: TierKey): 0 | 1 | 2 | 3 {
  return key === 'money' || key === 'unknown' ? 3 : key;
}

export function tierWord(key: TierKey, lang: Lang | string = 'en'): string {
  const s = TIER_STRINGS[langOf(lang)];
  return key === 'money' ? s.money : key === 'unknown' ? s.unknown : s[`t${key}` as 't0' | 't1' | 't2' | 't3'];
}
