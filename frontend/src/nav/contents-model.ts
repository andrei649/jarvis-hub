/* What an area's contents column lists (PHASE_B_PLAN.md §3.3 "More pages", §3.9).

   Pure, so the column, the All pages site map and their tests agree:
     - only `listed` pages (Glance and the `jobs` panel duplicate are searchable but not listed);
     - `primary` pages first, the rest behind "N more pages";
     - on a duplicate (/v2/console/jobs) the page it duplicates is the current one;
     - a note beside a page only when its signal has an honest live value (never a 0). */
import { defineStrings, plural, pick, type Lang } from '../frame/strings';
import { attentionWords, pageKey, textOf, type Area, type AttentionWords, type Group, type PageEntry } from './areas';
import type { Attention } from '../signals/types';
import { pathOf } from './routes';

export const CONTENTS_STRINGS = defineStrings({
  en: {
    navLabel: 'Pages in {area}',
    count: { one: '{n} page', few: '{n} pages', other: '{n} pages' },
    more: { one: '{n} more page', few: '{n} more pages', other: '{n} more pages' },
    fewer: 'Show fewer pages',
    find: '{key} finds any of the {n}',
    findPanel: 'Find a panel…',
    allPagesNote: 'Every page of every area. {key} searches them all.',
  },
  ro: {
    navLabel: 'Paginile din {area}',
    count: { one: '{n} pagină', few: '{n} pagini', other: '{n} de pagini' },
    more: { one: 'încă {n} pagină', few: 'încă {n} pagini', other: 'încă {n} de pagini' },
    fewer: 'Arată mai puține pagini',
    find: '{key} găsește oricare dintre cele {n}',
    findPanel: 'Caută un panou…',
    allPagesNote: 'Fiecare pagină din fiecare zonă. {key} le caută pe toate.',
  },
});

export interface ContentsItem {
  readonly entry: PageEntry;
  readonly current: boolean;
  readonly path: string;
}
export interface ContentsGroup {
  readonly group: Group;
  readonly label: { readonly en: string; readonly ro: string } | null;
  /** Primary pages first; `more` holds the rest, in contents order. */
  readonly primary: readonly ContentsItem[];
  readonly more: readonly ContentsItem[];
}
export interface ContentsModel {
  readonly groups: readonly ContentsGroup[];
  /** Listed pages of the area. */
  readonly total: number;
  /** Listed pages behind "N more pages". */
  readonly moreCount: number;
  /** The key of the page the column marks current, or null (a page that is not listed). */
  readonly currentKey: string | null;
  /** The current page sits behind "N more pages", so the column opens expanded. */
  readonly currentInMore: boolean;
}

/** The key of the page a route's page is marked as in the column: a duplicate marks its original. */
export function currentKeyOf(current: PageEntry): string {
  return current.duplicateOf ? pageKey(current.duplicateOf) : current.key;
}

export function contentsModel(area: Area, current: PageEntry | null): ContentsModel {
  const currentKey = current ? currentKeyOf(current) : null;
  let total = 0;
  let moreCount = 0;
  let found: string | null = null;
  let currentInMore = false;
  const groups: ContentsGroup[] = [];
  for (const group of area.groups) {
    const primary: ContentsItem[] = [];
    const more: ContentsItem[] = [];
    for (const entry of group.pages) {
      if (!entry.listed) continue;
      total += 1;
      const isCurrent = entry.key === currentKey;
      if (isCurrent) found = entry.key;
      const item: ContentsItem = { entry, current: isCurrent, path: pathOf(entry.ref) };
      if (entry.primary) primary.push(item);
      else { more.push(item); moreCount += 1; if (isCurrent) currentInMore = true; }
    }
    if (primary.length || more.length) groups.push({ group, label: group.label, primary, more });
  }
  return { groups, total, moreCount, currentKey: found, currentInMore };
}

/** The note beside a page: only for a page that names a signal, and only when that signal has
 *  a live value. */
export function noteFor(entry: PageEntry, attention: Attention | undefined, lang: Lang | string): AttentionWords | null {
  const key = entry.attention;
  if (!key || !attention) return null;
  const note = attention[key];
  return note ? attentionWords(note, lang) : null;
}

/** "{n} pages" for an area header. */
export function pagesWord(lang: Lang, n: number): string {
  return plural(lang, pick(CONTENTS_STRINGS, lang).count, n);
}

/** The label of a page in a language. */
export function pageLabel(entry: PageEntry, lang: Lang | string): string {
  return textOf(entry.label, lang);
}
