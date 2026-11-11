// @ts-nocheck
/* The actual admin import request carries immutable pins; every import remains
   pending owner review. Read/provenance regressions remain distinct from writes. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { SkillsImportPanel, SkillSetup, SkillTaps } from './skills-import';

const COMMIT = '29112bef099274229cadff79cdff7bf7b99c4b77';
const DIGEST = 'a'.repeat(64);

const HERMES_ROW = {
  name: 'deep-research',
  description: 'multi-hop research loop',
  version: '1.4.0',
  author: 'NousResearch',
  license: 'MIT',
  source: 'hermes',
  imported: true,
  source_repository: 'NousResearch/hermes-agent',
  source_release_tag: 'v2026.8.31',
  source_commit: COMMIT,
  source_tree: 'daaffc303ae437041b7f76be17c5f61b14f2ce99',
  source_tier: 'optional',
  source_path: 'skills/research/deep-research/SKILL.md',
  content_sha256: DIGEST,
};
/* A legacy sidecar with none of the typed keys — list_imported keeps it because
   source is 'openclaw'. */
const LEGACY_ROW = { source: 'openclaw', foo: 'bar' };

/* handler(url, method, parsedBody) -> {status, body} | null (null = default 200 GET). */
function mockRoutes(handler, defaultGet = { imported: [] }) {
  const fn = vi.fn(async (url, init) => {
    const u = String(url);
    const method = String((init && init.method) || 'GET').toUpperCase();
    let parsed;
    try { parsed = init && init.body ? JSON.parse(init.body) : undefined; } catch { parsed = undefined; }
    const r = handler(u, method, parsed)
      || (u === '/skills/imported' ? { status: 200, body: defaultGet } : { status: 200, body: {} });
    return { ok: r.status < 400, status: r.status, json: async () => r.body };
  });
  global.fetch = fn;
  return fn;
}

const posts = (fn) => fn.mock.calls.filter((c) => String((c[1] && c[1].method) || 'GET').toUpperCase() === 'POST');
const gets = (fn) => fn.mock.calls.filter((c) => String((c[1] && c[1].method) || 'GET').toUpperCase() === 'GET');
const bodyOf = (call) => JSON.parse(call[1].body);
const btn = (name) => screen.getByRole('button', { name });

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } vi.restoreAllMocks(); });

