import { describe, expect, it } from '@jest/globals';

declare const require: (id: string) => any;
declare const __dirname: string;
const { readFileSync } = require('fs');
const { join } = require('path');

const mobileRoot = join(__dirname, '..', '..', '..');
const screen = () => readFileSync(join(mobileRoot, 'src', 'screens', 'MediaScreen.tsx'), 'utf8');
const app = () => readFileSync(join(mobileRoot, 'App.tsx'), 'utf8');

describe('native Media Director surface contract', () => {
  it('is a real native tab wired into the app shell', () => {
    expect(app()).toMatch(/import \{ MediaScreen \}/);
    expect(app()).toMatch(/key: 'media'.*label: 'Media'/);
    expect(app()).toMatch(/tab === 'media'.*<MediaScreen/s);
  });

  it('keeps actuation explicit and exposes honest outcome states', () => {
    const source = screen();
    expect(source).toContain('loaded && !enabled && !error');
    expect(source).toContain("accessibilityLabel=\"Present media\"");
    expect(source).toContain("accessibilityLabel={`Restore ${session.device_id}`}");
    expect(source).toMatch(/verified success/i);
    expect(source).toMatch(/unverified/i);
    expect(source).toMatch(/queued for approval/i);
    expect(source).toMatch(/refused/i);
  });

  it('is metadata-only and gates registry controls on the admin token', () => {
    const source = screen();
    expect(source).toContain('config.adminToken.trim()');
    expect(source).toMatch(/Admin token required/i);
    expect(source).not.toMatch(/\bImage\b/);
    expect(source).not.toMatch(/WebView|iframe/i);
  });
});
