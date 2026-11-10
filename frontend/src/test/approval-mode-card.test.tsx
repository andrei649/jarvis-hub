// @ts-nocheck
/* H484 — the approval card says which approval mode a task was held under, so the owner
   knows why they are being asked. The backend sends, on every waiting task,
   `approval_mode` ({effective, source, global}: the mode in force NOW) and, when the
   worker recorded it, `asked_under` ({mode, source, global, by_mode}: the mode in force
   when the task was held, and whether the mode itself is why it asks). The card states
   only what is known: a recorded mode is reported as recorded; without one it reports
   today's mode and says the earlier one is not known. Fail-closed: anything that is not
   one of the three modes shows nothing, never a guessed mode. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen } from '@testing-library/react';
import { DecisionInboxPanel } from '../gap';
import { ContextColumn } from '../shell';
import { approvalModeNote, decisionCard } from '../api/loaders';

const t = new Proxy({}, { get: (_target, key) => String(key) });
const now = (effective, source = 'global', overall = effective) => ({ effective, source, global: overall });
const asked = (mode, by_mode, source = 'global', overall = mode) => ({ mode, source, global: overall, by_mode });

describe('approvalModeNote', () => {
  it('reports the recorded mode, and whether the mode is why the task waits', () => {
    expect(approvalModeNote(now('auto'), asked('ask', true))).toEqual({
      label: 'asked under ask',
      why: 'Held because the approval mode was ask when this was queued: anything with a side effect waits for you. The mode is auto now.',
    });
    expect(approvalModeNote(now('off'), asked('off', true)).why)
      .toBe('Held because the approval mode was off when this was queued: nothing a machine approved runs.');
    expect(approvalModeNote(now('auto'), asked('auto', false))).toEqual({
      label: 'asked under auto',
      why: 'Queued under approval mode auto. The mode is not why it waits: its risk tier, a money cap or a safety check is.',
    });
    expect(approvalModeNote(now('ask'), asked('ask', true, 'agent', 'auto')).label)
      .toBe('asked under ask · agent override');
  });

  it('without a recorded mode it reports only the mode now, and says so', () => {
    expect(approvalModeNote(now('ask'))).toEqual({
      label: 'mode now ask',
      why: 'Approval mode is ask now. The mode in force when this was queued was not recorded, so it may not be why this waits.',
    });
    expect(approvalModeNote(now('off', 'agent', 'auto')).label).toBe('mode now off · agent override');
    expect(approvalModeNote(now('auto'), { mode: 'yolo', by_mode: true }).label).toBe('mode now auto');
  });

  it('never claims that auto always asks for the irreversible tier', () => {
    for (const mode of ['auto', 'ask', 'off']) {
      for (const note of [approvalModeNote(now(mode)), approvalModeNote(now(mode), asked(mode, true)),
        approvalModeNote(now(mode), asked(mode, false))]) {
        expect(note.why).not.toMatch(/always ask/);
        expect(note.why).not.toMatch(/because of its risk tier\.$/);
      }
    }
  });

  it('shows nothing for a value that is not a mode', () => {
    for (const bad of [null, undefined, 'ask', {}, { effective: 'yolo' }, { effective: true }, { effective: 'ASK' }]) {
      expect(approvalModeNote(bad)).toBeNull();
    }
    // A recorded mode alone is enough to report it.
    expect(approvalModeNote(null, asked('ask', true)).label).toBe('asked under ask');
  });
});

describe('the cockpit decision card', () => {
  it('carries the mode of the task it was projected from', () => {
    const card = decisionCard({ id: 7, agent: 'friday', kind: 'comms.send', title: 'Send it', reversible: false,
      approval_mode: now('auto'), asked_under: asked('ask', true, 'agent', 'auto') });
    expect(card.mode.label).toBe('asked under ask · agent override');
    expect(decisionCard({ id: 8, kind: 'file.write', title: 'x', reversible: true }).mode).toBeNull();
  });

  it('renders the mode line, and none for a card without one', () => {
    const decisions = [
      { ...decisionCard({ id: 1, agent: 'friday', kind: 'k', title: 'first', reversible: true,
        approval_mode: now('off'), asked_under: asked('off', true) }), _id: 'a' },
      { ...decisionCard({ id: 2, agent: 'jarvis', kind: 'k', title: 'second', reversible: true }), _id: 'b' },
    ];
    const { container } = render(<ContextColumn decisions={decisions} onDecision={() => {}} t={t} />);
    const cards = [...container.querySelectorAll('.dcard')];
    expect(cards[0].querySelector('.dm').textContent).toBe('asked under off');
    expect(cards[0].querySelector('.dm').getAttribute('title')).toContain('nothing a machine approved runs');
    expect(cards[1].querySelector('.dm')).toBeNull();
  });
});

describe('Decision Inbox', () => {
  beforeEach(() => {
    try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'admin-secret'); } catch { /* ignore */ }
    global.fetch = vi.fn((url) => {
      const reply = (body) => ({ ok: true, status: 200, json: async () => body });
      if (String(url).includes('/autonomy/tasks')) {
        return Promise.resolve(reply({ total: 3, tasks: [
          { id: 11, agent: 'friday', kind: 'note.write', title: 'Write the note', risk_tier: 1, status: 'blocked',
            approval_mode: now('auto'), asked_under: asked('ask', true, 'agent', 'auto') },
          { id: 12, agent: 'jarvis', kind: 'note.write', title: 'Older hub card', risk_tier: 1, status: 'blocked' },
          { id: 13, agent: 'jarvis', kind: 'note.write', title: 'Unrecorded card', risk_tier: 1, status: 'blocked',
            approval_mode: now('ask') },
        ] }));
      }
      return Promise.resolve(reply({}));
    });
  });

  it('shows the mode each approval card was asked under, or only the mode now', async () => {
    render(<DecisionInboxPanel />);
    await screen.findByText('Write the note');
    const tag = screen.getByLabelText('Approval mode for Write the note');
    expect(tag.textContent).toBe('asked under ask · agent override');
    expect(tag.getAttribute('title')).toContain('The mode is auto now.');
    expect(screen.queryByLabelText('Approval mode for Older hub card')).toBeNull();
    expect(screen.getByLabelText('Approval mode for Unrecorded card').textContent).toBe('mode now ask');
  });
});
