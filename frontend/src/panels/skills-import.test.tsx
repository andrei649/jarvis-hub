// @ts-nocheck
/* SKILLS IMPORT panel — GET /skills/imported (unguarded) + POST /skills/import (user tier,
   DEV_MODE-gated). fetch is mocked, like src/panels/marketplace-admin.test.tsx.

   The traps this file exists to pin:
     · a 503 on the read must NOT render as an empty list or a "0 imported" count.
     · the DEV_MODE 403 string must be rendered VERBATIM (em dash included) and must leave
       the import control disabled — no button that always 403s.
     · a 403 keyed `detail` is _user_guard, NOT the DEV_MODE gate: DEV_MODE was never
       evaluated, so the panel must not report it as "DEV_MODE=0".
     · the probe must never fire on mount — it is a real POST into the failure banner.
     · the collapsed 404 must be printed as it arrived, never paraphrased into a cause. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { SkillsImportPanel } from './skills-import';

const COMMIT = '5fc308a70719a83cccdbba4c0e39c23f5a8239d5';
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
  source_release_tag: 'v2026.8.27',
  source_commit: COMMIT,
  source_tree: '222ec43b5237deb643277bc2f64fa4b873dd7f28',
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

/* Press CHECK and let the backend's 400 unlock the import control. */
async function enableImport() {
  fireEvent.click(btn('check availability'));
  // the gate is open; the button additionally needs a skill name, which each test types
  await waitFor(() => expect(screen.getByText('import available')).toBeTruthy());
}

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } vi.restoreAllMocks(); });

