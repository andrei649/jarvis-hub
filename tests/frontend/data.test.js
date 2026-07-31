// data.js: static fallbacks + loadJarvisData(), the resilient loader that
// hydrates the HUD from several endpoints with graceful fallback.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

let env;
beforeEach(() => {
  env = loadHud({ files: ['i18n', 'data'], lang: 'ro' });
});
afterEach(() => env.cleanup());

describe('exposed constants', () => {
  it('publishes fallback datasets and agent metadata on window', () => {
    expect(env.window.JARVIS_AGENT_META.jarvis).toMatchObject({ tier: 'CNS' });
    expect(Array.isArray(env.window.JARVIS_FALLBACK_CALENDAR)).toBe(true);
    // Every telemetry field is null before anything is measured. It used to be a
    // complete plausible machine (ram_total 192, ram_used 42, gpu_load 30), which
    // the HUD rendered as live state on a box that had never been read.
    expect(env.window.JARVIS_FALLBACK_SYS.ram_total).toBeNull();
    expect(env.window.JARVIS_FALLBACK_SYS.measured).toBe(false);
    expect(typeof env.window.loadJarvisData).toBe('function');
  });
});

describe('loadJarvisData', () => {
  it('falls back to agent metadata when every endpoint fails', async () => {
    env.window.fetch = vi.fn().mockRejectedValue(new Error('offline'));
    const data = await env.window.loadJarvisData();

    // Agents are reconstructed from JARVIS_AGENT_META.
    expect(data.agents.length).toBe(Object.keys(env.window.JARVIS_AGENT_META).length);
    const jarvis = data.agents.find((a) => a.id === 'jarvis');
    expect(jarvis).toMatchObject({ tier: 'CNS', role: 'Prime Orchestrator', status: 'idle' });

    // Other sections fall back to their static defaults — and those defaults now
    // assert nothing. This test used to require the opposite: with every endpoint
    // down it asserted ram_total 192 and lmOnline true, so the HUD claimed to
    // know the host's memory and that the LM backend was up. Both were guesses.
    expect(data.sys).toMatchObject({ ram_total: null, measured: false });
    expect(data.weather).toEqual(env.window.JARVIS_FALLBACK_WEATHER);
    expect(data.tasks).toEqual([]);
    expect(data.lmOnline).toBeNull();
  });

  it('maps live /api/agents results with tier/role/glyph metadata', async () => {
    env.window.fetch = vi.fn((url) => {
      if (url === '/api/agents') {
        return Promise.resolve({
          json: async () => ({ agents: [{ id: 'gecko', name: 'Gecko', status: 'active', enabled: true }] }),
        });
      }
      if (url === '/status') {
        return Promise.resolve({ ok: true, json: async () => ({ lm_online: false, sys: { latency: 9.9 } }) });
      }
      return Promise.reject(new Error('no stub'));
    });

    const data = await env.window.loadJarvisData();
    expect(data.agents).toHaveLength(1);
    expect(data.agents[0]).toMatchObject({ id: 'gecko', tier: 'FND' });
    expect(data.agents[0].role).toBeTruthy();
    expect(data.lmOnline).toBe(false);
    expect(data.sys.latency).toBe(9.9);
  });
});
