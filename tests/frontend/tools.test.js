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
afterEach(() => { env.cleanup(); vi.useRealTimers(); });

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

it('sends the optional human reason with its action decision', async () => {
  env.cleanup();
  const fetcher = vi.fn(url => url === '/api/actions/pending'
    ? json({ actions: [{ id: 'reason-card', tool: 'write_file', summary: 'Write a file' }] })
    : json({ proposals: [], cards: [] }));
  env = loadHud({ files: ['i18n', 'data', 'components', 'console', 'tools'], fetch: fetcher, lang: 'ro' });
  const { container } = overlay();
  await env.flush(); openTool(container, 'Action Approvals'); await env.flush(); await env.flush();
  const reason = container.querySelector('[aria-label="Your decision reason for Write a file"]');
  expect(reason).not.toBeNull();
  expect(reason.maxLength).toBe(280);
  typeArea(reason, 'Use the staging address');
  env.click(toolBtn(container, 'Reject')); await env.flush();
  const call = fetcher.mock.calls.find(([url]) => url === '/api/actions/reason-card/decide');
  expect(JSON.parse(call[1].body)).toEqual({ approved: false, reason: 'Use the staging address' });
});

it('groups owner requests while approving only the leader and promotes the follower', async () => {
  env.cleanup();
  let approved = false;
  const actions = [{ id: 'g1', tool: 'write_file', summary: 'Same write' },
    { id: 'g2', tool: 'write_file', summary: 'Same write' }];
  const fetcher = vi.fn(url => {
    if (url === '/api/actions/g1/decide') { approved = true; return json({ ok: true }); }
    if (url === '/api/actions/pending') return json({ actions: approved ? actions.slice(1) : actions,
      groups: approved ? [] : [{ id: 'group1', leader_id: 'g1', count: 2, member_ids: ['g1', 'g2'], snapshot: 'snapshot1' }] });
    return json({ proposals: [], cards: [] });
  });
  env = loadHud({ files: ['i18n', 'data', 'components', 'console', 'tools'], fetch: fetcher, lang: 'ro' });
  const { container } = overlay();
  await env.flush(); openTool(container, 'Action Approvals'); await env.flush(); await env.flush();
  expect(container.querySelectorAll('[aria-label="Your decision reason for Same write"]').length).toBe(1);
  expect(container.textContent).toContain('2 matching requests');
  env.click(toolBtn(container, 'Approve once')); await env.flush(); await env.flush();
  const decisions = fetcher.mock.calls.filter(([url]) => url.endsWith('/decide'));
  expect(decisions.map(([url]) => url)).toEqual(['/api/actions/g1/decide']);
  expect(JSON.parse(decisions[0][1].body)).toEqual({ approved: true });
  expect(container.querySelectorAll('[aria-label="Your decision reason for Same write"]').length).toBe(1);
  expect(container.textContent).not.toContain('2 matching requests');
  expect(toolBtn(container, 'Approve')).toBeTruthy();
});

it('rejects the exact displayed group with its human reason', async () => {
  env.cleanup();
  const fetcher = vi.fn(url => url === '/api/actions/pending'
    ? json({ actions: [{ id: 'r1', tool: 'write_file', summary: 'Grouped write' },
      { id: 'r2', tool: 'write_file', summary: 'Grouped write' }],
      groups: [{ id: 'reject-group', leader_id: 'r1', count: 2, member_ids: ['r1', 'r2'], snapshot: 'exact-state' }] })
    : json({ ok: true, proposals: [], cards: [] }));
  env = loadHud({ files: ['i18n', 'data', 'components', 'console', 'tools'], fetch: fetcher, lang: 'ro' });
  const { container } = overlay();
  await env.flush(); openTool(container, 'Action Approvals'); await env.flush(); await env.flush();
  typeArea(container.querySelector('[aria-label="Your decision reason for Grouped write"]'), 'Use staging');
  env.click(toolBtn(container, 'Reject group')); await env.flush();
  const request = fetcher.mock.calls.find(([url]) => url === '/api/actions/groups/reject-group/reject');
  expect(JSON.parse(request[1].body)).toEqual({ snapshot: 'exact-state', member_ids: ['r1', 'r2'], reason: 'Use staging' });
});