describe('SkillsImportPanel — imported sidecars and governed pinned imports', () => {
  it('uses the existing user token for the imported-manifest read', async () => {
    localStorage.setItem('hud.user_token', 'owner-user');
    const fn = mockRoutes(() => null);
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText(/no imported skills on disk yet/)).toBeTruthy());
    const read = gets(fn).find(([url]) => String(url) === '/skills/imported');
    expect(read).toBeTruthy();
    expect(read[1].headers['X-User-Token']).toBe('owner-user');
    expect(read[1].headers['X-Admin-Token']).toBeUndefined();
    expect(screen.getByText(/GET \/skills\/imported is/).textContent).toContain('user tier');
    expect(screen.queryByText(/unguarded/)).toBeNull();
  });

  it('renders a hermes sidecar with its provenance, and a legacy row defensively', async () => {
    mockRoutes(() => null, { imported: [HERMES_ROW, LEGACY_ROW] });
    render(<SkillsImportPanel />);

    await waitFor(() => expect(screen.getByText('deep-research')).toBeTruthy());
    expect(screen.getByText('v1.4.0')).toBeTruthy();
    expect(screen.getByText('hermes')).toBeTruthy();
    expect(screen.getByText('pin v2026.8.31')).toBeTruthy();
    expect(screen.getByText('29112bef')).toBeTruthy();
    expect(screen.getByText('tier optional')).toBeTruthy();
    expect(screen.getByText(/sha256 aaaaaaaaaaaa…/)).toBeTruthy();
    expect(screen.getByText('multi-hop research loop')).toBeTruthy();
    // the full 64-hex digest is a title attribute, not inline text
    expect(screen.queryByText(DIGEST)).toBeNull();
    // a sidecar missing every typed key still renders, and is not invented into a name
    expect(screen.getByText('(unnamed manifest)')).toBeTruthy();
    expect(screen.getByText('2 imported')).toBeTruthy();
  });

  it('never submits an import on mount', async () => {
    const fn = mockRoutes(() => null);
    render(<SkillsImportPanel />);
    await waitFor(() => expect(gets(fn).length).toBeGreaterThan(0));
    expect(posts(fn)).toHaveLength(0);
    expect(btn('import').disabled).toBe(true);
  });

  it('offers an admin optional install and reports pending review after kernel queue', async () => {
    const fn = mockRoutes((u, method) => {
      if (u === '/api/skills/optional/catalog' && method === 'GET') return {
        status: 200, body: { skills: [{ name: 'calendar', tier: 'optional', installed: false, available: true }] },
      };
      if (u === '/api/skills/optional/install' && method === 'POST') return {
        status: 200, body: { status: 'installed_review_required', kernel: 'queue', quarantined: true },
      };
      return null;
    });
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText('calendar')).toBeTruthy());
    fireEvent.click(btn('install for review'));
    await waitFor(() => expect(screen.getByText(/calendar: installed_review_required · kernel queue/)).toBeTruthy());
    expect(bodyOf(posts(fn).find((c) => String(c[0]) === '/api/skills/optional/install'))).toEqual({ name: 'calendar' });
  });

  it('lists pinned upstream tiers and lets the owner choose an exact slug', async () => {
    mockRoutes((u, method) => u === '/skills/hermes/catalog' && method === 'GET'
      ? { status: 200, body: { release_tag: 'v2026.8.31', skills: [
        { slug: 'github', tier: 'bundled', reference_count: 10 },
        { slug: 'grill-me', tier: 'optional', reference_count: 0 },
      ] } } : null);
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText('github')).toBeTruthy());
    expect(screen.getByText('bundled')).toBeTruthy();
    expect(screen.getByText('optional')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'choose github' }));
    expect(screen.getByLabelText('skill name').value).toBe('github');
  });

  it('renders 200 {"imported": []} as an honest empty state, with no unavailable tag', async () => {
    mockRoutes(() => null, { imported: [] });
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText(/no imported skills on disk yet/)).toBeTruthy());
    expect(screen.getByText('0 imported')).toBeTruthy();
    expect(screen.queryByText(/unavailable · HTTP 503/)).toBeNull();
  });

  it('renders a 503 on the read as unavailable — no rows, no count, not "nothing yet"', async () => {
    mockRoutes((u) => (u === '/skills/imported' ? { status: 503, body: { error: 'not initialized' } } : null));
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText(/unavailable · HTTP 503/)).toBeTruthy());
    expect(screen.getByText(/NOT “zero imported”/)).toBeTruthy();
    expect(screen.queryByText('0 imported')).toBeNull();
    expect(screen.queryByText(/no imported skills on disk yet/)).toBeNull();
    expect(screen.queryByText('nothing yet')).toBeNull();
  });

  it.each([
    [403, { reason: 'install_denied' }, 'install_denied'],
    [403, { detail: 'admin token required' }, 'admin token required'],
    [404, { error: "Skill 'github' not found in hermes" }, "Skill 'github' not found in hermes"],
    [503, { error: 'not initialized' }, 'not initialized'],
    [429, { error: 'rate limit exceeded' }, 'rate limit exceeded'],
    [500, { message: 'Internal server error' }, 'POST /skills/import'],
  ])('shows HTTP %s refusal without inventing availability or issuing a probe', async (status, body, text) => {
    const fn = mockRoutes((u, method) => u === '/skills/import' && method === 'POST'
      ? { status, body } : null);
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText(/no imported skills on disk yet/)).toBeTruthy());
    fireEvent.change(screen.getByLabelText('skill name'), { target: { value: 'github' } });
    fireEvent.click(btn('import'));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain(`HTTP ${status}`);
    expect(alert.textContent).toContain(text);
    expect(posts(fn)).toHaveLength(1);
    expect(bodyOf(posts(fn)[0])).toEqual({ skill: 'github', source: 'hermes' });
    expect(screen.queryByText(/DEV_MODE/)).toBeNull();
    expect(screen.queryByText(/import available/)).toBeNull();
  });

  it('reports kernel queue as a quarantined copy awaiting owner review, and reloads', async () => {
    const fn = mockRoutes((u, method) => u === '/skills/import' && method === 'POST'
      ? { status: 200, body: { ok: true, source: 'hermes', skill: 'github',
          kernel: 'queue', quarantined: true, status: 'installed_review_required' } } : null);
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText(/no imported skills on disk yet/)).toBeTruthy());
    fireEvent.change(screen.getByLabelText('skill name'), { target: { value: 'github' } });
    const before = gets(fn).length;
    fireEvent.click(btn('import'));
    await waitFor(() => expect(screen.getByText(/staged · skill=github · source=hermes · kernel queue · pending owner review/)).toBeTruthy());
    await waitFor(() => expect(gets(fn).length).toBeGreaterThan(before));
    expect(bodyOf(posts(fn)[0])).toEqual({ skill: 'github', source: 'hermes' });
    expect(screen.queryByText(/activated/)).toBeNull();
  });

  it('requires and sends an immutable generic source pin, including reference digests', async () => {
    const fn = mockRoutes((u, method, body) => u === '/skills/import' && method === 'POST'
      ? { status: 200, body: { ok: true, source: body.source, skill: body.skill,
          kernel: 'grant', quarantined: true, status: 'installed_review_required' } } : null);
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText(/no imported skills on disk yet/)).toBeTruthy());
    fireEvent.change(screen.getByLabelText('import source'), { target: { value: 'github' } });
    fireEvent.change(screen.getByLabelText('github owner/repo'), { target: { value: 'owner/repo' } });
    fireEvent.change(screen.getByLabelText('skill name'), { target: { value: 'brief' } });
    expect(btn('import').disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('source commit'), { target: { value: 'main' } });
    fireEvent.change(screen.getByLabelText('source entry path'), { target: { value: 'skills/brief/SKILL.md' } });
    fireEvent.change(screen.getByLabelText('source sha256'), { target: { value: DIGEST } });
    expect(btn('import').disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('source commit'), { target: { value: COMMIT } });
    fireEvent.change(screen.getByLabelText('reference pins'), { target: { value: `skills/brief/references/guide.md ${'b'.repeat(64)}` } });
    expect(btn('import').disabled).toBe(false);
    fireEvent.click(btn('import'));
    await waitFor(() => expect(posts(fn)).toHaveLength(1));
    expect(bodyOf(posts(fn)[0])).toEqual({ skill: 'brief', source: 'owner/repo', pin: {
      repo: 'owner/repo', commit: COMMIT, entry_path: 'skills/brief/SKILL.md', content_sha256: DIGEST,
      references: [{ path: 'skills/brief/references/guide.md', content_sha256: 'b'.repeat(64) }],
    } });
    await waitFor(() => expect(screen.getByText(/kernel grant · pending owner review/)).toBeTruthy());
  });

  it('keeps malformed reference pins and mutable openclaw imports disabled', async () => {
    const fn = mockRoutes(() => null);
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText(/no imported skills on disk yet/)).toBeTruthy());
    fireEvent.change(screen.getByLabelText('import source'), { target: { value: 'openclaw' } });
    fireEvent.change(screen.getByLabelText('skill name'), { target: { value: 'brief' } });
    expect(btn('import').disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('source commit'), { target: { value: COMMIT } });
    fireEvent.change(screen.getByLabelText('source entry path'), { target: { value: 'skills/brief/SKILL.md' } });
    fireEvent.change(screen.getByLabelText('source sha256'), { target: { value: DIGEST } });
    fireEvent.change(screen.getByLabelText('reference pins'), { target: { value: 'guide.md bad-hash' } });
    expect(btn('import').disabled).toBe(true);
    expect(posts(fn)).toHaveLength(0);
  });

  it('uses admin credentials for the write and rejects an unexpected activation response', async () => {
    localStorage.setItem('hud.admin_token', 'owner-admin');
    const fn = mockRoutes((u, method) => u === '/skills/import' && method === 'POST'
      ? { status: 200, body: { ok: true, status: 'active', quarantined: false } } : null);
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText(/no imported skills on disk yet/)).toBeTruthy());
    fireEvent.change(screen.getByLabelText('skill name'), { target: { value: 'github' } });
    fireEvent.click(btn('import'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('unexpected import response'));
    expect(posts(fn)[0][1].headers['X-Admin-Token']).toBe('owner-admin');
    expect(screen.queryByText(/staged · skill=/)).toBeNull();
  });
});

