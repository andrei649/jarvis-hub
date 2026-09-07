import { describe, expect, it } from '@jest/globals';
import {
  captureState,
  captureStateLabel,
  describeExport,
  enabledSurfaces,
  exportFileName,
  exportStamp,
  isRecording,
  surfaceCaveat,
} from '../capturePolicy';
import type { CaptureExport, CaptureStatus } from '../../api/client';

const status = (over: Partial<CaptureStatus> = {}): CaptureStatus => ({
  enabled: false,
  surfaces: { clipboard: false, browser: false, files: false },
  records: 0,
  ...over,
});

describe('capture state — three facts that must not collapse into one', () => {
  it('separates "off", "on but nothing opted in", and "capturing"', () => {
    expect(captureState(status())).toBe('off');
    expect(captureState(status({ enabled: true }))).toBe('no_surfaces');
    expect(captureState(status({ enabled: true, surfaces: { clipboard: true, browser: false, files: false } })))
      .toBe('recording');
  });

  it('never reports "off" before the hub has answered', () => {
    // The dangerous default: a screen that renders an unfetched state as "off"
    // tells someone their clipboard is private when nobody has asked yet.
    expect(captureState(null)).toBe('unknown');
    expect(captureStateLabel('unknown')).toMatch(/has not answered/);
    expect(captureStateLabel('unknown')).not.toMatch(/\bOFF\b/);
  });

  it('an opted-in surface with the master switch off is not recording', () => {
    const s = status({ enabled: false, surfaces: { clipboard: true, browser: false, files: false } });
    expect(isRecording(s)).toBe(false);
    expect(enabledSurfaces(s)).toEqual(['clipboard']);
    expect(surfaceCaveat(s)).toBe("clipboard is opted in, but the hub's master switch is off.");
  });

  it('says nothing extra once it is genuinely recording', () => {
    const s = status({ enabled: true, surfaces: { clipboard: true, browser: true, files: false } });
    expect(isRecording(s)).toBe(true);
    expect(surfaceCaveat(s)).toBe('');
    expect(enabledSurfaces(s)).toEqual(['clipboard', 'browser']);
  });
});

describe('export naming and description', () => {
  const envelope = (over: Partial<CaptureExport> = {}): CaptureExport => ({
    version: 1,
    exported_at: 1_757_217_600,        // 2025-09-07T04:00:00Z
    surface: null,
    count: 2,
    surfaces: { clipboard: true, browser: false, files: false },
    records: [],
    ...over,
  });

  it('stamps the filename in UTC, because the file travels', () => {
    expect(exportStamp(1_757_217_600)).toBe('20250907-040000Z');
    expect(exportFileName(envelope())).toBe('nerva-capture-all-20250907-040000Z.json');
  });

  it('puts the surface filter in the filename', () => {
    expect(exportFileName(envelope({ surface: 'browser' }))).toBe('nerva-capture-browser-20250907-040000Z.json');
  });

  it('refuses to take a filename scope from an unknown surface', () => {
    // A hub that answered with a surface this client does not know must not be
    // able to write an arbitrary string into a filename.
    expect(exportFileName({ surface: '../../etc/passwd', exported_at: 1_757_217_600 }))
      .toBe('nerva-capture-all-20250907-040000Z.json');
  });

  it('says "unstamped" rather than inventing a time', () => {
    expect(exportStamp(null)).toBe('unstamped');
    expect(exportFileName(envelope({ exported_at: null }))).toBe('nerva-capture-all-unstamped.json');
  });

  it('always names the scope, so a filtered export cannot read as a complete one', () => {
    expect(describeExport(envelope())).toBe(
      '2 records from all surfaces · previews only, already redacted on the hub',
    );
    expect(describeExport(envelope({ surface: 'clipboard', count: 1 }))).toBe(
      '1 record from the clipboard surface · previews only, already redacted on the hub',
    );
  });
});
