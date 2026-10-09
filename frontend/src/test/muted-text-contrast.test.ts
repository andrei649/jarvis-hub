import { describe, expect, it } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join, relative } from 'node:path';

const source = join(process.cwd(), 'src');
const css = readFileSync(join(source, 'styles.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    return entry.isDirectory() ? files(path) : entry.name.endsWith('.tsx') && !entry.name.endsWith('.test.tsx') ? [path] : [];
  });
}

const luminance = (rgb: number[]) => rgb.map((v) => {
  const s = v / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}).reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);

const hex = (value: string) => [1, 3, 5].map((i) => parseInt(value.slice(i, i + 2), 16));
const rgba = (value: string, ground: number[]) => {
  const match = /^rgba\((\d+),(\d+),(\d+),([\d.]+)\)$/.exec(value);
  if (!match) throw new Error(`unexpected ink token ${value}`);
  return ground.map((v, i) => Number(match[i + 1]) * Number(match[4]) + v * (1 - Number(match[4])));
};
const ratio = (a: number[], b: number[]) => {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
};

describe('muted HUD text', () => {
  it('uses a normal-text foreground with AA contrast on both looks and both opaque grounds', () => {
    const grounds = [...css.matchAll(/--void(?:-2)?:\s*(#[0-9a-f]{6})/gi)].map((m) => hex(m[1]));
    const inks = [...css.matchAll(/--ink-2:\s*(rgba\([^)]*\))/g)].map((m) => m[1]);
    expect(grounds).toHaveLength(4);
    expect(inks).toHaveLength(2);
    for (const ink of inks) for (const ground of grounds) {
      expect(ratio(rgba(ink, ground), ground), `${ink} on ${ground.join(',')}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('keeps decorative ink-3 out of foregrounds, including inline badges and SVG text', () => {
    const exceptions = new Set(['.agent-row .gx', '.pal-item svg']); // icon-only color
    const badCss = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].flatMap((match) => {
      const selector = match[1].trim();
      if (exceptions.has(selector)) return [];
      return /(?:^|;)\s*(?:color|fill)\s*:\s*var\(--ink-3\)/.test(match[2]) ? [selector] : [];
    });
    expect(badCss, 'CSS text foregrounds still using decorative ink-3').toEqual([]);

    const decorative = new Map([
      ['network.tsx', /(?:\bstroke=\{|const taskColor =).*var\(--ink-3\)/],
      ['gap.tsx', /(?:off:|unknown:|const stroke =|const statusTextColor =).*var\(--ink-3\)/],
    ]);
    const badTsx = files(source).flatMap((path) => readFileSync(path, 'utf8').split('\n').flatMap((line, index) => {
      if (!line.includes('var(--ink-3)')) return [];
      const rel = relative(source, path);
      return decorative.get(rel)?.test(line) ? [] : [`${rel}:${index + 1}`];
    }));
    expect(badTsx, 'TSX text foregrounds still using decorative ink-3').toEqual([]);

    const systemMap = readFileSync(join(source, 'gap.tsx'), 'utf8');
    expect(systemMap).toContain("const statusTextColor = stroke === 'var(--ink-3)' ? 'var(--ink-2)' : stroke;");
    expect(systemMap).toContain('fill={statusTextColor}');
    expect(systemMap).not.toContain('fill={stroke} style={{ font:');
  });
});
