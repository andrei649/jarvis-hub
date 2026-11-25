// @ts-nocheck
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const root = process.cwd();
const hudDoc = readFileSync(join(root, '..', 'docs', 'design', 'HUD_V2_REMAINING.md'), 'utf8');
const gap = readFileSync(join(root, 'src', 'gap.tsx'), 'utf8');
const app = readFileSync(join(root, 'src', 'app.tsx'), 'utf8');
const cockpit = readFileSync(join(root, 'src', 'cockpit.tsx'), 'utf8');
// The trust readings the HUD v2 top bar drew as badges (shell.tsx, deleted with the classic shell)
// are the running head's Egress and Microphone items now: read fail-closed into the hub snapshot,
// worded by the trust signals.
const hubTypes = readFileSync(join(root, 'src', 'frame', 'types.ts'), 'utf8');
const trustSignals = readFileSync(join(root, 'src', 'signals', 'trust-signals.ts'), 'utf8');

describe('O26-P3.2 HUD remaining-work reconciliation', () => {
  it('does not list shipped cockpit voice/cognition/trust controls as missing', () => {
    expect(hudDoc).not.toMatch(/Per.message TTS[\s\S]*dropped in the port/i);
    expect(hudDoc).not.toMatch(/Streaming cognition[\s\S]*upgrade to a real\s+\*\*SSE\*\* stream/i);
    expect(hudDoc).not.toMatch(/Strict.local \/ mic trust badge[\s\S]*topbar edit deferred/i);
  });

  it('does not list shipped console controls inside the missing-controls paragraph', () => {
    const missingControls = hudDoc.match(/Still missing interactive controls[\s\S]*?\n\n/)?.[0] || '';

    expect(missingControls).not.toMatch(/prompt rollback\/commit/i);
    expect(missingControls).not.toMatch(/secrets store form/i);
    expect(missingControls).not.toMatch(/LM Studio model controls/i);
    expect(missingControls).not.toMatch(/heartbeat start\/stop\/run/i);
    expect(missingControls).not.toMatch(/sandbox\s+execute/i);
    expect(missingControls).not.toMatch(/Data Spaces assign\/unassign/i);
  });

  it('pins the source wiring that makes those doc closures true', () => {
    expect(cockpit).toContain("playTts(text, lang || 'en')");
    expect(cockpit).toContain('voice settings');
    // Phase B retired the cockpit's cognition trace and its live scoring stream (PHASE_B_PLAN.md
    // §2.4, honesty defects D11 and D15): the HUD neither subscribes to it nor asks the snapshot
    // for a trace; the Observe › Cognition panel keeps its own reads.
    expect(app).not.toContain('/api/cognition');
    expect(app).not.toContain('EventSource');
    expect(gap).toContain("useApi('/api/cognition/status')");
    expect(hubTypes).toContain('strictLocal: t.strict_local === true');
    expect(hubTypes).toContain("t.mic === 'off'");
    expect(trustSignals).toContain('hub.trust.strictLocal');
    expect(trustSignals).toContain("mic === 'on' ? s.micOn : s.micMuted");

    expect(gap).toContain("apiPut('/api/admin/settings/' + cat");
    expect(gap).toContain("apiPost(`${base}/rollback`");
    expect(gap).toContain("apiPost(`${base}/commit`");
    expect(gap).toContain("apiPost('/api/secrets/broker'");
    expect(gap).toContain("apiPost('/api/memory/spaces/assign'");
    expect(gap).toContain("apiPost('/api/memory/spaces/unassign'");
    expect(gap).toContain("apiPost('/sandbox/execute'");
    // DRA-28 — the v2 Console can create AND edit a workflow, not just read one.
    expect(gap).toContain("apiPost('/api/workflows'");
    expect(gap).toContain("apiPut('/api/workflows/'");
    expect(gap).toContain("act('/heartbeat/' + encodeURIComponent(id) + '/' + op");
    expect(gap).toContain("runAction('load', '/api/llm/load'");
    expect(gap).toContain("runAction('unload', '/api/llm/unload'");
  });
});
