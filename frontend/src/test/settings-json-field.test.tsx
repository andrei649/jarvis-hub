// @ts-nocheck
/* H340 review — a JSON setting (skills.template_vars) is edited as JSON and saved parsed.
   It used to fall through to a text box and be saved as a string the hub ignored. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { SettingsPanel } from '../gap';

let puts;
beforeEach(() => {
  try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'admin'); } catch { /* ignore */ }
  puts = [];
  global.fetch = vi.fn(async (url, init = {}) => {
    const u = String(url);
    if (init.method === 'PUT') puts.push({ url: u, body: JSON.parse(init.body) });
    const body = u.includes('/api/admin/settings') && init.method !== 'PUT'
      ? { skills: [{ key: 'template_vars', label: 'Skill template variables', value: { team: 'ops' }, kind: 'json' }] }
      : u.includes('/api/help/docs') ? { docs: [] } : { ok: true, updated: 1 };
    return { ok: true, status: 200, json: async () => body };
  });
});

describe('SettingsPanel — a JSON setting', () => {
  it('shows the value as JSON and saves what the owner types parsed, not as a string', async () => {
    render(<SettingsPanel />);
    const box = await screen.findByLabelText('json value of template_vars');
    expect(box.value).toBe('{"team":"ops"}');
    fireEvent.change(box, { target: { value: '{"team": "ops", "region": "eu"}' } });
    fireEvent.click(screen.getByText(/save 1 change/));
    await waitFor(() => expect(puts.length).toBe(1));
    expect(puts[0].url).toContain('/api/admin/settings/skills');
    expect(puts[0].body).toEqual({ values: { template_vars: { team: 'ops', region: 'eu' } } });
  });

  it('sends text that is not JSON as typed, so the hub can say what is wrong', async () => {
    render(<SettingsPanel />);
    const box = await screen.findByLabelText('json value of template_vars');
    fireEvent.change(box, { target: { value: '{team: ops' } });
    fireEvent.click(screen.getByText(/save 1 change/));
    await waitFor(() => expect(puts.length).toBe(1));
    expect(puts[0].body).toEqual({ values: { template_vars: '{team: ops' } });
  });
});
