import React, { useState } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { SessionsModal } from '../../mobile/src/components/SessionsModal';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { records } from './support/storage';
const fs = vi.hoisted(() => ({ documentDirectory: 'file:///app/documents/' as string | null, writeAsStringAsync: vi.fn(async (_uri: string, _body: string) => {}) }));
vi.mock('expo-file-system/legacy', () => fs);
const config = { baseUrl: 'https://hub.test', token: 'user', adminToken: 'owner' };
const rows = [{ id: 'root', title: 'Root conversation', resume_id: 'latest' }, { id: 'other', title: 'Other conversation' }];
const transcript = (id = 'root', content = 'Private retained answer') => ({ schema_version: 1, session_id: id, scope: 'retained_current_history', redacted: true, turn_count: 1,
  turns: [{ role: 'assistant', content, agent_id: 'frigga', timestamp: '2026-11-13T12:00:00Z' }] });
const response = (body: unknown, status = 200) => ({ ok: status < 400, status, json: async () => body });
const deferred = () => { let resolve!: (value: any) => void; const promise = new Promise<any>(r => { resolve = r; }); return { promise, resolve }; };
let fetchMock: ReturnType<typeof vi.fn>, onResumed: ReturnType<typeof vi.fn>, server: ReturnType<typeof useServer>;
function Probe() {
  server = useServer(); const [visible, setVisible] = useState(true);
  return <><button onClick={() => setVisible(false)}>Close from test</button><button onClick={() => setVisible(true)}>Reopen from test</button>
    {server.ready && <SessionsModal visible={visible} onClose={() => setVisible(false)} onResumed={onResumed} />}</>;
}
const mount = async () => { render(<ServerProvider><Probe /></ServerProvider>); await screen.findByText('Root conversation'); };
const preview = (id = 'root') => screen.getByLabelText(`Preview transcript for ${id}`);
const exportButton = () => screen.getByLabelText('Export transcript JSON');
const search = () => screen.getByLabelText('Search loaded recent sessions');
const transcripts = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/transcript'));
const resumes = () => fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/sessions/resume'));
const openPreview = async () => { fireEvent.click(preview()); await screen.findByText('Private retained answer'); };
beforeEach(() => {
  records.clear(); records.set('jarvis.server.config.v1', JSON.stringify({ version: 2, config, appearance: null, chatScope: 'transcripts' }));
  fs.documentDirectory = 'file:///app/documents/'; fs.writeAsStringAsync.mockReset(); fs.writeAsStringAsync.mockResolvedValue(undefined);
  onResumed = vi.fn();
  fetchMock = vi.fn(async (url: string) => url.endsWith('/transcript') ? response(url.includes('/other/') ? transcript('other', 'Current other answer') : transcript())
    : url.endsWith('/sessions/resume') ? response({ ok: true, session: 'latest', turns: [] }) : response({ sessions: rows, next_cursor: null }));
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it('only fetches a transcript after explicit preview and never resumes or writes during preview', async () => {
  await mount(); expect(transcripts()).toHaveLength(0); await openPreview();
  expect(transcripts()).toHaveLength(1); expect(transcripts()[0][0]).toBe('https://hub.test/sessions/root/transcript');
  expect(new Headers(transcripts()[0][1]?.headers).get('X-Admin-Token')).toBe('owner');
  expect(new Headers(transcripts()[0][1]?.headers).get('X-User-Token')).toBe('user');
  expect(resumes()).toHaveLength(0); expect(onResumed).not.toHaveBeenCalled(); expect(fs.writeAsStringAsync).not.toHaveBeenCalled();
});
it('exports the validated projection only on click into app documents with unique safe filenames', async () => {
  fetchMock.mockImplementation(async (url: string) => url.endsWith('/transcript')
    ? response({ ...transcript(), owner_secret: 'SECRET', turns: [{ ...transcript().turns[0], tool_calls: 'SECRET' }] })
    : response({ sessions: rows, next_cursor: null }));
  await mount(); await openPreview(); fireEvent.click(exportButton());
  await waitFor(() => expect(fs.writeAsStringAsync).toHaveBeenCalledTimes(1));
  const [uri, body] = fs.writeAsStringAsync.mock.calls[0];
  expect(uri).toMatch(/^file:\/\/\/app\/documents\/[A-Za-z0-9_.-]+\.json$/); expect(JSON.parse(body)).toEqual(transcript());
  expect(body).not.toContain('SECRET'); await screen.findByText(/saved.*app.*folder/i);
  fireEvent.click(exportButton()); await waitFor(() => expect(fs.writeAsStringAsync).toHaveBeenCalledTimes(2));
  expect(fs.writeAsStringAsync.mock.calls[1][0]).not.toBe(uri); expect(resumes()).toHaveLength(0);
});
it('blocks duplicate export clicks synchronously while one write is pending', async () => {
  const pending = deferred(); fs.writeAsStringAsync.mockImplementation(() => pending.promise);
  await mount(); await openPreview(); const button = exportButton();
  act(() => { button.dispatchEvent(new MouseEvent('click', { bubbles: true })); button.dispatchEvent(new MouseEvent('click', { bubbles: true })); });
  expect(fs.writeAsStringAsync).toHaveBeenCalledTimes(1); await act(async () => pending.resolve(undefined));
});
it.each(['close', 'search', 'refresh', 'connection', 'same-config', 'resume', 'other-row', 'preview-close'])('fences a delayed transcript after %s', async mode => {
  const pending = deferred(); fetchMock.mockImplementation(async (url: string) => url.endsWith('/root/transcript') ? pending.promise
    : url.endsWith('/other/transcript') ? response(transcript('other', 'Current other answer'))
    : url.endsWith('/sessions/resume') ? response({ ok: true, session: 'latest', turns: [] }) : response({ sessions: rows, next_cursor: null }));
  await mount(); fireEvent.click(preview());
  if (mode === 'close') { fireEvent.click(screen.getByText('Close from test')); fireEvent.click(screen.getByText('Reopen from test')); }
  if (mode === 'search') fireEvent.change(search(), { target: { value: 'Other' } });
  if (mode === 'refresh') fireEvent.click(screen.getByLabelText('Refresh recent sessions'));
  if (mode === 'connection' || mode === 'same-config') await act(async () => server.updateConfig(mode === 'same-config' ? config : { ...config, baseUrl: 'https://elsewhere.test' }));
  if (mode === 'resume') fireEvent.click(screen.getByText('Root conversation'));
  if (mode === 'other-row') { fireEvent.click(preview('other')); await screen.findByText('Current other answer'); }
  if (mode === 'preview-close') fireEvent.click(screen.getByLabelText('Close transcript preview'));
  await act(async () => pending.resolve(response(transcript())));
  expect(screen.queryByText('Private retained answer')).toBeNull(); expect(fs.writeAsStringAsync).not.toHaveBeenCalled();
  if (mode !== 'other-row') expect(screen.queryByLabelText('Export transcript JSON')).toBeNull();
});
it.each(['close', 'search', 'refresh', 'connection', 'other-row'])('drops a completed preview and its export authority after %s', async mode => {
  await mount(); await openPreview();
  if (mode === 'close') { fireEvent.click(screen.getByText('Close from test')); fireEvent.click(screen.getByText('Reopen from test')); }
  if (mode === 'search') fireEvent.change(search(), { target: { value: 'Other' } });
  if (mode === 'refresh') fireEvent.click(screen.getByLabelText('Refresh recent sessions'));
  if (mode === 'connection') await act(async () => server.updateConfig(config));
  if (mode === 'other-row') { fireEvent.click(preview('other')); await screen.findByText('Current other answer'); }
  expect(screen.queryByText('Private retained answer')).toBeNull();
  if (mode !== 'other-row') expect(screen.queryByLabelText('Export transcript JSON')).toBeNull();
  expect(fs.writeAsStringAsync).not.toHaveBeenCalled();
});
it.each(['missing-folder', 'write-error'])('shows a visible failure without claiming saved for %s', async mode => {
  await mount(); await openPreview();
  if (mode === 'missing-folder') fs.documentDirectory = null; else fs.writeAsStringAsync.mockRejectedValue(new Error('disk failure'));
  fireEvent.click(exportButton()); await screen.findByText(/unavailable|failed|could not|unable|no writable app folder/i);
  expect(screen.queryByText(/saved.*app.*folder/i)).toBeNull(); if (mode === 'missing-folder') expect(fs.writeAsStringAsync).not.toHaveBeenCalled();
});
it.each(['close', 'other-row', 'refresh', 'connection'])('does not publish a late save status into a new scope after %s', async mode => {
  const pending = deferred(); fs.writeAsStringAsync.mockImplementation(() => pending.promise); await mount(); await openPreview(); fireEvent.click(exportButton());
  expect(fs.writeAsStringAsync).toHaveBeenCalledTimes(1);
  if (mode === 'close') { fireEvent.click(screen.getByText('Close from test')); fireEvent.click(screen.getByText('Reopen from test')); }
  if (mode === 'other-row') fireEvent.click(preview('other'));
  if (mode === 'refresh') fireEvent.click(screen.getByLabelText('Refresh recent sessions'));
  if (mode === 'connection') await act(async () => server.updateConfig(config));
  await act(async () => pending.resolve(undefined)); expect(screen.queryByText(/saved.*app.*folder/i)).toBeNull(); expect(fs.writeAsStringAsync).toHaveBeenCalledTimes(1);
});
it.each([403, 404, 500])('shows transcript HTTP %s without fallback, export, or error body leakage', async status => {
  fetchMock.mockImplementation(async (url: string) => url.endsWith('/transcript') ? response({ error: 'SECRET_ERR', detail: 'SECRET_DETAIL' }, status) : response({ sessions: rows, next_cursor: null }));
  await mount(); fireEvent.click(preview()); await screen.findByText(/could not load.*transcript/i);
  expect(document.body.textContent).not.toContain('SECRET_');
  expect(transcripts()).toHaveLength(1); expect(resumes()).toHaveLength(0); expect(screen.queryByLabelText('Export transcript JSON')).toBeNull(); expect(fs.writeAsStringAsync).not.toHaveBeenCalled();
});
it('renders escaped plain text, discards pending transcript on unmount, and clears prior text before a failed preview', async () => {
  fetchMock.mockImplementation(async (url: string) => url.endsWith('/root/transcript') ? response(transcript('root', '<b>Private HTML</b>'))
    : url.endsWith('/other/transcript') ? response({ detail: 'SECRET_NEXT' }, 500) : response({ sessions: rows, next_cursor: null }));
  const view = render(<ServerProvider><Probe /></ServerProvider>); await screen.findByText('Root conversation');
  fireEvent.click(preview()); await screen.findByText('<b>Private HTML</b>');
  expect(view.container.querySelector('b')).toBeNull();
  fireEvent.click(preview('other')); expect(screen.queryByText('<b>Private HTML</b>')).toBeNull();
  await screen.findByText(/could not load.*transcript/i); expect(document.body.textContent).not.toContain('SECRET_NEXT');
  const pending = deferred(); fetchMock.mockImplementation(async (url: string) => url.endsWith('/transcript') ? pending.promise : response({ sessions: rows, next_cursor: null }));
  fireEvent.click(preview()); view.unmount(); await act(async () => pending.resolve(response(transcript('root', 'Unmounted secret'))));
  expect(screen.queryByText('Unmounted secret')).toBeNull(); expect(fs.writeAsStringAsync).not.toHaveBeenCalled();
});
it('rejects wrong-session payload without rendering its private text or enabling export', async () => {
  fetchMock.mockImplementation(async (url: string) => url.endsWith('/transcript') ? response(transcript('other', 'Leaked wrong session')) : response({ sessions: rows, next_cursor: null }));
  await mount(); fireEvent.click(preview()); await screen.findByText(/invalid|failed|could not load/i);
  expect(screen.queryByText('Leaked wrong session')).toBeNull(); expect(screen.queryByLabelText('Export transcript JSON')).toBeNull(); expect(fs.writeAsStringAsync).not.toHaveBeenCalled();
});
it('allows a new explicit export while an old-scope write finishes without reusing its filename or status', async () => {
  const oldWrite = deferred(); const newWrite = deferred(); fs.writeAsStringAsync.mockImplementationOnce(() => oldWrite.promise).mockImplementationOnce(() => newWrite.promise);
  await mount(); await openPreview(); fireEvent.click(exportButton());
  fireEvent.click(preview('other')); await screen.findByText('Current other answer'); fireEvent.click(exportButton());
  expect(fs.writeAsStringAsync).toHaveBeenCalledTimes(2);
  const oldCall = fs.writeAsStringAsync.mock.calls[0], newCall = fs.writeAsStringAsync.mock.calls[1];
  expect(oldCall[0]).not.toBe(newCall[0]); expect(JSON.parse(newCall[1]).session_id).toBe('other');
  await act(async () => oldWrite.resolve(undefined)); expect(screen.queryByText(/saved.*app.*folder/i)).toBeNull();
  expect((exportButton() as HTMLButtonElement).disabled).toBe(true);
  await act(async () => newWrite.resolve(undefined)); const saved = await screen.findByText(/saved.*app.*folder/i);
  expect(saved.textContent).toContain(newCall[0].split('/').pop()); expect(saved.textContent).not.toContain(oldCall[0].split('/').pop());
});
it('explicit resume remains a separate action and targets the lineage newest member', async () => {
  await mount(); await openPreview(); fireEvent.click(screen.getByText('Root conversation'));
  await waitFor(() => expect(onResumed).toHaveBeenCalledWith('latest', []));
  expect(resumes()).toHaveLength(1); expect(JSON.parse(resumes()[0][1].body).session_id).toBe('latest');
  expect(fs.writeAsStringAsync).not.toHaveBeenCalled(); expect(screen.queryByText('Private retained answer')).toBeNull();
});
