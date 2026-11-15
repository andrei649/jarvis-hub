import { describe, expect, it } from '@jest/globals';

declare const require: (id: string) => any;
declare const __dirname: string;
const { readFileSync } = require('fs');
const { join } = require('path');

const mobileRoot = join(__dirname, '..', '..', '..');
const component = () => readFileSync(join(mobileRoot, 'src', 'components', 'ExtensionInspection.tsx'), 'utf8');
const api = () => readFileSync(join(mobileRoot, 'src', 'api', 'extensions.ts'), 'utf8');
const status = () => readFileSync(join(mobileRoot, 'src', 'screens', 'StatusScreen.tsx'), 'utf8');

describe('native extension inspection disclosure contract', () => {
  it('is placed after delivery receipts on Status', () => {
    const source = status();
    expect(source).toMatch(/import \{ ExtensionInspection \} from '..\/components\/ExtensionInspection'/);
    expect(source.indexOf('<DeliveryReceipts />')).toBeGreaterThanOrEqual(0);
    expect(source.indexOf('<ExtensionInspection />')).toBeGreaterThan(source.indexOf('<DeliveryReceipts />'));
  });

  it('is collapsed by default and reads only while open against a configured hub', () => {
    const source = component();
    expect(source).toMatch(/useState\(false\)/);
    expect(source).toContain('if (open && ready && configured) load()');
    expect(source).toContain('fetchExtensionInspection(config, abort.signal)');
    expect(source).toContain('accessibilityLabel="Open extension inspection"');
  });

  it('aborts and fences old data when closed, unmounted, refreshed, or the hub identity changes', () => {
    const source = component();
    expect(source).toContain('key={`${chatScope}:${connectionEpoch}`}');
    expect(source).toContain('controller.current?.abort()');
    expect(source).toContain('++sequence.current');
    expect(source).toContain('setReport(null)');
    expect(source).toContain('sequence.current === request && !abort.signal.aborted');
  });

  it('has no activation or consent controls and displays separate inspection facts', () => {
    const source = component();
    expect(source).toMatch(/Signature \{row\.signatureVerified/);
    expect(source).toMatch(/Owner approval \{row\.approvalVerified/);
    expect(source).toMatch(/Currently callable tools/);
    expect(source).toMatch(/Currently callable commands/);
    expect(source).toMatch(/Quarantine not checked/);
    expect(source).not.toMatch(/\/activate|\/consent|POST|install\(|dispatch\(/i);
  });

  it('uses only the existing user-guarded GET and never retains raw response bodies', () => {
    const source = api();
    expect(source).toContain("'/api/plugins/extensions'");
    expect(source).toContain("method: 'GET'");
    expect(source).toContain("headers['X-User-Token']");
    expect(source).not.toMatch(/adminToken|X-Admin-Token|response\.text\(\)/);
    expect(source).toContain("'Extension inspection unavailable'");
  });
});
