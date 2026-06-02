// Agent Dossier modal (dossier-modal.js): badges, identity/memory columns and
// the full modal (close paths + lazy SOUL.md fetch).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

let env, h;
beforeEach(() => {
  env = loadHud({
    files: ['i18n', 'data', 'components', 'dossier-modal'],
    expose: ['DossierModal', 'TierBadge', 'StatusIndicator', 'DossierIdentity', 'DossierMemory'],
    lang: 'ro',
  });
  h = env.React.createElement;
});
afterEach(() => env.cleanup());

const agent = { id: 'gecko', name: 'Gecko', role: 'Markets', tier: 'FND', status: 'active', glyph: 'M0,0' };
const dossier = {
  archetype: 'Markets & Capital', personality: 'Analytical', model: 'gemma',
  channel: 'telegram', heartbeat: '2h', policy: 'auto', plugins: ['gmail'],
  skills: 2, memory_facts: 5, soul_excerpt: 'You are Gecko.',
};

describe('TierBadge', () => {
  it('maps the tier code to a human label', () => {
    const { container } = env.render(h(env.hud.TierBadge, { tier: 'CNS' }));
    expect(container.querySelector('.dossier-tier-badge').textContent).toBe('CNS · Command');
    expect(container.querySelector('.dossier-tier-badge').className).toContain('tier-cns');
  });
});

describe('StatusIndicator', () => {
  it('uppercases the status and tags the class', () => {
    const { container } = env.render(h(env.hud.StatusIndicator, { status: 'active' }));
    const el = container.querySelector('.dossier-status');
    expect(el.className).toContain('status-active');
    expect(el.textContent).toContain('ACTIVE');
  });
});

describe('DossierIdentity', () => {
  it('renders config rows and plugin pills', () => {
    const { container } = env.render(h(env.hud.DossierIdentity, { agent, dossier }));
    expect(container.textContent).toContain('gemma');
    expect(container.textContent).toContain('telegram');
    expect([...container.querySelectorAll('.dossier-plugin-pill')].map((p) => p.textContent)).toEqual(['gmail']);
  });

  it('shows "None assigned" when there are no plugins', () => {
    const { container } = env.render(h(env.hud.DossierIdentity, { agent, dossier: { ...dossier, plugins: [] } }));
    expect(container.querySelector('.dossier-empty').textContent).toBe('None assigned');
  });
});

describe('DossierMemory', () => {
  it('renders fact count and recent memory keys', () => {
    const { container } = env.render(
      h(env.hud.DossierMemory, { agent, dossier, memoryContext: { last_trade: 1, budget: 2 } }),
    );
    expect(container.querySelector('.dossier-mem-val').textContent).toBe('5');
    expect([...container.querySelectorAll('.dossier-memkey')].map((k) => k.textContent)).toEqual([
      'last_trade', 'budget',
    ]);
  });

  it('shows an empty state with no facts', () => {
    const { container } = env.render(
      h(env.hud.DossierMemory, { agent, dossier: { ...dossier, memory_facts: 0 }, memoryContext: {} }),
    );
    expect(container.querySelector('.dossier-empty').textContent).toBe('No memory context yet');
  });
});

describe('DossierModal', () => {
  it('returns nothing without an agent or dossier', () => {
    const { container } = env.render(h(env.hud.DossierModal, { agent: null, dossier, onClose: vi.fn() }));
    expect(container.innerHTML).toBe('');
  });

  it('renders the header and closes via the close button', () => {
    const onClose = vi.fn();
    const { container } = env.render(h(env.hud.DossierModal, { agent, dossier, onClose }));
    expect(container.querySelector('.dossier-head-name').textContent).toBe('Gecko');
    env.click(container.querySelector('.dossier-close'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('closes when the backdrop itself is clicked', () => {
    const onClose = vi.fn();
    const { container } = env.render(h(env.hud.DossierModal, { agent, dossier, onClose }));
    env.click(container.querySelector('.dossier-backdrop'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('fires onChat with the agent id', () => {
    const onChat = vi.fn();
    const { container } = env.render(h(env.hud.DossierModal, { agent, dossier, onClose: vi.fn(), onChat }));
    const chatBtn = [...container.querySelectorAll('button')].find((b) => /Chat with/.test(b.textContent));
    env.click(chatBtn);
    expect(onChat).toHaveBeenCalledWith('gecko');
  });

  it('lazy-loads SOUL.md on demand and toggles the full view', async () => {
    const onViewSoul = vi.fn();
    env.window.fetch = vi.fn().mockResolvedValue({ json: async () => ({ soul: '# Gecko soul' }) });
    const { container } = env.render(
      h(env.hud.DossierModal, { agent, dossier, onClose: vi.fn(), onViewSoul }),
    );
    const soulBtn = [...container.querySelectorAll('button')].find((b) => /SOUL\.md/.test(b.textContent));
    env.click(soulBtn);
    await env.flush();
    expect(env.window.fetch).toHaveBeenCalledWith('/api/agents/gecko/soul');
    expect(container.querySelector('.dossier-soul-full-view')).not.toBeNull();
    expect(container.textContent).toContain('# Gecko soul');
    expect(onViewSoul).toHaveBeenCalledWith('gecko');
  });
});
