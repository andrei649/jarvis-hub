import { describe, expect, it } from 'vitest';
import { defineStrings, fmt, langOf, pick, plural, pluralForm, stringProblems } from './strings';

const SAMPLE = defineStrings({
  en: { empty: 'Nothing is waiting for you.', checked: 'checked {time}', entries: { one: '{n} entry', few: '{n} entries', other: '{n} entries' } },
  ro: { empty: 'Nimic nu te așteaptă.', checked: 'verificat la {time}', entries: { one: '{n} intrare', few: '{n} intrări', other: '{n} de intrări' } },
});

describe('the strings convention', () => {
  it('picks a language, English for anything but ro', () => {
    expect(langOf('ro')).toBe('ro');
    expect(langOf('en')).toBe('en');
    expect(langOf('de')).toBe('en');
    expect(langOf(undefined)).toBe('en');
    expect(pick(SAMPLE, 'ro').empty).toBe('Nimic nu te așteaptă.');
    expect(pick(SAMPLE, 'xx').empty).toBe('Nothing is waiting for you.');
  });

  it('fills placeholders and leaves a missing one visible', () => {
    expect(fmt('checked {time}', { time: '10:50' })).toBe('checked 10:50');
    expect(fmt('{a} of {b}', { a: 115, b: 121 })).toBe('115 of 121');
    expect(fmt('checked {time}')).toBe('checked {time}');
  });

  it('follows each language\'s plural rules', () => {
    const en = pick(SAMPLE, 'en').entries;
    const ro = pick(SAMPLE, 'ro').entries;
    expect(plural('en', en, 0)).toBe('0 entries');
    expect(plural('en', en, 1)).toBe('1 entry');
    expect(plural('en', en, 21)).toBe('21 entries');
    expect(plural('ro', ro, 0)).toBe('0 intrări');
    expect(plural('ro', ro, 1)).toBe('1 intrare');
    expect(plural('ro', ro, 7)).toBe('7 intrări');
    expect(plural('ro', ro, 19)).toBe('19 intrări');
    expect(plural('ro', ro, 20)).toBe('20 de intrări');
    expect(plural('ro', ro, 101)).toBe('101 intrări');
    expect(pluralForm('ro', 120)).toBe('other');
  });

  it('finds nothing wrong with a complete pair', () => {
    expect(stringProblems(SAMPLE)).toEqual([]);
  });

  it('reports missing, extra, blank, mismatched and cedilla strings', () => {
    const problems = stringProblems({
      en: { a: 'A {x}', b: 'B', c: { one: 'c', few: 'cs', other: 'cs' }, d: 'D' },
      ro: { a: 'A {y}', b: ' ', c: 'c', e: 'E', d: 'Şeful ţine' } as any,
    });
    expect(problems).toEqual(expect.arrayContaining([
      '"a" has placeholders {x} in en but {y} in ro',
      'ro has "e", which en does not',
      'ro.b is blank',
      '"c" is a plural in en but not in ro',
      'ro.d uses a cedilla ş or ţ; Romanian takes ș and ț',
    ]));
    expect(stringProblems({ en: { a: 'x' }, ro: {} })).toEqual(['ro is missing "a"']);
  });
});
