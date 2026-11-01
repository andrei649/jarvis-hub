// @ts-nocheck
/* 2026-07-27 QA, finding F-02 — generalised. The HUD swallows rejections in 27 places
   (`.catch(() => {})`) plus inline catches on direct apiPost/apiPut/apiDelete calls, so a
   failed admin action left no trace anywhere: the run pressed HALT ALL, the kernel
   answered 403, and the card kept reading "ARMED · operational".

   Patching call sites cannot fix the class — a new silent catch is one line away. The
   failure is therefore recorded in api/client.ts where it is CREATED, before it is
   thrown, and surfaced once by ActionFailureBanner. These tests pin that contract:
   a swallowed mutation is still visible, and a GET is still not noise. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { apiGet, apiPost, apiPut, apiDelete, actionFailures, clearActionFailures } from '../api/client';
import { ActionFailureBanner } from '../gap';

beforeEach(() => {
  clearActionFailures();
  try { localStorage.clear(); } catch { /* ignore */ }
});

function mockStatus(status) {
  global.fetch = vi.fn().mockResolvedValue({ ok: status < 400, status, json: async () => ({}) });
}

describe('failed-mutation sink — a swallowed action still leaves a trace', () => {
  it('records a POST that the caller swallows', async () => {
    mockStatus(403);
    // exactly what 27 call sites do today
    await apiPost('/api/security/kill-switch', { engage: true }).catch(() => {});
    const f = actionFailures();
    expect(f.length).toBe(1);
    expect(f[0]).toMatchObject({ method: 'POST', path: '/api/security/kill-switch', status: 403 });
  });

  it('records PUT and DELETE too, newest first', async () => {
    mockStatus(500);
    await apiPut('/api/notes', { content: 'x' }).catch(() => {});
    await apiDelete('/api/memory/spaces/x').catch(() => {});
    const f = actionFailures();
    expect(f.map((x) => x.method)).toEqual(['DELETE', 'PUT']);
  });

  it('still throws, so existing callers behave exactly as before', async () => {
    mockStatus(403);
    await expect(apiPost('/api/x', {})).rejects.toThrow(/403/);
  });

  /* Review of #1321: a queued owner approval answers 422 approval_required with its task
     id. A caller that names that answer gets the body back and the Console banner no longer
     reports a FAILED action for a task that was just created; any other refusal still is. */
  it('returns a refusal the caller accepts without recording it', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 422,
      json: async () => ({ ok: false, reason: 'approval_required', task_id: 7 }) });
    const accept = (status, body) => status === 422 && body?.reason === 'approval_required';
    await expect(apiPost('/api/toolrpc/call', {}, { accept })).resolves
      .toEqual({ ok: false, reason: 'approval_required', task_id: 7 });
    expect(actionFailures().length).toBe(0);
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 422,
      json: async () => ({ ok: false, reason: 'tool_denied' }) });
    await expect(apiPost('/api/toolrpc/call', {}, { accept })).rejects
      .toMatchObject({ status: 422, body: { reason: 'tool_denied' } });
    expect(actionFailures()).toHaveLength(1);
  });

  it('does NOT record GETs — panels surface those, polling would drown the signal', async () => {
    mockStatus(500);
    await apiGet('/api/swarm/summary').catch(() => {});
    expect(actionFailures().length).toBe(0);
  });

  /* BLOCKER-hud (b) — apiPost threw before anyone could read the body, so NO call site
     could show the server's own refusal reason and one caller invented a plausible-looking
     cause instead. The parsed body now rides along on the thrown error; `message` and
     `status` are unchanged, so every existing caller behaves exactly as before. */
  it('attaches the parsed refusal body to the thrown error', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false, status: 409, json: async () => ({ status: 'refused', reason: 'reuse_available' }),
    });
    const err = await apiPost('/api/acquisition/x/drive', {}).catch((e) => e);
    expect(err.status).toBe(409);
    expect(err.message).toBe('POST /api/acquisition/x/drive -> 409');
    expect(err.body).toEqual({ status: 'refused', reason: 'reuse_available' });
  });

  it('still throws with no body attached when the error body is not JSON', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false, status: 502, json: async () => { throw new SyntaxError('Unexpected token <'); },
    });
    const err = await apiPost('/api/x', {}).catch((e) => e);
    expect(err.status).toBe(502);
    expect(err.body).toBeUndefined();
    expect(actionFailures()[0]).toMatchObject({ method: 'POST', path: '/api/x', status: 502 });
  });

  it('records nothing on success', async () => {
    mockStatus(200);
    await apiPost('/api/x', {});
    expect(actionFailures().length).toBe(0);
  });
});

describe('ActionFailureBanner — the one place it becomes visible', () => {
  it('renders nothing until something fails', () => {
    const { container } = render(<ActionFailureBanner />);
    expect(container.textContent).toBe('');
  });

  it('announces a failure with its route and status, and can be dismissed', async () => {
    mockStatus(403);
    render(<ActionFailureBanner />);
    await apiPost('/api/security/kill-switch', { engage: true }).catch(() => {});
    const alert = await waitFor(() => screen.getByRole('alert'));
    expect(alert.textContent).toMatch(/1 action FAILED/);
    expect(alert.textContent).toMatch(/the change did not happen/);
    expect(alert.textContent).toMatch(/\/api\/security\/kill-switch/);
    expect(alert.textContent).toMatch(/403/);
    expect(alert.textContent).toMatch(/refused/);
    fireEvent.click(screen.getByText('dismiss'));
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });

  it('pluralises and keeps counting across several failures', async () => {
    mockStatus(500);
    render(<ActionFailureBanner />);
    await apiPost('/api/a', {}).catch(() => {});
    await apiPost('/api/b', {}).catch(() => {});
    const alert = await waitFor(() => screen.getByRole('alert'));
    expect(alert.textContent).toMatch(/2 actions FAILED/);
  });
});
