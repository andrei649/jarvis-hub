// @ts-nocheck
/* TRUST OPS — the safety properties of a destructive control, pinned.

   /api/admin/rotate-tokens invalidates live tokens and is not reversible: the panel's own
   copy says "the old token does not come back", and there is no read route for token state
   (list_tokens is CLI-only), so an accidental rotation cannot even be diagnosed from the
   HUD. That makes the confirm gate a real safety boundary rather than a nicety, and it is
   the thing most likely to be quietly loosened by a later edit — so it is tested here.

   1. The button is inert until the operator types the scope back exactly. A disabled
      button is not enough on its own: the handler ALSO returns early on !rotateReady, and
      this test asserts no request is made even when the click is forced.
   2. Changing the scope re-arms the gate. Otherwise "type admin, switch to user, click"
      would rotate a scope the operator never confirmed.
   3. A refusal renders AS a refusal. apiPost throws on 4xx, so a `.then(r => r.error…)`
      branch would be dead code; the test asserts the backend's own detail string reaches
      the screen and that no rotated-token success line appears next to it. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

const apiGet = vi.fn();
const apiPost = vi.fn();
vi.mock('../api/client', () => ({
  apiGet: (...a: any[]) => apiGet(...a),
  apiPost: (...a: any[]) => apiPost(...a),
  apiPut: vi.fn(), apiPatch: vi.fn(), apiDelete: vi.fn(),
  actionFailures: () => [], onActionFailure: () => () => {}, clearActionFailures: vi.fn(),
}));

import { TrustOpsPanel } from './trust-ops';

const ROTATE = '/api/admin/rotate-tokens';

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  // the broker read this panel does on mount; irrelevant to the rotation gate
  apiGet.mockResolvedValue({ available: false, reason: 'not configured' });
});

const rotateCalls = () => apiPost.mock.calls.filter((c) => c[0] === ROTATE);

describe('TRUST OPS · rotate-tokens confirm gate', () => {
  it('does not rotate until the scope is typed back exactly', async () => {
    render(<TrustOpsPanel />);
    const btn = await screen.findByLabelText('Rotate tokens for the selected scope');

    expect((btn as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(btn);                       // forced click, gate must still hold
    expect(rotateCalls()).toHaveLength(0);

    const confirm = screen.getByLabelText('type the scope to confirm');
    fireEvent.change(confirm, { target: { value: 'admi' } });   // near miss
    expect((btn as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(btn);
    expect(rotateCalls()).toHaveLength(0);

    fireEvent.change(confirm, { target: { value: 'admin' } });  // exact
    expect((btn as HTMLButtonElement).disabled).toBe(false);

    apiPost.mockResolvedValueOnce({ ok: true, scope: 'admin', token: 'tok-new' });
    fireEvent.click(btn);
    await waitFor(() => expect(rotateCalls()).toHaveLength(1));
    expect(rotateCalls()[0][1]).toMatchObject({ scope: 'admin' });
  });

  it('re-arms the gate when the scope changes, so a stale confirm cannot fire', async () => {
    render(<TrustOpsPanel />);
    const btn = await screen.findByLabelText('Rotate tokens for the selected scope');
    const confirm = screen.getByLabelText('type the scope to confirm');

    fireEvent.change(confirm, { target: { value: 'admin' } });
    expect((btn as HTMLButtonElement).disabled).toBe(false);

    // switching scope must clear the confirmation, not carry it over
    fireEvent.change(screen.getByLabelText('rotation scope'), { target: { value: 'user' } });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(btn);
    expect(rotateCalls()).toHaveLength(0);
  });

  it('renders a refusal as a refusal, never under a success line', async () => {
    render(<TrustOpsPanel />);
    const btn = await screen.findByLabelText('Rotate tokens for the selected scope');
    fireEvent.change(screen.getByLabelText('type the scope to confirm'), { target: { value: 'admin' } });

    // apiPost THROWS on 4xx and carries the parsed body on err.body
    const err: any = new Error('HTTP 403');
    err.status = 403;
    err.body = { detail: 'admin token required' };
    apiPost.mockRejectedValueOnce(err);

    fireEvent.click(btn);
    await waitFor(() => expect(rotateCalls()).toHaveLength(1));

    // the backend's own words reach the screen
    await screen.findByText(/admin token required/);
    // and nothing claims a token was issued
    expect(screen.queryByText(/tok-new/)).toBeNull();
  });
});