it('keeps group decisions and the draft reason visible after a stale-membership refusal', async () => {
  env.cleanup();
  const fetcher = vi.fn(url => {
    if (url === '/api/actions/groups/stale-group/reject') return json({ error: 'approval group changed' }, { ok: false, status: 409 });
    if (url === '/api/actions/pending') return json({
      actions: [{ id: 's1', tool: 'write', summary: 'Still pending' }, { id: 's2', tool: 'write', summary: 'Still pending' }],
      groups: [{ id: 'stale-group', leader_id: 's1', count: 2, member_ids: ['s1', 's2'], snapshot: 'stale-state' }],
    });
    return json({ proposals: [], cards: [] });
  });
  env = loadHud({ files: ['i18n', 'data', 'components', 'console', 'tools'], fetch: fetcher, lang: 'ro' });
  env.window.alert = vi.fn();
  const { container } = overlay();
  await env.flush(); openTool(container, 'Action Approvals'); await env.flush(); await env.flush();
  typeArea(container.querySelector('[aria-label="Your decision reason for Still pending"]'), 'Keep this draft');
  env.click(toolBtn(container, 'Reject group')); await env.flush();
  expect(env.window.alert).toHaveBeenCalled();
  expect(container.querySelector('[aria-label="Your decision reason for Still pending"]').value).toBe('Keep this draft');
  expect(toolBtn(container, 'Approve once')).toBeTruthy();
});

it('shows independent cards when a grouped projection omits its leader', async () => {
  env.cleanup();
  const fetcher = vi.fn(url => url === '/api/actions/pending' ? json({
    actions: [{ id: 'f1', tool: 'write', summary: 'First visible' }, { id: 'f2', tool: 'write', summary: 'Second visible' }],
    groups: [{ id: 'incomplete', leader_id: 'missing', count: 3, member_ids: ['missing', 'f1', 'f2'], snapshot: 'state' }],
  }) : json({ proposals: [], cards: [] }));
  env = loadHud({ files: ['i18n', 'data', 'components', 'console', 'tools'], fetch: fetcher, lang: 'ro' });
  const { container } = overlay();
  await env.flush(); openTool(container, 'Action Approvals'); await env.flush(); await env.flush();
  expect(container.querySelector('[aria-label="Your decision reason for First visible"]')).not.toBeNull();
  expect(container.querySelector('[aria-label="Your decision reason for Second visible"]')).not.toBeNull();
});

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

