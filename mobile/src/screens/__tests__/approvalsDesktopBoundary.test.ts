import { describe, expect, it } from '@jest/globals';
import { approvalPolicy } from '../approvalPolicy';

declare const require: (id: string) => any;
declare const __dirname: string;
const { readFileSync } = require('fs');
const { join } = require('path');

const mobileRoot = join(__dirname, '..', '..', '..');
const approvalsScreen = () =>
  readFileSync(join(mobileRoot, 'src', 'screens', 'ApprovalsScreen.tsx'), 'utf8');

describe('native desktop approval boundary', () => {
  it('withholds desktop payload and Approve while preserving stop and postpone actions', () => {
    expect(approvalPolicy({ kind: 'toolrpc.desktop_run' })).toEqual({
      showPayload: false,
      canApprove: false,
      canReject: true,
      canDefer: true,
    });
  });

  it('leaves generic approval cards unchanged', () => {
    const genericPolicy = {
      showPayload: true,
      canApprove: true,
      canReject: true,
      canDefer: true,
    };

    expect(approvalPolicy({ kind: 'calendar.create_event' })).toEqual(genericPolicy);
    expect(approvalPolicy({ kind: 'toolrpc.desktop_run.preview' })).toEqual(genericPolicy);
    expect(approvalPolicy({})).toEqual(genericPolicy);
  });

  it('routes desktop approval to the Owner HUD without exposing payload or Approve', () => {
    const source = approvalsScreen();

    expect(source).toMatch(/import \{ approvalPolicy \} from '\.\/approvalPolicy';/);
    expect(source).toMatch(/const policy = approvalPolicy\(task\);/);
    expect(source).toMatch(/policy\.showPayload\s*\?\s*payloadPreview\(task\)\s*:\s*null/);
    expect(source).toContain('Approval unavailable in mobile app · continue in Owner HUD');
    expect(source).toMatch(/\{policy\.canApprove\s*&&\s*button\('accept', 'Approve'/);
    expect(source.match(/button\('accept'/g)).toHaveLength(1);
    expect(source).toMatch(/\{policy\.canReject\s*&&\s*button\('reject', 'Reject'/);
    expect(source).toMatch(/\{policy\.canDefer\s*&&\s*button\('defer', 'Defer'/);
  });
});
