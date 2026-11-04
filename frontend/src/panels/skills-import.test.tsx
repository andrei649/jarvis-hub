// @ts-nocheck
/* The actual admin import request carries immutable pins; every import remains
   pending owner review. Read/provenance regressions remain distinct from writes. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { SkillsImportPanel } from './skills-import';

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
