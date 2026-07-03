// @ts-nocheck
/* HUD-v3 C7 — the Console Workflows panel reads the workflow runtime (/api/workflows),
   runs a pipeline (POST /api/workflows/run, user-guard) and deletes a user-defined one
   (DELETE /api/workflows/{id}, admin). fetch is mocked, like kernel-safety-panels.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { WorkflowsPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

function mockFetch(payload) {
  const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload });
  global.fetch = fn;
  return fn;
}

describe('WorkflowsPanel — the workflow runtime is live', () => {
  it('GETs /api/workflows and lists a pipeline with its step count', async () => {
    const fn = mockFetch({ workflows: [
      { id: 'daily-brief', name: 'Daily Brief', description: '', steps: [{}, {}, {}] },
    ], total: 1 });
    render(<WorkflowsPanel />);
    await waitFor(() => expect(screen.getByText('Daily Brief')).toBeTruthy());
    expect(fn.mock.calls.some((c) => String(c[0]).includes('/api/workflows'))).toBe(true);
    expect(screen.getByText('3 steps')).toBeTruthy();
  });

  it('runs a pipeline (POST /api/workflows/run) when "run" is clicked', async () => {
    const fn = mockFetch({ workflows: [{ id: 'p1', name: 'P1', steps: [] }], ok: true });
    render(<WorkflowsPanel />);
    await waitFor(() => expect(screen.getByText('run')).toBeTruthy());
    fireEvent.click(screen.getByText('run'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/api/workflows/run')
        && c[1]?.method === 'POST' && String(c[1]?.body).includes('"pipeline_id":"p1"'))
    ).toBe(true));
    await waitFor(() => expect(screen.getByText(/ran p1 · ok/)).toBeTruthy());
  });

  it('DELETEs a user-defined pipeline when ✕ is clicked', async () => {
    const fn = mockFetch({ workflows: [{ id: 'mine', name: 'Mine', steps: [] }], ok: true });
    render(<WorkflowsPanel />);
    await waitFor(() => expect(screen.getByText('Mine')).toBeTruthy());
    fireEvent.click(screen.getByTitle('delete'));
    await waitFor(() => expect(
      fn.mock.calls.some((c) => String(c[0]).includes('/api/workflows/mine') && c[1]?.method === 'DELETE')
    ).toBe(true));
  });
});