/* Adopt lane slice 3 — the vendored Hermes catalog carried by GET /skills/imported. */
const CATALOG = {
  available: true,
  source: 'hermes-catalog',
  repository: 'NousResearch/hermes-agent',
  commit: '9c0560f8e6856bc14c11bfe6d666df06be14d2de',
  counts: { instruction: 1, upstream_only: 1, excluded: 0 },
  skills: [
    { slug: 'agentmail', category: 'email', kind: 'instruction', installable: true,
      description: 'Give the agent its own inbox', required_env: ['AGENTMAIL_API_KEY'],
      unmapped_keys: ['metadata.hermes.homepage'], injection_flags: [], files: 6 },
    { slug: 'comfyui', category: 'creative', kind: 'upstream_only', installable: false,
      description: 'Drive ComfyUI', code_files: ['scripts/run.py'], required_env: [], files: 9 },
  ],
};

describe('SkillsImportPanel — the vendored Hermes catalog', () => {
  it('shows no catalog section when the backend reports none', async () => {
    mockRoutes(() => null, { imported: [] });
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText(/no imported skills on disk yet/)).toBeTruthy());
    expect(screen.queryByText(/HERMES CATALOG · vendored/)).toBeNull();
  });

  it('installs a catalog row through the owner route', async () => {
    const fn = mockRoutes((u, method) => {
      if (u === '/api/skills/catalog/install' && method === 'POST') {
        return { status: 200, body: { ok: true, action: 'install', status: 'installed', skill: 'agentmail',
          changed: true, audited: true } };
      }
      return null;
    }, { imported: [], hermes_catalog: CATALOG });
    localStorage.setItem('hud.admin_token', 'owner-token');
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText('HERMES CATALOG · vendored @9c0560f8')).toBeTruthy());
    expect(screen.getByText('agentmail')).toBeTruthy();
    expect(screen.getByText('needs AGENTMAIL_API_KEY')).toBeTruthy();
    expect(screen.getByText(/not read by Nerva: metadata.hermes.homepage/)).toBeTruthy();
    expect(btn('install agentmail').disabled).toBe(false);
    fireEvent.click(btn('install agentmail'));
    await waitFor(() => expect(posts(fn).length).toBe(1));
    expect(String(posts(fn)[0][0])).toBe('/api/skills/catalog/install');
    expect(bodyOf(posts(fn)[0])).toEqual({ skill: 'agentmail', repair: false, force: false });
    // sent with the admin token header, not the user token alone
    const headers = posts(fn)[0][1].headers || {};
    expect(Object.keys(headers).map((k) => k.toLowerCase())).toContain('x-admin-token');
    await waitFor(() => expect(screen.getByText(/installed · agentmail · installed/)).toBeTruthy());
    // no POST /skills/import probe was made
    expect(posts(fn).some((c) => String(c[0]) === '/skills/import')).toBe(false);
  });

  it('repairs an installed row and offers a forced repair over local edits', async () => {
    const installed = { ...CATALOG, skills: [{ ...CATALOG.skills[0], installed_commit: CATALOG.commit }, CATALOG.skills[1]] };
    let calls = 0;
    const fn = mockRoutes((u, method, body) => {
      if (u === '/api/skills/catalog/install' && method === 'POST') {
        calls += 1;
        if (!body.force) {
          return { status: 409, body: { ok: false, reason: 'local_edits', files: ['SKILL.md'],
            error: "the installed files of 'agentmail' were edited; nothing was written" } };
        }
        return { status: 200, body: { ok: true, action: 'repair', status: 'repaired', skill: 'agentmail',
          restored: [], replaced: ['SKILL.md'], changed: true, audited: true } };
      }
      return null;
    }, { imported: [], hermes_catalog: installed });
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText('installed @9c0560f8')).toBeTruthy());
    expect(screen.queryByRole('button', { name: 'install agentmail' })).toBeNull();
    fireEvent.click(btn('repair agentmail'));
    // the panel names a refusal by its reason key first (main's refusal(): reason ?? error ?? detail)
    await waitFor(() => expect(screen.getByText(/HTTP 409 · local_edits/)).toBeTruthy());
    expect(bodyOf(posts(fn)[0])).toEqual({ skill: 'agentmail', repair: true, force: false });
    fireEvent.click(btn('force repair agentmail'));
    await waitFor(() => expect(calls).toBe(2));
    expect(bodyOf(posts(fn)[1])).toEqual({ skill: 'agentmail', repair: true, force: true });
    await waitFor(() => expect(screen.getByText(/replaced SKILL.md \(a copy was kept\)/)).toBeTruthy());
  });

  it('shows a skill that carries code with its code files and no install button', async () => {
    mockRoutes(() => null, { imported: [], hermes_catalog: CATALOG });
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText(/HERMES CATALOG · vendored/)).toBeTruthy());
    fireEvent.change(screen.getByLabelText('catalog kind'), { target: { value: 'upstream_only' } });
    expect(screen.getByText('comfyui')).toBeTruthy();
    expect(screen.getByText(/code it carries: scripts\/run.py/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'install comfyui' })).toBeNull();
  });

  it('imports through POST /skills/import with source hermes-catalog and no remote pin', async () => {
    const fn = mockRoutes((u, method) => {
      if (u === '/skills/import' && method === 'POST') {
        return { status: 200, body: { ok: true, source: 'hermes-catalog', skill: 'agentmail' } };
      }
      return null;
    }, { imported: [], hermes_catalog: CATALOG });
    localStorage.setItem('hud.admin_token', 'owner-token');
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText(/HERMES CATALOG · vendored/)).toBeTruthy());
    fireEvent.change(screen.getByLabelText('import source'), { target: { value: 'hermes-catalog' } });
    fireEvent.change(screen.getByLabelText('skill name'), { target: { value: 'agentmail' } });
    expect(screen.queryByLabelText('source commit')).toBeNull();
    fireEvent.click(btn('import'));
    await waitFor(() => expect(posts(fn).length).toBe(1));
    expect(String(posts(fn)[0][0])).toBe('/skills/import');
    expect(bodyOf(posts(fn)[0])).toEqual({ skill: 'agentmail', source: 'hermes-catalog' });
    await waitFor(() => expect(screen.getByText(/imported · skill=agentmail · source=hermes-catalog/)).toBeTruthy());
  });
});

