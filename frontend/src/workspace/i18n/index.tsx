/* Typed translations and locale-aware formatting for the Workspace.

   Romanian is the default; English mirrors every key (enforced by the type of `defineMessages`
   and by i18n.test.ts). Copy lives in ./messages, one namespace per area. `t` interpolates
   `{name}` placeholders (numbers are formatted for the locale); `tn` picks the plural form from
   Intl.PluralRules — Romanian has three (`one`, `few`, `other`: „1 utilizator", „3 utilizatori",
   „20 de utilizatori"), English uses `one`/`other` and repeats `other` for `few`. Dates and
   numbers always go through Intl in the user's locale, never hand-built strings. */
import React, { createContext, useCallback, useContext, useMemo, useState } from 'react';
import type { EpochSeconds, Locale } from '../api/types';
import { EN, RO } from './messages';

export type Messages = typeof RO;
export type MessageKey = keyof Messages & string;
export type PluralKey = MessageKey extends infer K ? (K extends `${infer B}.other` ? B : never) : never;
export type Vars = Record<string, string | number>;

const DICTIONARIES: Record<Locale, Record<MessageKey, string>> = { ro: RO, en: EN };
const LANGUAGE_TAGS: Record<Locale, string> = { ro: 'ro-RO', en: 'en-GB' };

export function languageTag(locale: Locale): string {
  return LANGUAGE_TAGS[locale];
}

function interpolate(template: string, vars: Vars | undefined, locale: Locale): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) => {
    const value = vars[name];
    if (value === undefined) return match;
    return typeof value === 'number' ? new Intl.NumberFormat(languageTag(locale)).format(value) : value;
  });
}

/** Outside React (document titles, tests): the same lookup the hook uses. */
export function translate(locale: Locale, key: MessageKey, vars?: Vars): string {
  return interpolate(DICTIONARIES[locale][key] ?? DICTIONARIES.ro[key] ?? key, vars, locale);
}

export function translatePlural(locale: Locale, key: PluralKey, count: number, vars?: Vars): string {
  const category = new Intl.PluralRules(languageTag(locale)).select(count);
  const dictionary = DICTIONARIES[locale] as Record<string, string>;
  const template = dictionary[`${key}.${category}`] ?? dictionary[`${key}.other`];
  return interpolate(template, { count, ...vars }, locale);
}

export interface Formatters {
  number(value: number, options?: Intl.NumberFormatOptions): string;
  percent(value: number): string;
  date(ts: EpochSeconds): string;
  dateTime(ts: EpochSeconds): string;
  /** Wall-clock time in an IANA zone (a report's schedule zone); the browser's zone if unknown. */
  dateTimeIn(ts: EpochSeconds, timeZone: string): string;
  time(ts: EpochSeconds): string;
  relative(ts: EpochSeconds, now?: number): string;
  /** A calendar day `YYYY-MM-DD` (a date the server counted, already in the asked zone) as a
      short label, e.g. „17 oct."; formatted in UTC so the label is that date and no other. */
  day(isoDate: string): string;
  bytes(size: number): string;
  durationMs(ms: number): string;
}

const RELATIVE_STEPS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['second', 60], ['minute', 60], ['hour', 24], ['day', 7], ['week', 4.35], ['month', 12], ['year', Infinity],
];

export function makeFormatters(locale: Locale): Formatters {
  const tag = languageTag(locale);
  const dateFmt = new Intl.DateTimeFormat(tag, { dateStyle: 'medium' });
  const dateTimeFmt = new Intl.DateTimeFormat(tag, { dateStyle: 'medium', timeStyle: 'short' });
  const timeFmt = new Intl.DateTimeFormat(tag, { timeStyle: 'short' });
  const dayFmt = new Intl.DateTimeFormat(tag, { day: 'numeric', month: 'short', timeZone: 'UTC' });
  const relativeFmt = new Intl.RelativeTimeFormat(tag, { numeric: 'auto' });
  return {
    number: (value, options) => new Intl.NumberFormat(tag, options).format(value),
    percent: (value) => new Intl.NumberFormat(tag, { style: 'percent', maximumFractionDigits: 0 }).format(value),
    date: (ts) => dateFmt.format(new Date(ts * 1000)),
    dateTime: (ts) => dateTimeFmt.format(new Date(ts * 1000)),
    dateTimeIn: (ts, timeZone) => {
      try {
        return new Intl.DateTimeFormat(tag, { dateStyle: 'medium', timeStyle: 'short', timeZone }).format(new Date(ts * 1000));
      } catch {
        return dateTimeFmt.format(new Date(ts * 1000));
      }
    },
    time: (ts) => timeFmt.format(new Date(ts * 1000)),
    relative: (ts, now = Date.now()) => {
      let value = (ts * 1000 - now) / 1000;
      for (const [unit, size] of RELATIVE_STEPS) {
        if (Math.abs(value) < size) return relativeFmt.format(Math.round(value), unit);
        value /= size;
      }
      return dateFmt.format(new Date(ts * 1000));
    },
    day: (isoDate) => {
      const parsed = new Date(`${isoDate}T00:00:00Z`);
      return Number.isNaN(parsed.getTime()) ? isoDate : dayFmt.format(parsed);
    },
    bytes: (size) => {
      const units = ['byte', 'kilobyte', 'megabyte', 'gigabyte'] as const;
      let value = size;
      let unit = 0;
      while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
      return new Intl.NumberFormat(tag, { style: 'unit', unit: units[unit], unitDisplay: 'short', maximumFractionDigits: unit ? 1 : 0 }).format(value);
    },
    durationMs: (ms) => (ms < 1000
      ? new Intl.NumberFormat(tag, { style: 'unit', unit: 'millisecond', unitDisplay: 'short' }).format(Math.round(ms))
      : new Intl.NumberFormat(tag, { style: 'unit', unit: 'second', unitDisplay: 'short', maximumFractionDigits: 1 }).format(ms / 1000)),
  };
}

export interface I18n {
  locale: Locale;
  setLocale(locale: Locale): void;
  t(key: MessageKey, vars?: Vars): string;
  tn(key: PluralKey, count: number, vars?: Vars): string;
  /** For server codes mapped to copy (`error.<code>`): is there a translation for it? */
  has(key: string): key is MessageKey;
  fmt: Formatters;
}

const I18nContext = createContext<I18n | null>(null);

export function I18nProvider({ initialLocale = 'ro', children }: { initialLocale?: Locale; children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(initialLocale);
  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    document.documentElement.lang = next;
  }, []);
  const value = useMemo<I18n>(() => ({
    locale,
    setLocale,
    t: (key, vars) => translate(locale, key, vars),
    tn: (key, count, vars) => translatePlural(locale, key, count, vars),
    has: (key): key is MessageKey => key in DICTIONARIES[locale],
    fmt: makeFormatters(locale),
  }), [locale, setLocale]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error('useI18n outside I18nProvider');
  return ctx;
}

export { DICTIONARIES };
