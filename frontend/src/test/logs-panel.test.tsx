// @ts-nocheck
/* H145 — the Logs console panel tails the hub log through the admin-only
   GET /api/admin/logs: File / Level / Component / Lines filters, level colours,
   newest first, a 5 s auto-refresh with a LIVE badge, and an honest note when file
   logging is off. fetch is mocked. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup, act } from '@testing-library/react';
import { LOG_LEVELS, LogsPanel, REFRESH_MS, levelColor, logsPath } from '../panels/logs';
import { CONSOLE_PANELS } from '../console-routes';

let answer;
let status;
let calls;

function reply(code, body) {
  return { ok: code < 400, status: code, json: async () => body, text: async () => JSON.stringify(body) };
}

const ON = {
  enabled: true, path: '/data/logs/jarvis.log', file: 'jarvis.log', note: '', truncated: false, scanned_bytes: 900,
  limit: 200, components: ['jarvis.agent', 'jarvis.web'],
  files: [{ name: 'jarvis.log', size: 900, modified: 1 }, { name: 'jarvis.log.1', size: 10, modified: 0 }],
  entries: [
    { ts: '2026-09-25 10:00:00', level: 'INFO', component: 'jarvis.web', message: 'older', text: '2026-09-25 10:00:00  INFO  jarvis.web  older', cut: false },
    { ts: '2026-09-25 10:00:01', level: 'ERROR', component: 'jarvis.agent', message: 'newer', text: '2026-09-25 10:00:01  ERROR  jarvis.agent  newer\nTraceback: x', cut: false },
  ],
};

beforeEach(() => {
  cleanup();
  try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'admin-secret'); } catch { /* ignore */ }
  answer = ON;
  status = 200;
  calls = [];
  global.fetch = vi.fn(async (url, init = {}) => {
    calls.push({ url: String(url), admin: (init.headers || {})['X-Admin-Token'] });
    if ((init.headers || {})['X-Admin-Token'] !== 'admin-secret') return reply(401, { detail: 'admin token required' });
    return reply(status, answer);
  });
});

afterEach(() => { vi.useRealTimers(); });

const lastQuery = () => new URL(calls[calls.length - 1].url, 'http://x').searchParams;

