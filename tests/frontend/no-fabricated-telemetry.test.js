// The legacy HUD presented three things it had never measured as if it had.
//
// 1. `useLiveSys` SYNTHESIZED host telemetry. Every 1400ms it layered sine waves
//    and `Math.random()` jitter onto ram_used / vram_used / gpu_load / latency
//    and rendered the result as the machine's live state. Because the numbers
//    moved, they were more convincing than a static readout.
// 2. `JARVIS_FALLBACK_SYS` seeded that with a complete, credible picture of a
//    machine nobody had looked at — 42/192 GB RAM, 30% GPU, 2.1s latency — so a
//    box whose /status poll never succeeded showed plausible drifting telemetry
//    forever, and the SYSTEM bracket certified it "NOMINAL".
// 3. `TrustIndicator` computed strict-local as `!trust || trust.strict_local`,
//    so a HUD that had not reached (or could not reach) /api/trust/status showed
//    a padlock reading "nothing leaves this machine" — a privacy assurance
//    asserted from the absence of information.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

let env, h;
beforeEach(() => {
  env = loadHud({
    files: ['i18n', 'data', 'components', 'enhancements'],
    expose: ['SysMeter', 'AgentList', 'TrustIndicator', 'useLiveSys', 'JARVIS_FALLBACK_SYS'],
    lang: 'en',
  });
  h = env.React.createElement;
});
afterEach(() => env.cleanup());

describe('useLiveSys no longer invents telemetry', () => {
  it('returns the measured sample unchanged instead of animating it', () => {
    const base = { ram_used: 48, ram_total: 192, vram_used: 10, vram_total: 24, gpu_load: 30, latency: 2.1 };
    let seen;
    function Probe() {
      seen = env.hud.useLiveSys(base);
      return null;
    }
    env.render(h(Probe));
    expect(seen).toEqual(base);
  });

  it('does not drift over time — no timer rewrites the values', () => {
    vi.useFakeTimers();
    try {
      const base = { ram_used: 48, ram_total: 192, vram_used: 10, vram_total: 24, gpu_load: 30, latency: 2.1 };
      const samples = [];
      function Probe() {
        samples.push(env.hud.useLiveSys(base));
        return null;
      }
      env.render(h(Probe));
      vi.advanceTimersByTime(10_000); // ~7 ticks of the old 1400ms interval
      // Every sample is the same object we passed in; nothing synthesized one.
      expect(samples.every((s) => s.gpu_load === 30 && s.ram_used === 48)).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('JARVIS_FALLBACK_SYS carries no fabricated readings', () => {
  it('has null for every telemetry number, and says it is unmeasured', () => {
    const fb = env.hud.JARVIS_FALLBACK_SYS;
    expect(fb.measured).toBe(false);
    for (const key of ['ram_used', 'ram_total', 'vram_used', 'vram_total', 'gpu_load', 'latency']) {
      expect(fb[key], `${key} must be null before anything is measured`).toBeNull();
    }
  });
});

describe('SysMeter renders unknown as unknown', () => {
  it('shows an em dash rather than "null/null GB" when nothing was measured', () => {
    const { container } = env.render(
      h(env.hud.SysMeter, { label: 'RAM', used: null, total: null, unit: 'GB' }),
    );
    expect(container.querySelector('.sys-val').textContent).toBe('—');
    expect(container.querySelector('.sys-meter').className).toContain('is-unknown');
  });

  it('draws no bar fill at all — a 0% bar reads as a measurement of zero', () => {
    const { container } = env.render(
      h(env.hud.SysMeter, { label: 'GPU', used: null, total: 100, unit: '%', raw: true }),
    );
    expect(container.querySelector('.sys-bar-fill')).toBeNull();
  });

  it('still renders a real reading normally', () => {
    const { container } = env.render(
      h(env.hud.SysMeter, { label: 'RAM', used: 48, total: 192, unit: 'GB' }),
    );
    expect(container.querySelector('.sys-val').textContent).toBe('48/192 GB');
    expect(container.querySelector('.sys-bar-fill').style.width).toBe('25%');
  });
});

describe('the SYSTEM panel does not certify a host it never read', () => {
  const tiers = [{ id: 'CNS', label: 'Command' }];
  const agents = [{ id: 'jarvis', name: 'Jarvis', role: 'O', tier: 'CNS', status: 'active', model: 'm', glyph: 'M0,0' }];

  it('reads UNMEASURED, not NOMINAL, before any sample lands', () => {
    const { container } = env.render(h(env.hud.AgentList, {
      agents, tiers, activeAgent: 'jarvis', onSelect: vi.fn(),
      sys: { ...env.hud.JARVIS_FALLBACK_SYS },
    }));
    expect(container.querySelector('.sys-bracket').textContent).toContain('UNMEASURED');
  });

  it('shows an em dash for latency instead of a confident 0.0s avg', () => {
    const { container } = env.render(h(env.hud.AgentList, {
      agents, tiers, activeAgent: 'jarvis', onSelect: vi.fn(),
      sys: { ...env.hud.JARVIS_FALLBACK_SYS },
    }));
    const rows = [...container.querySelectorAll('.sys-row')].map((r) => r.textContent);
    expect(rows.some((t) => t.includes('0.0s avg'))).toBe(false);
  });

  it('says NOMINAL once a real sample has been measured', () => {
    const { container } = env.render(h(env.hud.AgentList, {
      agents, tiers, activeAgent: 'jarvis', onSelect: vi.fn(),
      sys: { host: 'h', cpu: 'c', ram_used: 48, ram_total: 192, vram_used: 10,
             vram_total: 24, gpu_load: 30, latency: 2.1, uptime: '1d',
             backend: 'lmstudio', model: 'm', measured: true },
    }));
    expect(container.querySelector('.sys-bracket').textContent).toContain('NOMINAL');
  });
});

describe('TrustIndicator never claims strict-local from missing data', () => {
  it('shows unknown when the trust status has not arrived', () => {
    const { container } = env.render(h(env.hud.TrustIndicator, { trust: null }));
    const chip = container.querySelector('.trust-chip.trust-local');
    expect(chip.className).toContain('is-unknown');
    expect(chip.querySelector('.trust-chip-val').textContent).toBe('—');
    // The reassuring padlock must not appear for an unknown state.
    expect(chip.textContent).not.toContain('🔒');
    expect(chip.getAttribute('title')).toContain('unknown');
  });

  it('shows unknown when the field is present but null', () => {
    const { container } = env.render(h(env.hud.TrustIndicator, { trust: { strict_local: null } }));
    expect(container.querySelector('.trust-chip.trust-local').className).toContain('is-unknown');
  });

  it('claims STRICT only when the hub actually reported strict-local', () => {
    const { container } = env.render(h(env.hud.TrustIndicator, { trust: { strict_local: true } }));
    const chip = container.querySelector('.trust-chip.trust-local');
    expect(chip.className).toContain('is-on');
    expect(chip.querySelector('.trust-chip-val').textContent).toBe('STRICT');
    expect(chip.getAttribute('title')).toContain('nothing leaves this machine');
  });

  it('reports CLOUD when the hub says cloud routing is available', () => {
    const { container } = env.render(h(env.hud.TrustIndicator, { trust: { strict_local: false } }));
    const chip = container.querySelector('.trust-chip.trust-local');
    expect(chip.className).toContain('is-off');
    expect(chip.querySelector('.trust-chip-val').textContent).toBe('CLOUD');
  });
});
