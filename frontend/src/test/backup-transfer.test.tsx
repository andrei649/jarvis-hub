// @ts-nocheck
/* H162 — the Backup panel restores (through a card), downloads, uploads and lists checkpoints.
   fetch is mocked per URL. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { BackupPanel } from '../gap';
import { restoreQueuedNote } from '../panels/backup-transfer';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

const NAME = 'jarvis-backup-20261111T000000_000000Z_abcdef.tar.gz';

function route(handlers) {
  const fn = vi.fn(async (url, init) => {
    const u = String(url);
    for (const [key, h] of handlers) {
      if (u.includes(key) && (!h.method || h.method === (init?.method || 'GET'))) {
        const out = typeof h.reply === 'function' ? h.reply(u, init) : h.reply;
        return { ok: (out.status || 200) < 400, status: out.status || 200, json: async () => out.body,
                 blob: async () => new Blob(['archive-bytes']) };
      }
    }
    return { ok: true, status: 200, json: async () => ({ backups: [{ name: NAME, bytes: 2048 }] }) };
  });
  global.fetch = fn;
  return fn;
}

const calls = (fn, part, method) => fn.mock.calls.filter((c) => String(c[0]).includes(part)
  && (c[1]?.method || 'GET') === method);

describe('BackupPanel — H162 restore, download, upload, checkpoints', () => {
  it('asks for a restore only after the typed RESTORE confirmation and says a card waits', async () => {
    const fn = route([['/api/admin/backup/restore', { method: 'POST', reply: { status: 202, body: { pending: 41, restart: 'self' } } }]]);
    render(<BackupPanel />);
    fireEvent.click(await screen.findByLabelText(`restore ${NAME}`));
    const ask = await screen.findByText('ask to restore');
    fireEvent.click(ask);
    expect(calls(fn, '/api/admin/backup/restore', 'POST')).toHaveLength(0);
    fireEvent.change(screen.getByPlaceholderText('RESTORE'), { target: { value: 'RESTORE' } });
    fireEvent.click(screen.getByText('ask to restore'));
    await waitFor(() => expect(calls(fn, '/api/admin/backup/restore', 'POST')).toHaveLength(1));
    expect(JSON.parse(calls(fn, '/api/admin/backup/restore', 'POST')[0][1].body)).toEqual({ name: NAME, replace_credentials: false });
    await waitFor(() => expect(screen.getByText(/card #41 in the decision inbox/)).toBeTruthy());
  });

  it('shows why a restore was refused (the drill failed)', async () => {
    route([['/api/admin/backup/restore', { method: 'POST', reply: { status: 422, body: { error: 'the backup failed its restore drill', verify: { ok: false, problem: 'manifest missing' } } } }]]);
    render(<BackupPanel />);
    fireEvent.click(await screen.findByLabelText(`restore ${NAME}`));
    fireEvent.change(await screen.findByPlaceholderText('RESTORE'), { target: { value: 'RESTORE' } });
    fireEvent.click(screen.getByText('ask to restore'));
    await waitFor(() => expect(screen.getByText(/restore not asked · .*manifest missing/)).toBeTruthy());
  });

  it('shows a staged restore and withdraws it with DELETE after a confirm', async () => {
    const fn = route([
      ['/api/admin/backup/restore', { method: 'DELETE', reply: { body: { ok: true, cancelled: NAME } } }],
      ['/api/admin/backup/checkpoints', { reply: { body: { ok: true, items: [] } } }],
      ['/api/admin/backup', { reply: { body: { backups: [], pending_restore: { name: NAME, state: 'waiting' } } } }],
    ]);
    render(<BackupPanel />);
    await waitFor(() => expect(screen.getByText(/applied at the next hub start/)).toBeTruthy());
    fireEvent.click(screen.getByText('withdraw'));
    fireEvent.click(await screen.findByText('confirm withdraw'));
    await waitFor(() => expect(calls(fn, '/api/admin/backup/restore', 'DELETE')).toHaveLength(1));
    await waitFor(() => expect(screen.getByText(/withdrew the staged restore/)).toBeTruthy());
  });

  it('downloads with the browser itself (no Blob) when no header token is needed', async () => {
    const clicked: string[] = [];
    const orig = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function () { clicked.push(this.getAttribute('href') || ''); };
    URL.createObjectURL = vi.fn(() => 'blob:x');
    try {
      const fn = route([]);
      render(<BackupPanel />);
      fireEvent.click(await screen.findByLabelText(`download ${NAME}`));
      await waitFor(() => expect(screen.getByText(`download of ${NAME} started in your browser`)).toBeTruthy());
      expect(clicked.some((h) => h.includes('/api/admin/backup/download') && h.includes(encodeURIComponent(NAME)))).toBe(true);
      expect(calls(fn, '/api/admin/backup/download', 'GET')).toHaveLength(0);   // never fetched into memory
      expect(URL.createObjectURL).not.toHaveBeenCalled();
    } finally { HTMLAnchorElement.prototype.click = orig; }
  });

  it('with a header token and no streaming API, refuses instead of buffering', async () => {
    localStorage.setItem('hud.admin_token', 'adm');
    const fn = route([]);
    render(<BackupPanel />);
    fireEvent.click(await screen.findByLabelText(`download ${NAME}`));
    await waitFor(() => expect(screen.getByText(/not downloaded · .*cannot stream/)).toBeTruthy());
    expect(calls(fn, '/api/admin/backup/download', 'GET')).toHaveLength(0);
  });

  it('with a header token, streams the body into the file the owner picked', async () => {
    localStorage.setItem('hud.admin_token', 'adm');
    const piped: any[] = [];
    (globalThis as any).showSaveFilePicker = vi.fn(async () => ({ createWritable: async () => 'W' }));
    try {
      const fn = vi.fn(async (url) => {
        if (String(url).includes('/api/admin/backup/download')) {
          return { ok: true, status: 200, body: { pipeTo: async (w) => { piped.push(w); } } };
        }
        return { ok: true, status: 200, json: async () => ({ backups: [{ name: NAME, bytes: 2048 }] }) };
      });
      global.fetch = fn;
      render(<BackupPanel />);
      fireEvent.click(await screen.findByLabelText(`download ${NAME}`));
      await waitFor(() => expect(screen.getByText(`downloaded ${NAME}`)).toBeTruthy());
      expect(piped).toEqual(['W']);
      const call = fn.mock.calls.find((c) => String(c[0]).includes('/api/admin/backup/download'));
      expect(call[1].headers['X-Admin-Token']).toBe('adm');
    } finally { delete (globalThis as any).showSaveFilePicker; }
  });

  it('asks to replace credentials only when the owner ticks it', async () => {
    const fn = route([['/api/admin/backup/restore', { method: 'POST', reply: { status: 202, body: { pending: 5, restart: 'self' } } }]]);
    render(<BackupPanel />);
    fireEvent.click(await screen.findByLabelText(`also replace credentials and hooks from ${NAME}`));
    fireEvent.click(screen.getByLabelText(`restore ${NAME}`));
    expect(screen.getByText(/including the credentials/)).toBeTruthy();
    fireEvent.change(await screen.findByPlaceholderText('RESTORE'), { target: { value: 'RESTORE' } });
    fireEvent.click(screen.getByText('ask to restore'));
    await waitFor(() => expect(calls(fn, '/api/admin/backup/restore', 'POST')).toHaveLength(1));
    expect(JSON.parse(calls(fn, '/api/admin/backup/restore', 'POST')[0][1].body)).toEqual({ name: NAME, replace_credentials: true });
  });

  it('uploads a file as a raw PUT and reports the drilled, listed name', async () => {
    const fn = route([['/api/admin/backup/upload', { method: 'PUT', reply: { status: 201, body: { ok: true, name: 'jarvis-backup-upload-x.tar.gz' } } }]]);
    render(<BackupPanel />);
    const input = await screen.findByLabelText('upload a backup archive');
    const file = new File(['bytes'], 'offsite.tar.gz', { type: 'application/gzip' });
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(calls(fn, '/api/admin/backup/upload', 'PUT')).toHaveLength(1));
    expect(calls(fn, '/api/admin/backup/upload', 'PUT')[0][1].headers['Content-Type']).toBe('application/octet-stream');
    await waitFor(() => expect(screen.getByText(/listed as jarvis-backup-upload-x.tar.gz/)).toBeTruthy());
  });

  it('says why an upload was refused', async () => {
    route([['/api/admin/backup/upload', { method: 'PUT', reply: { status: 422, body: { error: 'failed_drill', verify: { ok: false, problem: 'no manifest' } } } }]]);
    render(<BackupPanel />);
    const input = await screen.findByLabelText('upload a backup archive');
    fireEvent.change(input, { target: { files: [new File(['x'], 'bad.tar.gz')] } });
    await waitFor(() => expect(screen.getByText(/bad.tar.gz not added · failed_drill · no manifest/)).toBeTruthy());
  });

  it('lists checkpoints read-only', async () => {
    route([
      ['/api/admin/backup/checkpoints', { reply: { body: { ok: true, items: [{ id: 'file:abc123', type: 'file', path: 'src/a.py' }] } } }],
      ['/api/admin/backup', { reply: { body: { backups: [] } } }],
    ]);
    render(<BackupPanel />);
    await waitFor(() => expect(screen.getByText('file:abc123')).toBeTruthy());
    expect(screen.getByText('src/a.py')).toBeTruthy();
    expect(screen.getByText('CHECKPOINTS')).toBeTruthy();
  });

  it('words the queued note by restart mode', () => {
    expect(restoreQueuedNote({ pending: 3, existing: true, restart: 'manual' }, 'a')).toMatch(/already waiting.*restart the hub after your accept/);
  });
});