describe('SkillsImportPanel — imported sidecars and the DEV_MODE-gated import', () => {
  it('renders a hermes sidecar with its provenance, and a legacy row defensively', async () => {
    mockRoutes(() => null, { imported: [HERMES_ROW, LEGACY_ROW] });
    render(<SkillsImportPanel />);

    await waitFor(() => expect(screen.getByText('deep-research')).toBeTruthy());
    expect(screen.getByText('v1.4.0')).toBeTruthy();
    expect(screen.getByText('hermes')).toBeTruthy();
    expect(screen.getByText('pin v2026.8.27')).toBeTruthy();
    expect(screen.getByText('5fc308a7')).toBeTruthy();
    expect(screen.getByText(/sha256 aaaaaaaaaaaa…/)).toBeTruthy();
    expect(screen.getByText('multi-hop research loop')).toBeTruthy();
    // the full 64-hex digest is a title attribute, not inline text
    expect(screen.queryByText(DIGEST)).toBeNull();
    // a sidecar missing every typed key still renders, and is not invented into a name
    expect(screen.getByText('(unnamed manifest)')).toBeTruthy();
    expect(screen.getByText('2 imported')).toBeTruthy();
  });

  it('never fires the probe on mount — it is a real POST into the failure banner', async () => {
    const fn = mockRoutes(() => null);
    render(<SkillsImportPanel />);
    await waitFor(() => expect(gets(fn).length).toBeGreaterThan(0));
    expect(posts(fn)).toHaveLength(0);
    expect(btn('import').disabled).toBe(true);
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

  it('CHECK against the DEV_MODE 403 prints it verbatim and leaves import disabled', async () => {
    const fn = mockRoutes((u, method) => (u === '/skills/import' && method === 'POST'
      ? { status: 403, body: { error: 'skill import disabled — set DEV_MODE=1 to enable' } } : null));
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText(/no imported skills on disk yet/)).toBeTruthy());

    fireEvent.click(btn('check availability'));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('skill import disabled — set DEV_MODE=1 to enable');
    expect(alert.textContent).toContain('HTTP 403');
    expect(screen.getByText('DEV_MODE=0 — import disabled by the server')).toBeTruthy();
    expect(btn('import').disabled).toBe(true);
    // the probe posts an EMPTY skill name — argument validation, no import
    expect(bodyOf(posts(fn)[0])).toEqual({ skill: '' });
  });

  it('CHECK against the 400 "skill name required" unlocks the import control', async () => {
    mockRoutes((u, method, body) => (u === '/skills/import' && method === 'POST' && body && body.skill === ''
      ? { status: 400, body: { error: 'skill name required' } } : null));
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText(/no imported skills on disk yet/)).toBeTruthy());

    await enableImport();
    expect(screen.getByText(/skill name required/)).toBeTruthy();
    expect(screen.getByText('import available')).toBeTruthy();
  });

  it('classifies a guard 403 keyed `detail` as blocked, NOT as DEV_MODE=0', async () => {
    mockRoutes((u, method) => (u === '/skills/import' && method === 'POST'
      ? { status: 403, body: { detail: 'user routes disabled from network — set JARVIS_USER_TOKEN to enable remote access' } } : null));
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText(/no imported skills on disk yet/)).toBeTruthy());

    fireEvent.click(btn('check availability'));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('user routes disabled from network — set JARVIS_USER_TOKEN to enable remote access');
    expect(screen.queryByText('DEV_MODE=0 — import disabled by the server')).toBeNull();
    expect(screen.getByText(/the DEV_MODE gate was never reached and its state is unknown/)).toBeTruthy();
    expect(btn('import').disabled).toBe(true);
  });

  it('renders the collapsed import 404 verbatim and reports no success', async () => {
    const fn = mockRoutes((u, method, body) => {
      if (u !== '/skills/import' || method !== 'POST') return null;
      if (body && body.skill === '') return { status: 400, body: { error: 'skill name required' } };
      return { status: 404, body: { ok: false, error: "Skill 'nope' not found in hermes" } };
    });
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText(/no imported skills on disk yet/)).toBeTruthy());
    await enableImport();

    fireEvent.change(screen.getByLabelText('skill name'), { target: { value: 'nope' } });
    fireEvent.click(btn('import'));

    await waitFor(() => expect(screen.getByText(/Skill 'nope' not found in hermes/)).toBeTruthy());
    expect(screen.getByText(/refused · HTTP 404/)).toBeTruthy();
    expect(screen.queryByText(/^imported · skill=/)).toBeNull();
    // the cause is left collapsed, exactly as the backend left it
    expect(screen.getByText(/covers a name outside the pin allowlist/)).toBeTruthy();
    const call = posts(fn).find((c) => bodyOf(c).skill === 'nope');
    expect(bodyOf(call)).toEqual({ skill: 'nope', source: 'hermes' });
  });

  it('renders a 200 as the echoed skill/source only, and re-reads the imported list', async () => {
    const fn = mockRoutes((u, method, body) => {
      if (u !== '/skills/import' || method !== 'POST') return null;
      if (body && body.skill === '') return { status: 400, body: { error: 'skill name required' } };
      return { status: 200, body: { ok: true, source: 'openclaw', skill: 'Deep Research' } };
    });
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText(/no imported skills on disk yet/)).toBeTruthy());
    await enableImport();

    fireEvent.change(screen.getByLabelText('import source'), { target: { value: 'openclaw' } });
    fireEvent.change(screen.getByLabelText('skill name'), { target: { value: 'Deep Research' } });
    const before = gets(fn).length;
    fireEvent.click(btn('import'));

    await waitFor(() => expect(screen.getByText('imported · skill=Deep Research · source=openclaw')).toBeTruthy());
    // the echo is the RAW input, never presented as the directory that was written
    expect(screen.getByText(/the raw input, not the directory it wrote/)).toBeTruthy();
    await waitFor(() => expect(gets(fn).length).toBeGreaterThan(before));
    expect(bodyOf(posts(fn).slice(-1)[0])).toEqual({ skill: 'Deep Research', source: 'openclaw' });
  });

  it('warns locally about a bare GitHub repo without pre-empting the backend', async () => {
    mockRoutes((u, method, body) => (u === '/skills/import' && method === 'POST' && body && body.skill === ''
      ? { status: 400, body: { error: 'skill name required' } } : null));
    render(<SkillsImportPanel />);
    await waitFor(() => expect(screen.getByText(/no imported skills on disk yet/)).toBeTruthy());
    await enableImport();

    fireEvent.change(screen.getByLabelText('import source'), { target: { value: 'github' } });
    fireEvent.change(screen.getByLabelText('github owner/repo'), { target: { value: 'openclaw' } });
    fireEvent.change(screen.getByLabelText('skill name'), { target: { value: 'brief' } });

    expect(screen.getByText(/local hint: owner\/repo required/)).toBeTruthy();
    // the hint never blocks the POST — the backend still owns the answer
    expect(btn('import').disabled).toBe(false);
  });
});
