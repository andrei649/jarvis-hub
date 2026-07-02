// @ts-nocheck
/* 0.37 — the Console ProvenancePanel reads the ingestion-provenance ledger
   (GET /api/ingestion/provenance, admin) and renders recent records + by-source
   stats. fetch is mocked (like media-gallery-panel.test.tsx). Asserts the wiring,
   record rows, and the honesty banner when the ledger is disabled (flag off). */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { ProvenancePanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('ProvenancePanel — the ingestion provenance read surface is live', () => {
  it('GETs /api/ingestion/provenance and renders records + by-source stats', async () => {
    const fn = mockFetch({
      enabled: true,
      stats: { total: 2, runs: 1, by_source: { facebook: 1, whatsapp: 1 } },
      records: [
        { id: 'pv-1', source: 'facebook', phase: 'parse', content_hash: 'deadbeefcafe' },
        { id: 'pv-2', source: 'whatsapp', phase: 'parse', content_hash: 'feedface0001' },
      ],
    });
    render(<ProvenancePanel />);
    await waitFor(() => expect(screen.getByText('facebook')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/ingestion/provenance'))).toBe(true);
    expect(screen.getByText('1 facebook')).toBeTruthy();
    expect(screen.getByText('LIVE')).toBeTruthy(); // TASK-2 tail: per-panel honesty chip
  });

  it('shows the honesty banner when the ledger is disabled (flag off)', async () => {
    mockFetch({ enabled: false, records: [], stats: { total: 0, runs: 0, by_source: {} } });
    render(<ProvenancePanel />);
    await waitFor(() => expect(screen.getByText(/JARVIS_PROVENANCE is on/)).toBeTruthy());
    expect(screen.getByText('SEED')).toBeTruthy();
  });
});
