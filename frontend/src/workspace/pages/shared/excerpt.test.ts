/* UX-06: a cited passage whose whitespace the server collapsed reads as a table again. */
import { describe, expect, it } from 'vitest';
import { excerptMarkdown } from './excerpt';

describe('excerptMarkdown', () => {
  it('rebuilds a DOCX table that arrived on one line, keeping the sentences around it', () => {
    const excerpt = 'Reducerea se notează în fișa clientului. | Categorie client | Discount | | --- | --- | | Client nou | 12% | | Client fidel | 8% | Politica intră în vigoare la 1 noiembrie 2026.';
    expect(excerptMarkdown(excerpt)).toBe([
      'Reducerea se notează în fișa clientului.',
      '',
      '| Categorie client | Discount |',
      '| --- | --- |',
      '| Client nou | 12% |',
      '| Client fidel | 8% |',
      '',
      'Politica intră în vigoare la 1 noiembrie 2026.',
    ].join('\n'));
  });

  it('puts an XLSX sheet heading on its own line, and keeps empty cells in place', () => {
    const excerpt = '## Încasări | Lună | Județ | Încasări (lei) | | --- | --- | --- | | Iulie | | 41250 | | August | Constanța | 38900.5 |';
    expect(excerptMarkdown(excerpt)).toBe([
      '## Încasări',
      '',
      '| Lună | Județ | Încasări (lei) |',
      '| --- | --- | --- |',
      '| Iulie | | 41250 |',
      '| August | Constanța | 38900.5 |',
    ].join('\n'));
  });

  it('leaves plain text, text that already has line breaks and a lone "#" alone', () => {
    expect(excerptMarkdown('Comisionul este de 3% din încasări.')).toBe('Comisionul este de 3% din încasări.');
    expect(excerptMarkdown('| a | b |\n| --- | --- |\n| 1 | 2 |')).toBe('| a | b |\n| --- | --- |\n| 1 | 2 |');
    expect(excerptMarkdown('Camera # 4 | Etaj | | --- | --- | | 1 | 2 |')).toContain('Camera # 4');
    expect(excerptMarkdown('Text fără separator | doar o bară |')).toBe('Text fără separator | doar o bară |');
  });

  it('handles two tables in one passage', () => {
    const out = excerptMarkdown('| A | B | | --- | --- | | 1 | 2 | Între ele. | C | | --- | | 3 |');
    expect(out).toBe('| A | B |\n| --- | --- |\n| 1 | 2 |\n\nÎntre ele.\n\n| C |\n| --- |\n| 3 |');
  });
});
