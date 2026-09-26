// @ts-nocheck
/* H157 — SettingsPanel searches every category, resets one category (after asking), and
   moves a configuration as JSON: export names what the hub left out, import previews
   the hub's dry run and applies it only on a second step. fetch is mocked. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import { SettingsPanel } from '../gap';
import { refusalList, resetPath, settingMatches } from '../panels/settings-tools';

let calls;
let importReply;

function reply(status, body) {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) };
}

const SETTINGS = {
  system: [{ key: 'log_level', value: 'INFO', label: 'Log level', kind: 'select', opts: ['INFO', 'DEBUG'] },
           { key: 'log_to_file', value: false, label: 'Write the log to a file', kind: 'toggle' }],
  llm: [{ key: 'openrouter_order', value: [], label: 'OpenRouter provider order', kind: 'tags' }],
};

beforeEach(() => {
  cleanup();
  try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'admin-secret'); } catch { /* ignore */ }
  calls = [];
  importReply = null;
  global.fetch = vi.fn(async (url, init = {}) => {
    const u = String(url);
    const method = init.method || 'GET';
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ method, url: u, body, admin: (init.headers || {})['X-Admin-Token'] });
    if (u.endsWith('/api/admin/settings')) return reply(200, SETTINGS);
    if (u.endsWith('/api/admin/settings/export')) {
      return reply(200, { format: 'nerva-settings/1', settings: { system: { log_level: 'INFO' } },
                         excluded: [{ setting: 'plugins.tuya_secret', reason: 'a secret' }] });
    }
    if (u.endsWith('/api/admin/settings/import')) {
      if (importReply) return importReply(body);
      if (body.dry_run) return reply(200, { dry_run: true, count: 1, changes: [{ setting: 'system.log_level', from: 'INFO', to: 'DEBUG' }] });
      return reply(200, { ok: true, updated: 1, changes: [] });
    }
    if (u.endsWith('/reset')) return reply(200, { ok: true, category: 'system', reset: ['log_level'] });
    return reply(404, { error: 'unexpected' });
  });
});

describe('settingMatches', () => {
  it('matches category.key and the label, case-blind; empty matches all', () => {
    const it0 = { key: 'log_level', label: 'Log level' };
    expect(settingMatches('system', it0, '')).toBe(true);
    expect(settingMatches('system', it0, 'SYSTEM.LOG')).toBe(true);
    expect(settingMatches('system', it0, 'log level')).toBe(true);
    expect(settingMatches('system', it0, 'openrouter')).toBe(false);
    expect(resetPath('a b')).toBe('/api/admin/settings/a%20b/reset');
    expect(refusalList({ body: { details: ['x: bad', 'y: bad'] } })).toEqual(['x: bad', 'y: bad']);
    expect(refusalList({ body: { error: 'nope' } })).toEqual(['nope']);
  });
});

