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

  it('shows a null owner list as null and saves an explicit owner list as JSON', async () => {
    global.fetch = vi.fn(async (url, init = {}) => {
      const u = String(url);
      if (init.method === 'PUT') puts.push({ url: u, body: JSON.parse(init.body) });
      const body = u.includes('/api/admin/settings') && init.method !== 'PUT'
        ? { autonomy: [{ key: 'owner_user_ids', label: 'Telegram owners (JSON user ID list; null uses the allowed sender list)',
                         value: null, kind: 'json' }] }
        : u.includes('/api/help/docs') ? { docs: [] } : { ok: true, updated: 1 };
      return { ok: true, status: 200, json: async () => body };
    });
    render(<SettingsPanel />);
    const box = await screen.findByLabelText('json value of owner_user_ids');
    expect(box.value).toBe('null');
    expect(screen.getByText(/null uses the allowed sender list/)).toBeTruthy();
    fireEvent.change(box, { target: { value: '[42]' } });
    fireEvent.click(screen.getByText(/save 1 change/));
    await waitFor(() => expect(puts.length).toBe(1));
    expect(puts[0].body).toEqual({ values: { owner_user_ids: [42] } });
  });

  it('saves JSON null when the owner restores legacy allowlist fallback', async () => {
    global.fetch = vi.fn(async (url, init = {}) => {
      const u = String(url);
      if (init.method === 'PUT') puts.push({ url: u, body: JSON.parse(init.body) });
      const body = u.includes('/api/admin/settings') && init.method !== 'PUT'
        ? { autonomy: [{ key: 'owner_user_ids', label: 'Telegram owners (JSON user ID list; null uses the allowed sender list)',
                         value: [42], kind: 'json' }] }
        : u.includes('/api/help/docs') ? { docs: [] } : { ok: true, updated: 1 };
      return { ok: true, status: 200, json: async () => body };
    });
    render(<SettingsPanel />);
    const box = await screen.findByLabelText('json value of owner_user_ids');
    expect(box.value).toBe('[42]');
    fireEvent.change(box, { target: { value: 'null' } });
    fireEvent.click(screen.getByText(/save 1 change/));
    await waitFor(() => expect(puts.length).toBe(1));
    expect(puts[0].body).toEqual({ values: { owner_user_ids: null } });
  });

  it('shows a setting only its own route writes, with where to change it, and no edit box (review-H329 F1)', async () => {
    global.fetch = vi.fn(async (url, init = {}) => {
      const u = String(url);
      const body = u.includes('/api/admin/settings')
        ? { skills: [{ key: 'channel_disabled', label: 'Skills switched off on one channel', value: { telegram: ['Spotify'] },
                       kind: 'json', default: {}, written_by: 'Console → Trust → Skill Switches (POST /api/skills/switch)' }] }
        : { docs: [] };
      return { ok: true, status: 200, json: async () => body };
    });
    render(<SettingsPanel />);
    await waitFor(() => expect(screen.getByText(/change it in Console → Trust → Skill Switches/)).toBeTruthy());
    expect(screen.getByText('{"telegram":["Spotify"]}')).toBeTruthy();
    expect(screen.queryByLabelText('json value of channel_disabled')).toBeNull();
    expect(screen.queryByLabelText('put skills.channel_disabled back to its default')).toBeNull();
  });

  it('says when the hub refuses the save, with its reason, and keeps the edit (review-H318b n-4)', async () => {
    global.fetch = vi.fn(async (url, init = {}) => {
      const u = String(url);
      if (init.method === 'PUT') {
        puts.push({ url: u, body: JSON.parse(init.body) });
        return { ok: false, status: 422, json: async () => ({ error: 'template_vars: "team" must be text' }),
                 text: async () => '{"error": "template_vars: \\"team\\" must be text"}' };
      }
      const body = u.includes('/api/admin/settings')
        ? { skills: [{ key: 'template_vars', label: 'Skill template variables', value: { team: 'ops' }, kind: 'json' }] }
        : { docs: [] };
      return { ok: true, status: 200, json: async () => body };
    });
    render(<SettingsPanel />);
    const box = await screen.findByLabelText('json value of template_vars');
    fireEvent.change(box, { target: { value: '{"team": 1}' } });
    fireEvent.click(screen.getByText(/save 1 change/));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/not saved · skills: template_vars/));
    expect(screen.getByText(/save 1 change/)).toBeTruthy();          // the edit is kept to fix and resend
  });
});
