import { describe, expect, it } from '@jest/globals';

declare const require: (id: string) => any;
declare const __dirname: string;
const { readFileSync } = require('fs');
const { join } = require('path');

const mobileRoot = join(__dirname, '..', '..', '..');
const screen = () => readFileSync(join(mobileRoot, 'src', 'screens', 'HouseScreen.tsx'), 'utf8');
const app = () => readFileSync(join(mobileRoot, 'App.tsx'), 'utf8');

describe('native House Brain parity contract', () => {
  it('is a real native tab wired into the app shell', () => {
    expect(app()).toMatch(/import \{ HouseScreen \}/);
    expect(app()).toMatch(/key: 'house'.*label: 'Home'/);
    expect(app()).toMatch(/tab === 'house'.*<HouseScreen/s);
  });

  it('is read parity with a deliberate handoff to the approvals surface', () => {
    const source = screen();
    expect(source).toContain('fetchHouseState');
    expect(source).toContain('onGoToApprovals');
    expect(source).toMatch(/Open Approvals/);
    expect(source).toMatch(/Strong confirmation stays on the owner HUD/);
  });

  it('never exposes a mobile security actuation or confirmation shortcut', () => {
    const source = screen();
    expect(source).not.toMatch(/control\/security|security\/.*challenge|security\/.*confirm/);
    expect(source).not.toMatch(/Confirm exact security action|Unlock door|Disarm alarm/);
    expect(source).not.toContain('adminToken');
  });
});
