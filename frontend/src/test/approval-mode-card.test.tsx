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
import { approvalModeNote, decisionCard } from '../api/loaders';
import { parseDocketFeed } from '../docket/model';
import { whySentences } from '../docket/DocketEntry';
import { DOCKET_STRINGS } from '../docket/strings';

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

describe('the briefing wall\'s read-only decision card', () => {
  it('carries the mode of the task it was projected from', () => {
    const card = decisionCard({ id: 7, agent: 'friday', kind: 'comms.send', title: 'Send it', reversible: false,
      approval_mode: now('auto'), asked_under: asked('ask', true, 'agent', 'auto') });
    expect(card.mode.label).toBe('asked under ask · agent override');
    expect(decisionCard({ id: 8, kind: 'file.write', title: 'x', reversible: true }).mode).toBeNull();
  });
});

/* The cockpit's decision cards (the HUD v2 context column) were deleted with the classic shell; the
   docket is where a waiting task is decided now (PHASE_B_PLAN.md §5.4, §8.3), and its Why row says
   the same things, fail-closed, from its own words table. Docket.test.tsx draws them in an entry. */
describe('the docket entry\'s Why row', () => {
  const why = (task) => {
    const [entry] = parseDocketFeed({ tasks: [{ id: 1, kind: 'k', title: 'first', risk_tier: 1, ...task }] }).entries;
    return whySentences(entry.why, entry.pushed, DOCKET_STRINGS.en);
  };

  it('says a recorded mode is why it waits, and nothing for a task without one', () => {
    expect(why({ approval_mode: now('off'), asked_under: asked('off', true) }))
      .toEqual(['Held because the approval mode was Off when this was queued: nothing a machine approved runs.']);
    expect(why({})).toEqual([]);
  });

  it('without a recorded mode it says only the mode now, and that the earlier one is not known', () => {
    expect(why({ approval_mode: now('ask') }))
      .toEqual(['Approval mode is Ask now. The mode in force when this was queued was not recorded, so it may not be why this waits.']);
    expect(why({ approval_mode: now('ask', 'agent', 'auto') })).toContain('This agent has its own approval mode.');
  });

  it('says a recorded mode that is not why it waits, and a mode that moved since', () => {
    expect(why({ approval_mode: now('auto'), asked_under: asked('auto', false) }))
      .toEqual(['Queued under approval mode Auto. The mode is not why it waits: its risk tier, a money cap or a safety check is.']);
    expect(why({ approval_mode: now('auto'), asked_under: asked('ask', true) }))
      .toEqual(['Held because the approval mode was Ask when this was queued: anything with a side effect waits for you.', 'The mode is Auto now.']);
  });

  it('shows nothing for a value that is not a mode, never a guessed one', () => {
    for (const bad of ['ask', {}, { effective: 'yolo' }, { effective: true }, { effective: 'ASK' }]) {
      expect(why({ approval_mode: bad }), JSON.stringify(bad)).toEqual([]);
    }
    expect(why({ approval_mode: now('auto'), asked_under: { mode: 'yolo', by_mode: true } }))
      .toEqual(['Approval mode is Auto now. The mode in force when this was queued was not recorded, so it may not be why this waits.']);
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