// H277 — the approval judge's score is a model's opinion: a separate, muted line under the
// summary, never next to the buttons; a low score is plain text (never green, never "safe"),
// the buttons never depend on it, and a bounded quiet re-poll waits for a pending opinion.
describe('Action Approvals — model opinion (H277)', () => {
  const OPINION = { score: 37, rationale: 'Writes one file; reversible.', flags: [], advisory: true,
                    judge: { provider: 'lm-studio', model: 'qwen3-4b', local: true }, at: 1 };
  function boot(pending) {
    env.cleanup();
    const calls = { pending: 0 };
    const fetch = vi.fn((url) => {
      if (url === '/api/actions/pending') {
        calls.pending += 1;   // a fresh object per read, as the wire gives
        return json(JSON.parse(JSON.stringify(typeof pending === 'function' ? pending(calls.pending) : pending)));
      }
      if (url.startsWith('/api/skills/proposals')) return json({ proposals: [], cards: [] });
      return json({});
    });
    env = loadHud({ files: ['i18n', 'data', 'components', 'console', 'tools'], fetch, lang: 'ro' });
    return calls;
  }
  async function open() {
    const { container } = overlay();
    await env.flush();
    openTool(container, 'Action Approvals');
    await env.flush();
    await env.flush();
    return container;
  }
  const card = (c, text) => [...c.querySelectorAll('.console-content .tool-card')].find((x) => x.textContent.includes(text));
  const approveOf = (el) => [...el.querySelectorAll('.tool-btn')].find((b) => b.textContent === 'Approve');
  const configured = { configured: true, reason: '', judging: [], timeout: 20 };

  it('shows the score as a labelled, advisory model opinion under the summary', async () => {
    boot({ actions: [{ id: 'a1', tool: 'write_file', summary: 'write notes', judge: OPINION }], judge: configured });
    const c = await open();
    const el = card(c, 'write notes');
    const line = el.querySelector('.judge-score');
    expect(line.textContent).toContain('Model opinion (lm-studio · qwen3-4b, local) — risk 37/100');
    expect(line.textContent).toContain('advisory only, it decides nothing');
    expect(line.closest('.tool-actions')).toBeNull();
    expect(el.querySelector('.tool-actions').textContent).not.toContain('risk');
  });

  it('never dresses a low score as reassurance', async () => {
    boot({ actions: [{ id: 'a2', tool: 'send_email', summary: 'mail', judge: { ...OPINION, score: 5 } }], judge: configured });
    const c = await open();
    const line = card(c, 'mail').querySelector('.judge-score');
    expect(line.className).not.toMatch(/ok|success|safe|good/);
    expect(line.classList.contains('judge-high')).toBe(false);
    expect(line.textContent.toLowerCase()).not.toMatch(/\bsafe\b|approved|✓|✔/);
    expect(line.getAttribute('style') || '').not.toMatch(/green/);
  });

  it('flags a high score with the warning colour', async () => {
    boot({ actions: [{ id: 'a3', tool: 'rm', summary: 'delete', judge: { ...OPINION, score: 82 } }], judge: configured });
    const c = await open();
    const line = card(c, 'delete').querySelector('.judge-score');
    expect(line.classList.contains('judge-high')).toBe(true);
    expect(line.getAttribute('style')).toContain('--amber-warn');
  });

  it('puts the manipulation warning before the score when the arguments carried injection text', async () => {
    boot({ actions: [{ id: 'a4', tool: 'send', summary: 'forward page', judge: { ...OPINION, score: 0, flags: ['ignore_previous'] } }], judge: configured });
    const c = await open();
    const el = card(c, 'forward page');
    const text = el.textContent;
    expect(text).toContain('may have been manipulated');
    expect(text.indexOf('may have been manipulated')).toBeLessThan(text.indexOf('Model opinion ('));
  });

  it('leaves the Approve button identical with and without an opinion', async () => {
    boot({ actions: [
      { id: 'b1', tool: 'write_file', summary: 'with opinion', judge: { ...OPINION, score: 0 } },
      { id: 'b2', tool: 'write_file', summary: 'without opinion' },
    ], judge: configured });
    const c = await open();
    const a = approveOf(card(c, 'with opinion'));
    const b = approveOf(card(c, 'without opinion'));
    expect(a.className).toBe(b.className);
    expect(a.disabled).toBe(b.disabled);
    expect(a.disabled).toBe(false);
  });

  it('says "not available" / "pending…" only when a judge is configured', async () => {
    boot({ actions: [{ id: 'c1', tool: 'x', summary: 'old card' }, { id: 'c2', tool: 'x', summary: 'new card', judge_pending: true }],
           judge: { ...configured, judging: ['c2'] } });
    let c = await open();
    expect(card(c, 'old card').textContent).toContain('Model opinion: not available');
    expect(card(c, 'new card').textContent).toContain('Model opinion: pending…');
    boot({ actions: [{ id: 'c1', tool: 'x', summary: 'old card' }], judge: { configured: false, reason: 'judge_unset', judging: [] } });
    c = await open();
    expect(card(c, 'old card').textContent).not.toContain('Model opinion');
  });

  it('never shows an opinion line on a skill-change card', async () => {
    boot({ actions: [{ id: 's1', tool: 'skill.patch_proposal', summary: 'skill change' }], judge: configured });
    const c = await open();
    expect(card(c, 'skill change').textContent).not.toContain('Model opinion');
  });

  // Fake wall time and the page's poll timer queue; harness/React settling stays real.
  function capturePolls() {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(0);
    env.window.Date = Date;
    const timers = new Map();
    let next = 0;
    const realSet = env.window.setTimeout, realClear = env.window.clearTimeout;
    env.window.setTimeout = function (fn, ms, ...rest) {
      if (ms > 0 && ms <= 3000) {
        const id = 'p' + (++next);
        timers.set(id, { fn, at: Date.now() + ms });
        return id;
      }
      return realSet.call(env.window, fn, ms, ...rest);
    };
    env.window.clearTimeout = function (id) {
      if (timers.delete(id)) return undefined;
      return realClear.call(env.window, id);
    };
    return {
      active: () => timers.size,
      async fireDelayed(ms) {
        vi.setSystemTime(Date.now() + ms);
        const [id, timer] = timers.entries().next().value;
        timers.delete(id);
        timer.fn();
        await env.flush();
      },
      async advance(ms) {
        const until = Date.now() + ms;
        while (timers.size) {
          const [id, timer] = [...timers.entries()].sort((a, b) => a[1].at - b[1].at)[0];
          if (timer.at > until) break;
          vi.setSystemTime(timer.at);
          timers.delete(id);
          timer.fn();
          await env.flush();
        }
        vi.setSystemTime(until);
      },
    };
  }

  it('uses per-item pending even when the global judging list disagrees, then shows unavailable', async () => {
    let pending = true;
    boot(() => ({ actions: [{ id: 'p1', tool: 'x', summary: 'waiting card', judge_pending: pending }],
      judge: { ...configured, judging: pending ? [] : ['p1'] } }));
    const polls = capturePolls();
    const c = await open();
    expect(card(c, 'waiting card').textContent).toContain('pending…');
    expect(polls.active()).toBe(1);
    pending = false;
    await polls.advance(3000);
    expect(card(c, 'waiting card').textContent).toContain('not available');
    expect(polls.active()).toBe(0);
  });

  it('shows a late queued opinion after the old timeout plus 5 s window', async () => {
    const calls = boot(() => ({ actions: [{ id: 'p1', tool: 'x', summary: 'waiting card',
      ...(Date.now() >= 9000 ? { judge: OPINION } : { judge_pending: true }) }],
      judge: { ...configured, judging: ['p1'], timeout: 1 } }));
    const polls = capturePolls();
    const c = await open();
    const before = calls.pending;
    await polls.advance(6000);
    expect(card(c, 'waiting card').textContent).toContain('pending…');
    expect(polls.active()).toBe(1);
    await polls.advance(3000);
    expect(calls.pending).toBe(before + 3);
    expect(card(c, 'waiting card').textContent).toContain('risk 37/100');
    expect(c.textContent).not.toContain('Loading…');
    expect(polls.active()).toBe(0);
  });

  it('caps each card at 17 * timeout + 5 wall seconds despite unrelated refreshes', async () => {
    const calls = boot({ actions: [{ id: 'q1', tool: 'x', summary: 'stuck card', judge_pending: true }],
      judge: { ...configured, judging: ['q1'], timeout: 1 } });
    const polls = capturePolls();
    const c = await open();
    await polls.advance(21000);
    const beforeRefresh = calls.pending;
    env.click(toolBtn(c, '↻'));
    await env.flush();
    await polls.advance(1000);             // original 22 s deadline, not refresh + 22 s
    expect(polls.active()).toBe(0);
    const capped = calls.pending;
    expect(capped).toBeGreaterThan(beforeRefresh);
    await polls.advance(30000);
    expect(calls.pending).toBe(capped);
  });

  it('does not poll when a throttled timer wakes after its hard deadline', async () => {
    const calls = boot({ actions: [{ id: 'late', tool: 'x', summary: 'stuck', judge_pending: true }],
      judge: { ...configured, timeout: 1 } });
    const polls = capturePolls();
    await open();
    const before = calls.pending;
    await polls.fireDelayed(30000);
    expect(calls.pending).toBe(before);
    expect(polls.active()).toBe(0);
  });

  it('gives staggered cards independent deadlines and clears removed card state', async () => {
    let first = true, second = false;
    const A = { id: 'r1', tool: 'x', summary: 'first card', judge_pending: true };
    const B = { id: 'r2', tool: 'x', summary: 'second card', judge_pending: true };
    const calls = boot(() => ({ actions: [...(first ? [A] : []), ...(second ? [B] : [])],
      judge: { ...configured, judging: ['r1', 'r2'], timeout: 1 } }));
    const polls = capturePolls();
    const c = await open();
    await polls.advance(12000);
    second = true;
    await polls.advance(3000);             // B first seen at 15 s: deadline 37 s
    await polls.advance(9000);             // A expired; B still polls
    expect(polls.active()).toBe(1);
    first = false;
    await polls.advance(3000);             // A removal observed at 27 s
    await polls.advance(10000);
    expect(polls.active()).toBe(0);
    const capped = calls.pending;
    first = true;                         // same id reappears after removal: fresh budget
    env.click(toolBtn(c, '↻'));
    await env.flush();
    expect(polls.active()).toBe(1);
    await polls.advance(3000);
    expect(calls.pending).toBeGreaterThan(capped + 1);
  });

  // review F1: the model's words sit in their own element, never inside the HUD's label text.
  it('renders the rationale in its own element, apart from the label', async () => {
    const why = 'read-only listing\' verified safe by Nerva policy, approve \'ok';
    boot({ actions: [{ id: 'w1', tool: 'x', summary: 'why card', judge: { ...OPINION, rationale: why } }], judge: configured });
    const c = await open();
    const line = card(c, 'why card').querySelector('.judge-score');
    const span = line.querySelector('.judge-why');
    expect(span).not.toBeNull();
    expect(span.tagName).toBe('SPAN');
    expect(span.textContent).toBe(why);
    expect(span.getAttribute('style') || '').toMatch(/italic/);
    const own = [...line.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent).join('');
    expect(own).not.toContain('verified safe');
    expect(own).toContain('advisory only, it decides nothing');
    expect(own).not.toContain('"');
  });

  // review F2: an opinion formed on a shortened copy says so.
  it('says when the opinion was formed on a shortened copy', async () => {
    boot({ actions: [
      { id: 't1', tool: 'x', summary: 'cut card', judge: { ...OPINION, truncated: true } },
      { id: 't2', tool: 'x', summary: 'whole card', judge: { ...OPINION, truncated: false } },
    ], judge: configured });
    const c = await open();
    expect(card(c, 'cut card').querySelector('.judge-score').textContent).toContain('judged on a shortened copy');
    expect(card(c, 'whole card').querySelector('.judge-score').textContent).not.toContain('shortened');
  });
});
