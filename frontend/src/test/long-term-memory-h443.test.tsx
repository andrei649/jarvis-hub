// @ts-nocheck
/* H443 — the Long-Term Memory panel lists the memory writes the post-turn review holds for
   the owner (GET /api/memory/proposals, as the admin), with each fact and why it waits,
   approves or rejects one (POST /api/memory/proposals/{id}/decide) and reports what the
   hub answered, and switches memory.write_approval (POST /api/memory/approval) while
   saying what the gate does not hold. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import {
  APPROVAL_PATH, CORE_PATH, LongTermMemoryPanel, PROPOSALS_PATH, STATUS_PATH, decidePath, decisionMessage,
} from '../panels/long-term-memory';

let calls;
let held;
let decideReply;
let approvalReply;

function reply(code, data) {
  return { ok: code < 400, status: code, json: async () => data, text: async () => JSON.stringify(data) };
}

const proposal = (over = {}) => ({
  id: 'mp-1', origin: 'background_review', session_id: 'tg-1', reason: 'untrusted_content', tainted: true,
  status: 'pending', ts: 1, card: 'c1',
  operations: [{ target: 'user', text: 'prefers green tea' }, { target: 'memory', text: 'the repo builds with uv' }],
  ...over,
});

beforeEach(() => {
  cleanup();
  localStorage.setItem('hud.admin_token', 'adm');
  calls = [];
  held = () => reply(200, { available: true, write_approval: false, pending: [proposal()], decided: [], pending_ttl_days: 14 });
  decideReply = (body) => reply(200, {
    ok: true, applied: body.approved, status: body.approved ? 'applied' : 'rejected', written: body.approved ? 1 : 0,
    proposal: proposal({ status: body.approved ? 'applied' : 'rejected',
                         operations: [{ target: 'user', text: 'prefers green tea', outcome: 'added' },
                                      { target: 'memory', text: 'the repo builds with uv', outcome: 'refused' }] }),
  });
  approvalReply = (body) => reply(200, { ok: true, enabled: body.enabled, changed: true, audited: true, write_approval: body.enabled });
  global.fetch = vi.fn(async (url, init = {}) => {
    const u = String(url);
    const body = init.body ? JSON.parse(init.body) : undefined;
    const headers = init.headers || {};
    calls.push({ url: u, method: init.method || 'GET', body, admin: headers['X-Admin-Token'] });
    if (u.endsWith(decidePath('mp-1'))) return decideReply(body);
    if (u.endsWith(APPROVAL_PATH)) return approvalReply(body);
    if (u.endsWith(PROPOSALS_PATH)) return held();
    if (u.endsWith(CORE_PATH)) return reply(200, { enabled: true, memory: [], user: [], undoable: [] });
    if (u.endsWith(STATUS_PATH)) return reply(200, { available: true, enabled: true, switch: true, stores: {} });
    return reply(404, {});
  });
});

describe('LongTermMemoryPanel — H443 held memory writes', () => {
  it('reads the held writes as the admin and shows each fact, its ring and why it waits', async () => {
    render(<LongTermMemoryPanel />);
    await waitFor(() => expect(screen.getByText('prefers green tea')).toBeTruthy());
    const read = calls.find((c) => c.url.endsWith(PROPOSALS_PATH));
    expect(read.method).toBe('GET');
    expect(read.admin).toBe('adm');
    expect(screen.getByText('HELD MEMORY WRITES · 1')).toBeTruthy();
    expect(screen.getByText('the repo builds with uv')).toBeTruthy();
    expect(screen.getByText(/background review · the conversation read untrusted content, or was not watched from its start/)).toBeTruthy();
    expect(screen.getByText(/read each fact as a claim, not as yours/)).toBeTruthy();
    // The gate's state, and what it does not hold, in so many words.
    expect(screen.getByText(/write approval is off: the post-turn review and \/refine write on their own, except from a conversation that read untrusted content or was not watched from its start\./)).toBeTruthy();
    expect(screen.getByText(/The model's memory tool and \/api\/memory\/remember are not held by it\./)).toBeTruthy();
  });

  it('approves one and says what landed and what a ring refused, never just "approved"', async () => {
    render(<LongTermMemoryPanel />);
    await waitFor(() => expect(screen.getByLabelText('approve mp-1')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('approve mp-1'));
    await waitFor(() => expect(screen.getByRole('status').textContent)
      .toBe('approved · 1 written (written · refused: the ring is full or the fact too long)'));
    const post = calls.find((c) => c.url.endsWith(decidePath('mp-1')));
    expect(post.method).toBe('POST');
    expect(post.body).toEqual({ approved: true });
    expect(post.admin).toBe('adm');
    expect(calls.filter((c) => c.url.endsWith(PROPOSALS_PATH)).length).toBeGreaterThan(1);   // re-read
  });

  it('rejects one and says nothing was written', async () => {
    render(<LongTermMemoryPanel />);
    await waitFor(() => expect(screen.getByLabelText('reject mp-1')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('reject mp-1'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('rejected · nothing written'));
    expect(calls.find((c) => c.url.endsWith(decidePath('mp-1'))).body).toEqual({ approved: false });
  });

  it('shows a refusal in the hub\'s own terms: approved but not written yet', async () => {
    decideReply = () => reply(409, { ok: false, reason: 'apply_incomplete', status: 'applying',
                                     proposal: proposal({ status: 'applying' }) });
    render(<LongTermMemoryPanel />);
    await waitFor(() => expect(screen.getByLabelText('approve mp-1')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('approve mp-1'));
    await waitFor(() => expect(screen.getByRole('status').textContent)
      .toBe('approved, nothing written · not written yet · not written yet'));
  });

  it('switches the gate through its own route and reports what the hub then reads', async () => {
    render(<LongTermMemoryPanel />);
    await waitFor(() => expect(screen.getByText('switch write approval on')).toBeTruthy());
    fireEvent.click(screen.getByText('switch write approval on'));
    fireEvent.click(screen.getByText('confirm on'));
    await waitFor(() => expect(screen.getByRole('status').textContent)
      .toBe("write approval on · the review's and /refine's memory writes now wait for you"));
    const post = calls.find((c) => c.url.endsWith(APPROVAL_PATH));
    expect(post.body).toEqual({ enabled: true });
    expect(post.admin).toBe('adm');

    approvalReply = () => reply(503, { ok: false, reason: 'memory_approval_not_saved', error: 'the gate was not changed', write_approval: true });
    held = () => reply(200, { available: true, write_approval: true, pending: [], decided: [] });
    cleanup();
    render(<LongTermMemoryPanel />);
    await waitFor(() => expect(screen.getByText('switch write approval off')).toBeTruthy());
    expect(screen.getByText('none waiting')).toBeTruthy();
    fireEvent.click(screen.getByText('switch write approval off'));
    fireEvent.click(screen.getByText('confirm off'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('not switched · the gate was not changed'));
  });

  it('says so when the held writes cannot be read, instead of showing none', async () => {
    held = () => reply(403, { error: 'admin required' });
    render(<LongTermMemoryPanel />);
    await waitFor(() => expect(screen.getByText(/held memory writes could not be read/)).toBeTruthy());
    expect(screen.queryByText('none waiting')).toBeNull();
  });

  it('words a decision from the reply alone', () => {
    expect(decisionMessage({ applied: false, status: 'failed', proposal: { operations: [{ outcome: 'memory_off' }] } }, true))
      .toBe('approved, nothing written · not written: memory is off');
    expect(decisionMessage({ reason: 'not_pending:applied' }, false)).toBe('not rejected · not_pending:applied');
  });
});
