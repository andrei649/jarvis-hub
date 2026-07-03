// @ts-nocheck
/* HUD-v3 C3 — the Console Knowledge-Graph panel reads /api/kg/entities, deletes an
   entity (DELETE /api/kg/entities/{name}) and forgets a memory item by id
   (POST /api/memory/decay/forget). fetch is mocked, like kernel-safety-panels.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { KgPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('KgPanel — knowledge-graph entity controls are live', () => {
  it('GETs /api/kg/entities and lists an entity with type + mention count', async () => {
    const fn = mockFetch({ entities: [
      { name: 'Andrei', type: 'person', mentions: 12 },
    ], total: 1 });
    render(<KgPanel />);
    await waitFor(() => expect(screen.getByText('Andrei')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/kg/entities'))).toBe(true);
    expect(screen.getByText('person')).toBeTruthy();
    expect(screen.getByText('12×')).toBeTruthy();
  });

  it('DELETEs an entity when its ✕ is clicked', async () => {
    const fn = mockFetch({ entities: [{ name: 'Acme', type: 'org', mentions: 3 }], total: 1 });
    render(<KgPanel />);
    await waitFor(() => expect(screen.getByText('Acme')).toBeTruthy());
    fireEvent.click(screen.getByTitle('delete entity'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/api/kg/entities/Acme') && c[1]?.method === 'DELETE')
    ).toBe(true));
  });

  it('forgets a memory item by id (POST /api/memory/decay/forget) only when an id is given', async () => {
    const fn = mockFetch({ entities: [], total: 0 });
    render(<KgPanel />);
    await waitFor(() => expect(screen.getByText('forget')).toBeTruthy());
    // empty id → no POST
    fireEvent.click(screen.getByText('forget'));
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/memory/decay/forget'))).toBe(false);
    // with an id → POST {id}
    fireEvent.change(screen.getByPlaceholderText('memory item id to forget'), { target: { value: 'fact-99' } });
    fireEvent.click(screen.getByText('forget'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/api/memory/decay/forget')
        && c[1]?.method === 'POST' && String(c[1]?.body).includes('"id":"fact-99"'))
    ).toBe(true));
  });
});
