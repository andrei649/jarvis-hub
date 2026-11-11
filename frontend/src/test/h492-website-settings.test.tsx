// @ts-nocheck
import { beforeEach, describe, expect, it, vi } from 'vitest';
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SettingsPanel } from '../gap';

const initial = { enabled: false, domains: [], shared_files: [] };
const selected = { enabled: true, domains: ['blocked.example'], shared_files: [] };
let writes;

function routes(refuse = false) {
  global.fetch = vi.fn(async (url, init = {}) => {
    if (init.method === 'PUT') {
      writes.push({ url: String(url), body: JSON.parse(init.body), headers: init.headers });
      if (refuse) return { ok: false, status: 422,
        json: async () => ({ error: 'website_blocklist.domains must be a list' }),
        text: async () => 'website_blocklist.domains must be a list' };
      return { ok: true, status: 200, json: async () => ({ updated: 1 }) };
    }
    const body = String(url).includes('/api/admin/settings')
      ? { security: [{ key: 'website_blocklist', kind: 'json', value: initial,
          default: initial, label: 'Blocked websites (domains and shared files)' }] }
      : { docs: [] };
    return { ok: true, status: 200, json: async () => body };
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  localStorage.setItem('hud.admin_token', 'owner-h492');
  writes = [];
});

describe('Owner website policy in the existing Settings panel', () => {
  it('sends the complete policy as JSON with the owner credential', async () => {
    routes();
    render(<SettingsPanel />);
    const box = await screen.findByLabelText('json value of website_blocklist');
    expect(JSON.parse(box.value)).toEqual(initial);
    fireEvent.change(box, { target: { value: JSON.stringify(selected) } });
    fireEvent.click(screen.getByText(/save 1 change/));
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0].url).toContain('/api/admin/settings/security');
    expect(writes[0].body).toEqual({ values: { website_blocklist: selected } });
    expect(writes[0].headers['X-Admin-Token']).toBe('owner-h492');
  });

  it('retains the draft and shows a refused policy without claiming it was saved', async () => {
    routes(true);
    render(<SettingsPanel />);
    const box = await screen.findByLabelText('json value of website_blocklist');
    const invalid = JSON.stringify({ ...selected, domains: 'bad' });
    fireEvent.change(box, { target: { value: invalid } });
    fireEvent.click(screen.getByText(/save 1 change/));
    await waitFor(() => expect(screen.getByText(/website_blocklist.domains must be a list/)).toBeTruthy());
    expect(box.value).toBe(invalid);
    expect(screen.getByText(/save 1 change/)).toBeTruthy();
    expect(writes).toHaveLength(1);
  });
});
