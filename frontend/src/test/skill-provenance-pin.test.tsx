// @ts-nocheck
/* H349 — the Skill Switches panel shows what the hub's usage sidecar recorded for each
   skill (where it came from, how often it ran, was viewed and was patched, the owner's
   pin) and pins or unpins through the admin route. A refusal or a failed write is shown
   in the hub's words and the list is re-read: the row never shows a pin the hub did not
   store. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import { PIN_PATH, SKILLS_PATH, SkillSwitchesPanel, originLabel, usageCounts } from '../panels/skill-switches';

let calls;
let skills;
let pinReply;

function reply(status, data) {
  return { ok: status < 400, status, json: async () => data, text: async () => JSON.stringify(data) };
}

const usage = (over = {}) => ({ use_count: 0, view_count: 0, patch_count: 0, last_used_at: null,
  last_viewed_at: null, last_patched_at: null, origin: 'local', source: '', state: 'active',
  pinned: false, pinnable: true, ...over });
const row = (name, use) => ({ name, essential: false, disabled: false, disabled_channels: [], category: '',
  ...(use ? { usage: use } : {}) });

beforeEach(() => {
  cleanup();
  calls = [];
  skills = {
    'Weather Intel': row('Weather Intel', usage({ origin: 'bundled', pinnable: false, use_count: 3, view_count: 1 })),
    'Meeting Notes': row('Meeting Notes', usage({ origin: 'import', source: 'hermes', patch_count: 2 })),
    'Tidy Notes': row('Tidy Notes', usage({ origin: 'agent', pinned: true })),
    'My Notes': row('My Notes', usage()),
    'Old Hub Skill': row('Old Hub Skill', null),
    'Unrecorded': row('Unrecorded', usage({ origin: 'unknown', pinnable: false })),
  };
  pinReply = (body) => reply(200, { ok: true, skill: body.skill, pinned: body.pinned, changed: true, audited: true });
  global.fetch = vi.fn(async (url, init = {}) => {
    const u = String(url);
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ url: u, method: init.method || 'GET', body });
    if (u.endsWith(PIN_PATH)) return pinReply(body);
    if (u.endsWith(SKILLS_PATH)) return reply(200, { skills });
    return reply(404, {});
  });
});

const pins = () => calls.filter((c) => c.url.endsWith(PIN_PATH));
const reads = () => calls.filter((c) => c.url.endsWith(SKILLS_PATH)).length;

describe('SkillSwitchesPanel — H349 provenance, counters and the pin', () => {
  it('shows where each skill came from, its counters and its pin', async () => {
    render(<SkillSwitchesPanel />);
    await waitFor(() => expect(screen.getByLabelText('pin My Notes')).toBeTruthy());
    expect(screen.getByText('ships with Nerva')).toBeTruthy();
    expect(screen.getByText('imported · hermes')).toBeTruthy();
    expect(screen.getByText('made by the agent')).toBeTruthy();
    expect(screen.getByText('local · no install record')).toBeTruthy();
    expect(screen.getByText('used 3× · viewed 1× · patched 0×')).toBeTruthy();
    expect(screen.getByText('used 0× · viewed 0× · patched 2×')).toBeTruthy();
    expect(screen.getByText('pinned')).toBeTruthy();                       // Tidy Notes
    expect(screen.getByLabelText('unpin Tidy Notes')).toBeTruthy();
    expect(screen.getByLabelText('pin Meeting Notes')).toBeTruthy();
    // No pin where the hub would refuse one, and none invented for a hub that sent no record.
    expect(screen.queryByLabelText('pin Weather Intel')).toBeNull();
    expect(screen.queryByLabelText('pin Old Hub Skill')).toBeNull();
    expect(screen.queryByLabelText('pin Unrecorded')).toBeNull();
    expect(screen.getByText(/A skill that ships with Nerva has no pin/)).toBeTruthy();
    expect(screen.getByText(/Your own removals are not blocked and take the pin with the skill/)).toBeTruthy();
  });

  it('labels only what the hub recorded', () => {
    expect(originLabel({ origin: 'import', source: '  marketplace ' })).toBe('imported · marketplace');
    expect(originLabel({ origin: 'local', source: 'ignored' })).toBe('local · no install record');
    expect(originLabel({ origin: 'unknown' })).toBe('');
    // Both facts when both are true; and a skill the model wrote in a turn says it is not curated.
    expect(originLabel({ origin: 'agent', agent_created: true, write_origin: 'learning' })).toBe('made by the agent');
    expect(originLabel({ origin: 'agent', agent_created: true, write_origin: 'assistant_tool' }))
      .toBe('made by the agent in a turn · not curated');
    expect(originLabel({ origin: 'import', source: 'hermes', agent_created: true }))
      .toBe('made by the agent · imported · hermes');
    expect(originLabel({ origin: 'import', source: 'hermes', agent_created: 'yes' })).toBe('imported · hermes');
    expect(originLabel({ origin: 'made-up' })).toBe('');
    expect(originLabel(null)).toBe('');
    expect(usageCounts(null)).toBeNull();
    expect(usageCounts({})).toBeNull();
    expect(usageCounts({ use_count: 2, view_count: 'x', patch_count: -4 })).toBe('used 2× · viewed 0× · patched 0×');
  });

  it('pins a skill through the admin route and re-reads the list', async () => {
    render(<SkillSwitchesPanel />);
    await waitFor(() => expect(screen.getByLabelText('pin My Notes')).toBeTruthy());
    const before = reads();
    fireEvent.click(screen.getByLabelText('pin My Notes'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('pinned · My Notes'));
    expect(pins()).toHaveLength(1);
    expect(pins()[0].method).toBe('POST');
    expect(pins()[0].body).toEqual({ skill: 'My Notes', pinned: true });
    await waitFor(() => expect(reads()).toBeGreaterThan(before));
  });

  it('unpins, and says when the intent log did not record it', async () => {
    pinReply = (body) => reply(200, { ok: true, skill: body.skill, pinned: false, changed: true, audited: false });
    render(<SkillSwitchesPanel />);
    await waitFor(() => expect(screen.getByLabelText('unpin Tidy Notes')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('unpin Tidy Notes'));
    await waitFor(() => expect(screen.getByRole('status').textContent)
      .toBe('unpinned · Tidy Notes · not recorded in the intent log'));
    expect(pins()[0].body).toEqual({ skill: 'Tidy Notes', pinned: false });
  });

  it('shows the hub\'s refusal and re-reads, never a pin it did not store', async () => {
    pinReply = () => reply(409, { error: "'My Notes' ships with Nerva: nothing ages it out or deletes it, so there is nothing to pin",
      reason: 'not_pinnable' });
    render(<SkillSwitchesPanel />);
    await waitFor(() => expect(screen.getByLabelText('pin My Notes')).toBeTruthy());
    const before = reads();
    fireEvent.click(screen.getByLabelText('pin My Notes'));
    await waitFor(() => expect(screen.getByRole('status').textContent)
      .toBe("not pinned · 'My Notes' ships with Nerva: nothing ages it out or deletes it, so there is nothing to pin"));
    await waitFor(() => expect(reads()).toBeGreaterThan(before));
    expect(screen.getByLabelText('pin My Notes')).toBeTruthy();            // still not pinned
    expect(screen.getAllByText('pinned')).toHaveLength(1);                 // only Tidy Notes
  });

  it('shows a write the hub could not make', async () => {
    pinReply = () => reply(503, { error: 'the pin could not be saved; nothing changed', reason: 'write_failed' });
    render(<SkillSwitchesPanel />);
    await waitFor(() => expect(screen.getByLabelText('pin My Notes')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('pin My Notes'));
    await waitFor(() => expect(screen.getByRole('status').textContent)
      .toBe('not pinned · the pin could not be saved; nothing changed'));
  });

  it('does not report a pin the hub answered 200 to without confirming', async () => {
    pinReply = (body) => reply(200, { ok: true, skill: body.skill, pinned: false, changed: false });
    render(<SkillSwitchesPanel />);
    await waitFor(() => expect(screen.getByLabelText('pin My Notes')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('pin My Notes'));
    await waitFor(() => expect(screen.getByRole('status').textContent)
      .toBe('not pinned · the hub did not confirm it'));
  });

  it('says when the skill was already pinned', async () => {
    pinReply = (body) => reply(200, { ok: true, skill: body.skill, pinned: true, changed: false, audited: false });
    render(<SkillSwitchesPanel />);
    await waitFor(() => expect(screen.getByLabelText('pin My Notes')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('pin My Notes'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('My Notes was already pinned'));
  });
});
