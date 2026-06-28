// @ts-nocheck
/* HUD-v3 C6 — the Console Governance scorecard + Security posture panels read the real
   security endpoints (/api/security/governance open · /api/security/posture admin) and
   render the suite scores + packaged posture. fetch is mocked, like
   kernel-safety-panels.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { GovernancePanel, PosturePanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('GovernancePanel — the trust scorecard is live', () => {
  it('GETs /api/security/governance and shows the gate + per-suite scores', async () => {
    const fn = mockFetch({
      injection: { n: 6, passed: 6, score: 1.0 },
      harm: { n: 6, passed: 5, score: 0.83 },
      owasp: { n: 10, passed: 10, score: 1.0 },
      overall_score: 0.94, threshold: 0.9, pass: true,
    });
    render(<GovernancePanel />);
    await waitFor(() => expect(screen.getByText('gate: pass')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/security/governance'))).toBe(true);
    expect(screen.getByText('injection')).toBeTruthy();
    expect(screen.getByText('5/6')).toBeTruthy();   // the harm suite's partial pass
  });

  it('surfaces a FAILED gate honestly', async () => {
    mockFetch({
      injection: { n: 6, passed: 4, score: 0.66 }, harm: { n: 6, passed: 6, score: 1.0 },
      owasp: { n: 10, passed: 9, score: 0.9 }, overall_score: 0.85, threshold: 0.9, pass: false,
    });
    render(<GovernancePanel />);
    await waitFor(() => expect(screen.getByText('gate: FAIL')).toBeTruthy());
  });
});

describe('PosturePanel — packaged security posture is live', () => {
  it('GETs /api/security/posture and shows secrets/signing/sandbox state', async () => {
    const fn = mockFetch({
      secrets: { encrypted_at_rest: true, backend: 'fernet' },
      skills: { require_signed: true, total: 10, trusted: 9, untrusted: 1, untrusted_names: ['x'] },
      sandbox: { isolated: true, docker_available: true },
      guardrails: { mode: 'BLOCK' },
    });
    render(<PosturePanel />);
    await waitFor(() => expect(screen.getByText('guardrails: BLOCK')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/security/posture'))).toBe(true);
    expect(screen.getByText('encrypted')).toBeTruthy();
    expect(screen.getByText('fernet')).toBeTruthy();
    expect(screen.getByText('9/10 trusted')).toBeTruthy();
    expect(screen.getByText('isolated')).toBeTruthy();
  });
});