describe('SkillSetup — H342 declared variables, values never shown', () => {
  it('lists missing names, PUTs a value once and never renders it', async () => {
    const SECRET = 'sk-live-0123456789abcdefWXYZ';
    const view = (set) => ({ skill: 'weather-tool', ready: set, missing: set ? [] : ['WEATHER_KEY'],
      requirements: [{ name: 'WEATHER_KEY', prompt: 'Enter WEATHER_KEY', optional: false, set,
        source: set ? 'skill' : null, settable: true }] });
    const fn = mockRoutes((u, method) => {
      if (u === '/api/skills/setup/weather-tool' && method === 'GET') return { status: 200, body: view(false) };
      if (u === '/api/skills/setup/weather-tool/WEATHER_KEY' && method === 'PUT') {
        return { status: 200, body: { ok: true, ...view(true) } };
      }
      return null;
    });
    localStorage.setItem('hud.admin_token', 'owner-token');
    const { container } = render(<SkillSetup />);
    fireEvent.change(screen.getByLabelText('skill to set up'), { target: { value: 'weather-tool' } });
    fireEvent.click(btn('show setup'));
    await waitFor(() => expect(screen.getByText(/missing WEATHER_KEY/)).toBeTruthy());
    fireEvent.change(screen.getByLabelText('value for WEATHER_KEY'), { target: { value: SECRET } });
    fireEvent.click(btn('save WEATHER_KEY'));
    await waitFor(() => expect(screen.getByText(/set · for this skill/)).toBeTruthy());
    const put = fn.mock.calls.find((c) => String((c[1] && c[1].method) || '').toUpperCase() === 'PUT');
    expect(bodyOf(put)).toEqual({ value: SECRET });
    expect(put[1].headers['X-Admin-Token']).toBe('owner-token');
    expect(container.innerHTML).not.toContain(SECRET);
    expect(screen.getByLabelText('value for WEATHER_KEY').value).toBe('');
  });
});

