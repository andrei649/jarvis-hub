// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { AcquisitionPanel } from '../gap';

function response(payload) {
  return Promise.resolve({ ok: true, status: 200, json: async () => payload });
}

const status = {
  enabled: true,
  status: 'ready',
  reason: null,
  states: { missing: 1, installed: 1 },
  reuse: { reused: 1, generated: 1, blocked: 0, abandoned: 0, reuse_rate: 0.5 },
  packages: [{ name: 'acme_parser', version: '0.1.0', status: 'active', confidence: 0.1 }],
  audit: { status: 'healthy', events: 1, summarized_events: 0, chain_valid: true },
};

const events = {
  enabled: true,
  status: 'ready',
  events: [{ sequence: 7, event_type: 'install.committed', actor: 'acquired-package-store', status: 'installed', request_hash: 'a'.repeat(64), artifact_hash: 'b'.repeat(64), detail_hash: 'c'.repeat(64) }],
};

const REQUEST_ID = 'a1b2c3d4e5f60718293a4b5c6d7e8f90';

const requests = {
  enabled: true,
  requests: [{ request_id: REQUEST_ID, status: 'missing', agent_id: 'jarvis', reason: 'tool_not_allowed', occurrences: 2, updated_at: 1750000000.0 }],
};

beforeEach(() => {
  localStorage.clear();
  global.fetch = vi.fn((url) => {
    if (String(url).includes('/api/acquisition/status')) return response(status);
    if (String(url).includes('/api/acquisition/events')) return response(events);
    if (String(url).includes('/api/acquisition/ledger/export')) return response({ schema: 1, summary: { count: 2 }, events: [] });
    if (String(url).includes('/api/acquisition/requests')) return response(requests);
    if (String(url).includes('/drive')) return response({ status: 'proposed', proposal_id: 'p1', name: 'acme_parser', request_status: 'approval_pending' });
    if (String(url).includes('/revoke')) return response({ status: 'revoked', name: 'acme_parser' });
    if (String(url).includes('/rollback')) return response({ status: 'restored', name: 'acme_parser', version: '0.0.9' });
    if (String(url).includes('/ledger/purge')) return response({ status: 'purged', purged: 1, summarized_events: 3 });
    return response({});
  });
});

describe('AcquisitionPanel (H32.6)', () => {
  it('renders honest lifecycle, reuse, signed package, and hash-only audit state', async () => {
    render(<AcquisitionPanel />);
    await waitFor(() => expect(screen.getByText('acme_parser')).toBeTruthy());
    expect(screen.getByText(/reuse 50%/i)).toBeTruthy();
    expect(screen.getByText(/missing · 1/i)).toBeTruthy();
    expect(screen.getByText(/install.committed/i)).toBeTruthy();
    expect(screen.getByText(/chain verified/i)).toBeTruthy();
    expect(document.body.textContent).not.toContain('a'.repeat(64));
  });

  it('shows a truthful default-off state and no lifecycle controls', async () => {
    global.fetch = vi.fn((url) => String(url).includes('/status')
      ? response({ ...status, enabled: false, status: 'disabled', reason: 'acquisition_disabled', states: {}, packages: [], audit: { status: 'disabled', events: 0, summarized_events: 0, chain_valid: true } })
      : response({ enabled: false, status: 'disabled', events: [] }));
    render(<AcquisitionPanel />);
    await waitFor(() => expect(screen.getByText(/capability acquisition is off/i)).toBeTruthy());
    expect(screen.queryByRole('button', { name: /revoke acme_parser/i })).toBeNull();
  });

  it('keeps revoke, rollback, export, and destructive purge in the admin zone', async () => {
    localStorage.setItem('hud.admin_token', 'owner-token');
    render(<AcquisitionPanel />);
    await waitFor(() => expect(screen.getByText('acme_parser')).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: /revoke acme_parser/i }));
    await waitFor(() => expect(screen.getByText(/revoked · acme_parser/i)).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /rollback acme_parser/i }));
    await waitFor(() => expect(screen.getByText(/restored · acme_parser/i)).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /export acquisition ledger/i }));
    await waitFor(() => expect(screen.getByText(/export ready · 2 summarized events/i)).toBeTruthy());

    const purge = screen.getByLabelText('acquisition purge confirmation');
    fireEvent.change(purge, { target: { value: 'PURGE ACQUISITION DETAIL' } });
    fireEvent.click(screen.getByRole('button', { name: /purge acquisition detail/i }));
    await waitFor(() => expect(screen.getByText(/purged · 1 detailed events/i)).toBeTruthy());

    const adminCalls = vi.mocked(global.fetch).mock.calls.filter(([url]) => /revoke|rollback|ledger/.test(String(url)));
    expect(adminCalls).toHaveLength(4);
    for (const [, options] of adminCalls) expect(options.headers['X-Admin-Token']).toBe('owner-token');
  });
});