describe('SettingsPanel — H157 tools', () => {
  it('searches across every category', async () => {
    render(<SettingsPanel />);
    await waitFor(() => expect(screen.getByText('Log level')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('search settings'), { target: { value: 'openrouter' } });
    expect(screen.queryByText('Log level')).toBeNull();
    expect(screen.getByText('OpenRouter provider order')).toBeTruthy();
    expect(screen.getByText('1 match')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('search settings'), { target: { value: 'zzz' } });
    expect(screen.getByText(/no setting matches/)).toBeTruthy();
  });

  it('resets one category only after a second click, with the admin credential', async () => {
    render(<SettingsPanel />);
    await waitFor(() => expect(screen.getByText('Log level')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('reset system'));
    // H259: arming asks the hub for a dry run; nothing is reset before the second click
    expect(calls.filter((c) => c.url.endsWith('/reset')).map((c) => c.body)).toEqual([{ dry_run: true }]);
    fireEvent.click(screen.getByLabelText('confirm reset system'));
    await waitFor(() => expect(screen.getByText('reset 1')).toBeTruthy());
    const call = calls.find((c) => c.url.endsWith('/api/admin/settings/system/reset'));
    expect(call.method).toBe('POST');
    expect(call.admin).toBe('admin-secret');
  });

  it('exports and names what the hub left out', async () => {
    render(<SettingsPanel />);
    await waitFor(() => expect(screen.getByText('Log level')).toBeTruthy());
    fireEvent.click(screen.getByText('⬇ export JSON'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('plugins.tuya_secret (a secret)'));
    expect(screen.getByRole('status').textContent).toContain('exported 1 settings');
    expect(calls.find((c) => c.url.endsWith('/export')).admin).toBe('admin-secret');
  });

  it('previews an import with a dry run, then applies on a second step', async () => {
    render(<SettingsPanel />);
    await waitFor(() => expect(screen.getByText('Log level')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('settings document'),
      { target: { value: '{"settings": {"system": {"log_level": "DEBUG"}}}' } });
    fireEvent.click(screen.getByText('preview import'));
    await waitFor(() => expect(screen.getByTestId('import-change').textContent).toBe('system.log_level: INFO → DEBUG'));
    const dry = calls.filter((c) => c.url.endsWith('/import'));
    expect(dry).toHaveLength(1);
    expect(dry[0].body).toEqual({ settings: { system: { log_level: 'DEBUG' } }, dry_run: true });
    fireEvent.click(screen.getByText('apply 1 change'));
    await waitFor(() => expect(screen.getByText('imported 1 setting')).toBeTruthy());
    const applied = calls.filter((c) => c.url.endsWith('/import'))[1];
    expect(applied.body).toEqual({ settings: { system: { log_level: 'DEBUG' } } });
    expect(applied.admin).toBe('admin-secret');
  });

  it('lists every reason the hub refused, and writes nothing', async () => {
    importReply = () => reply(422, { error: 'invalid settings', details: ['system.bogus: unknown setting', 'security.sandbox_temp_max_age_hours: expected a number of hours between 1 and 8760'] });
    render(<SettingsPanel />);
    await waitFor(() => expect(screen.getByText('Log level')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('settings document'), { target: { value: '{"settings": {}}' } });
    fireEvent.click(screen.getByText('preview import'));
    await waitFor(() => expect(screen.getAllByRole('alert')).toHaveLength(2));
    expect(screen.queryByText(/apply \d/)).toBeNull();
  });

  it('refuses text that is not JSON without calling the hub', async () => {
    render(<SettingsPanel />);
    await waitFor(() => expect(screen.getByText('Log level')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('settings document'), { target: { value: '{nope' } });
    fireEvent.click(screen.getByText('preview import'));
    expect(screen.getByRole('alert').textContent).toBe('the document is not JSON');
    expect(calls.some((c) => c.url.endsWith('/import'))).toBe(false);
  });

  it('says when an import changes nothing, and offers no apply', async () => {
    importReply = () => reply(200, { dry_run: true, count: 0, changes: [] });
    render(<SettingsPanel />);
    await waitFor(() => expect(screen.getByText('Log level')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('settings document'), { target: { value: '{"settings": {}}' } });
    fireEvent.click(screen.getByText('preview import'));
    await waitFor(() => expect(screen.getByText(/nothing to change/)).toBeTruthy());
    expect(screen.queryByText(/apply \d/)).toBeNull();
  });

  it('drops unsaved edits of a reset category, and names kept secrets and posture settings', async () => {
    const realFetch = global.fetch;
    global.fetch = vi.fn(async (url, init = {}) => {
      if (String(url).endsWith('/reset')) {
        calls.push({ method: init.method || 'GET', url: String(url) });
        return reply(200, { ok: true, category: 'system', reset: ['log_level'], kept: ['a_token'], overridden: ['recall_enabled'] });
      }
      return realFetch(url, init);
    });
    render(<SettingsPanel />);
    await waitFor(() => expect(screen.getByText('Log level')).toBeTruthy());
    fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'DEBUG' } });
    expect(screen.getByText(/save 1 change/)).toBeTruthy();
    fireEvent.click(screen.getByLabelText('reset system'));
    expect(screen.getByLabelText('confirm reset system').textContent).toContain('all 2 system settings');
    expect(document.activeElement).toBe(screen.getByLabelText('confirm reset system'));
    fireEvent.click(screen.getByLabelText('confirm reset system'));
    await waitFor(() => expect(screen.getByText(/kept 1 secret/)).toBeTruthy());
    expect(screen.getByText(/recall_enabled still set by the posture/)).toBeTruthy();
    expect(screen.queryByText(/save 1 change/)).toBeNull();
  });

  it('counts edits hidden by the search', async () => {
    render(<SettingsPanel />);
    await waitFor(() => expect(screen.getByText('Log level')).toBeTruthy());
    fireEvent.change(screen.getAllByRole('combobox')[0], { target: { value: 'DEBUG' } });
    fireEvent.change(screen.getByLabelText('search settings'), { target: { value: 'openrouter' } });
    expect(screen.getByText(/save 1 change \(1 hidden by the search\)/)).toBeTruthy();
  });

  it('never applies a pasted dry run, and holds the text while the hub answers', async () => {
    let answer;
    importReply = (body) => (body.dry_run ? new Promise((r) => { answer = () => r(reply(200, { dry_run: true, count: 1, changes: [{ setting: 'system.log_level', from: 'INFO', to: 'DEBUG' }] })); })
      : reply(200, { ok: true, updated: 1, changes: [{ setting: 'system.log_level' }] }));
    render(<SettingsPanel />);
    await waitFor(() => expect(screen.getByText('Log level')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('settings document'),
      { target: { value: '{"settings": {"system": {"log_level": "DEBUG"}}, "dry_run": true}' } });
    fireEvent.click(screen.getByText('preview import'));
    expect(screen.getByLabelText('settings document').disabled).toBe(true);
    answer();
    await waitFor(() => expect(screen.getByText('apply 1 change')).toBeTruthy());
    fireEvent.click(screen.getByText('apply 1 change'));
    await waitFor(() => expect(screen.getByText('imported 1 setting')).toBeTruthy());
    const applied = calls.filter((c) => c.url.endsWith('/import'))[1];
    expect(applied.body).toEqual({ settings: { system: { log_level: 'DEBUG' } } });
  });

  it('reaches the file import from the keyboard', async () => {
    render(<SettingsPanel />);
    await waitFor(() => expect(screen.getByText('Log level')).toBeTruthy());
    const button = screen.getByRole('button', { name: '⬆ import file' });
    const input = screen.getByLabelText('import settings file');
    const clicked = vi.fn();
    input.addEventListener('click', clicked);
    fireEvent.click(button);
    expect(clicked).toHaveBeenCalled();
  });
});
