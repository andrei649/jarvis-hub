import { describe, expect, it } from '@jest/globals';

declare const require: (id: string) => any;
declare const __dirname: string;
const { readFileSync } = require('fs');
const { join } = require('path');
const mobileRoot = join(__dirname, '..', '..', '..');
const screen = () => readFileSync(join(mobileRoot, 'src', 'screens', 'CaptureScreen.tsx'), 'utf8');
/** The source with comments removed.
 *
 * The absence assertions below must be about what the screen CALLS, not about what it
 * talks about: the header comment names `/api/capture/surfaces` and
 * `/api/capture/ingest` precisely to record that they are absent by decision, and a
 * naive grep would read that explanation as the violation it is documenting. Block
 * comments and whole-line `//` comments only — nothing here strips a `//` out of the
 * middle of a line, so a URL in a string literal survives. */
const code = () => screen()
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .split('\n')
  .filter((line: string) => !/^\s*(\/\/|\*)/.test(line))
  .join('\n');
const app = () => readFileSync(join(mobileRoot, 'App.tsx'), 'utf8');

describe('native Capture inbox parity contract (T-0.26)', () => {
  it('is a real native tab, not a stub', () => {
    expect(app()).toMatch(/import \{ CaptureScreen \}/);
    expect(app()).toMatch(/key: 'capture'.*label: 'Capture'/);
    expect(app()).toMatch(/tab === 'capture'.*<CaptureScreen/s);
  });

  it('covers the whole H12.7 promise: inspect, forget one, clear all, export', () => {
    const source = screen();
    for (const fn of ['fetchCaptureStatus', 'fetchCaptureRecords', 'forgetCaptureRecord',
      'clearCapture', 'fetchCaptureExport']) {
      expect(source).toContain(fn);
    }
  });

  it('cannot arm capture from the phone', () => {
    // /api/capture/surfaces and /api/capture/ingest are user-guarded and reachable —
    // they are absent by decision, not by permission. Enabling a surface arms an
    // ambient recorder on a machine you are not sitting at, so a lost or borrowed
    // handset must not be a way to start recording someone else's desk. Deleting is
    // safe in the direction that matters: the worst case is losing a record you
    // wanted, never gaining one nobody consented to.
    const source = code();
    expect(source).not.toMatch(/capture\/surfaces|capture\/ingest|setSurfaces|ingestCapture/);
    expect(source).not.toMatch(/adminToken|X-Admin-Token/);
    // and the explanation is still in the file, where the next reader will find it
    expect(screen()).toMatch(/absent by decision|deliberately cannot do/);
  });

  it('never renders an unanswered hub as "capture is off"', () => {
    const source = code();
    // The failure path sets the status back to null (state `unknown`), never to a
    // fabricated disabled snapshot — the most reassuring possible lie on this screen.
    expect(source).toMatch(/setStatus\(null\)/);
    expect(source).not.toMatch(/setStatus\(\{[^}]*enabled:\s*false/);
    expect(source).toContain('captureStateLabel');
  });

  it('confirms both destructive actions before they run', () => {
    const source = code();
    expect(source).toMatch(/Alert\.alert\('Forget this record\?'/);
    expect(source).toMatch(/Alert\.alert\('Clear the inbox\?'/);
    expect((source.match(/style: 'destructive'/g) || []).length).toBe(2);
  });

  it('reports a no-op delete as a no-op', () => {
    // `forgotten: false` means the hub had no such record. Removing the row anyway
    // would look exactly like success for something that did not happen.
    expect(code()).toMatch(/res\.forgotten \?[\s\S]{0,120}nothing was deleted/);
  });
});
