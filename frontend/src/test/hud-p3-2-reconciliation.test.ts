// @ts-nocheck
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const root = process.cwd();
const hudDoc = readFileSync(join(root, '..', 'docs', 'design', 'HUD_V2_REMAINING.md'), 'utf8');
const gap = readFileSync(join(root, 'src', 'gap.tsx'), 'utf8');
const app = readFileSync(join(root, 'src', 'app.tsx'), 'utf8');
const cockpit = readFileSync(join(root, 'src', 'cockpit.tsx'), 'utf8');
const shell = readFileSync(join(root, 'src', 'shell.tsx'), 'utf8');

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
  });

  it('pins the source wiring that makes those doc closures true', () => {
    expect(cockpit).toContain("playTts(text, lang || 'en')");
    expect(cockpit).toContain('voice settings');
    expect(app).toContain("new EventSource('/api/cognition/stream')");
    expect(shell).toContain('strict_local');
    expect(shell).toContain("tr.mic === 'off'");

    expect(gap).toContain("apiPut('/api/admin/settings/' + cat");
    expect(gap).toContain("apiPost(`${base}/rollback`");
    expect(gap).toContain("apiPost(`${base}/commit`");
    expect(gap).toContain("apiPost('/api/secrets/broker'");
    expect(gap).toContain("apiPost('/sandbox/execute'");
    expect(gap).toContain("act('/heartbeat/' + encodeURIComponent(id) + '/' + op");
    expect(gap).toContain("actA('/api/llm/load'");
    expect(gap).toContain("actA('/api/llm/unload'");
  });
});
