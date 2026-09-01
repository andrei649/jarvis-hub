// @ts-nocheck
/* DRA-27 (write legs) — the memory cluster owned only its READ and FORGET halves: KgPanel
   listed entities and deleted them, MemoryHygienePanel listed decay candidates and forgot
   them. Nothing in any client ever WROTE: `/api/memory/remember`, `/api/kg/relations`,
   `/api/kg/ingest` and the two `/api/memory/eval/*` routes had zero callers repo-wide.

   These pin the write halves, and — the load-bearing part — pin that a refusal is VISIBLE.
   apiPost throws on 4xx (failMutation is typed `never`), so a control without an `onErr`
   silently reads as success; the KG writes are contract- and kernel-mediated and answer a
   real 403 "kernel denied: …", so that branch is exercised here rather than assumed. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { KgPanel, MemoryWritePanel, MemoryEvalPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

const ENTITIES = { entities: [{ name: 'Cosmina', type: 'person', mentions: 3 }] };

const CORPUS = {
  abilities: ['extraction', 'multi_session', 'temporal', 'update', 'abstention'],
  cases: [
    { id: 'ext-1', ability: 'extraction', facts: ['a'], question: 'q1', expected: ['a'], abstain: false },
    { id: 'ext-2', ability: 'extraction', facts: ['b'], question: 'q2', expected: ['b'], abstain: false },
    { id: 'abs-1', ability: 'abstention', facts: [], question: 'q3', expected: [], abstain: true },
  ],
};

const RUN = {
  overall: { n: 3, passed: 2, score: 0.667 },
  by_ability: {
    extraction: { n: 2, passed: 2, score: 1.0 },
    abstention: { n: 1, passed: 0, score: 0.0 },
  },
  results: [],
};

/* Route-aware fetch mock: `routes` maps a url substring -> {body, status}. Anything
   unmatched answers 200 {} so an unrelated panel read never explodes the test. */
function mockApi(routes) {
  const calls = [];
  const fn = vi.fn().mockImplementation((url, init) => {
    const u = String(url);
    calls.push({ url: u, method: (init && init.method) || 'GET', body: init && init.body });
    const hit = routes.find((r) => u.includes(r.match) && (!r.method || r.method === ((init && init.method) || 'GET')));
    const status = hit ? (hit.status || 200) : 200;
    return Promise.resolve({ ok: status < 400, status, json: async () => (hit ? hit.body : {}) });
  });
  global.fetch = fn;
  return calls;
}

const bodyOf = (calls, match) => JSON.parse(calls.filter((c) => c.url.includes(match) && c.method === 'POST').pop().body);

describe('MemoryWritePanel — the write half of the memory loop', () => {
  it('posts the typed text (and its source) to /api/memory/remember and reports the id', async () => {
    const calls = mockApi([{ match: '/api/memory/remember', method: 'POST', body: { ok: true, id: 'mem-abc' } }]);
    render(<MemoryWritePanel />);

    fireEvent.change(screen.getByPlaceholderText(/fact to remember/i), { target: { value: 'Andrei prefers dark mode' } });
    fireEvent.change(screen.getByPlaceholderText(/source/i), { target: { value: 'hud-test' } });
    fireEvent.click(screen.getByText('remember'));

    await waitFor(() => expect(screen.getByText(/stored · mem-abc/)).toBeTruthy());
    const body = bodyOf(calls, '/api/memory/remember');
    expect(body.text).toBe('Andrei prefers dark mode');
    expect(body.metadata).toEqual({ source: 'hud-test' });
  });

  it('does NOT claim "stored" when the route answers 200 {ok:false} (no embedder)', async () => {
    mockApi([{ match: '/api/memory/remember', method: 'POST', body: { ok: false, id: null } }]);
    render(<MemoryWritePanel />);

    fireEvent.change(screen.getByPlaceholderText(/fact to remember/i), { target: { value: 'x' } });
    fireEvent.click(screen.getByText('remember'));

    await waitFor(() => expect(screen.getByText(/not stored/i)).toBeTruthy());
    expect(screen.queryByText(/^stored ·/)).toBeNull();
  });

  it('surfaces a refusal instead of silently reading as success', async () => {
    mockApi([{ match: '/api/memory/remember', method: 'POST', status: 503, body: { error: 'not initialized' } }]);
    render(<MemoryWritePanel />);

    fireEvent.change(screen.getByPlaceholderText(/fact to remember/i), { target: { value: 'x' } });
    fireEvent.click(screen.getByText('remember'));

    await waitFor(() => expect(screen.getByText(/refused · 503/)).toBeTruthy());
  });
});

describe('MemoryEvalPanel — the memory harness has a run button', () => {
  it('renders the corpus abilities and case count', async () => {
    mockApi([{ match: '/api/memory/eval/corpus', body: CORPUS }]);
    render(<MemoryEvalPanel />);

    await waitFor(() => expect(screen.getByText(/extraction · multi_session · temporal · update · abstention/)).toBeTruthy());
    expect(screen.getByText('3 cases')).toBeTruthy();
  });

  it('runs the keyword mode and renders the real per-ability scores', async () => {
    const calls = mockApi([
      { match: '/api/memory/eval/corpus', body: CORPUS },
      { match: '/api/memory/eval/run', method: 'POST', body: RUN },
    ]);
    render(<MemoryEvalPanel />);
    await waitFor(() => expect(screen.getByText('3 cases')).toBeTruthy());

    fireEvent.click(screen.getByText('run keyword'));

    await waitFor(() => expect(screen.getByText('2/3 passed')).toBeTruthy());
    expect(calls.some((c) => c.method === 'POST' && c.url.includes('/api/memory/eval/run?mode=keyword'))).toBe(true);
    expect(screen.getByText('extraction')).toBeTruthy();
    expect(screen.getByText('2/2 · 1')).toBeTruthy();
    expect(screen.getByText('0/1 · 0')).toBeTruthy();
  });

  it('states the recall mode writes the corpus into the vector store', async () => {
    mockApi([{ match: '/api/memory/eval/corpus', body: CORPUS }]);
    render(<MemoryEvalPanel />);
    await waitFor(() => expect(screen.getByText('3 cases')).toBeTruthy());
    expect(screen.getByText(/writes the corpus into the vector store/i)).toBeTruthy();
  });
});

