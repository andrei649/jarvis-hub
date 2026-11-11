// @ts-nocheck
/* H665 — several skills edited in one atomic batch. The Decision Inbox lists the batches
   the agent proposed (GET /api/skills/batches, admin) with every file's diff and decides
   the batch's own card; the owner's editor checks a batch with a dry run and applies
   exactly what was checked (POST /api/skills/batch); a refusal shows the hub's lesson. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { SkillBatchEditor, SkillBatchesInbox, batchOutcome, parseOperations, referenceLine } from '../panels/skill-batches';
import { DecisionInboxPanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'admin'); } catch { /* ignore */ } });

const batch = {
  id: 'sb-1', origin: 'agent:friday', card: 'c9', skills: ['alpha', 'gamma'],
  operations: [{ name: 'alpha', action: 'patch' }, { name: 'gamma', action: 'create' }],
  preview: [
    { name: 'alpha', change: 'changed', files: [{ file: 'SKILL.md', change: 'changed', diff: '--- a\n+++ b\n-Do it.\n+Done.' }] },
    { name: 'gamma', change: 'created', files: [{ file: 'SKILL.md', change: 'added', diff: '+++ b\n+name: gamma' }] },
  ],
};

const ok = (body) => ({ ok: true, status: 200, json: async () => body });

