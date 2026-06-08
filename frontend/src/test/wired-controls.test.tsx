// @ts-nocheck
/* Smoke test: wired controls POST to the right endpoint through their component.
   Renders BuildMode and clicks an INSTALL button → asserts the mocked fetch hit
   /api/skills/marketplace/install with the skill name. This exercises the full path
   (component → api/actions → client → fetch), not just the helper in isolation. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BuildMode, AutonomyMode } from '../modes2';
import { V2 } from '../data';

const t = V2.I18N.en;

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

describe('BuildMode — skill install is live', () => {
  it('clicking INSTALL POSTs the skill name to the marketplace install endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ ok: true, installed: 'x' }),
    });
    global.fetch = fetchMock as any;

    render(<BuildMode t={t} />);
    // First not-yet-installed skill in the seed corpus shows an enabled INSTALL button.
    const installBtns = screen.getAllByText('INSTALL').filter((b) => !(b as HTMLButtonElement).disabled);
    expect(installBtns.length).toBeGreaterThan(0);
    fireEvent.click(installBtns[0]);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) => String(c[0]).includes('/api/skills/marketplace/install'));
      expect(call).toBeTruthy();
      expect(call![1].method).toBe('POST');
      expect(JSON.parse(call![1].body)).toHaveProperty('name');
    });
  });
});

describe('AutonomyMode — global AUTO/ASK/OFF is live', () => {
  it('loads the current mode then POSTs the chosen mode to /autonomy/mode', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => Promise.resolve({
      ok: true, status: 200,
      json: async () => (String(url).includes('/autonomy/mode') ? { mode: 'auto' } : {}),
    }));
    global.fetch = fetchMock as any;

    render(<AutonomyMode t={t} />);
    // The three mode buttons enable once the initial GET resolves. Scope to role=button
    // (the per-agent reference rows render the same labels as spans, not buttons).
    await waitFor(() => {
      const off = screen.getByRole('button', { name: 'OFF' }) as HTMLButtonElement;
      expect(off.disabled).toBe(false);
    });
    fireEvent.click(screen.getByRole('button', { name: 'OFF' }));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        (c) => String(c[0]).includes('/autonomy/mode') && c[1] && c[1].method === 'POST',
      );
      expect(post).toBeTruthy();
      expect(JSON.parse(post![1].body)).toMatchObject({ mode: 'off' });
    });
  });
});
