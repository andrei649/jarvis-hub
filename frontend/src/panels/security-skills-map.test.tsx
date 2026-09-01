// @ts-nocheck
/* SECURITY SKILLS · MAP — the three previously-uncalled 0.42 Security Skills routes.

   Covers the happy path of all three (frameworks read, behavior→candidates, candidates→
   playbook) AND the two honesty properties the panel exists for:
     * a 422 renders as a REFUSED alert carrying FastAPI's own `detail` verbatim, with no
       candidate rows left sitting under it;
     * the ATT&CK half of /frameworks is deliberately NOT rendered here (it is already
       shipped in gap.tsx's SecuritySkillsPanel), so TA0043/Reconnaissance must be absent. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { SecuritySkillsMapPanel } from './security-skills-map';

const FRAMEWORKS = {
  attack_tactics: [
    { id: 'TA0043', name: 'Reconnaissance', summary: 'Gather information to plan future operations.' },
    { id: 'TA0002', name: 'Execution', summary: 'Run adversary-controlled code.' },
  ],
  d3fend_tactics: [
    { id: 'D3-HARDEN', name: 'Harden', summary: 'Reduce attack surface before compromise.' },
    { id: 'D3-DETECT', name: 'Detect', summary: 'Identify adversary activity.' },
  ],
  csf_functions: [
    { id: 'GV', name: 'Govern', summary: 'Establish and monitor the cybersecurity risk strategy.' },
    { id: 'DE', name: 'Detect', summary: 'Find and analyze possible attacks and compromises.' },
  ],
  curated: true,
  disclaimer: 'Curated educational subset of public security taxonomies (MITRE ATT&CK, MITRE D3FEND, NIST CSF 2.0). NOT a complete control set and NOT security advice — verify against the authoritative sources before relying on it operationally.',
  sources: { attack: 'https://attack.mitre.org/ (MITRE ATT&CK Enterprise)', d3fend: 'https://d3fend.mitre.org/ (MITRE D3FEND)', nist_csf: 'https://www.nist.gov/cyberframework (NIST CSF 2.0)' },
};

const MAP_OK = {
  candidates: [
    { id: 'T1027', name: 'Obfuscated Files or Information', tactics: ['TA0005'], score: 2, evidence: ['encode', 'base64'] },
    { id: 'T1059', name: 'Command and Scripting Interpreter', tactics: ['TA0002'], score: 2, evidence: ['shell', 'powershell'] },
  ],
  count: 2,
  heuristic: 'keyword-match',
  curated: true,
  disclaimer: FRAMEWORKS.disclaimer,
  sources: FRAMEWORKS.sources,
};

const PLAYBOOK_OK = {
  playbook: [{
    id: 'T1059', name: 'Command and Scripting Interpreter', tactics: ['TA0002'],
    countermeasures: [
      { id: 'D3-SEA', name: 'Script Execution Analysis', d3fend_tactic: 'D3-DETECT' },
      { id: 'D3-EAL', name: 'Executable Allowlisting', d3fend_tactic: 'D3-HARDEN' },
    ],
    csf_functions: ['DE', 'PR'], gap: false,
  }],
  unknown: ['bogus-id'],
  csf_coverage: ['DE', 'PR'],
  csf_gaps: ['GV', 'ID', 'RS', 'RC'],
  generated: false,
  curated: true,
  disclaimer: FRAMEWORKS.disclaimer,
  sources: FRAMEWORKS.sources,
};

const ok = (payload) => ({ ok: true, status: 200, json: async () => payload });
const fail = (status, payload) => ({ ok: false, status, json: async () => payload });

/* routes: { '<url substring>': Response-ish } */
function mockFetch(routes) {
  const fn = vi.fn(async (url) => {
    const u = String(url);
    const hit = Object.keys(routes).find((k) => u.includes(k));
    if (!hit) throw new Error('unexpected fetch ' + u);
    return routes[hit];
  });
  global.fetch = fn;
  return fn;
}

const bodyOf = (fn, needle) => {
  const call = fn.mock.calls.find((c) => String(c[0]).includes(needle) && c[1] && c[1].body);
  return call ? JSON.parse(call[1].body) : null;
};

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

