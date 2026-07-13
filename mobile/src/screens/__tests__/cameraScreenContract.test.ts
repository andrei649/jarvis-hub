import { describe, expect, it } from '@jest/globals';

declare const require: (id: string) => any;
declare const __dirname: string;
const { readFileSync } = require('fs');
const { join } = require('path');

const mobileRoot = join(__dirname, '..', '..', '..');
const screen = () => readFileSync(join(mobileRoot, 'src', 'screens', 'CameraScreen.tsx'), 'utf8');
const app = () => readFileSync(join(mobileRoot, 'App.tsx'), 'utf8');

describe('native Camera Intelligence parity contract', () => {
  it('is a real native tab wired into the app shell', () => {
    expect(app()).toMatch(/import \{ CameraScreen \}/);
    expect(app()).toMatch(/key: 'cameras'.*label: 'Cameras'/);
    expect(app()).toMatch(/tab === 'cameras'.*<CameraScreen/s);
  });

  it('supports bounded status, event refresh, and private-body temporal search', () => {
    const source = screen();
    expect(source).toContain('fetchCameraStatus');
    expect(source).toContain('fetchCameraEvents');
    expect(source).toContain('searchCameraEvents');
    expect(source).toMatch(/description_provenance/);
    expect(source).toMatch(/Search events/);
  });

  it('is metadata-only and has no native image, video, stream, or admin discovery seam', () => {
    const source = screen();
    expect(source).not.toMatch(/\bImage\b|\bVideo\b|WebView|snapshot|rtsp|clip/i);
    expect(source).not.toMatch(/onvif|adminToken|X-Admin-Token/i);
  });
});
