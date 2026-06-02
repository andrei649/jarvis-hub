// Pure formatting/escaping helpers from components.js.
// These are `const` lexical globals, so we pull them off window.__hud.
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { loadHud } from './harness.js';

let env;
beforeEach(() => {
  env = loadHud({ files: ['components'], expose: ['pad2', 'fmtTime', 'fmtDate', 'nowTs', 'esc'] });
});
afterEach(() => env.cleanup());

describe('pad2', () => {
  it('zero-pads single digits', () => {
    expect(env.hud.pad2(3)).toBe('03');
    expect(env.hud.pad2(0)).toBe('00');
  });
  it('leaves two-digit numbers unchanged', () => {
    expect(env.hud.pad2(42)).toBe('42');
  });
});

describe('fmtTime', () => {
  it('formats HH:MM:SS with zero padding', () => {
    const d = new Date(2026, 5, 2, 7, 4, 9);
    expect(env.hud.fmtTime(d)).toBe('07:04:09');
  });
});

describe('fmtDate', () => {
  it('formats with Romanian day/month abbreviations', () => {
    // 2026-06-02 is a Tuesday → MAR · 02 IUN 2026
    const d = new Date(2026, 5, 2);
    expect(env.hud.fmtDate(d)).toBe('MAR · 02 IUN 2026');
  });
});

describe('nowTs', () => {
  it('returns a HH:MM:SS timestamp string', () => {
    expect(env.hud.nowTs()).toMatch(/^\d{2}:\d{2}:\d{2}$/);
  });
});

describe('esc', () => {
  it('escapes HTML-significant characters', () => {
    expect(env.hud.esc(`<script>"x" & 'y'</script>`)).toBe(
      '&lt;script&gt;&quot;x&quot; &amp; &#39;y&#39;&lt;/script&gt;',
    );
  });
  it('coerces non-strings', () => {
    expect(env.hud.esc(123)).toBe('123');
  });
  it('leaves safe text untouched', () => {
    expect(env.hud.esc('hello world')).toBe('hello world');
  });
});
