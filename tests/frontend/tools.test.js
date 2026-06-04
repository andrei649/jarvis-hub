// tools.js — the ▦ Console overlay, its 25-panel tool registry, and a few of the
// per-panel flows (Notes save, admin-token'd Secret Broker write). Shipped globally
// (window.JARVIS_TOOLS / window.ConsoleOverlay) with zero coverage until now.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadHud } from './harness.js';

function json(body, { ok = true, status = 200 } = {}) {
  return Promise.resolve({ ok, status, json: async () => body });
}

// Permissive backend: concrete shapes where a test asserts on content, an empty
// object otherwise so every panel renders (and never throws) when swept.
function backend() {
  return vi.fn((url) => {
    if (url === '/api/health/components') return json({ summary: 'all ok', components: { qdrant: 'ok', neo4j: 'bad' } });
    if (url === '/api/arena/leaderboard') return json({ leaderboard: [{ model: 'gemma', elo: 1500, win_rate: 0.5 }] });
    if (url === '/api/notes') return json({ content: 'hi' });
    if (url === '/api/security/kill-switch') return json({ halted: {}, global: false });
    if (url === '/api/security/governance') return json({ pass: true, overall_score: 1, threshold: 0.9, injection: { score: 1 }, harm: { score: 1 }, owasp: { covered: 10, total: 10, score: 1 } });
    return json({});
  });
}

let env;
beforeEach(() => {
  env = loadHud({ files: ['i18n', 'data', 'components', 'console', 'tools'], fetch: backend(), lang: 'ro' });
});
afterEach(() => env.cleanup());

const h = (...a) => env.React.createElement(...a);
function overlay(props) {
  return env.render(h(env.window.ConsoleOverlay, Object.assign({ open: true, onClose: vi.fn(), agents: [] }, props)));
}
const navLinks = (c) => [...c.querySelectorAll('.console-nav .console-link')];
const toolBtn = (c, label) => [...c.querySelectorAll('.console-content .tool-btn')].find((b) => b.textContent === label);
function openTool(c, label) { env.click(navLinks(c).find((l) => l.textContent === label)); }
// The harness `type` helper targets HTMLInputElement; textareas need their own setter.
function typeArea(el, value) {
  Object.getOwnPropertyDescriptor(env.window.HTMLTextAreaElement.prototype, 'value').set.call(el, value);
  env.fire(el, 'input');
}

describe('tool registry', () => {
  it('registers 25 tools with unique ids and render functions', () => {
    const tools = env.window.JARVIS_TOOLS;
    expect(Array.isArray(tools)).toBe(true);
    expect(tools).toHaveLength(25);
    const ids = tools.map((t) => t.id);
    expect(new Set(ids).size).toBe(25);
    for (const t of tools) {
      expect(typeof t.render).toBe('function');
      expect(typeof t.label).toBe('string');
      expect(typeof t.group).toBe('string');
    }
    // Governance tools the product story leans on now have a home.
    expect(ids).toEqual(expect.arrayContaining(['arena', 'secrets', 'webhooks', 'killswitch', 'trust', 'capabilities', 'audit', 'cost']));
    expect(tools.some((t) => t.group === 'Security')).toBe(true);
  });
});

describe('ConsoleOverlay', () => {
  it('renders nothing when closed', () => {
    const { container } = env.render(h(env.window.ConsoleOverlay, { open: false, onClose: vi.fn() }));
    expect(container.querySelector('.console')).toBeNull();
  });

  it('opens with one nav link per tool and the default panel fetched', async () => {
    const { container } = overlay();
    await env.flush();
    expect(container.querySelector('.console')).not.toBeNull();
    expect(navLinks(container).length).toBe(env.window.JARVIS_TOOLS.length);
    // Default tool (Component Health) auto-fetched and rendered its data.
    expect(container.textContent).toContain('all ok');
    expect(container.textContent).toContain('qdrant');
  });

  it('sweeps every panel without crashing (each renders content)', async () => {
    const { container } = overlay();
    await env.flush();
    for (const label of env.window.JARVIS_TOOLS.map((t) => t.label)) {
      const link = navLinks(container).find((l) => l.textContent === label);
      expect(link, `nav link for ${label}`).toBeTruthy();
      env.click(link);
      await env.flush();
      expect(container.querySelector('.console'), `${label} kept overlay mounted`).not.toBeNull();
      expect(
        container.querySelector('.console-content').textContent.length,
        `${label} rendered content`,
      ).toBeGreaterThan(0);
    }
  });

  it('calls onClose from the × button and the backdrop', () => {
    const onClose = vi.fn();
    const { container } = overlay({ onClose });
    env.click(container.querySelector('.console-x'));
    expect(onClose).toHaveBeenCalledTimes(1);
    env.click(container.querySelector('.console-backdrop'));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});

describe('panel flows', () => {
  it('Conversation Notes — Save PUTs the edited content', async () => {
    const { container } = overlay();
    await env.flush();
    openTool(container, 'Conversation Notes');
    await env.flush();
    const ta = container.querySelector('.console-content textarea');
    expect(ta).not.toBeNull();
    typeArea(ta, 'remember the milk');
    env.click(toolBtn(container, 'Save'));
    const put = env.window.fetch.mock.calls.find((c) => c[0] === '/api/notes' && c[1] && c[1].method === 'PUT');
    expect(put, 'PUT /api/notes issued').toBeTruthy();
    expect(JSON.parse(put[1].body).content).toBe('remember the milk');
  });

  it('Secret Broker — Store sends the admin token header and the secret', async () => {
    env.window.localStorage.setItem('hud.admin_token', 'adm');
    const { container } = overlay();
    await env.flush();
    openTool(container, 'Secret Broker');
    await env.flush();
    const inputs = container.querySelectorAll('.console-content .tool-input');
    env.type(inputs[0], 'OPENAI_KEY');
    env.type(inputs[1], 'sk-xxx');
    env.click(toolBtn(container, 'Store'));
    const post = env.window.fetch.mock.calls.find((c) => c[0] === '/api/secrets/broker' && c[1] && c[1].method === 'POST');
    expect(post, 'POST /api/secrets/broker issued').toBeTruthy();
    expect(post[1].headers['X-Admin-Token']).toBe('adm');
    expect(JSON.parse(post[1].body)).toMatchObject({ name: 'OPENAI_KEY', value: 'sk-xxx' });
  });

  it('Kill-Switch — Engage halt POSTs (admin) with engage:true', async () => {
    env.window.localStorage.setItem('hud.admin_token', 'adm');
    const { container } = overlay();
    await env.flush();
    openTool(container, 'Kill-Switch');
    await env.flush();
    expect(container.querySelector('.console-content').textContent).toContain('Operational');
    env.click(toolBtn(container, 'Engage halt'));
    const post = env.window.fetch.mock.calls.find((c) => c[0] === '/api/security/kill-switch' && c[1] && c[1].method === 'POST');
    expect(post, 'POST /api/security/kill-switch issued').toBeTruthy();
    expect(post[1].headers['X-Admin-Token']).toBe('adm');
    expect(JSON.parse(post[1].body).engage).toBe(true);
  });

  it('Trust Scorecard — renders the governance gate result', async () => {
    const { container } = overlay();
    await env.flush();
    openTool(container, 'Trust Scorecard');
    await env.flush();
    const txt = container.querySelector('.console-content').textContent;
    expect(txt).toContain('PASS');
    expect(txt).toContain('100%');
  });
});
