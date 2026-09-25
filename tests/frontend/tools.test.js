// tools.js — the ▦ Console overlay, its 30-panel tool registry, and a few of the
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
    if (url === '/api/local-docs') return json({ available: ['notes'] });
    if (url === '/api/eval/datasets') return json({ datasets: [{ name: 'smoke', latest_version: 2, cases: 12, last_score: 0.92 }] });
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
  it('registers 30 tools with unique ids and render functions', () => {
    const tools = env.window.JARVIS_TOOLS;
    expect(Array.isArray(tools)).toBe(true);
    expect(tools).toHaveLength(30);
    const ids = tools.map((t) => t.id);
    expect(new Set(ids).size).toBe(30);
    for (const t of tools) {
      expect(typeof t.render).toBe('function');
      expect(typeof t.label).toBe('string');
      expect(typeof t.group).toBe('string');
    }
    // Governance tools the product story leans on now have a home.
    expect(ids).toEqual(expect.arrayContaining(['arena', 'eval', 'secrets', 'webhooks', 'killswitch', 'trust', 'capabilities', 'audit', 'cost', 'localdocs', 'models', 'reflection']));
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

  it('Local Docs — Index posts the configured folder key', async () => {
    const { container } = overlay();
    await env.flush();
    openTool(container, 'Local Docs');
    await env.flush();
    const btn = [...container.querySelectorAll('.console-content .tool-btn')].find((b) => b.textContent === 'Index');
    expect(btn, 'Index button rendered').toBeTruthy();
    env.click(btn);
    const post = env.window.fetch.mock.calls.find((c) => c[0] === '/api/local-docs/index' && c[1] && c[1].method === 'POST');
    expect(post, 'POST /api/local-docs/index issued').toBeTruthy();
    expect(JSON.parse(post[1].body).key).toBe('notes');
  });

  it('Eval Datasets — renders the dataset and Run posts its name', async () => {
    const { container } = overlay();
    await env.flush();
    openTool(container, 'Eval Datasets');
    await env.flush();
    const txt = container.querySelector('.console-content').textContent;
    expect(txt).toContain('smoke');
    expect(txt).toContain('92%');
    const btn = [...container.querySelectorAll('.console-content .tool-btn')].find((b) => b.textContent === 'Run');
    env.click(btn);
    const post = env.window.fetch.mock.calls.find((c) => c[0] === '/api/eval/datasets/run' && c[1] && c[1].method === 'POST');
    expect(post, 'POST /api/eval/datasets/run issued').toBeTruthy();
    expect(JSON.parse(post[1].body).name).toBe('smoke');
  });
});