describe('SkillBatchesInbox', () => {
  it('shows every touched skill and its diffs, and who proposed it', () => {
    render(<SkillBatchesInbox reply={{ batches: [batch] }} />);
    expect(screen.getByText('SKILL BATCHES · 1 awaiting you')).toBeTruthy();
    expect(screen.getByText('2 operation(s) on alpha, gamma')).toBeTruthy();
    expect(screen.getAllByTestId('skill-batch-skill').length).toBe(2);
    expect(screen.getAllByTestId('skill-change-diff')[0].textContent).toContain('+Done.');
    expect(screen.getByText('agent friday')).toBeTruthy();
  });

  it('approves through the batch\'s own card and says what was applied', async () => {
    const fn = vi.fn().mockResolvedValue(ok({ ok: true, action: { id: 'c9', applied: {
      ok: true, skills: [{ name: 'alpha', change: 'changed' }, { name: 'gamma', change: 'created' }] } } }));
    global.fetch = fn;
    const decided = vi.fn();
    render(<SkillBatchesInbox reply={{ batches: [batch] }} onDecided={decided} />);
    fireEvent.click(screen.getByTitle('approve skill batch'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('applied · alpha changed, gamma created'));
    const call = fn.mock.calls.find((c) => String(c[0]).includes('/api/actions/c9/decide'));
    expect(JSON.parse(call[1].body)).toEqual({ approved: true });
    expect(decided).toHaveBeenCalled();
  });

  it('folds a long diff behind its line count and opens it whole (review-H665 r3)', () => {
    const lines = Array.from({ length: 600 }, (_, i) => `+- step ${i}: an ordinary line of a real skill`);
    const diff = ['--- SKILL.md (now)', '+++ SKILL.md (after)', '@@ -0,0 +1,600 @@', ...lines].join('\n');
    const long = { ...batch, preview: [{ name: 'gamma', change: 'created',
      files: [{ file: 'SKILL.md', change: 'added', diff }] }] };
    render(<SkillBatchesInbox reply={{ batches: [long] }} />);
    const fold = screen.getByTestId('skill-batch-long-diff');
    expect(fold.textContent).toContain('added SKILL.md · 603 lines · show the whole diff');
    // review-H665 r4: a folded diff builds no lines until the owner opens it.
    expect(screen.queryByTestId('skill-change-diff')).toBeNull();
    (fold as HTMLDetailsElement).open = true;
    fireEvent(fold, new Event('toggle'));
    const shown = screen.getByTestId('skill-change-diff').textContent;
    expect(shown).toContain('+- step 0:');
    expect(shown).toContain('+- step 599:');                      // every line, none cut
  });

  it('says when the hub cut a diff short, and whether added text is missing', () => {
    const cut = { ...batch, preview: [{ name: 'alpha', change: 'deleted', files: [
      { file: 'SKILL.md', change: 'removed', diff: '-old', diff_truncated: true }] }] };
    render(<SkillBatchesInbox reply={{ batches: [cut] }} />);
    expect(screen.getByText('cut short · only removed or unchanged lines omitted')).toBeTruthy();
  });

  it('says which touched skill the owner has pinned (H349)', () => {
    const pinned = { ...batch, preview: [
      { name: 'alpha', change: 'changed', pinned: true, files: [{ file: 'SKILL.md', change: 'changed', diff: '+x' }] },
      { name: 'beta', change: 'changed', files: [{ file: 'SKILL.md', change: 'changed', diff: '+y' }] }] };
    render(<SkillBatchesInbox reply={{ batches: [pinned] }} />);
    const rows = screen.getAllByTestId('skill-batch-skill');
    expect(rows[0].textContent).toContain('alpha · changed · pinned by you');
    expect(rows[1].textContent).not.toContain('pinned');
  });

  it('cannot be decided without a card, and a failed read says so', () => {
    const { rerender } = render(<SkillBatchesInbox reply={{ batches: [{ ...batch, card: null }] }} />);
    expect(screen.getByTitle('approve skill batch').disabled).toBe(true);
    rerender(<SkillBatchesInbox reply={null} error="403" />);
    expect(screen.getByText(/skill batches could not be read · 403/)).toBeTruthy();
  });
});

describe('batchOutcome and parseOperations', () => {
  it('reads what a decision did', () => {
    expect(batchOutcome({ action: { applied: { ok: false, reason: 'skill_batch_drifted', detail: "'alpha' changed" } } }, true))
      .toBe("not applied · 'alpha' changed");
    expect(batchOutcome({ action: { applied: { ok: true, status: 'rejected' } } }, false)).toBe('rejected · no skill changed');
    expect(batchOutcome({ action: {} }, true)).toBe('approved · not applied yet');
    expect(batchOutcome({ action: { note: 'skill batches are not available' } }, true)).toBe('skill batches are not available');
  });

  it('takes a list or {operations}, nothing else', () => {
    expect(parseOperations('[{"name":"a","action":"delete"}]')).toEqual([{ name: 'a', action: 'delete' }]);
    expect(parseOperations('{"operations":[{"name":"a","action":"delete"}]}')).toHaveLength(1);
    expect(parseOperations('[]')).toBeNull();
    expect(parseOperations('{nope')).toBeNull();
  });
});

describe('SkillBatchEditor', () => {
  const ops = '[{"name":"alpha","action":"patch","old_string":"Do it.","new_string":"Done."}]';

  it('applies only the batch it checked', async () => {
    const fn = vi.fn(async (url, init) => {
      const body = JSON.parse(init.body);
      return ok(body.dry_run
        ? { ok: true, dry_run: true, skills: [{ name: 'alpha', change: 'changed', files: [{ file: 'SKILL.md', diff: '+Done.' }] }] }
        : { ok: true, applied: true, skills: [{ name: 'alpha', change: 'changed' }] });
    });
    global.fetch = fn;
    const applied = vi.fn();
    render(<SkillBatchEditor onApplied={applied} />);
    const box = screen.getByLabelText('skill batch operations');
    fireEvent.change(box, { target: { value: ops } });
    expect(screen.getByTitle('apply exactly the checked batch').disabled).toBe(true);
    fireEvent.click(screen.getByText('check'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/^checked · 1 skill/));
    expect(screen.getByTestId('skill-change-diff').textContent).toContain('+Done.');
    fireEvent.click(screen.getByTitle('apply exactly the checked batch'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('applied · alpha changed'));
    const calls = fn.mock.calls.filter((c) => String(c[0]).includes('/api/skills/batch'));
    expect(calls.map((c) => JSON.parse(c[1].body).dry_run)).toEqual([true, false]);
    expect(applied).toHaveBeenCalled();
    // an edit after the check needs a new check
    fireEvent.change(box, { target: { value: ops.replace('Done.', 'Done!') } });
    expect(screen.getByTitle('apply exactly the checked batch').disabled).toBe(true);
  });

  it('shows the hub\'s lesson for a refused batch', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({
      ok: false, reason: 'skill_batch_patch_no_match', detail: "old_string is not in 'SKILL.md' of 'alpha'",
      failed_op: { index: 0, action: 'patch', name: 'alpha' }, hints: ['the closest line is 7: \'Do it now.\''],
      file_preview: { skill: 'alpha', path: 'SKILL.md', content: '   7| Do it now.' }, rolled_back: [] }) });
    render(<SkillBatchEditor />);
    fireEvent.change(screen.getByLabelText('skill batch operations'), { target: { value: ops } });
    fireEvent.click(screen.getByText('check'));
    await waitFor(() => expect(screen.getByTestId('skill-batch-lesson')).toBeTruthy());
    const lesson = screen.getByTestId('skill-batch-lesson').textContent;
    expect(lesson).toContain('operation 0 · patch · alpha');
    expect(lesson).toContain('the closest line is 7');
    expect(lesson).toContain('alpha/SKILL.md');
    expect(screen.getByRole('status').textContent).toMatch(/^refused · /);
  });
});