describe('SecuritySkillsMapPanel — the D3FEND/CSF half of the curated pack is reachable', () => {
  it('GETs /api/security-skills/frameworks and renders D3FEND + CSF, never the already-shipped ATT&CK tactics', async () => {
    const fn = mockFetch({ '/api/security-skills/frameworks': ok(FRAMEWORKS) });
    render(<SecuritySkillsMapPanel />);

    await waitFor(() => expect(screen.getByText('D3-HARDEN')).toBeTruthy());
    expect(screen.getByText('Reduce attack surface before compromise.')).toBeTruthy();
    expect(screen.getByText('GV')).toBeTruthy();
    expect(screen.getByText('Govern')).toBeTruthy();
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/security-skills/frameworks'))).toBe(true);

    // the whole reason this route is buildable: the ATT&CK half is already shipped elsewhere
    expect(screen.queryByText('TA0043')).toBeNull();
    expect(screen.queryByText('Reconnaissance')).toBeNull();

    // the payload's own honesty fields, verbatim
    expect(screen.getByText(FRAMEWORKS.disclaimer)).toBeTruthy();
    expect(screen.getByText(/https:\/\/d3fend\.mitre\.org\//)).toBeTruthy();
  });

  it('POSTs the typed behavior to /api/security-skills/map and prints the matched keywords verbatim', async () => {
    const fn = mockFetch({
      '/api/security-skills/frameworks': ok(FRAMEWORKS),
      '/api/security-skills/map': ok(MAP_OK),
    });
    render(<SecuritySkillsMapPanel />);
    await waitFor(() => expect(screen.getByText('D3-HARDEN')).toBeTruthy());

    fireEvent.change(screen.getByLabelText('behavior'), { target: { value: 'powershell base64 encoded script' } });
    fireEvent.click(screen.getByRole('button', { name: /map behavior/ }));

    await waitFor(() => expect(screen.getByText(/T1027 · Obfuscated Files or Information/)).toBeTruthy());
    expect(bodyOf(fn, '/api/security-skills/map')).toEqual({ behavior: 'powershell base64 encoded script', top_k: 5 });

    // evidence verbatim — the operator sees WHY the row surfaced
    expect(screen.getByText(/matched: encode, base64/)).toBeTruthy();
    expect(screen.getByText(/matched: shell, powershell/)).toBeTruthy();
    // score is rendered as a raw count, never a percentage or a verdict
    expect(screen.getAllByText('score 2').length).toBe(2);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('renders a 422 from /api/security-skills/map as a visible refusal carrying FastAPI detail verbatim', async () => {
    mockFetch({
      '/api/security-skills/frameworks': ok(FRAMEWORKS),
      '/api/security-skills/map': fail(422, {
        detail: [{ type: 'string_too_long', loc: ['body', 'behavior'], msg: 'String should have at most 2000 characters' }],
      }),
    });
    render(<SecuritySkillsMapPanel />);
    await waitFor(() => expect(screen.getByText('D3-HARDEN')).toBeTruthy());

    fireEvent.change(screen.getByLabelText('behavior'), { target: { value: 'a very long behavior' } });
    fireEvent.click(screen.getByRole('button', { name: /map behavior/ }));

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('REFUSED · 422 · body.behavior: String should have at most 2000 characters');
    // a refusal never leaves a result (or an empty "no candidate" success) underneath it
    expect(screen.queryByText(/T1027/)).toBeNull();
    expect(screen.queryByText(/no candidate/)).toBeNull();
  });

  it('POSTs the ticked candidate to /api/security-skills/playbook and renders unknown ids + the csf_gaps caveat', async () => {
    const fn = mockFetch({
      '/api/security-skills/frameworks': ok(FRAMEWORKS),
      '/api/security-skills/map': ok(MAP_OK),
      '/api/security-skills/playbook': ok(PLAYBOOK_OK),
    });
    render(<SecuritySkillsMapPanel />);
    await waitFor(() => expect(screen.getByText('D3-HARDEN')).toBeTruthy());

    fireEvent.change(screen.getByLabelText('behavior'), { target: { value: 'powershell base64 encoded script' } });
    fireEvent.click(screen.getByRole('button', { name: /map behavior/ }));
    await waitFor(() => expect(screen.getByLabelText('select T1059')).toBeTruthy());

    // selection is composed from real state: an id the backend just returned, plus a typed id
    fireEvent.click(screen.getByLabelText('select T1059'));
    fireEvent.change(screen.getByLabelText('extra technique ids'), { target: { value: 'bogus-id, ' } });
    fireEvent.click(screen.getByRole('button', { name: /build playbook/ }));

    await waitFor(() => expect(screen.getByText(/D3-SEA · Script Execution Analysis \(D3-DETECT\)/)).toBeTruthy());
    // blanks filtered, no duplicates, ids taken from real state
    expect(bodyOf(fn, '/api/security-skills/playbook')).toEqual({ techniques: ['T1059', 'bogus-id'] });

    // the only domain-level refusal these routes have: a 200 that reports the id as unknown
    expect(screen.getByText(/not in the curated set: "bogus-id"/)).toBeTruthy();
    // coverage is described as a limit of the curated mapping, never as a posture finding
    expect(screen.getByText(/CSF reached by this curated mapping: DE, PR/)).toBeTruthy();
    expect(screen.getByText(/CSF not reached: GV, ID, RS, RC/)).toBeTruthy();
    expect(screen.getByText(/NOT an assessment of your defenses/)).toBeTruthy();
    expect(screen.getByText(/generated: false/)).toBeTruthy();
  });
});