describe('AcquisitionPanel · open capability gaps (DRA-38)', () => {
  it('lists the drive-eligible gaps and drives one', async () => {
    localStorage.setItem('hud.admin_token', 'owner-token');
    render(<AcquisitionPanel />);
    await waitFor(() => expect(screen.getByText(/open capability gaps/i)).toBeTruthy());
    expect(screen.getByText(REQUEST_ID.slice(0, 8))).toBeTruthy();
    expect(screen.getByText(/tool_not_allowed/)).toBeTruthy();
    expect(screen.getByText(/×2/)).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: new RegExp(`Drive ${REQUEST_ID}`, 'i') }));
    await waitFor(() => expect(screen.getByText(/proposed · acme_parser/i)).toBeTruthy());

    const drive = vi.mocked(global.fetch).mock.calls.find(([url]) => String(url).includes('/drive'));
    expect(drive).toBeTruthy();
    expect(String(drive[0])).toBe(`/api/acquisition/${REQUEST_ID}/drive`);
    expect(drive[1].method).toBe('POST');
    expect(JSON.parse(drive[1].body)).toEqual({ entrypoint: 'run', cases: [{ input: {}, expected: null }] });
    expect(drive[1].headers['X-Admin-Token']).toBe('owner-token');
  });

  it('refuses invalid contract-case JSON before touching the network', async () => {
    localStorage.setItem('hud.admin_token', 'owner-token');
    render(<AcquisitionPanel />);
    await waitFor(() => expect(screen.getByText(/open capability gaps/i)).toBeTruthy());

    fireEvent.change(screen.getByLabelText('acquisition drive contract cases'), { target: { value: 'not json' } });
    fireEvent.click(screen.getByRole('button', { name: new RegExp(`Drive ${REQUEST_ID}`, 'i') }));
    await waitFor(() => expect(screen.getByText(/refused · cases must be valid JSON/i)).toBeTruthy());
    expect(vi.mocked(global.fetch).mock.calls.filter(([url]) => String(url).includes('/drive'))).toHaveLength(0);
  });

  it('renders a 409 precondition refusal instead of reading as success', async () => {
    localStorage.setItem('hud.admin_token', 'owner-token');
    const base = global.fetch;
    global.fetch = vi.fn((url, options) => (String(url).includes('/drive')
      ? Promise.resolve({ ok: false, status: 409, json: async () => ({ status: 'refused' }) })
      : base(url, options)));
    render(<AcquisitionPanel />);
    await waitFor(() => expect(screen.getByText(/open capability gaps/i)).toBeTruthy());

    fireEvent.click(screen.getByRole('button', { name: new RegExp(`Drive ${REQUEST_ID}`, 'i') }));
    await waitFor(() => expect(screen.getByText(/refused · 409 · preconditions not met/i)).toBeTruthy());
    expect(screen.queryByText(/proposed/i)).toBeNull();
  });

  it('shows the empty state rather than a bare drive button', async () => {
    localStorage.setItem('hud.admin_token', 'owner-token');
    const base = global.fetch;
    global.fetch = vi.fn((url, options) => (String(url).includes('/api/acquisition/requests')
      ? response({ enabled: true, requests: [] })
      : base(url, options)));
    render(<AcquisitionPanel />);
    await waitFor(() => expect(screen.getByText(/no open capability gaps/i)).toBeTruthy());
    expect(screen.queryByRole('button', { name: /^Drive /i })).toBeNull();
  });

  it('hides the gap list and never fetches it without an admin token', async () => {
    render(<AcquisitionPanel />);
    await waitFor(() => expect(screen.getByText('acme_parser')).toBeTruthy());
    expect(screen.queryByText(/open capability gaps/i)).toBeNull();
    expect(screen.queryByRole('button', { name: new RegExp(`Drive ${REQUEST_ID}`, 'i') })).toBeNull();
    expect(vi.mocked(global.fetch).mock.calls.filter(([url]) => String(url).includes('/api/acquisition/requests'))).toHaveLength(0);
  });
});
