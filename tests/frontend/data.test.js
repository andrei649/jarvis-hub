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
    expect(env.window.JARVIS_FALLBACK_SYS.ram_total).toBe(192);
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

    // Other sections fall back to their static defaults.
    expect(data.sys).toMatchObject({ ram_total: 192 });
    expect(data.weather).toEqual(env.window.JARVIS_FALLBACK_WEATHER);
    expect(data.tasks).toEqual([]);
    expect(data.lmOnline).toBe(true);
  });

  it('maps live /api/agents results with tier/role/glyph metadata', async () => {
    env.window.fetch = vi.fn((url) => {
      if (url === '/api/agents') {
        return Promise.resolve({
          json: async () => ({ agents: [{ id: 'gecko', name: 'Gecko', status: 'active', enabled: true }] }),
        });
      }
      if (url === '/status') {
        return Promise.resolve({ json: async () => ({ lm_online: false, sys: { latency: 9.9 } }) });
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
