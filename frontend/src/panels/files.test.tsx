// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { FilesPanel, humanSize } from './files';
import { CONSOLE_PANELS } from '../console-routes';

const ROOTS = { roots: [{ id: 'r1', label: 'share', path: '/srv/share' }], max_bytes: 104857600, preview_bytes: 262144,
  configured_by: 'JARVIS_FILE_BROWSER_DIRS' };
const TOP = { path: '', hidden: 3, truncated: false, max_bytes: 104857600, entries: [
  { name: 'docs', kind: 'dir', modified: 1 }, { name: 'notes.txt', kind: 'file', size: 12, modified: 1 }] };
const DOCS = { path: 'docs', hidden: 0, truncated: false, max_bytes: 104857600, entries: [
  { name: 'plan.md', kind: 'file', size: 7, modified: 1 }] };

function hub(routes) {
  const calls = [];
  global.fetch = vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET';
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : init.body;
    calls.push({ url: String(url), method, body, headers: init.headers });
    const answer = routes(String(url), method, body);
    return { ok: answer.status < 400, status: answer.status, json: async () => answer.body,
      blob: async () => new Blob(['x']) };
  });
  return calls;
}

const standard = (url, method) => {
  if (url.includes('/api/files/roots')) return { status: 200, body: ROOTS };
  if (url.includes('/api/files/list') && url.includes('path=docs')) return { status: 200, body: DOCS };
  if (url.includes('/api/files/list')) return { status: 200, body: TOP };
  if (url.includes('/api/files/read')) return { status: 200, body: { path: 'notes.txt', size: 12, binary: false, text: 'hello owner', truncated: false } };
  if (url.includes('/api/files/delete') && method === 'POST') return { status: 202, body: { pending: 41 } };
  if (url.includes('/api/files/rename') && method === 'POST') return { status: 202, body: { pending: 42 } };
  if (url.includes('/api/files/mkdir')) return { status: 201, body: { ok: true } };
  if (url.includes('/api/files/upload')) return { status: 403, body: { error: 'denied_name', detail: 'that name is never shown or written' } };
  return { status: 404, body: {} };
};

beforeEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

describe('Files panel', () => {
  it('is registered as an admin console panel', () => {
    expect(CONSOLE_PANELS).toContainEqual({ id: 'files', label: 'Files', group: 'Admin', component: 'FilesPanel' });
  });

  it('lists the approved folder, says how many names were hidden, and previews a file', async () => {
    const calls = hub(standard);
    render(<FilesPanel />);
    await screen.findByLabelText('open notes.txt');
    expect(screen.getByText(/3 hidden/)).toBeTruthy();
    fireEvent.click(screen.getByLabelText('open notes.txt'));
    expect(await screen.findByText('hello owner')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('open docs'));
    await screen.findByLabelText('open plan.md');
    expect(calls.some((c) => c.url.includes('/api/files/list') && c.url.includes('path=docs'))).toBe(true);
  });

  it('asks the decision inbox for a delete and a rename instead of doing them', async () => {
    const calls = hub(standard);
    render(<FilesPanel />);
    await screen.findByLabelText('open notes.txt');
    fireEvent.click(screen.getAllByText('delete…')[1]);
    expect(await screen.findByText(/card #41 in the decision inbox/)).toBeTruthy();
    expect(calls.find((c) => c.url.includes('/api/files/delete')).body).toEqual({ root: 'r1', path: 'notes.txt' });
    fireEvent.click(screen.getAllByText('rename…')[1]);
    fireEvent.change(screen.getByLabelText('to'), { target: { value: 'renamed.txt' } });
    fireEvent.click(screen.getByText('ask'));
    expect(await screen.findByText(/card #42/)).toBeTruthy();
    expect(calls.find((c) => c.url.includes('/api/files/rename')).body).toEqual({ root: 'r1', path: 'notes.txt', new_name: 'renamed.txt' });
  });

  it('says why an upload was refused, and sends the raw bytes', async () => {
    const calls = hub(standard);
    render(<FilesPanel />);
    await screen.findByLabelText('open notes.txt');
    const file = new File(['k=v'], '.env');
    fireEvent.change(screen.getByLabelText('Upload'), { target: { files: [file] } });
    expect(await screen.findByText(/\.env not uploaded · that name is never shown or written/)).toBeTruthy();
    const put = calls.find((c) => c.method === 'PUT');
    expect(put.url).toContain('name=.env');
    expect(put.headers['Content-Type']).toBe('application/octet-stream');
  });

  it('uploads every file dropped on the list', async () => {
    const calls = hub((url, method) => (method === 'PUT' ? { status: 201, body: { path: 'a.txt', size: 1 } } : standard(url, method)));
    render(<FilesPanel />);
    await screen.findByLabelText('open notes.txt');
    const files = [new File(['a'], 'a.txt'), new File(['b'], 'b.txt')];
    fireEvent.drop(screen.getByLabelText('drop files here to upload'), { dataTransfer: { files } });
    await waitFor(() => expect(calls.filter((c) => c.method === 'PUT').length).toBe(2));
    expect(calls.filter((c) => c.method === 'PUT').map((c) => new URL(c.url, 'http://x').searchParams.get('name'))).toEqual(['a.txt', 'b.txt']);
  });

  it('makes a folder', async () => {
    const calls = hub(standard);
    render(<FilesPanel />);
    await screen.findByLabelText('open notes.txt');
    fireEvent.change(screen.getByLabelText('New folder'), { target: { value: 'drafts' } });
    fireEvent.click(screen.getByText('make'));
    await waitFor(() => expect(calls.find((c) => c.url.includes('/api/files/mkdir')).body).toEqual({ root: 'r1', path: '', name: 'drafts' }));
  });

  it('formats sizes', () => {
    expect(humanSize(12)).toBe('12 B');
    expect(humanSize(2048)).toBe('2.0 KiB');
    expect(humanSize(undefined)).toBe('');
  });
});
