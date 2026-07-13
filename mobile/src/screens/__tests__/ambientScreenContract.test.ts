import { describe, expect, it } from '@jest/globals';

declare const require: (id: string) => any;
declare const __dirname: string;
const { readFileSync } = require('fs');
const { join } = require('path');
const mobileRoot = join(__dirname, '..', '..', '..');
const screen = () => readFileSync(join(mobileRoot, 'src', 'screens', 'AmbientScreen.tsx'), 'utf8');
const app = () => readFileSync(join(mobileRoot, 'App.tsx'), 'utf8');

describe('native Ambient Watch parity contract', () => {
  it('is a real read-only native tab', () => {
    expect(app()).toMatch(/import \{ AmbientScreen \}/);
    expect(app()).toMatch(/key: 'ambient'.*label: 'Watch'/);
    expect(app()).toMatch(/tab === 'ambient'.*<AmbientScreen/s);
  });

  it('shows monitor health, chosen rung, and global attention without admin mutation', () => {
    const source = screen();
    expect(source).toContain('fetchAmbientMonitors');
    expect(source).toMatch(/What Jarvis is watching/);
    expect(source).toMatch(/Global attention/);
    expect(source).toMatch(/policy_reason/);
    expect(source).not.toMatch(/apiPost|apiPut|apiDelete|adminToken|X-Admin-Token/);
    expect(source).not.toMatch(/monitor\.subject_id|monitor\.predicates|decision\.event_fingerprint|data\.recipients/);
  });
});
