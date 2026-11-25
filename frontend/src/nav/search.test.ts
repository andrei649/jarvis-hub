import { describe, expect, it } from 'vitest';
import { fold, matchScore, rankBy, tokenScore, wordsOf } from './search';

describe('fold', () => {
  it('ignores case and Romanian diacritics, comma-below and cedilla alike', () => {
    expect(fold('Încredere')).toBe('incredere');
    expect(fold('ȘTEFAN Țară ăâîșț')).toBe('stefan tara aaist');
    expect(fold('ştefan ţară')).toBe('stefan tara');
    expect(fold(null)).toBe('');
    expect(wordsOf('Look · Ledger ✓')).toEqual(['look', 'ledger']);
  });
});

describe('tokenScore', () => {
  it('ranks the whole text over its start, a word start and (3+ letters) the inside', () => {
    expect(tokenScore('logs', 'Logs')).toBe(5);
    expect(tokenScore('log', 'Logs')).toBe(4);
    expect(tokenScore('inbox', 'Decision inbox')).toBe(3);
    expect(tokenScore('ocum', 'Documentation')).toBe(1);
    expect(tokenScore('oc', 'Documentation')).toBe(0);
    expect(tokenScore('', 'x')).toBe(0);
  });
});

describe('matchScore and rankBy', () => {
  const items = [
    { label: 'Overview', hint: 'Trust' },
    { label: 'Trust', aliases: ['Încredere'] },
    { label: 'Logs', ids: ['logs'] },
    { label: 'Decision inbox', ids: ['decision-inbox'], otherLabels: ['Decizii'] },
  ];
  const read = (i: typeof items[number]) => ({ label: i.label, aliases: i.aliases, ids: i.ids, hint: i.hint, otherLabels: i.otherLabels });

  it('needs every word to match something', () => {
    expect(matchScore('trust overview', read(items[0]))).toBeGreaterThan(0);
    expect(matchScore('trust nothing', read(items[0]))).toBe(0);
    expect(matchScore('', read(items[0]))).toBe(0);
  });

  it('puts a label above an alias above a hint, and keeps ties in the registry order', () => {
    expect(rankBy(items, 'trust', read).map((i) => i.label)).toEqual(['Trust', 'Overview']);
    expect(rankBy(items, 'increder', read).map((i) => i.label)).toEqual(['Trust']);
    expect(rankBy(items, 'decizii', read).map((i) => i.label)).toEqual(['Decision inbox']);
    expect(rankBy(items, 'decision-inbox', read).map((i) => i.label)).toEqual(['Decision inbox']);
    expect(rankBy(items, '', read)).toEqual([]);
  });

  it('lifts a recent item and honours the limit', () => {
    const same = [{ label: 'Alpha one' }, { label: 'Alpha two' }, { label: 'Alpha three' }];
    const r = (i: { label: string }) => ({ label: i.label });
    expect(rankBy(same, 'alpha', r).map((i) => i.label)).toEqual(['Alpha one', 'Alpha two', 'Alpha three']);
    expect(rankBy(same, 'alpha', r, { recency: (i) => (i.label === 'Alpha three' ? 5 : 0) })[0].label).toBe('Alpha three');
    expect(rankBy(same, 'alpha', r, { limit: 2 })).toHaveLength(2);
  });
});
