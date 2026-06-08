// @ts-nocheck
/* Smoke tests for the newly-wired interactive controls: each helper in api/actions.ts
   must hit the REAL endpoint (method + path + body) verified against agents/web.py.
   fetch is fully mocked — no network, no backend — so these assert the wiring only. */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  getKillSwitch, setKillSwitch, installSkill, togglePlugin,
  getAgentSoul, getAgentHistory, memorySearch, kgEntities, playTts,
} from '../api/actions';

function mockFetch(json: any = { ok: true }, opts: any = {}) {
  const fn = vi.fn().mockResolvedValue({
    ok: opts.ok !== false,
    status: opts.status || 200,
    json: async () => json,
    blob: async () => new Blob(['audio'], { type: 'audio/mpeg' }),
  });
  global.fetch = fn as any;
  return fn;
}

// The last call's [path, init] so each test can assert method/path/body precisely.
const lastCall = (fn: any) => fn.mock.calls[fn.mock.calls.length - 1];

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
});

describe('kill-switch wiring', () => {
  it('GET reads /api/security/kill-switch', async () => {
    const fn = mockFetch({ halted: false });
    await getKillSwitch();
    const [path, init] = lastCall(fn);
    expect(path).toBe('/api/security/kill-switch');
    expect(init.method).toBe('GET');
  });

  it('POST engages with {engage:true, scope:"global"} to /api/security/kill-switch', async () => {
    const fn = mockFetch({ ok: true, engaged: true });
    await setKillSwitch(true);
    const [path, init] = lastCall(fn);
    expect(path).toBe('/api/security/kill-switch');
    expect(init.method).toBe('POST');
    const body = JSON.parse(init.body);
    expect(body).toMatchObject({ engage: true, scope: 'global' });
  });
});

describe('marketplace skill install (H12.12)', () => {
  it('POSTs the skill name to /api/skills/marketplace/install', async () => {
    const fn = mockFetch({ ok: true, installed: 'Demo Skill' });
    await installSkill('Demo Skill');
    const [path, init] = lastCall(fn);
    expect(path).toBe('/api/skills/marketplace/install');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ name: 'Demo Skill' });
  });
});

describe('plugin enable/disable', () => {
  it('PUTs /plugins/{id}/toggle (id encoded, no body)', async () => {
    const fn = mockFetch({ id: 'gmail', enabled: false, action: 'disabled' });
    await togglePlugin('gmail');
    const [path, init] = lastCall(fn);
    expect(path).toBe('/plugins/gmail/toggle');
    expect(init.method).toBe('PUT');
  });
});

describe('dossier soul + history', () => {
  it('GETs /api/agents/{id}/soul', async () => {
    const fn = mockFetch({ agent_id: 'pepper', soul: '...' });
    await getAgentSoul('pepper');
    expect(lastCall(fn)[0]).toBe('/api/agents/pepper/soul');
  });
  it('GETs /api/agents/{id}/history', async () => {
    const fn = mockFetch({ agent_id: 'pepper', runs: [] });
    await getAgentHistory('pepper');
    expect(lastCall(fn)[0]).toBe('/api/agents/pepper/history');
  });
});

describe('memory + KG', () => {
  it('memorySearch GETs /api/memory/search?q=', async () => {
    const fn = mockFetch({ results: [] });
    await memorySearch('recent');
    expect(lastCall(fn)[0]).toContain('/api/memory/search?q=recent');
  });
  it('kgEntities GETs /api/kg/entities', async () => {
    const fn = mockFetch({ entities: [] });
    await kgEntities();
    expect(lastCall(fn)[0]).toContain('/api/kg/entities');
  });
});

describe('per-message TTS replay', () => {
  it('POSTs {text,lang} to /tts and reads the audio blob', async () => {
    const fn = mockFetch({});
    // jsdom has no Audio; stub it so play() fires onended → playTts resolves.
    global.Audio = class {
      onended: any = null; onerror: any = null;
      play() { setTimeout(() => this.onended && this.onended(), 0); return Promise.resolve(); }
    } as any;
    global.URL.createObjectURL = vi.fn(() => 'blob:x');
    global.URL.revokeObjectURL = vi.fn();
    await playTts('hello world', 'en');
    const [path, init] = lastCall(fn);
    expect(path).toBe('/tts');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ text: 'hello world', lang: 'en' });
  });
});
