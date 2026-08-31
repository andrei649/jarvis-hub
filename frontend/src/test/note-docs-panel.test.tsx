// @ts-nocheck
/* DRA-53 — `agents/core/notes_store.py` (the block-tree document store) shipped with 21
   green tests and ADOPTED BY NOTHING: no route, no caller, no way for a person to reach it.
   The roadmap's framing was "adopt it behind a route or delete it". This is the HUD half of
   the adoption: NOTE DOCS drives the new /api/notes/docs + /api/notes/blocks family.

   Two properties are pinned deliberately:
   · the doc LISTING exists — without it a panel could create a doc and then lose its id,
     which is the degenerate write-only surface the store's adoption had to avoid;
   · a refusal is rendered — apiPost/apiPatch/apiDelete throw on 4xx, so a control without
     an onErr reads as a silent success (the bug class already found twice in this repo). */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { NoteDocsPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

const DOCS = {
  docs: [
    { id: 'd1', title: 'Field notes', created_at: '2026-08-30T09:00:00+00:00', updated_at: '2026-08-30T10:00:00+00:00' },
    { id: 'd2', title: '', created_at: '2026-08-29T09:00:00+00:00', updated_at: '2026-08-29T09:00:00+00:00' },
  ],
};

const TREE = {
  id: 'd1', title: 'Field notes', created_at: 'x', updated_at: 'y',
  children: [
    { id: 'b1', type: 'heading', text: 'Roof rack', ordering: 'V', children: [
      { id: 'b2', type: 'paragraph', text: 'bolts are M8', ordering: 'V', children: [] },
    ] },
    { id: 'b3', type: 'todo', text: 'order a torque wrench', ordering: 'k', children: [] },
  ],
};

/* Exact-path routing: GET /api/notes/docs and GET /api/notes/docs/d1 are different
   routes and a substring mock would conflate them. */
function mockApi(overrides = {}) {
  const calls = [];
  const table = {
    'GET /api/notes/docs': { body: DOCS },
    'GET /api/notes/docs/d1': { body: TREE },
    ...overrides,
  };
  const fn = vi.fn().mockImplementation((url, init) => {
    const method = (init && init.method) || 'GET';
    const u = String(url);
    calls.push({ url: u, method, body: init && init.body });
    const hit = table[`${method} ${u}`] || { body: { ok: true } };
    const status = hit.status || 200;
    return Promise.resolve({ ok: status < 400, status, json: async () => hit.body });
  });
  global.fetch = fn;
  return calls;
}

const find = (calls, method, url) => calls.filter((c) => c.method === method && c.url === url);

describe('NoteDocsPanel — the block store is reachable', () => {
  it('lists the docs so a created doc can be found again', async () => {
    mockApi();
    render(<NoteDocsPanel />);

    await waitFor(() => expect(screen.getByText('Field notes')).toBeTruthy());
    // an untitled doc still has to be identifiable — it falls back to its id
    expect(screen.getByText('d2')).toBeTruthy();
    expect(screen.getByText('2 docs')).toBeTruthy();
  });

  it('creates a doc with the typed title and reloads the listing', async () => {
    const calls = mockApi({ 'POST /api/notes/docs': { body: { ok: true, id: 'd9' } } });
    render(<NoteDocsPanel />);
    await waitFor(() => expect(screen.getByText('Field notes')).toBeTruthy());
    const before = find(calls, 'GET', '/api/notes/docs').length;

    fireEvent.change(screen.getByPlaceholderText(/doc title/i), { target: { value: 'Trip plan' } });
    fireEvent.click(screen.getByText('new doc'));

    await waitFor(() => expect(find(calls, 'POST', '/api/notes/docs').length).toBe(1));
    expect(JSON.parse(find(calls, 'POST', '/api/notes/docs')[0].body)).toEqual({ title: 'Trip plan' });
    await waitFor(() => expect(find(calls, 'GET', '/api/notes/docs').length).toBeGreaterThan(before));
  });

  it('renders a refusal instead of looking like the doc was created', async () => {
    mockApi({ 'POST /api/notes/docs': { status: 400, body: { error: 'nope' } } });
    render(<NoteDocsPanel />);
    await waitFor(() => expect(screen.getByText('Field notes')).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText(/doc title/i), { target: { value: 'x' } });
    fireEvent.click(screen.getByText('new doc'));

    await waitFor(() => expect(screen.getByText(/refused · 400/)).toBeTruthy());
  });

  it('opens a doc and renders the nested block tree with each block type', async () => {
    mockApi();
    render(<NoteDocsPanel />);
    await waitFor(() => expect(screen.getByText('Field notes')).toBeTruthy());

    fireEvent.click(screen.getByText('Field notes'));

    await waitFor(() => expect(screen.getByText('Roof rack')).toBeTruthy());
    expect(screen.getByText('bolts are M8')).toBeTruthy();       // a child of the heading
    expect(screen.getByText('order a torque wrench')).toBeTruthy();
    expect(screen.getByText('heading')).toBeTruthy();
    expect(screen.getByText('todo')).toBeTruthy();
  });

  it('adds a block to the open doc', async () => {
    const calls = mockApi({ 'POST /api/notes/docs/d1/blocks': { body: { ok: true, id: 'b9' } } });
    render(<NoteDocsPanel />);
    await waitFor(() => expect(screen.getByText('Field notes')).toBeTruthy());
    fireEvent.click(screen.getByText('Field notes'));
    await waitFor(() => expect(screen.getByText('Roof rack')).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText(/new block/i), { target: { value: 'check the tyres' } });
    fireEvent.click(screen.getByText('add block'));

    await waitFor(() => expect(find(calls, 'POST', '/api/notes/docs/d1/blocks').length).toBe(1));
    const body = JSON.parse(find(calls, 'POST', '/api/notes/docs/d1/blocks')[0].body);
    expect(body.text).toBe('check the tyres');
    expect(body.type).toBe('paragraph');
  });

  it('edits a block through PATCH /api/notes/blocks/{id}', async () => {
    const calls = mockApi({ 'PATCH /api/notes/blocks/b2': { body: { ok: true, block: { id: 'b2', text: 'bolts are M10' } } } });
    render(<NoteDocsPanel />);
    await waitFor(() => expect(screen.getByText('Field notes')).toBeTruthy());
    fireEvent.click(screen.getByText('Field notes'));
    await waitFor(() => expect(screen.getByText('bolts are M8')).toBeTruthy());

    fireEvent.click(screen.getAllByTitle('edit this block')[1]);   // b2
    fireEvent.change(screen.getByPlaceholderText(/block text/i), { target: { value: 'bolts are M10' } });
    fireEvent.click(screen.getByText('save block'));

    await waitFor(() => expect(find(calls, 'PATCH', '/api/notes/blocks/b2').length).toBe(1));
    expect(JSON.parse(find(calls, 'PATCH', '/api/notes/blocks/b2')[0].body).text).toBe('bolts are M10');
  });

  it('deletes a block, and says the delete takes the whole subtree with it', async () => {
    const calls = mockApi({ 'DELETE /api/notes/blocks/b1': { body: { ok: true, deleted: 2 } } });
    render(<NoteDocsPanel />);
    await waitFor(() => expect(screen.getByText('Field notes')).toBeTruthy());
    fireEvent.click(screen.getByText('Field notes'));
    await waitFor(() => expect(screen.getByText('Roof rack')).toBeTruthy());

    fireEvent.click(screen.getAllByTitle(/delete this block and its children/i)[0]);

    await waitFor(() => expect(find(calls, 'DELETE', '/api/notes/blocks/b1').length).toBe(1));
    await waitFor(() => expect(screen.getByText(/deleted 2 block\(s\)/)).toBeTruthy());
  });

  it('deletes a doc and refreshes the listing', async () => {
    const calls = mockApi({ 'DELETE /api/notes/docs/d1': { body: { ok: true, deleted: 3 } } });
    render(<NoteDocsPanel />);
    await waitFor(() => expect(screen.getByText('Field notes')).toBeTruthy());
    const before = find(calls, 'GET', '/api/notes/docs').length;

    fireEvent.click(screen.getAllByTitle(/delete this doc/i)[0]);

    await waitFor(() => expect(find(calls, 'DELETE', '/api/notes/docs/d1').length).toBe(1));
    await waitFor(() => expect(find(calls, 'GET', '/api/notes/docs').length).toBeGreaterThan(before));
  });

  it('is registered in the Memory section, beside the free-text NOTES card', () => {
    const src = readFileSync(join(process.cwd(), 'src', 'gap.tsx'), 'utf8');
    const memory = src.match(/\['Memory', \[([^\]]*)\]\]/);
    expect(memory).toBeTruthy();
    expect(memory[1]).toContain('NoteDocsPanel');
    expect(memory[1]).toContain('NotesPanel');   // the sibling it belongs beside
  });
});
