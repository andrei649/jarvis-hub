import { describe, expect, it } from 'vitest';
import { makeFormatters, translate, translatePlural } from './index';
import { EN, RO } from './messages';
import { AUDIT_ACTIONS } from '../app/labels';

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe('dictionaries', () => {
  it('have identical key sets in Romanian and English', () => {
    expect(Object.keys(EN).sort()).toEqual(Object.keys(RO).sort());
  });

  it('have no empty strings and the same placeholders in both languages', () => {
    for (const key of Object.keys(RO) as (keyof typeof RO)[]) {
      expect(RO[key].trim(), `ro ${key}`).not.toBe('');
      expect(EN[key].trim(), `en ${key}`).not.toBe('');
      expect(placeholders(EN[key]), key).toEqual(placeholders(RO[key]));
    }
  });

  it('write Romanian with comma-below ș ț, never the cedilla look-alikes', () => {
    const cedilla = /[ŞşŢţ]/;
    const offenders = Object.entries(RO).filter(([, text]) => cedilla.test(text)).map(([key]) => key);
    expect(offenders).toEqual([]);
  });

  it('give every plural key one/few/other forms in both languages', () => {
    const bases = new Set(Object.keys(RO).filter((k) => /\.(one|few|other)$/.test(k)).map((k) => k.replace(/\.(one|few|other)$/, '')));
    for (const base of bases) {
      for (const form of ['one', 'few', 'other']) {
        expect(`${base}.${form}` in RO, `${base}.${form}`).toBe(true);
      }
    }
  });

  it('label every audit action the server can record', () => {
    for (const action of AUDIT_ACTIONS) expect(`audit.action.${action}` in RO, action).toBe(true);
  });
});

describe('translate', () => {
  it('interpolates variables and formats numbers for the locale', () => {
    expect(translate('ro', 'common.charCount', { count: 12, max: 40 })).toBe('12 / 40');
    expect(translate('ro', 'common.tooLong', { max: 40000 })).toBe(`Textul depășește ${new Intl.NumberFormat('ro-RO').format(40000)} de caractere.`);
    expect(translate('en', 'users.link.emailed', { email: 'a@b.ro' })).toBe('The link was emailed to a@b.ro.');
  });

  it('picks Romanian plural forms: one, few and the "de" form from 20', () => {
    expect(translatePlural('ro', 'usage.count.questions', 1)).toBe('1 întrebare');
    expect(translatePlural('ro', 'usage.count.questions', 3)).toBe('3 întrebări');
    expect(translatePlural('ro', 'usage.count.questions', 0)).toBe('0 întrebări');
    expect(translatePlural('ro', 'usage.count.questions', 20)).toBe('20 de întrebări');
    expect(translatePlural('en', 'usage.count.questions', 1)).toBe('1 question');
    expect(translatePlural('en', 'usage.count.questions', 20)).toBe('20 questions');
  });
});

describe('formatters', () => {
  it('format dates, days and sizes per locale through Intl', () => {
    const ts = Date.UTC(2026, 9, 17, 12, 0, 0) / 1000;
    expect(makeFormatters('ro').day('2026-10-17')).toBe(new Intl.DateTimeFormat('ro-RO', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(new Date(ts * 1000)));
    expect(makeFormatters('en').date(ts)).toBe(new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium' }).format(new Date(ts * 1000)));
    expect(makeFormatters('en').bytes(2048)).toContain('2');
    expect(makeFormatters('ro').day('not-a-date')).toBe('not-a-date');
  });

  it('show a moment as wall-clock time in a given IANA zone, falling back for an unknown one', () => {
    const ts = Date.UTC(2026, 9, 21, 6, 30) / 1000;
    const inBucharest = new Intl.DateTimeFormat('ro-RO', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/Bucharest' }).format(new Date(ts * 1000));
    expect(makeFormatters('ro').dateTimeIn(ts, 'Europe/Bucharest')).toBe(inBucharest);
    expect(makeFormatters('ro').dateTimeIn(ts, 'Not/AZone')).toBe(makeFormatters('ro').dateTime(ts));
  });

  it('describe relative times in the user language', () => {
    const now = Date.UTC(2026, 9, 17, 12, 0, 0);
    expect(makeFormatters('en').relative(now / 1000 - 120, now)).toBe('2 minutes ago');
    expect(makeFormatters('ro').relative(now / 1000 - 120, now)).toBe(new Intl.RelativeTimeFormat('ro-RO', { numeric: 'auto' }).format(-2, 'minute'));
  });
});
