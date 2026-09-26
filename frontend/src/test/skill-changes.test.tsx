// @ts-nocheck
/* H318 (review-H318b M-2) — the owner decides a skill change seeing all of it. The
   Decision Inbox lists GET /api/skills/proposals (admin): the whole diff built from the
   ledger, never cut, the flags and the drift, and decides the proposal's own card. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { SkillChangesInbox, decisionOutcome, originLabel, refusedByHub, SKILL_CHANGES_SHOWN } from '../panels/skill-changes';
import { DecisionInboxPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'admin'); } catch { /* ignore */ } });

const long = ['--- SKILL.md (now)', '+++ SKILL.md (proposed)', '@@ -1,1 +1,400 @@', '-Old.']
  .concat(Array.from({ length: 400 }, (_, i) => `+line ${i} of the new text`)).join('\n');
const change = { id: 'sp-1', skill: 'plan', origin: 'agent:friday', card: 'a7', diff: long, drifted: false, flags: [] };

describe('SkillChangesInbox', () => {
  it('shows the whole diff, not a cut of it, and who proposed it', () => {
    render(<SkillChangesInbox reply={{ proposals: [change] }} />);
    const diff = screen.getByTestId('skill-change-diff');
    expect(diff.textContent).toContain('+line 0 of the new text');
    expect(diff.textContent).toContain('+line 399 of the new text');       // the tail is there
    expect(screen.getByText('agent friday')).toBeTruthy();
    expect(screen.getByText("change to skill 'plan'")).toBeTruthy();
  });

  it('names what the change does beyond its text and a drifted skill', () => {
    render(<SkillChangesInbox reply={{ proposals: [{ ...change, flags: ['renames the skill'], drifted: true }] }} />);
    expect(screen.getByText('renames the skill')).toBeTruthy();
    expect(screen.getByText(/changed since · approving applies nothing/)).toBeTruthy();
  });

  it('approves through the proposal\'s own card and says what happened to the skill', async () => {
    const fn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ ok: true, action: {
      id: 'a7', status: 'approved', applied: { outcomes: [{ proposal_id: 'sp-1', ok: true, state: 'shown' }] } } }) });
    global.fetch = fn;
    const decided = vi.fn();
    render(<SkillChangesInbox reply={{ proposals: [change] }} onDecided={decided} />);
    fireEvent.click(screen.getByTitle('approve skill change'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('applied · the skill is shown'));
    const call = fn.mock.calls.find((c) => String(c[0]).includes('/api/actions/a7/decide'));
    expect(call[1].method).toBe('POST');
    expect(JSON.parse(call[1].body)).toEqual({ approved: true });
    expect(decided).toHaveBeenCalled();
  });

  it('cannot be decided without its card, and a failed read says so', () => {
    const { rerender } = render(<SkillChangesInbox reply={{ proposals: [{ ...change, card: null }] }} />);
    expect(screen.getByTitle('approve skill change').disabled).toBe(true);
    rerender(<SkillChangesInbox reply={null} error="403" />);
    expect(screen.getByText(/skill changes could not be read · 403/)).toBeTruthy();
  });

  it('shows at most SKILL_CHANGES_SHOWN and counts the rest', () => {
    const many = Array.from({ length: SKILL_CHANGES_SHOWN + 2 }, (_, i) => ({ ...change, id: `sp-${i}`, card: `a${i}` }));
    render(<SkillChangesInbox reply={{ proposals: many }} />);
    expect(screen.getAllByTestId('skill-change').length).toBe(SKILL_CHANGES_SHOWN);
    expect(screen.getByText('2 more after these are decided')).toBeTruthy();
  });
});