// H153 / H200 review — the legacy Webhooks panel: admin-only routes, a delete that
// asks first, a refused list that says why, and one credential shown until dismissed.
describe('Webhooks panel', () => {
  function hooksBackend(listReply) {
    const calls = [];
    const fetch = vi.fn((url, init = {}) => {
      calls.push({ url, method: init.method || 'GET', admin: (init.headers || {})['X-Admin-Token'] });
      if (url === '/api/webhooks' && !init.method) return listReply();
      if (url === '/api/webhooks' && init.method === 'POST') {
        const signed = JSON.parse(init.body).signed;
        return json({ id: 'hk2', token: 'tok-1', signing_secret: signed ? 'sec-1' : null, signed });
      }
      if (init.method === 'DELETE') return json({ ok: true });
      return json({});
    });
    return { fetch, calls };
  }
  async function openWebhooks(listReply) {
    env.cleanup();
    const backendCalls = hooksBackend(listReply);
    env = loadHud({ files: ['i18n', 'data', 'components', 'console', 'tools'], fetch: backendCalls.fetch, lang: 'ro' });
    env.window.localStorage.setItem('hud.admin_token', 'adm');
    const { container } = overlay();
    await env.flush();
    openTool(container, 'Webhooks');
    await env.flush(6);
    return { container, calls: backendCalls.calls, text: () => container.querySelector('.console-content').textContent };
  }
  const listed = () => json({ webhooks: [{ id: 'hk1', name: 'ci', target: 'jarvis', signed: false, enabled: false }] });

  it('lists with the admin token, and a delete asks first and carries it too', async () => {
    const { container, calls, text } = await openWebhooks(listed);
    expect(calls.find((c) => c.url === '/api/webhooks').admin).toBe('adm');
    expect(text()).toContain('ci → POST /api/webhooks/hk1 (off)');
    env.window.confirm = vi.fn(() => false);
    env.click(toolBtn(container, 'Delete'));
    expect(env.window.confirm).toHaveBeenCalledTimes(1);
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false);
    env.window.confirm = vi.fn(() => true);
    env.click(toolBtn(container, 'Delete'));
    const del = calls.find((c) => c.method === 'DELETE');
    expect(del.url).toBe('/api/webhooks/hk1');
    expect(del.admin).toBe('adm');
  });

  it('says why a refused list failed instead of "No webhooks."', async () => {
    const { text } = await openWebhooks(() => json({ detail: 'admin token required' }, { ok: false, status: 401 }));
    expect(text()).toContain('admin token required (set it in ⚙ Settings)');
    expect(text()).not.toContain('No webhooks.');
  });

  it('shows a signed hook only its signing secret, until it is dismissed', async () => {
    const { container, calls, text } = await openWebhooks(listed);
    env.toggle(container.querySelector('.console-content input[type="checkbox"]'));
    env.click(toolBtn(container, 'Create'));
    await env.flush(6);
    expect(calls.find((c) => c.method === 'POST').admin).toBe('adm');
    expect(text()).toContain('signing secret: sec-1');
    expect(text()).not.toContain('tok-1');
    env.click(toolBtn(container, 'I have saved it'));
    expect(text()).not.toContain('sec-1');
  });

  it('reads the receiver with the admin token, and shows every hook refused while it is off', async () => {
    env.cleanup();
    const calls = [];
    const fetch = vi.fn((url, init = {}) => {
      calls.push({ url, admin: (init.headers || {})['X-Admin-Token'] });
      if (url === '/api/webhooks') return json({ webhooks: [{ id: 'hk1', name: 'ci', target: 'jarvis', enabled: true, deliver: 'telegram' }] });
      if (url === '/api/admin/settings/webhooks') return json({ webhooks: [{ key: 'receiver_enabled', value: false }] });
      return json({});
    });
    env = loadHud({ files: ['i18n', 'data', 'components', 'console', 'tools'], fetch, lang: 'ro' });
    env.window.localStorage.setItem('hud.admin_token', 'adm');
    const { container } = overlay();
    await env.flush();
    openTool(container, 'Webhooks');
    await env.flush(6);
    const text = container.querySelector('.console-content').textContent;
    expect(calls.find((c) => c.url === '/api/admin/settings/webhooks').admin).toBe('adm');
    expect(text).toContain('Receiver off: every delivery is refused');
    expect(text).toContain('ci → POST /api/webhooks/hk1 (receiver off) · deliver to telegram');
  });

  // H153 third round — only a literal true is on, and a read that failed is "not read",
  // never a guessed "on".
  async function openWithReceiver(settings) {
    env.cleanup();
    const fetch = vi.fn((url) => {
      if (url === '/api/webhooks') return json({ webhooks: [{ id: 'hk1', name: 'ci', target: 'jarvis', enabled: true }] });
      if (url === '/api/admin/settings/webhooks') return settings();
      return json({});
    });
    env = loadHud({ files: ['i18n', 'data', 'components', 'console', 'tools'], fetch, lang: 'ro' });
    env.window.localStorage.setItem('hud.admin_token', 'adm');
    const { container } = overlay();
    await env.flush();
    openTool(container, 'Webhooks');
    await env.flush(6);
    return container.querySelector('.console-content').textContent;
  }

  it('reads a stored receiver value that is not literally true as off', async () => {
    const text = await openWithReceiver(() => json({ webhooks: [{ key: 'receiver_enabled', value: 'yes' }] }));
    expect(text).toContain('Receiver off: every delivery is refused');
    expect(text).toContain('ci → POST /api/webhooks/hk1 (receiver off)');
  });

  it('says the receiver was not read when its read fails, never "on"', async () => {
    const text = await openWithReceiver(() => json({ error: 'boom' }, { ok: false, status: 500 }));
    expect(text).toContain('Receiver: not read');
    expect(text).not.toContain('Receiver: on');
  });

  it('shows a token hook its token', async () => {
    const { container, text } = await openWebhooks(listed);
    env.click(toolBtn(container, 'Create'));
    await env.flush(6);
    expect(text()).toContain('token: tok-1');
    expect(text()).not.toContain('secret');
  });
});

