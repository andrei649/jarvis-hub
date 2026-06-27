// H23.17 — i18n completeness gate: every locale must define the same keys as the
// reference (English), with no empty strings. Fails CI on a missing/extra/blank translation
// so a half-localized string can't ship.
import { describe, it, expect } from 'vitest';
import { V2 } from '../data';

describe('i18n completeness', () => {
  const I18N = (V2 as any).I18N as Record<string, Record<string, unknown>>;
  const locales = Object.keys(I18N);
  const REF = 'en';

  it('has the reference locale plus at least one translation', () => {
    expect(locales).toContain(REF);
    expect(locales.length).toBeGreaterThanOrEqual(2);
  });

  const refKeys = new Set(Object.keys(I18N[REF]));

  for (const loc of locales) {
    it(`"${loc}" key set matches "${REF}" (no missing / extra)`, () => {
      const locKeys = new Set(Object.keys(I18N[loc]));
      const missing = [...refKeys].filter((k) => !locKeys.has(k));
      const extra = [...locKeys].filter((k) => !refKeys.has(k));
      // Surface the offending keys in the failure message.
      expect({ locale: loc, missing, extra }).toEqual({ locale: loc, missing: [], extra: [] });
    });

    it(`"${loc}" has no empty translations`, () => {
      const blanks = Object.entries(I18N[loc])
        .filter(([, v]) => typeof v === 'string' && (v as string).trim() === '')
        .map(([k]) => k);
      expect(blanks).toEqual([]);
    });
  }
});
