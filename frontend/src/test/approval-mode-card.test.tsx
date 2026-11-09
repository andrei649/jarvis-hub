// @ts-nocheck
/* H484 — the approval card says which approval mode applies to its agent right now, so
   the owner knows why they are being asked. The backend sends `approval_mode`
   ({effective, source, global}) on every waiting task; the HUD shows it on the Decision
   Inbox card and on the cockpit's decision card. Fail-closed: anything that is not one of
   the three modes shows nothing, never a guessed mode. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen } from '@testing-library/react';
import { DecisionInboxPanel } from '../gap';
import { ContextColumn } from '../shell';
import { approvalModeNote, decisionCard } from '../api/loaders';

const t = new Proxy({}, { get: (_target, key) => String(key) });

describe('approvalModeNote', () => {
  it('names the mode and where it comes from', () => {
    expect(approvalModeNote({ effective: 'ask', source: 'global', global: 'ask' }))
      .toEqual({ label: 'mode ask', why: 'Approval mode is ask: anything with a side effect waits for you.' });
    expect(approvalModeNote({ effective: 'off', source: 'agent', global: 'auto' }))
      .toEqual({ label: 'mode off · agent override',
        why: 'Approval mode for this agent is off (the global mode is auto): nothing runs without you.' });
    expect(approvalModeNote({ effective: 'auto', source: 'global', global: 'auto' }).why)
      .toBe('Approval mode is auto: this waits because of its risk tier.');
  });

  it('shows nothing for a value that is not a mode', () => {
    for (const bad of [null, undefined, 'ask', {}, { effective: 'yolo' }, { effective: true }, { effective: 'ASK' }]) {
      expect(approvalModeNote(bad)).toBeNull();
    }
    // An override whose global is unreadable is still an honest "agent override".
    expect(approvalModeNote({ effective: 'ask', source: 'agent', global: 7 }).label).toBe('mode ask · agent override');
  });
});

describe('the cockpit decision card', () => {
  it('carries the mode of the task it was projected from', () => {
    const card = decisionCard({ id: 7, agent: 'friday', kind: 'comms.send', title: 'Send it', reversible: false,
      approval_mode: { effective: 'ask', source: 'agent', global: 'auto' } });
    expect(card.mode.label).toBe('mode ask · agent override');
    expect(decisionCard({ id: 8, kind: 'file.write', title: 'x', reversible: true }).mode).toBeNull();
  });

  it('renders the mode line, and none for a card without one', () => {
    const decisions = [
      { ...decisionCard({ id: 1, agent: 'friday', kind: 'k', title: 'first', reversible: true,
        approval_mode: { effective: 'off', source: 'global', global: 'off' } }), _id: 'a' },
      { ...decisionCard({ id: 2, agent: 'jarvis', kind: 'k', title: 'second', reversible: true }), _id: 'b' },
    ];
    const { container } = render(<ContextColumn decisions={decisions} onDecision={() => {}} t={t} />);
    const cards = [...container.querySelectorAll('.dcard')];
    expect(cards[0].querySelector('.dm').textContent).toBe('mode off');
    expect(cards[0].querySelector('.dm').getAttribute('title')).toContain('nothing runs without you');
    expect(cards[1].querySelector('.dm')).toBeNull();
  });
});

describe('Decision Inbox', () => {
  beforeEach(() => {
    try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'admin-secret'); } catch { /* ignore */ }
    global.fetch = vi.fn((url) => {
      const reply = (body) => ({ ok: true, status: 200, json: async () => body });
      if (String(url).includes('/autonomy/tasks')) {
        return Promise.resolve(reply({ total: 2, tasks: [
          { id: 11, agent: 'friday', kind: 'note.write', title: 'Write the note', risk_tier: 1, status: 'blocked',
            approval_mode: { effective: 'ask', source: 'agent', global: 'auto' } },
          { id: 12, agent: 'jarvis', kind: 'note.write', title: 'Older hub card', risk_tier: 1, status: 'blocked' },
        ] }));
      }
      return Promise.resolve(reply({}));
    });
  });

  it('shows the effective mode on each approval card that carries one', async () => {
    render(<DecisionInboxPanel />);
    await screen.findByText('Write the note');
    const tag = screen.getByLabelText('Approval mode for Write the note');
    expect(tag.textContent).toBe('mode ask · agent override');
    expect(tag.getAttribute('title')).toContain('the global mode is auto');
    expect(screen.queryByLabelText('Approval mode for Older hub card')).toBeNull();
  });
});