describe('SkillTaps — H025 trusted sources behind an approval card', () => {
  const TAPS = {
    taps: [
      { id: 'hermes-catalog', builtin: true, trust: 'official', status: 'active', commit: '9c0560f8e6856bc14c11bfe6d666df06be14d2de', repo: 'NousResearch/hermes-agent', skills: 185 },
      { id: 'hermes', builtin: true, trust: 'official', status: 'active', commit: '29112bef099274229cadff79cdff7bf7b99c4b77', release_tag: 'v2026.8.31', repo: 'NousResearch/hermes-agent', skills: 190 },
      { id: 'acme--skills', builtin: false, trust: 'community', status: 'pending', commit: 'c'.repeat(40), repo: 'acme/skills', path: 'skills', skills: 0 },
    ],
    pin_alignment: { available: true, aligned: false, import_pin: { release_tag: 'v2026.8.31', commit: '29112bef', skills: 190 },
      catalog_pin: { commit: '9c0560f8', skills: 185 }, same_bytes: 87, changed: 68, not_in_catalog: 35, why: 'release vs main' },
  };

  it('shows both official pins, queues a card for a pinned tap, and installs through the tap route', async () => {
    const fn = mockRoutes((u, method) => {
      if (u === '/api/skills/taps' && method === 'GET') return { status: 200, body: TAPS };
      if (u === '/api/skills/taps' && method === 'POST') return { status: 202, body: { ok: true, task_id: 7, status: 'pending_approval' } };
      if (u.startsWith('/api/skills/taps/search')) {
        return { status: 200, body: { results: [{ tap: 'acme--skills', trust: 'community', slug: 'good-skill', commit: 'c'.repeat(40),
          installable: true, install: 'import', required_env: ['G20_TOOL_KEY'] }] } };
      }
      if (u === '/api/skills/taps/install' && method === 'POST') {
        return { status: 200, body: { ok: true, status: 'installed_review_required', quarantined: true,
          setup: { missing: ['G20_TOOL_KEY'] } } };
      }
      return null;
    });
    localStorage.setItem('hud.admin_token', 'owner-token');
    render(<SkillTaps />);
    await waitFor(() => expect(screen.getByText('awaiting approval')).toBeTruthy());
    expect(screen.getByText(/87 have the same SKILL.md bytes/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'remove hermes' })).toBeNull();
    fireEvent.change(screen.getByLabelText('tap repository'), { target: { value: 'acme/skills' } });
    fireEvent.change(screen.getByLabelText('tap commit'), { target: { value: 'main' } });
    expect(btn('ask to add tap').disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('tap commit'), { target: { value: 'c'.repeat(40) } });
    fireEvent.click(btn('ask to add tap'));
    await waitFor(() => expect(screen.getByText(/approval card #7 queued/)).toBeTruthy());
    expect(bodyOf(posts(fn)[0])).toEqual({ repo: 'acme/skills', commit: 'c'.repeat(40), path: 'skills', trust: 'community' });
    fireEvent.change(screen.getByLabelText('search all skill sources'), { target: { value: 'good' } });
    fireEvent.click(btn('search'));
    await waitFor(() => expect(screen.getByText('good-skill')).toBeTruthy());
    fireEvent.click(btn('install good-skill from acme--skills'));
    await waitFor(() => expect(screen.getByText(/quarantined, pending your review · needs G20_TOOL_KEY/)).toBeTruthy());
    const install = posts(fn).find(([url]) => String(url) === '/api/skills/taps/install');
    expect(bodyOf(install)).toEqual({ tap: 'acme--skills', skill: 'good-skill' });
  });
});
