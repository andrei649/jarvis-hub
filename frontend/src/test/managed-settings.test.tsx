// @ts-nocheck
/* G1 (H249/H267/H629) — Settings: a setting the administrator pinned shows its value and
   "managed by your administrator", with no edit box and no reset arrow; the rest of the
   category stays editable. The env-sources label names the managed layer. fetch is mocked. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, cleanup } from '@testing-library/react';
import { SettingsPanel } from '../gap';
import { hydrateAdminKeys } from '../api/live';

function reply(status, body) {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) };
}

const SETTINGS = {
  llm: [
    { key: 'cloud_fallback', value: 'never', default: 'on-demand', source: 'set', label: 'Cloud fallback', kind: 'text',
      managed: { source: '/etc/nerva/config.yaml', leaves: [] } },
    { key: 'backend_type', value: ['auto'], default: ['auto'], source: 'default', label: 'Backend', kind: 'tags' },
  ],
};

beforeEach(() => {
  cleanup();
  try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'admin-secret'); } catch { /* ignore */ }
  global.fetch = vi.fn(async (url) => {
    const u = String(url).replace(/^https?:\/\/[^/]+/, '');
    if (u === '/api/admin/settings') return reply(200, SETTINGS);
    if (u === '/api/admin/settings/resets') return reply(200, { resets: [] });
    return reply(404, { error: 'unexpected' });
  });
});

describe('Settings — managed (G1)', () => {
  it('a pinned setting is shown read-only and named as managed', async () => {
    render(<SettingsPanel />);
    await screen.findByText('Cloud fallback');
    const pinned = screen.getByTestId('managed-setting');
    expect(pinned.textContent).toContain('never');
    expect(pinned.textContent).toContain('managed by your administrator');
    expect(screen.queryByLabelText('value of cloud_fallback')).toBeNull();
    expect(screen.queryByLabelText('put llm.cloud_fallback back to its default')).toBeNull();
    expect(screen.getByLabelText('value of backend_type')).toBeTruthy();
  });

  it('the env sources name the managed layer', () => {
    const rows = hydrateAdminKeys({ OPENAI_API_KEY: 'sk-…' },
      { sources: [{ key: 'OPENAI_API_KEY', label: 'managed by your administrator', layer: 'managed', shadowed: ['user_env'] }] });
    expect(rows[0].source).toBe('managed by your administrator, overriding data-home .env');
  });
});
