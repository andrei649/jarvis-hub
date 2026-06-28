// @ts-nocheck
/* HUD-v3 (0.42 Security Skills) — the Console Security Skills panel browses the curated
   ATT&CK pack (/api/security-skills/tactics → /techniques?tactic=). fetch is mocked, like
   kernel-safety-panels.test.tsx. One payload serves both the tactics list and the
   per-tactic techniques (different keys). */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { SecuritySkillsPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('SecuritySkillsPanel — the ATT&CK knowledge browser is live', () => {
  it('GETs /api/security-skills/tactics and lists a tactic', async () => {
    const fn = mockFetch({
      tactics: [{ id: 'TA0001', name: 'Initial Access', summary: 'Get in.' }],
      techniques: [{ id: 'T1566', name: 'Phishing', tactics: ['TA0001'], summary: 'Malicious messages.' }],
    });
    render(<SecuritySkillsPanel />);
    await waitFor(() => expect(screen.getByText('TA0001 · Initial Access')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/security-skills/tactics'))).toBe(true);
  });

  it('expands a tactic and GETs its curated techniques', async () => {
    const fn = mockFetch({
      tactics: [{ id: 'TA0001', name: 'Initial Access', summary: 'Get in.' }],
      techniques: [{ id: 'T1566', name: 'Phishing', tactics: ['TA0001'], summary: 'Malicious messages.' }],
    });
    render(<SecuritySkillsPanel />);
    await waitFor(() => expect(screen.getByText('TA0001 · Initial Access')).toBeTruthy());
    fireEvent.click(screen.getByText('TA0001 · Initial Access'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/api/security-skills/techniques') && String(c[0]).includes('tactic=TA0001'))
    ).toBe(true));
    await waitFor(() => expect(screen.getByText('T1566 · Phishing')).toBeTruthy());
  });
});
