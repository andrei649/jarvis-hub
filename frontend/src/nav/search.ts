/* Search ranking for the command sheet (PHASE_B_PLAN.md §3.7).

   Matching ignores case and diacritics ("Încredere" is found by "incredere" or "inc", though not by a definite form such as "increderea"; "ș ț ă â î" and
   their cedilla look-alikes fold to plain letters). A query is split into words; every word must
   match something of the item, and the item's score is the sum of each word's best match:

     the whole text / its start / the start of one of its words / (3+ letters) inside it

   weighted by where it matched: the label in the shown language, the label in the other
   language, an alias, an id, then the hint ("Trust › The record"). A query that is the label
   itself, or starts it, gets a bonus. Recent items break ties and lift an item a little. A tie
   keeps the registry's order, so the result is stable. */

/** Lower case, no diacritics, no ß: the one spelling matching compares. */
export function fold(value: unknown): string {
  return String(value ?? '')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/ß/g, 'ss')
    .replace(/ı/g, 'i')
    .toLowerCase();
}

const NOT_WORD = /[^a-z0-9]+/;

/** The words of a text, folded. */
export function wordsOf(value: unknown): string[] {
  return fold(value).split(NOT_WORD).filter(Boolean);
}

/** What search reads of one item. */
export interface Searchable {
  /** The label in the shown language. */
  readonly label: string;
  /** The label in the other language (and any other spelling of the name). */
  readonly otherLabels?: readonly string[];
  readonly aliases?: readonly string[];
  /** Ids as written ("decision-inbox"): matched as words and as written. */
  readonly ids?: readonly string[];
  /** Quiet context: "Trust › The record". */
  readonly hint?: string;
}

export const WEIGHT = { label: 10, other: 8, alias: 6, id: 5, hint: 2 } as const;

/** 5 the whole text · 4 starts the text · 3 starts a word · 1 inside it (3+ letters) · 0 none.
 *  `token` is already folded. */
export function tokenScore(token: string, text: string): number {
  if (!token) return 0;
  const folded = fold(text).trim();
  if (!folded) return 0;
  if (folded === token) return 5;
  if (folded.startsWith(token)) return 4;
  if (folded.split(NOT_WORD).some((w) => w.startsWith(token))) return 3;
  if (token.length >= 3 && folded.includes(token)) return 1;
  return 0;
}

/** The score of one query word against an item: its best field. */
function wordScore(token: string, item: Searchable): number {
  let best = tokenScore(token, item.label) * WEIGHT.label;
  for (const other of item.otherLabels || []) best = Math.max(best, tokenScore(token, other) * WEIGHT.other);
  for (const alias of item.aliases || []) best = Math.max(best, tokenScore(token, alias) * WEIGHT.alias);
  for (const id of item.ids || []) best = Math.max(best, tokenScore(token, id) * WEIGHT.id);
  if (item.hint) best = Math.max(best, tokenScore(token, item.hint) * WEIGHT.hint);
  return best;
}

/** How well a query matches an item: 0 when any word of it matches nothing. An empty query
 *  matches everything with 0, so callers decide what an empty query shows. */
export function matchScore(query: string, item: Searchable): number {
  const tokens = wordsOf(query);
  if (!tokens.length) return 0;
  let total = 0;
  for (const token of tokens) {
    const s = wordScore(token, item);
    if (s <= 0) return 0;
    total += s;
  }
  const whole = fold(query).trim().replace(/\s+/g, ' ');
  const names = [item.label, ...(item.otherLabels || [])].map((n) => fold(n).trim());
  if (names.some((n) => n === whole)) total += 40;
  else if (names.some((n) => n.startsWith(whole))) total += 15;
  return total;
}

export interface RankOptions<T> {
  /** 0 for an item that is not recent; larger is more recent (lifts the score a little). */
  readonly recency?: (item: T) => number;
  readonly limit?: number;
}

/** The items that match a query, best first; ties keep their order in `items`. An empty query
 *  returns nothing: the sheet shows its own default list then. */
export function rankBy<T>(items: readonly T[], query: string, read: (item: T) => Searchable, options: RankOptions<T> = {}): T[] {
  if (!wordsOf(query).length) return [];
  const scored: Array<{ item: T; score: number; index: number }> = [];
  items.forEach((item, index) => {
    const base = matchScore(query, read(item));
    if (base > 0) scored.push({ item, score: base + (options.recency?.(item) ?? 0) * 3, index });
  });
  scored.sort((a, b) => b.score - a.score || a.index - b.index);
  const out = scored.map((s) => s.item);
  return options.limit ? out.slice(0, options.limit) : out;
}
