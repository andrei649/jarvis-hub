// @ts-nocheck
/* HUD-v3 §4.3 — the Console Ambient Capture panel reads the opt-in capture stream
   (/api/capture + /api/capture/status), deletes a single item (DELETE
   /api/capture/{id}) and clears all (POST /api/capture/clear). fetch is mocked, like
   kernel-safety-panels.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { CapturePanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('CapturePanel — the privacy-forward capture stream is live', () => {
  it('GETs /api/capture and shows a redacted preview + its surface', async () => {
    const fn = mockFetch({
      enabled: true, surfaces: { clipboard: true }, records: [
        { id: 'r1', surface: 'clipboard', source: 'os', preview: 'meeting at 3pm…', created_at: 1 },
      ],
    });
    render(<CapturePanel />);
    await waitFor(() => expect(screen.getByText('meeting at 3pm…')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/capture'))).toBe(true);
    expect(screen.getByText('clipboard')).toBeTruthy();
  });

  it('DELETEs a single captured item when its ✕ is clicked (the privacy promise)', async () => {
    const fn = mockFetch({ enabled: true, records: [{ id: 'r9', surface: 'browser', preview: 'x' }] });
    render(<CapturePanel />);
    await waitFor(() => expect(screen.getByTitle('delete')).toBeTruthy());
    fireEvent.click(screen.getByTitle('delete'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/api/capture/r9') && c[1]?.method === 'DELETE')
    ).toBe(true));
  });

  it('clears all captured items (POST /api/capture/clear)', async () => {
    const fn = mockFetch({ enabled: true, records: [{ id: 'r1', surface: 's', preview: 'p' }] });
    render(<CapturePanel />);
    await waitFor(() => expect(screen.getByText('clear all')).toBeTruthy());
    fireEvent.click(screen.getByText('clear all'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/api/capture/clear') && c[1]?.method === 'POST')
    ).toBe(true));
  });

  it('shows the honest empty-state when nothing is captured', async () => {
    mockFetch({ enabled: false, records: [] });
    render(<CapturePanel />);
    await waitFor(() => expect(screen.getByText(/nothing captured/)).toBeTruthy());
  });
});
