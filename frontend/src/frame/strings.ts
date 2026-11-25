/* The strings convention for Phase B (PHASE_B_PLAN.md §9.2.2).

   Every user-visible string of a Phase B module comes from one {en, ro} pair of tables that
   the module defines and exports, and that module's test asserts the pair is complete:

     // docket/strings.ts (or at the top of the module)
     export const DOCKET_STRINGS = defineStrings({
       en: { empty: 'Nothing is waiting for you.', entries: { one: '{n} entry', few: '{n} entries', other: '{n} entries' } },
       ro: { empty: 'Nimic nu te așteaptă.', entries: { one: '{n} intrare', few: '{n} intrări', other: '{n} de intrări' } },
     });
     // in the component
     const s = pick(DOCKET_STRINGS, lang);
     s.empty;                              // 'Nothing is waiting for you.'
     plural(lang, s.entries, 21);          // '21 entries' · '21 de intrări'
     fmt(s.checked, { time: '10:50' });    // a '{time}' placeholder filled in
     // in the module's test
     expect(stringProblems(DOCKET_STRINGS)).toEqual([]);

   Rules the completeness check enforces:
     - both languages define exactly the same keys, and each key has the same kind
       (a plain string, or a plural with `one`, `few` and `other` forms);
     - no blank value;
     - the same {placeholders} in both languages (for a plural, across its forms);
     - Romanian uses the comma-below letters ș ț Ș Ț, never the cedilla look-alikes ş ţ Ş Ţ.

   Plural forms follow Intl.PluralRules: English uses `one` and `other` (write `few` equal to
   `other`); Romanian `one` (1), `few` (0, 2–19, and 101–119 …) and `other` (20 and up, which
   takes "de": "20 de intrări"). Never build a sentence by concatenating translated pieces;
   write the whole sentence with placeholders. */

export type Lang = 'en' | 'ro';
export const LANGS: readonly Lang[] = ['en', 'ro'];

/** A count-dependent string: pick it with plural(). `{n}` is the count. */
export interface Plural { readonly one: string; readonly few: string; readonly other: string }
export type Entry = string | Plural;
/** One language's table: a flat map of keys to strings or plurals. */
export type Table = { readonly [key: string]: Entry };
/** The Romanian table mirrors the English one: the same keys, the same kinds. */
export type Translation<T extends Table> = { readonly [K in keyof T]: T[K] extends string ? string : Plural };
/** A module's strings: the English table and its Romanian mirror. */
export interface Strings<T extends Table> { readonly en: Translation<T>; readonly ro: Translation<T> }

/** Declare a module's strings. Typing makes Romanian mirror English; the test makes it complete. */
export function defineStrings<T extends Table>(strings: { en: T; ro: Translation<T> }): Strings<T> {
  return strings as unknown as Strings<T>;
}

/** The language a value names: 'ro' only for exactly 'ro', everything else English. */
export function langOf(value: unknown): Lang {
  return value === 'ro' ? 'ro' : 'en';
}

/** The table for a language (anything that is not 'ro' reads English). */
export function pick<T extends Table>(strings: Strings<T>, lang: unknown): Translation<T> {
  return strings[langOf(lang)];
}

/** Fill `{name}` placeholders. A placeholder with no value is left as written, so a missing
 *  value shows up in review instead of becoming an empty gap. */
export function fmt(template: string, values: { readonly [name: string]: string | number } = {}): string {
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : whole);
}

const RULES: Partial<Record<Lang, Intl.PluralRules>> = {};

/** The plural form a count takes in a language (Intl.PluralRules, with a fallback). */
export function pluralForm(lang: Lang, n: number): keyof Plural {
  try {
    const rules = RULES[lang] ?? (RULES[lang] = new Intl.PluralRules(lang));
    const category = rules.select(n);
    return category === 'one' ? 'one' : category === 'few' ? 'few' : 'other';
  } catch {
    if (n === 1) return 'one';
    if (lang === 'ro' && Number.isInteger(n) && (n === 0 || (n % 100 >= 1 && n % 100 <= 19))) return 'few';
    return 'other';
  }
}

/** A count-dependent string, with `{n}` and any other placeholders filled. */
export function plural(lang: unknown, forms: Plural, n: number, values: { readonly [name: string]: string | number } = {}): string {
  return fmt(forms[pluralForm(langOf(lang), n)], { n, ...values });
}

function placeholders(text: string): string[] {
  return [...new Set(Array.from(text.matchAll(/\{(\w+)\}/g), (m) => m[1]))].sort();
}

function isPlural(value: unknown): value is Plural {
  return !!value && typeof value === 'object'
    && typeof (value as Plural).one === 'string'
    && typeof (value as Plural).few === 'string'
    && typeof (value as Plural).other === 'string';
}

const CEDILLA = /[ŞşŢţ]/;   // Ş ş Ţ ţ — the wrong Romanian letters

/** Everything wrong with a module's strings, one sentence per problem; [] when complete.
 *  Use it in the module's test: `expect(stringProblems(MY_STRINGS)).toEqual([])`. */
export function stringProblems(strings: { en: Table; ro: Table } | Strings<Table>): string[] {
  const problems: string[] = [];
  const en = strings.en as Table;
  const ro = strings.ro as Table;
  for (const key of Object.keys(en)) if (!(key in ro)) problems.push(`ro is missing "${key}"`);
  for (const key of Object.keys(ro)) if (!(key in en)) problems.push(`ro has "${key}", which en does not`);
  for (const lang of LANGS) {
    for (const [key, value] of Object.entries(strings[lang] as Table)) {
      const texts = typeof value === 'string' ? [value] : isPlural(value) ? [value.one, value.few, value.other] : null;
      if (!texts) { problems.push(`${lang}.${key} is neither a string nor a plural with one, few and other`); continue; }
      if (texts.some((text) => text.trim() === '')) problems.push(`${lang}.${key} is blank`);
      if (lang === 'ro' && texts.some((text) => CEDILLA.test(text))) problems.push(`ro.${key} uses a cedilla ş or ţ; Romanian takes ș and ț`);
    }
  }
  for (const key of Object.keys(en)) {
    if (!(key in ro)) continue;
    const a = en[key];
    const b = ro[key];
    if (typeof a !== typeof b) { problems.push(`"${key}" is a ${typeof a === 'string' ? 'string' : 'plural'} in en but not in ro`); continue; }
    const all = (value: Entry) => typeof value === 'string' ? placeholders(value)
      : isPlural(value) ? [...new Set([...placeholders(value.one), ...placeholders(value.few), ...placeholders(value.other)])].sort() : [];
    const pa = all(a).join(',');
    const pb = all(b).join(',');
    if (pa !== pb) problems.push(`"${key}" has placeholders {${pa}} in en but {${pb}} in ro`);
  }
  return problems;
}
