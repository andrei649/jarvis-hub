// @ts-nocheck
/* T-0.50 — the Console PublishReadinessPanel over POST /api/creative/publish/*.
   The rule under test is the governance one: this panel never publishes. It
   shows checks and, at best, "ready to REQUEST approval" — and it says so on
   screen so nobody reads a green checklist as "it went out". */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { PublishReadinessPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('PublishReadinessPanel — readiness without publishing', () => {
  it('POSTs the checklist and renders each check with its state', async () => {
    const fn = mockFetch({
      platform: 'youtube',
      checklist: [
        { id: 'platform.known', ok: true },
        { id: 'asset.valid', ok: false },
        { id: 'disclosure.confirmed', ok: false },
      ],
      violations: ['missing required field: thumbnail'],
    });
    render(<PublishReadinessPanel />);
    fireEvent.click(screen.getByText('check'));
    await waitFor(() => expect(screen.getByText('platform.known')).toBeTruthy());
    const post = fn.mock.calls.find((c) => String(c[0]).includes('/api/creative/publish/checklist'));
    expect(post).toBeTruthy();
    expect(screen.getByText('asset.valid')).toBeTruthy();
    expect(screen.getByText(/missing required field: thumbnail/)).toBeTruthy();
  });

  it('sends the manual confirmations the owner ticked', async () => {
    const fn = mockFetch({ checklist: [], violations: [] });
    render(<PublishReadinessPanel />);
    fireEvent.click(screen.getByText('rights'));
    fireEvent.click(screen.getByText('check'));
    await waitFor(() => {
      const post = fn.mock.calls.find((c) => String(c[0]).includes('/publish/checklist'));
      expect(JSON.parse(post[1].body).confirmations).toEqual({
        disclosure: false, rights: true, preview: false,
      });
    });
  });

  it('says "still not published" even when approval-ready', async () => {
    mockFetch({ checklist: [], violations: [], ready_for_approval: true, release_payload: { x: 1 } });
    render(<PublishReadinessPanel />);
    fireEvent.click(screen.getByText('package'));
    await waitFor(() => expect(screen.getByText(/still not published/)).toBeTruthy());
  });

  it('reports a withheld payload when not ready', async () => {
    mockFetch({ checklist: [], violations: [], ready_for_approval: false, release_payload: null });
    render(<PublishReadinessPanel />);
    fireEvent.click(screen.getByText('package'));
    await waitFor(() => expect(screen.getByText(/release payload withheld/)).toBeTruthy());
  });

  it('refuses invalid metadata JSON without calling the API', async () => {
    const fn = mockFetch({});
    render(<PublishReadinessPanel />);
    fireEvent.change(screen.getByPlaceholderText('metadata JSON'), { target: { value: '{not json' } });
    fireEvent.click(screen.getByText('check'));
    await waitFor(() => expect(screen.getByText(/not valid JSON/)).toBeTruthy());
    expect(fn.mock.calls.filter((c) => String(c[0]).includes('/publish/'))).toHaveLength(0);
  });

  it('always shows the never-uploads disclaimer', async () => {
    mockFetch({});
    render(<PublishReadinessPanel />);
    expect(screen.getByText(/never uploads/)).toBeTruthy();
  });
});
