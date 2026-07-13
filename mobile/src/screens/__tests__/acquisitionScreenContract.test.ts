import { describe, expect, it } from '@jest/globals';

declare const require: (id: string) => any;
declare const __dirname: string;
const { readFileSync } = require('fs');
const { join } = require('path');

const mobileRoot = join(__dirname, '..', '..', '..');
const screen = () => readFileSync(join(mobileRoot, 'src', 'screens', 'AcquisitionScreen.tsx'), 'utf8');
const app = () => readFileSync(join(mobileRoot, 'App.tsx'), 'utf8');

describe('native governed acquisition parity contract', () => {
  it('is a real native tab wired into the app shell', () => {
    expect(app()).toMatch(/import \{ AcquisitionScreen \}/);
    expect(app()).toMatch(/key: 'acquisition'.*label: 'Acquire'/);
    expect(app()).toMatch(/tab === 'acquisition'.*<AcquisitionScreen/s);
  });

  it('renders read-only status, reuse, signed packages, and hash-only event metadata', () => {
    const source = screen();
    expect(source).toContain('fetchAcquisitionStatus');
    expect(source).toContain('fetchAcquisitionEvents');
    expect(source).toMatch(/reuse_rate/);
    expect(source).toMatch(/chain_valid/);
    expect(source).toMatch(/event_type/);
  });

  it('has no admin token, install, revoke, rollback, signing, or purge seam', () => {
    const source = screen();
    expect(source).not.toMatch(/adminToken|X-Admin-Token|revoke|rollback|signing|purge|install\(/i);
  });
});