describe('LogsPanel', () => {
  it('is registered in the console Observe group', () => {
    expect(CONSOLE_PANELS.find((p) => p.component === 'LogsPanel'))
      .toEqual({ id: 'logs', label: 'Logs', group: 'Observe', component: 'LogsPanel' });
  });

  it('builds a query with only the filters that narrow', () => {
    expect(logsPath({ level: 'ALL', lines: 200 })).toBe('/api/admin/logs?lines=200');
    expect(logsPath({ file: 'jarvis.log.1', level: 'ERROR', component: 'jarvis.agent', lines: 500 }))
      .toBe('/api/admin/logs?file=jarvis.log.1&level=ERROR&component=jarvis.agent&lines=500');
  });

  it('reads with the admin credential and shows records newest first, coloured by level', async () => {
    const { container } = render(<LogsPanel />);
    await waitFor(() => expect(screen.getByText(/newer/)).toBeTruthy());
    expect(calls[0].admin).toBe('admin-secret');
    const records = [...container.querySelectorAll('[data-testid="log-records"] pre')];
    expect(records.map((r) => r.getAttribute('data-level'))).toEqual(['ERROR', 'INFO']);
    expect(records[0].textContent).toContain('Traceback: x');
    expect(records[0].style.color).toBe(levelColor('ERROR'));
    expect(levelColor('WARNING')).toBe('var(--amber)');
    expect(levelColor('CRITICAL')).toBe('var(--red)');
    expect(levelColor('')).toBe('var(--ink)');
  });

  it('sends each filter to the hub', async () => {
    render(<LogsPanel />);
    await waitFor(() => expect(screen.getByText(/newer/)).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'WARNING' }));
    await waitFor(() => expect(lastQuery().get('level')).toBe('WARNING'));
    fireEvent.click(screen.getByRole('button', { name: '500' }));
    await waitFor(() => expect(lastQuery().get('lines')).toBe('500'));
    fireEvent.change(screen.getByLabelText('File'), { target: { value: 'jarvis.log.1' } });
    await waitFor(() => expect(lastQuery().get('file')).toBe('jarvis.log.1'));
    fireEvent.change(screen.getByLabelText('Component'), { target: { value: 'jarvis.agent' } });
    await waitFor(() => expect(lastQuery().get('component')).toBe('jarvis.agent'));
    expect(LOG_LEVELS).toEqual(['ALL', 'INFO', 'WARNING', 'ERROR']);
  });

  it('auto-refreshes every 5 s with a LIVE badge, and stops when switched off', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<LogsPanel />);
    await waitFor(() => expect(screen.getByText(/newer/)).toBeTruthy());
    expect(screen.queryByText('LIVE')).toBeNull();
    fireEvent.click(screen.getByLabelText('Auto-refresh every 5 s'));
    expect(screen.getByText('LIVE')).toBeTruthy();
    const before = calls.length;
    await act(async () => { vi.advanceTimersByTime(REFRESH_MS + 10); });
    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(before + 1));
    await act(async () => { vi.advanceTimersByTime(REFRESH_MS + 10); });
    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(before + 2));
    fireEvent.click(screen.getByLabelText('Auto-refresh every 5 s'));
    const after = calls.length;
    await act(async () => { vi.advanceTimersByTime(REFRESH_MS * 3); });
    expect(calls.length).toBe(after);
    expect(screen.queryByText('LIVE')).toBeNull();
  });

  it('says file logging is off instead of showing an empty log', async () => {
    answer = { enabled: false, files: [], file: null, entries: [], components: [], limit: 200,
               note: 'File logging is off, so there is no log file to read. Turn on system.log_to_file …' };
    render(<LogsPanel />);
    await waitFor(() => expect(screen.getByRole('note').textContent).toContain('system.log_to_file'));
    expect(screen.queryByText('No records match these filters.')).toBeNull();
  });

  it('says when nothing matches, and when only part of the file was read', async () => {
    answer = { ...ON, entries: [], truncated: true, scanned_bytes: 4 * 1024 * 1024 };
    render(<LogsPanel />);
    await waitFor(() => expect(screen.getByText('No records match these filters.')).toBeTruthy());
    expect(screen.getByText(/last 4096 KiB of the file were read/)).toBeTruthy();
  });

  it('names the admin token on a refusal and the hub’s reason on a bad filter', async () => {
    try { localStorage.setItem('hud.admin_token', 'wrong'); } catch { /* ignore */ }
    const { unmount } = render(<LogsPanel />);
    await waitFor(() => expect(screen.getByText(/needs the admin token/)).toBeTruthy());
    unmount();
    try { localStorage.setItem('hud.admin_token', 'admin-secret'); } catch { /* ignore */ }
    status = 400;
    answer = { error: 'bad_request', reason: 'file must be one of the listed log files' };
    render(<LogsPanel />);
    await waitFor(() => expect(screen.getByText(/file must be one of the listed log files/)).toBeTruthy());
  });

  it('renders a record as text, never as markup', async () => {
    answer = { ...ON, entries: [{ ts: 't', level: 'INFO', component: 'x', message: 'm', text: '<img src=x onerror=alert(1)>', cut: false }] };
    const { container } = render(<LogsPanel />);
    await waitFor(() => expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeTruthy());
    expect(container.querySelector('img')).toBeNull();
  });

  it('skips a tick while a read is in flight, and stops polling on a refusal', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let release;
    render(<LogsPanel />);
    await waitFor(() => expect(screen.getByText(/newer/)).toBeTruthy());
    global.fetch = vi.fn((url) => { calls.push({ url: String(url) }); return new Promise((r) => { release = () => r(reply(200, ON)); }); });
    fireEvent.click(screen.getByLabelText('Auto-refresh every 5 s'));
    const before = calls.length;
    await act(async () => { vi.advanceTimersByTime(REFRESH_MS * 4 + 10); });
    expect(calls.length).toBe(before + 1);
    await act(async () => { release(); });
  });

  it('does not poll while the page is hidden, and uses a 5 s interval', async () => {
    expect(REFRESH_MS).toBe(5000);
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<LogsPanel />);
    await waitFor(() => expect(screen.getByText(/newer/)).toBeTruthy());
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    try {
      fireEvent.click(screen.getByLabelText('Auto-refresh every 5 s'));
      const before = calls.length;
      await act(async () => { vi.advanceTimersByTime(REFRESH_MS * 3); });
      expect(calls.length).toBe(before);
    } finally {
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
    }
  });

  it('shows no old records after a refused filter, and goes back to the current log', async () => {
    render(<LogsPanel />);
    await waitFor(() => expect(screen.getByText(/newer/)).toBeTruthy());
    status = 400;
    answer = { error: 'bad_request', reason: 'file must be one of the listed log files' };
    fireEvent.change(screen.getByLabelText('File'), { target: { value: 'jarvis.log.1' } });
    await waitFor(() => expect(screen.getByText(/file must be one of the listed log files/)).toBeTruthy());
    expect(screen.queryByText(/newer/)).toBeNull();
    status = 200;
    answer = ON;
    await waitFor(() => expect(lastQuery().get('file')).toBeNull());
  });

  it('shows LIVE only while the hub writes its file', async () => {
    answer = { ...ON, enabled: false, note: 'File logging is off …' };
    render(<LogsPanel />);
    await waitFor(() => expect(screen.getByRole('note')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('Auto-refresh every 5 s'));
    expect(screen.queryByText('LIVE')).toBeNull();
  });

  it('names a 403 like a 401, dims DEBUG, and keeps a chosen component listed', async () => {
    expect(levelColor('DEBUG')).toBe('var(--ink-3)');
    render(<LogsPanel />);
    await waitFor(() => expect(screen.getByText(/newer/)).toBeTruthy());
    answer = { ...ON, components: ['jarvis.web'] };
    fireEvent.change(screen.getByLabelText('Component'), { target: { value: 'jarvis.agent' } });
    await waitFor(() => expect(lastQuery().get('component')).toBe('jarvis.agent'));
    const options = [...screen.getByLabelText('Component').querySelectorAll('option')].map((o) => o.value);
    expect(options).toContain('jarvis.agent');
    cleanup();
    status = 403;
    answer = { detail: 'forbidden' };
    render(<LogsPanel />);
    await waitFor(() => expect(screen.getByText(/needs the admin token/)).toBeTruthy());
  });
});
