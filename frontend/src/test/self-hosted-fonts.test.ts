// @ts-nocheck
import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const root = process.cwd();
const styles = readFileSync(join(root, 'src', 'styles.css'), 'utf8');

const fontAssets = [
  'src/assets/fonts/space-grotesk-latin-var.woff2',
  'src/assets/fonts/jetbrains-mono-latin-var.woff2',
];

describe('HUD v2 self-hosted fonts', () => {
  it('loads Space Grotesk and JetBrains Mono from local woff2 assets', () => {
    expect(styles).toContain("@font-face");
    expect(styles).toContain("font-family: 'Space Grotesk'");
    expect(styles).toContain("font-family: 'JetBrains Mono'");
    expect(styles).toContain("url('./assets/fonts/space-grotesk-latin-var.woff2')");
    expect(styles).toContain("url('./assets/fonts/jetbrains-mono-latin-var.woff2')");
    expect(styles).toContain('font-display: swap');
    expect(styles).not.toMatch(/fonts\.(googleapis|gstatic)\.com/);
  });

  it('commits valid woff2 files for the branded HUD font stack', () => {
    for (const asset of fontAssets) {
      const path = join(root, asset);
      expect(existsSync(path), `${asset} exists`).toBe(true);
      const file = readFileSync(path);
      expect(file.toString('ascii', 0, 4), `${asset} is a WOFF2 file`).toBe('wOF2');
      expect(file.length, `${asset} is not an empty placeholder`).toBeGreaterThan(1024);
    }
  });
});

/* The latin slices above stop at U+00FF: â and î are in them, ă ș ț (and the cedilla ş ţ older
   text still uses) are not. theme/fonts.css adds the latin-ext slices of the same faces. */
describe('HUD latin-ext font slices (theme/fonts.css)', () => {
  const strip = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '');
  const fonts = strip(readFileSync(join(root, 'src', 'theme', 'fonts.css'), 'utf8'));
  const faces = (css) => [...css.matchAll(/@font-face\s*\{([^}]*)\}/g)].map((m) => {
    const prop = (name) => new RegExp(`(?:^|[;{\\s])${name}\\s*:\\s*([^;]+);`).exec(m[1])?.[1].trim();
    return { family: prop('font-family'), style: prop('font-style'), weight: prop('font-weight'), src: prop('src'), range: prop('unicode-range') };
  });
  const covers = (range, code) => range.split(',').some((part) => {
    const [lo, hi] = part.trim().replace(/^U\+/i, '').split('-').map((hex) => parseInt(hex, 16));
    return code >= lo && code <= (hi ?? lo);
  });

  it('declares the latin-ext slice of each vendored face from a local woff2, so Romanian never falls back', () => {
    expect(fonts, 'fonts.css stays local').not.toMatch(/https?:|\/\/fonts\.|@import/);
    const latin = faces(strip(styles));
    const ext = faces(fonts).filter((face) => face.family === "'JetBrains Mono'" || face.family === "'Space Grotesk'");
    expect(ext.map((face) => face.family).sort()).toEqual(["'JetBrains Mono'", "'Space Grotesk'"]);
    for (const face of ext) {
      const url = /^url\('([^']+)'\) format\('woff2'\)$/.exec(face.src ?? '')?.[1];
      expect(url, `${face.family} src`).toMatch(/^\.\.\/assets\/fonts\/[a-z-]+-latin-ext-var\.woff2$/);
      const file = readFileSync(join(root, 'src', 'theme', url));
      expect(file.toString('ascii', 0, 4), `${url} is a WOFF2 file`).toBe('wOF2');
      expect(file.length, `${url} is not an empty placeholder`).toBeGreaterThan(1024);
      // the same face as styles.css's latin slice, so the browser composes the two into one font
      const twin = latin.find((other) => other.family === face.family);
      expect(twin, `styles.css declares the latin ${face.family}`).toBeTruthy();
      expect({ style: face.style, weight: face.weight }).toEqual({ style: twin.style, weight: twin.weight });
      for (const ch of 'ăĂșȘțȚşŞţŢ') expect(covers(face.range, ch.codePointAt(0)), `${face.family} latin-ext covers ${ch}`).toBe(true);
      for (const ch of 'âÂîÎ') expect(covers(twin.range, ch.codePointAt(0)), `${face.family} latin covers ${ch}`).toBe(true);
    }
  });

  /* The Ledger faces (2026-11-23, owner-approved download, SIL OFL 1.1): Literata for what Nerva
     writes, variable with optical sizes, upright and italic; Barlow for the instrument, static
     300-700. Each in a latin and a latin-ext slice, from local woff2 files. */
  it('self-hosts Literata and Barlow, latin and latin-ext, from local woff2 files', () => {
    const ledger = faces(fonts).filter((face) => face.family === "'Literata'" || face.family === "'Barlow'");
    const want = [
      ...['normal', 'italic'].flatMap((style) => ['latin', 'latin-ext'].map((slice) => `'Literata' ${style} 200 900 ${slice}`)),
      ...['300', '400', '500', '600', '700'].flatMap((weight) => ['latin', 'latin-ext'].map((slice) => `'Barlow' normal ${weight} ${slice}`)),
    ].sort();
    const got = ledger.map((face) => {
      const url = /^url\('([^']+)'\) format\('woff2'\)$/.exec(face.src ?? '')?.[1] ?? '';
      expect(url, `${face.family} ${face.weight} src`).toMatch(/^\.\.\/assets\/fonts\/(literata|barlow)-latin(-ext)?-[a-z0-9-]+\.woff2$/);
      const file = readFileSync(join(root, 'src', 'theme', url));
      expect(file.toString('ascii', 0, 4), `${url} is a WOFF2 file`).toBe('wOF2');
      expect(file.length, `${url} is not an empty placeholder`).toBeGreaterThan(1024);
      const slice = /-latin-ext-/.test(url) ? 'latin-ext' : 'latin';
      if (slice === 'latin-ext') for (const ch of 'ăĂșȘțȚ') expect(covers(face.range, ch.codePointAt(0)), `${url} covers ${ch}`).toBe(true);
      else for (const ch of 'âÂîÎ') expect(covers(face.range, ch.codePointAt(0)), `${url} covers ${ch}`).toBe(true);
      return `${face.family} ${face.style} ${face.weight} ${slice}`;
    }).sort();
    expect(got).toEqual(want);
    // the licences travel with the files
    for (const licence of ['OFL-Literata.txt', 'OFL-Barlow.txt']) {
      expect(readFileSync(join(root, 'src', 'assets', 'fonts', licence), 'utf8')).toContain('SIL Open Font License');
    }
  });

  it('is the first stylesheet theme/index.css imports', () => {
    const index = strip(readFileSync(join(root, 'src', 'theme', 'index.css'), 'utf8'));
    const imports = [...index.matchAll(/@import\s+['"]([^'"]+)['"]/g)].map((m) => m[1]);
    expect(imports[0]).toBe('./fonts.css');
  });
});