describe('decisionOutcome and originLabel', () => {
  it('reads every outcome the hub reports', () => {
    const reply = (o) => ({ action: { applied: { outcomes: [{ proposal_id: 'p', ...o }] } } });
    expect(decisionOutcome(reply({ ok: true, state: 'sandboxed' }), 'p', true)).toBe('applied · the skill is sandboxed');
    expect(decisionOutcome(reply({ ok: false, reason: 'bundled_skill' }), 'p', true))
      .toBe('not applied · a bundled skill cannot be changed here');
    expect(decisionOutcome(reply({ ok: false, reason: 'drifted_since_proposal' }), 'p', true))
      .toBe('not applied · the skill changed since the proposal');
    expect(decisionOutcome({ action: { note: 'this card is not a proposal\'s own approval card: no skill was changed' } }, 'p', true))
      .toMatch(/not a proposal's own/);
    expect(decisionOutcome({ action: {} }, 'p', false)).toBe('rejected · the skill is unchanged');
    expect(decisionOutcome({ action: { applied: { outcomes: [] } } }, 'p', true)).toBe('approved · not applied yet');
  });

  it('names the proposer', () => {
    expect(originLabel('agent:friday')).toBe('agent friday');
    expect(originLabel('refine')).toBe('/refine');
    expect(originLabel('background_review')).toBe('background review');
    expect(originLabel('')).toBe('unknown');
  });
});

describe('DecisionInboxPanel reads the skill changes', () => {
  it('asks for GET /api/skills/proposals with the admin token and shows the change', async () => {
    const fn = vi.fn(async (url) => ({ ok: true, status: 200, json: async () => (
      String(url).includes('/api/skills/proposals') ? { proposals: [change] } : { tasks: [] }) }));
    global.fetch = fn;
    render(<DecisionInboxPanel />);
    await waitFor(() => expect(screen.getByText("change to skill 'plan'")).toBeTruthy());
    const call = fn.mock.calls.find((c) => String(c[0]).includes('/api/skills/proposals'));
    const headers = call[1]?.headers || {};
    expect(headers['X-Admin-Token'] || headers['x-admin-token']).toBe('admin');
  });
});

// review-H318c: a refused change offers reject only; the hub's page counts the rest;
// the apply's new reasons are named.
describe('SkillChangesInbox, the third review', () => {
  it('offers reject only for a change the hub will refuse', () => {
    expect(refusedByHub({ flags: ['a bundled skill: it cannot be changed here'] })).toBe(true);
    expect(refusedByHub({ flags: ['renames the skill'] })).toBe(true);
    expect(refusedByHub({ flags: [] })).toBe(false);
    render(<SkillChangesInbox reply={{ proposals: [{ ...change, flags: ['renames the skill'] }] }} />);
    expect(screen.getByTitle(/the hub will refuse this change/).disabled).toBe(true);
    expect(screen.getByTitle('reject skill change').disabled).toBe(false);
  });

  it('counts the proposals the hub did not send', () => {
    render(<SkillChangesInbox reply={{ proposals: [change], more: 7 }} />);
    expect(screen.getByText(/SKILL CHANGES · 8 awaiting you/)).toBeTruthy();
    expect(screen.getByText(/7 more after these are decided/)).toBeTruthy();
  });

  it('names a renewal that failed or a missing key', () => {
    const reply = (reason) => ({ action: { applied: { outcomes: [{ proposal_id: 'p', ok: false, reason }] } } });
    expect(decisionOutcome(reply('changed_during_apply'), 'p', true)).toMatch(/files changed while it was applied/);
    expect(decisionOutcome(reply('standing_not_renewed'), 'p', true)).toMatch(/could not be renewed/);
    expect(decisionOutcome(reply('signing_key_missing'), 'p', true)).toMatch(/signing key/);
    // review-H318d n-2: a rollback that failed says the new text stays
    expect(decisionOutcome(reply('rollback_failed'), 'p', true)).toMatch(/the new text stays/);
  });

  it('names a signature that could not be put back, an unreadable skill and a failed apply', () => {
    const reply = (reason) => ({ action: { applied: { outcomes: [{ proposal_id: 'p', ok: false, reason }] } } });
    // review-H318e n-1: the old text is back, its signature is not
    expect(decisionOutcome(reply('signature_not_restored'), 'p', true)).toMatch(/the old text is back, but not its old signature/);
    expect(decisionOutcome(reply('unreadable_skill'), 'p', true)).toMatch(/cannot be read/);
    expect(decisionOutcome(reply('apply_error'), 'p', true)).toMatch(/could not be applied/);
    // review-H318f n-1: a signature read that failed is retried, not given up
    expect(decisionOutcome(reply('unreadable_signature'), 'p', true)).toMatch(/tried again at the next pass/);
  });
});