// H318 (review-H318e n-4): a skill-change card is approved only beside the diff it shows.
// A card beyond the loaded page, or one no proposal names, offers Reject only.
describe('Action Approvals — skill changes', () => {
  it('enables Approve only for a card whose diff is shown', async () => {
    env.cleanup();
    const fetch = vi.fn((url) => {
      if (url === '/api/actions/pending') {
        return json({ actions: [
          { id: 'c1', tool: 'skill.patch_proposal', summary: 'shown change' },
          { id: 'c2', tool: 'skill.patch_proposal', summary: 'beyond the page' },
          { id: 'c3', tool: 'skill.patch_proposal', summary: 'unknown card' },
          { id: 'c4', tool: 'send_email', summary: 'plain action' },
        ] });
      }
      if (url.startsWith('/api/skills/proposals')) {
        return json({ proposals: [{ id: 'p1', card: 'c1', skill: 'brief', diff: '-old\n+new', flags: [] }],
                      cards: ['c1', 'c2'], more: 1 });
      }
      return json({});
    });
    env = loadHud({ files: ['i18n', 'data', 'components', 'console', 'tools'], fetch, lang: 'ro' });
    const { container } = overlay();
    await env.flush();
    openTool(container, 'Action Approvals');
    await env.flush();
    await env.flush();
    const cards = [...container.querySelectorAll('.console-content .tool-card')];
    const approve = (text) => [...cards.find((c) => c.textContent.includes(text)).querySelectorAll('.tool-btn')]
      .find((b) => b.textContent === 'Approve');
    expect(approve('shown change').disabled).toBe(false);
    expect(approve('beyond the page').disabled).toBe(true);
    expect(approve('unknown card').disabled).toBe(true);
    expect(approve('plain action').disabled).toBe(false);
    const text = container.textContent;
    expect(text).toContain('+new');
    expect(text).not.toContain('Decision Inbox');
    expect(text).toContain('cannot be approved from this panel');
  });
});

// H318 (review-H318f V4): a change the hub will refuse (a bundled skill, a rename) offers
// Reject only, even beside its diff.
describe('Action Approvals — a refused change', () => {
  it.each([['a bundled skill: it cannot be changed here'], ['renames the skill']])('disables Approve for a change the hub will refuse (%s)', async (flag) => {
    env.cleanup();
    const fetch = vi.fn((url) => {
      if (url === '/api/actions/pending') {
        return json({ actions: [{ id: 'c9', tool: 'skill.patch_proposal', summary: 'bundled change' }] });
      }
      if (url.startsWith('/api/skills/proposals')) {
        return json({ proposals: [{ id: 'p9', card: 'c9', skill: 'core', diff: '-a\n+b', flags: [flag] }],
                      cards: ['c9'] });
      }
      return json({});
    });
    env = loadHud({ files: ['i18n', 'data', 'components', 'console', 'tools'], fetch, lang: 'ro' });
    const { container } = overlay();
    await env.flush();
    openTool(container, 'Action Approvals');
    await env.flush();
    await env.flush();
    const card = [...container.querySelectorAll('.console-content .tool-card')].find((c) => c.textContent.includes('bundled change'));
    const buttons = [...card.querySelectorAll('.tool-btn')];
    expect(buttons.find((b) => b.textContent === 'Approve').disabled).toBe(true);
    expect(buttons.find((b) => b.textContent === 'Reject').disabled).toBeFalsy();
  });
});
