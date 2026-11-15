// @ts-nocheck
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SessionsPanel } from '../panels/sessions';
const reply = (status, body) => ({ ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) });
const transcript = (id = 'chat-a', content = '<b>retained private text</b>') => ({ schema_version: 1, session_id: id, scope: 'retained_current_history', redacted: true, turn_count: 2, turns: [{ role: 'user', content, agent_id: null, timestamp: '' }, { role: 'assistant', content: 'Safe answer', agent_id: 'nerva', timestamp: '' }] });
let calls, onTranscript, onDownload;
beforeEach(() => {
 cleanup(); calls = []; onTranscript = undefined; onDownload = undefined; localStorage.setItem('hud.admin_token', 'owner-token');
 global.fetch = vi.fn(async (url, init = {}) => {
  const parsed = new URL(String(url), 'http://hud.test'); const call = { path: parsed.pathname, params: parsed.searchParams, method: init.method || 'GET', headers: init.headers }; calls.push(call);
  if (call.path === '/sessions/page') return reply(200, { sessions: [{ id: 'chat-a', title: 'Topic A' }, { id: 'chat-b', title: 'Topic B' }], next_cursor: null });
  if (call.path.endsWith('/transcript')) {
   if (call.params.get('download') === 'true') return onDownload ? onDownload(call) : reply(403, { error: 'owner_required' });
   return onTranscript ? onTranscript(call) : reply(200, transcript(call.path.split('/')[2]));
  }
  return reply(200, { ok: true });
 });
});
afterEach(() => { cleanup(); localStorage.clear(); delete globalThis.showSaveFilePicker; vi.restoreAllMocks(); });
const open = async (id = 'chat-a') => fireEvent.click(await screen.findByLabelText(`preview retained conversation ${id}`));
describe('SessionsPanel retained conversation preview', () => {
 it('reads explicitly as admin, renders escaped text, and never resumes or downloads on preview', async () => {
  const selected = vi.fn(); window.addEventListener('nerva:session-selected', selected);
  const { container } = render(<SessionsPanel />); await screen.findByText('Topic A'); expect(calls.filter(c => c.path.endsWith('/transcript'))).toHaveLength(0);
  await open(); expect(await screen.findByText('<b>retained private text</b>')).toBeTruthy(); expect(container.querySelector('b')).toBeNull();
  expect(screen.getByText(/2 retained text turns/)).toBeTruthy(); expect(screen.getByText(/Compacted archives/)).toBeTruthy();
  const read = calls.find(c => c.path === '/sessions/chat-a/transcript'); expect(read.headers['X-Admin-Token']).toBe('owner-token'); expect(read.method).toBe('GET'); expect(read.params.has('download')).toBe(false);
  expect(calls.some(c => c.path === '/sessions/resume')).toBe(false); expect(selected).not.toHaveBeenCalled(); expect(calls.filter(c => c.path.endsWith('/transcript'))).toHaveLength(1);
  window.removeEventListener('nerva:session-selected', selected);
 });
 it.each(['close', 'row', 'tab', 'search', 'reload', 'mutation', 'rename'])('discards a pending private response after %s', async action => {
  let release; onTranscript = () => new Promise(resolve => { release = resolve; }); render(<SessionsPanel />); await open(); await waitFor(() => expect(release).toBeDefined());
  if (action === 'close') fireEvent.click(screen.getByLabelText('close retained conversation chat-a'));
  if (action === 'row') { onTranscript = () => reply(200, transcript('chat-b', 'Other conversation')); await open('chat-b'); await screen.findByText('Other conversation'); }
  if (action === 'tab') fireEvent.click(screen.getByRole('tab', { name: 'archived' }));
  if (action === 'search') fireEvent.change(screen.getByLabelText('Search loaded recent sessions'), { target: { value: 'Topic B' } });
  if (action === 'reload') fireEvent.click(screen.getByLabelText('Reload'));
  if (action === 'mutation') fireEvent.click(screen.getByLabelText('pin chat-a'));
  if (action === 'rename') fireEvent.click(screen.getByLabelText('rename chat-a'));
  await act(async () => release(reply(200, transcript()))); expect(screen.queryByText('<b>retained private text</b>')).toBeNull();
 });
 it.each(['refusal', 'wrong-session', 'malformed'])('clears private text when the next preview returns %s', async kind => {
  render(<SessionsPanel />); await open(); await screen.findByText('<b>retained private text</b>');
  onTranscript = () => kind === 'refusal' ? reply(409, { error: 'source_busy' }) : reply(200, kind === 'wrong-session' ? transcript('chat-a') : { ...transcript('chat-b'), redacted: false });
  await open('chat-b'); await screen.findByRole('alert'); expect(screen.queryByText('<b>retained private text</b>')).toBeNull(); expect(screen.queryByText('Safe answer')).toBeNull();
 });
 it('streams JSON only after explicit download, with admin credentials and a safe filename', async () => {
  const piped = []; globalThis.showSaveFilePicker = vi.fn(async () => ({ createWritable: async () => 'picked-file' })); onDownload = () => ({ ok: true, status: 200, body: { pipeTo: async target => { piped.push(target); } } });
  render(<SessionsPanel />); await open(); await screen.findByText('Safe answer'); expect(globalThis.showSaveFilePicker).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText('download retained conversation JSON chat-a')); await screen.findByText('Retained conversation JSON saved');
  expect(globalThis.showSaveFilePicker).toHaveBeenCalledWith({ suggestedName: 'session-chat-a-transcript.json' }); const download = calls.find(c => c.params.get('download') === 'true'); expect(download.path).toBe('/sessions/chat-a/transcript'); expect(download.headers['X-Admin-Token']).toBe('owner-token'); expect(piped).toEqual(['picked-file']);
 });
 it('clears private text on download refusal', async () => {
  globalThis.showSaveFilePicker = vi.fn(async () => ({ createWritable: async () => 'picked-file' })); render(<SessionsPanel />); await open(); await screen.findByText('Safe answer'); fireEvent.click(screen.getByLabelText('download retained conversation JSON chat-a')); expect((await screen.findByRole('alert')).textContent).toContain('owner_required'); expect(screen.queryByText('Safe answer')).toBeNull();
 });
 it('ignores late download failure after another preview opens', async () => {
  let rejectDownload; globalThis.showSaveFilePicker = vi.fn(() => new Promise((_, reject) => { rejectDownload = reject; })); render(<SessionsPanel />); await open(); await screen.findByText('Safe answer'); fireEvent.click(screen.getByLabelText('download retained conversation JSON chat-a')); await open('chat-b'); await screen.findByText('Safe answer'); await act(async () => rejectDownload(new Error('cancelled'))); expect(screen.queryByRole('alert')).toBeNull(); expect(screen.getByText('Safe answer')).toBeTruthy();
 });
 it('does not restore a pending preview after a refused download', async () => {
  let release; onTranscript = () => new Promise(resolve => { release = resolve; });
  globalThis.showSaveFilePicker = vi.fn(async () => ({ createWritable: async () => 'picked-file' }));
  render(<SessionsPanel />); await open(); await waitFor(() => expect(release).toBeDefined());
  fireEvent.click(screen.getByLabelText('download retained conversation JSON chat-a'));
  await screen.findByRole('alert'); await act(async () => release(reply(200, transcript())));
  expect(screen.queryByText('Safe answer')).toBeNull(); expect(screen.getByRole('alert').textContent).toContain('owner_required');
 });
 it('gives accurate guidance when token streaming is unavailable without requesting export', async () => {
  render(<SessionsPanel />); await open(); await screen.findByText('Safe answer');
  fireEvent.click(screen.getByLabelText('download retained conversation JSON chat-a'));
  expect((await screen.findByRole('alert')).textContent).toContain('file saving support');
  expect(calls.some(c => c.params.get('download') === 'true')).toBe(false);
  expect(screen.queryByText('Safe answer')).toBeNull();
 });

 it('ignores a late preview refusal after a different row succeeds', async () => {
  let release; onTranscript = () => new Promise(resolve => { release = resolve; });
  render(<SessionsPanel />); await open(); await waitFor(() => expect(release).toBeDefined());
  onTranscript = () => reply(200, transcript('chat-b', 'Current conversation'));
  await open('chat-b'); await screen.findByText('Current conversation');
  await act(async () => release(reply(403, { error: 'old_private_refusal' })));
  expect(screen.queryByRole('alert')).toBeNull(); expect(screen.getByText('Current conversation')).toBeTruthy();
 });
 it('requests a browser download for owner-session authentication without claiming it saved', async () => {
  localStorage.clear(); const clicked = []; vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () { clicked.push({ href: this.getAttribute('href'), filename: this.download }); });
  render(<SessionsPanel />); await open(); await screen.findByText('Safe answer');
  expect(clicked).toHaveLength(0); fireEvent.click(screen.getByLabelText('download retained conversation JSON chat-a'));
  await screen.findByText('Retained conversation JSON download requested');
  expect(clicked).toEqual([{ href: '/sessions/chat-a/transcript?download=true', filename: 'session-chat-a-transcript.json' }]);
  expect(screen.queryByText('Retained conversation JSON saved')).toBeNull();
 });

 it.each(['preview', 'download'])('does not expose raw private refusal fields on %s', async action => {
  render(<SessionsPanel />); await open(); await screen.findByText('Safe answer');
  const refusal = { error: 'SECRET_RAW_ERROR', reason: 'SECRET_RAW_REASON', detail: { token: 'SECRET_RAW_DETAIL' } };
  if (action === 'preview') { onTranscript = () => reply(403, refusal); await open('chat-b'); }
  else {
   globalThis.showSaveFilePicker = vi.fn(async () => ({ createWritable: async () => 'picked-file' }));
   onDownload = () => reply(403, refusal); fireEvent.click(screen.getByLabelText('download retained conversation JSON chat-a'));
  }
  const alert = await screen.findByRole('alert'); expect(alert.textContent).toContain('unavailable');
  expect(document.body.textContent).not.toContain('SECRET_RAW'); expect(screen.queryByText('Safe answer')).toBeNull();
 });
 it('ignores a private response after unmount and remount', async () => {
  let release; onTranscript = () => new Promise(resolve => { release = resolve; });
  const view = render(<SessionsPanel />); await open(); await waitFor(() => expect(release).toBeDefined());
  view.unmount(); render(<SessionsPanel />); await screen.findByText('Topic A');
  await act(async () => release(reply(200, transcript()))); expect(screen.queryByText('Safe answer')).toBeNull();
 });
 it.each(['close', 'tab', 'search', 'reload', 'mutation', 'rename'])('clears already shown private text on %s', async action => {
  render(<SessionsPanel />); await open(); await screen.findByText('Safe answer');
  if (action === 'close') fireEvent.click(screen.getByLabelText('close retained conversation chat-a'));
  if (action === 'tab') fireEvent.click(screen.getByRole('tab', { name: 'archived' }));
  if (action === 'search') fireEvent.change(screen.getByLabelText('Search loaded recent sessions'), { target: { value: 'Topic B' } });
  if (action === 'reload') fireEvent.click(screen.getByLabelText('Reload'));
  if (action === 'mutation') fireEvent.click(screen.getByLabelText('pin chat-a'));
  if (action === 'rename') fireEvent.click(screen.getByLabelText('rename chat-a'));
  expect(screen.queryByText('Safe answer')).toBeNull();
 });

});
