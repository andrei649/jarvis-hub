// @ts-nocheck
/* H259 — the Settings panel marks a setting that differs from its declared default and
   puts it back on the next save; a reset (one category, or every category) shows what it
   would change before its second step, keeps the secrets, and the latest reset can be
   undone. fetch is mocked. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup, within } from '@testing-library/react';
import { SettingsPanel } from '../gap';

let calls;
let resets;
let undoReply;

function reply(status, body) {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) };
}

const SETTINGS = {
  system: [{ key: 'log_level', value: 'DEBUG', default: 'INFO', source: 'set', label: 'Log level', kind: 'select', opts: ['INFO', 'DEBUG'] },
           { key: 'log_to_file', value: false, default: false, source: 'default', label: 'Write the log to a file', kind: 'toggle' }],
  plugins: [{ key: 'tuya_secret', value: '', source: 'default', label: 'Tuya secret', kind: 'text' }],
};

beforeEach(() => {
  cleanup();
  try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'admin-secret'); } catch { /* ignore */ }
  calls = [];
  resets = [];
  undoReply = null;
  global.fetch = vi.fn(async (url, init = {}) => {
    const u = String(url).replace(/^https?:\/\/[^/]+/, '');
    const method = init.method || 'GET';
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ method, url: u, body });
    if (u === '/api/admin/settings') return reply(200, SETTINGS);
    if (u === '/api/admin/settings/resets') return reply(200, { resets });
    if (u === '/api/admin/settings/system' && method === 'PUT') return reply(200, { ok: true, updated: 1 });
    if (u === '/api/admin/settings/system/reset') {
      if (body?.dry_run) return reply(200, { dry_run: true, category: 'system', changes: [{ setting: 'system.log_level', from: 'DEBUG', to: 'INFO' }], kept: [], overridden: [] });
      resets = [{ id: 7, at: 1790000000, scope: 'system', settings: ['system.log_level'], undone: false }];
      return reply(200, { ok: true, category: 'system', reset: ['log_level'], undo: 7, kept: [], overridden: [] });
    }
    if (u === '/api/admin/settings/reseed') {
      if (body?.dry_run) {
        return reply(200, { dry_run: true, kept: ['plugins.tuya_secret'], overridden: [],
          changes: [{ setting: 'system.log_level', from: 'DEBUG', to: 'INFO' }, { setting: 'llm.temperature', from: 1, to: 0.7 }] });
      }
      resets = [{ id: 8, at: 1790000000, scope: 'all', settings: ['llm.temperature', 'system.log_level'], undone: false }];
      return reply(200, { ok: true, reset: ['llm.temperature', 'system.log_level'], undo: 8, kept: ['plugins.tuya_secret'], overridden: [] });
    }
    if (u === '/api/admin/settings/undo') {
      if (undoReply) return undoReply();
      const done = resets[0];
      resets = resets.map((r) => ({ ...r, undone: true }));
      return reply(200, { ok: true, id: done.id, scope: done.scope, restored: ['system.log_level'],
        skipped: [{ setting: 'llm.temperature', reason: 'changed since the reset' }] });
    }
    return reply(404, { error: 'unexpected' });
  });
});

const ready = () => waitFor(() => expect(screen.getByText('Log level')).toBeTruthy());

describe('Settings defaults — H259', () => {
  it('marks a setting that differs from its default, and puts it back on the next save', async () => {
    render(<SettingsPanel />);
    await ready();
    const mark = screen.getByText('changed');
    expect(mark.getAttribute('title')).toBe('default: INFO');
    expect(screen.getAllByText('changed')).toHaveLength(1);                // log_to_file is the default
    fireEvent.click(screen.getByLabelText('put system.log_level back to its default'));
    expect(screen.queryByText('changed')).toBeNull();                      // the staged value is the default
    fireEvent.click(screen.getByText(/save 1 change/));
    await waitFor(() => expect(calls.some((c) => c.method === 'PUT')).toBe(true));
    expect(calls.find((c) => c.method === 'PUT').body).toEqual({ values: { log_level: 'INFO' } });
  });

  it('never marks or offers a default for a setting that carries none (a secret)', async () => {
    render(<SettingsPanel />);
    await ready();
    expect(screen.queryByLabelText('put plugins.tuya_secret back to its default')).toBeNull();
  });
});

