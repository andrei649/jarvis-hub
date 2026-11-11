// @ts-nocheck
/* H496 — the Trust card lists the integrations shared with guests and changes a share
   through POST /api/security/credential-shares (admin). fetch is mocked. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { CredentialShares } from '../panels/credential-shares';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('CredentialShares', () => {
  it('says nothing is shared by default', () => {
    render(<CredentialShares value={{ kinds: [], shares: [] }} reload={() => {}} />);
    expect(screen.getByText('Nothing is shared.')).toBeTruthy();
  });

  it('shares one integration and stops sharing another', async () => {
    const fn = mockFetch({ integration: 'web_search:tavily', shared: true });
    const reload = vi.fn();
    render(<CredentialShares value={{ shares: [{ integration: 'mcp:github', note: 'issues' }] }} reload={reload} />);
    fireEvent.change(screen.getByLabelText('Credential kind'), { target: { value: 'web_search' } });
    fireEvent.change(screen.getByLabelText('Integration name'), { target: { value: 'tavily' } });
    fireEvent.click(screen.getByText('share with guests'));
    await waitFor(() => expect(reload).toHaveBeenCalled());
    const [url, init] = fn.mock.calls[0];
    expect(String(url)).toContain('/api/security/credential-shares');
    expect(JSON.parse(init.body)).toEqual({ integration: 'web_search:tavily', shared: true });
    fn.mockResolvedValue({ ok: true, status: 200, json: async () => ({ integration: 'mcp:github', shared: false }) });
    fireEvent.click(screen.getByLabelText('Stop sharing mcp:github'));
    await waitFor(() => expect(reload).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fn.mock.calls[1][1].body)).toEqual({ integration: 'mcp:github', shared: false });
  });
});
