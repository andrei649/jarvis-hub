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