describe('Settings resets — H259', () => {
  it('a category reset shows what it would change before its second step', async () => {
    render(<SettingsPanel />);
    await ready();
    fireEvent.click(screen.getByLabelText('reset system'));
    await waitFor(() => expect(screen.getByText('system.log_level: DEBUG → INFO')).toBeTruthy());
    expect(calls.filter((c) => c.url.endsWith('/reset')).map((c) => c.body)).toEqual([{ dry_run: true }]);
    fireEvent.click(screen.getByLabelText('confirm reset system'));
    await waitFor(() => expect(screen.getByText(/reset 1 · can be undone/)).toBeTruthy());
    expect(calls.filter((c) => c.url.endsWith('/reset')).map((c) => c.body)).toEqual([{ dry_run: true }, {}]);
    await waitFor(() => expect(screen.getByText(/last reset: system · 1 setting/)).toBeTruthy());
  });

  it('resets every category after a preview that names the kept secrets', async () => {
    render(<SettingsPanel />);
    await ready();
    fireEvent.click(screen.getByText('reset every category…'));
    await waitFor(() => expect(screen.getByText(/2 settings would change/)).toBeTruthy());
    expect(screen.getByText('llm.temperature: 1 → 0.7')).toBeTruthy();
    expect(screen.getByText(/1 secret kept/)).toBeTruthy();
    fireEvent.click(screen.getByText('reset them to defaults'));
    await waitFor(() => expect(screen.getByText(/reset 2 settings · can be undone/)).toBeTruthy());
    expect(calls.filter((c) => c.url === '/api/admin/settings/reseed').map((c) => c.body)).toEqual([{ dry_run: true }, {}]);
    await waitFor(() => expect(screen.getByText(/last reset: every category · 2 settings/)).toBeTruthy());
  });

  it('undoes the latest reset after asking, and names what it left as it was', async () => {
    resets = [{ id: 7, at: 1790000000, scope: 'system', settings: ['system.log_level', 'llm.temperature'], undone: false }];
    render(<SettingsPanel />);
    await waitFor(() => expect(screen.getByText(/last reset: system · 2 settings/)).toBeTruthy());
    fireEvent.click(screen.getByText('undo…'));
    expect(calls.some((c) => c.url === '/api/admin/settings/undo')).toBe(false);
    fireEvent.click(screen.getByText('undo the reset'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('restored 1'));
    expect(screen.getByRole('status').textContent).toContain('llm.temperature (changed since the reset)');
    expect(calls.find((c) => c.url === '/api/admin/settings/undo').body).toEqual({});
    await waitFor(() => expect(screen.queryByText('undo…')).toBeNull());   // nothing left to undo
  });

  it('offers the newest reset first', async () => {
    resets = [{ id: 9, at: 1790000000, scope: 'all', settings: ['a.b', 'c.d', 'e.f'], undone: false },
              { id: 8, at: 1780000000, scope: 'system', settings: ['system.log_level'], undone: true }];
    render(<SettingsPanel />);
    await waitFor(() => expect(screen.getByText(/last reset: every category · 3 settings/)).toBeTruthy());
  });

  it('shows no undo when the latest reset was already undone, and a refused undo says why', async () => {
    resets = [{ id: 7, at: 1790000000, scope: 'system', settings: ['system.log_level'], undone: true }];
    const { unmount } = render(<SettingsPanel />);
    await ready();
    await waitFor(() => expect(calls.some((c) => c.url === '/api/admin/settings/resets')).toBe(true));
    expect(screen.queryByText('undo…')).toBeNull();
    unmount();
    resets = [{ id: 9, at: 1790000000, scope: 'system', settings: ['system.log_level'], undone: false }];
    undoReply = () => reply(404, { error: 'nothing to undo' });
    render(<SettingsPanel />);
    await waitFor(() => expect(screen.getByText('undo…')).toBeTruthy());
    fireEvent.click(screen.getByText('undo…'));
    fireEvent.click(screen.getByText('undo the reset'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('nothing to undo'));
  });
});