describe('KgPanel — the graph is now writable, and a kernel denial is visible', () => {
  it('adds a relation and refetches the entity list', async () => {
    const calls = mockApi([
      { match: '/api/kg/entities', body: ENTITIES },
      { match: '/api/kg/relations', method: 'POST', body: { ok: true } },
    ]);
    render(<KgPanel />);
    await waitFor(() => expect(screen.getByText('Cosmina')).toBeTruthy());
    const getsBefore = calls.filter((c) => c.url.includes('/api/kg/entities')).length;

    fireEvent.change(screen.getByPlaceholderText('source'), { target: { value: 'Andrei' } });
    fireEvent.change(screen.getByPlaceholderText('relation'), { target: { value: 'PARENT_OF' } });
    fireEvent.change(screen.getByPlaceholderText('target'), { target: { value: 'Cosmina' } });
    fireEvent.click(screen.getByText('add relation'));

    await waitFor(() => expect(screen.getByText(/relation added/)).toBeTruthy());
    expect(bodyOf(calls, '/api/kg/relations')).toEqual({ source: 'Andrei', relation: 'PARENT_OF', target: 'Cosmina' });
    await waitFor(() => expect(calls.filter((c) => c.url.includes('/api/kg/entities')).length).toBeGreaterThan(getsBefore));
  });

  it('renders the 403 kernel denial rather than looking like a success', async () => {
    mockApi([
      { match: '/api/kg/entities', body: ENTITIES },
      { match: '/api/kg/relations', method: 'POST', status: 403, body: { error: 'kernel denied: halted' } },
    ]);
    render(<KgPanel />);
    await waitFor(() => expect(screen.getByText('Cosmina')).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText('source'), { target: { value: 'a' } });
    fireEvent.change(screen.getByPlaceholderText('relation'), { target: { value: 'B' } });
    fireEvent.change(screen.getByPlaceholderText('target'), { target: { value: 'c' } });
    fireEvent.click(screen.getByText('add relation'));

    await waitFor(() => expect(screen.getByText(/refused · 403/)).toBeTruthy());
    expect(screen.queryByText(/relation added/)).toBeNull();
  });

  it('names the 400 case — a non-identifier relation type is rejected, not coerced', async () => {
    mockApi([
      { match: '/api/kg/entities', body: ENTITIES },
      { match: '/api/kg/relations', method: 'POST', status: 400, body: { error: 'invalid relation type' } },
    ]);
    render(<KgPanel />);
    await waitFor(() => expect(screen.getByText('Cosmina')).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText('source'), { target: { value: 'a' } });
    fireEvent.change(screen.getByPlaceholderText('relation'), { target: { value: 'is friends with' } });
    fireEvent.change(screen.getByPlaceholderText('target'), { target: { value: 'c' } });
    fireEvent.click(screen.getByText('add relation'));

    await waitFor(() => expect(screen.getByText(/invalid relation type/)).toBeTruthy());
  });

  it('ingests text and shows the triples that were actually written, not just a count', async () => {
    const calls = mockApi([
      { match: '/api/kg/entities', body: ENTITIES },
      { match: '/api/kg/ingest', method: 'POST', body: {
        ok: true, added: 2,
        triples: [['Andrei', 'PARENT_OF', 'Cosmina'], ['Cosmina', 'LIKES', 'guitar']],
      } },
    ]);
    render(<KgPanel />);
    await waitFor(() => expect(screen.getByText('Cosmina')).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText(/text to extract triples from/i), { target: { value: 'Andrei is the parent of Cosmina.' } });
    fireEvent.click(screen.getByText('ingest'));

    await waitFor(() => expect(screen.getByText('added 2 triple(s)')).toBeTruthy());
    expect(bodyOf(calls, '/api/kg/ingest')).toEqual({ text: 'Andrei is the parent of Cosmina.' });
    expect(screen.getByText(/Andrei · PARENT_OF · Cosmina/)).toBeTruthy();
    expect(screen.getByText(/Cosmina · LIKES · guitar/)).toBeTruthy();
  });
});

describe('registration', () => {
  it('puts both new write panels in the Memory section, beside the read/forget halves', () => {
    const src = readFileSync(join(process.cwd(), 'src', 'gap.tsx'), 'utf8');
    const memory = src.match(/\['Memory', \[([^\]]*)\]\]/);
    expect(memory).toBeTruthy();
    expect(memory[1]).toContain('MemoryWritePanel');
    expect(memory[1]).toContain('MemoryEvalPanel');
    // the forget half was already there — this must not have displaced it
    expect(memory[1]).toContain('MemoryHygienePanel');
    expect(memory[1]).toContain('KgPanel');
  });
});