describe('H330 — a delete, what absorbs it, and what still names it', () => {
  const refs = [{
    skill: 'alpha', absorbed_into: 'omega',
    migrated: [
      { holder: 'skill', name: 'rel', field: 'related_skills' },
      { holder: 'skill', name: 'omega', field: 'related_skills', dropped: true },
      { holder: 'bundle', name: 'research', slug: 'research', before: ['alpha', 'beta'], after: ['omega', 'beta'] },
      { holder: 'bundle', name: 'private', slug: 'private', before: ['alpha'], after: ['omega'], hidden_members: 1 },
    ],
    left: [
      { holder: 'skill', name: 'prose', field: 'text', file: 'SKILL.md', lines: [7] },
      { holder: 'job', id: 'j1', name: 'Daily', field: 'prompt', lines: [1] },
      { holder: 'load_set', setting: 'loadset.skills_only', skill: 'alpha',
        warning: "'omega' is not in skills_only, so it does not load after a restart" },
    ],
    hidden: 2,
  }];

  it('shows the inbox owner what moves and what is left beside the diffs', () => {
    const deleting = { ...batch, operations: [{ name: 'alpha', action: 'delete', absorbed_into: 'omega' }],
      references: refs };
    render(<SkillBatchesInbox reply={{ batches: [deleting] }} />);
    const text = screen.getByTestId('skill-batch-references').textContent;
    expect(text).toContain('alpha deleted · absorbed into omega');
    expect(text).toContain('skill rel · related_skills now names omega');
    expect(text).toContain('skill omega · related_skills no longer lists alpha');
    expect(text).toContain('bundle research: alpha, beta → omega, beta');
    expect(text).toContain('bundle private: alpha → omega (and 1 member(s) the agent cannot see, kept)');
    expect(text).toContain('still names it: skill prose · SKILL.md line 7');
    expect(text).toContain('still names it: job Daily (j1) · prompt');
    expect(text).toContain("'omega' is not in skills_only");
    expect(text).toContain('2 skill(s) the agent cannot see name it too');
  });

  it('shows the editor the same report after a check', async () => {
    global.fetch = vi.fn(async () => ok({ ok: true, dry_run: true, skills: [], references: refs }));
    render(<SkillBatchEditor />);
    fireEvent.change(screen.getByLabelText('skill batch operations'),
      { target: { value: '[{"name":"alpha","action":"delete","absorbed_into":"omega"}]' } });
    fireEvent.click(screen.getByText('check'));
    await waitFor(() => expect(screen.getByTestId('skill-batch-references')).toBeTruthy());
    expect(screen.getByTestId('skill-batch-references').textContent).toContain('absorbed into omega');
  });

  it('words every holder', () => {
    expect(referenceLine({ holder: 'bundle', name: 'r', member: 'alpha', why: 'no absorbing skill named' }))
      .toBe('bundle r · lists alpha · no absorbing skill named');
    expect(referenceLine({ holder: 'switch', setting: 'skills.channel_disabled', channel: 'voice' }))
      .toBe('skills.channel_disabled · voice');
    expect(referenceLine({ holder: 'proposal', id: 'sp-1' })).toBe('pending proposal sp-1');
    expect(referenceLine({ holder: 'batch', id: 'sb-2' })).toBe('pending batch sb-2');
    expect(referenceLine({ holder: 'job', unreadable: true })).toBe('job · could not be read');
    expect(referenceLine({ holder: 'bundle', skill: 'alpha', file: 'research.yaml', unreadable: true,
      why: 'invalid_yaml' })).toBe('bundle research.yaml · could not be read · invalid_yaml');
    expect(referenceLine({ holder: 'skill', name: 'q', field: 'related_skills', why: 'ships with Nerva' }))
      .toBe('skill q · related_skills · ships with Nerva');
  });
});

describe('DecisionInboxPanel reads the skill batches', () => {
  it('asks for GET /api/skills/batches with the admin token', async () => {
    const fn = vi.fn(async (url) => ok(String(url).includes('/api/skills/batches') ? { batches: [batch] } : { tasks: [] }));
    global.fetch = fn;
    render(<DecisionInboxPanel />);
    await waitFor(() => expect(screen.getByText('2 operation(s) on alpha, gamma')).toBeTruthy());
    const call = fn.mock.calls.find((c) => String(c[0]).includes('/api/skills/batches'));
    const headers = call[1]?.headers || {};
    expect(headers['X-Admin-Token'] || headers['x-admin-token']).toBe('admin');
  });
});
