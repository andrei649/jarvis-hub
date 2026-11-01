// @ts-nocheck
/* H026 — a named skill bundle is switched off and on as one unit from the Skill Switches
   panel: the same admin route as one skill ({bundle, enabled, channel?}), pending owner
   approval for on, and the members that are not installed are named. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import { BUNDLES_PATH, SKILLS_PATH, SWITCH_PATH, SkillSwitchesPanel } from '../panels/skill-switches';

let calls;
let bundlesBody;
let switchReply;

function reply(status, data) {
  return { ok: status < 400, status, json: async () => data, text: async () => JSON.stringify(data) };
}

beforeEach(() => {
  cleanup();
  calls = [];
  bundlesBody = { bundles: [
    { name: 'Morning', slug: 'morning', skills: ['Weather Intel', 'News', 'Gone'], description: 'am',
      installed: ['Weather Intel', 'News'], missing: ['Gone'] },
  ], problems: [] };
  switchReply = () => reply(200, { ok: true, changed: ['Weather Intel', 'News'], unchanged: [], essential: [],
    audited: true, bundle: 'morning', missing: ['Gone'] });
  global.fetch = vi.fn(async (url, init = {}) => {
    const u = String(url);
    calls.push({ url: u, method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : undefined });
    if (u.endsWith(SWITCH_PATH)) return switchReply();
    if (u.endsWith(BUNDLES_PATH)) return bundlesBody ? reply(200, bundlesBody) : reply(404, {});
    if (u.endsWith(SKILLS_PATH)) return reply(200, { skills: {
      'Weather Intel': { name: 'Weather Intel', essential: false, disabled: false, disabled_channels: [], category: '' },
      'News': { name: 'News', essential: false, disabled: false, disabled_channels: [], category: '' },
    } });
    return reply(404, {});
  });
});

const posts = () => calls.filter((c) => c.url.endsWith(SWITCH_PATH));

describe('SkillSwitchesPanel — H026 bundles', () => {
  it('lists a bundle and switches it off as one unit, naming members not installed', async () => {
    render(<SkillSwitchesPanel />);
    await waitFor(() => expect(screen.getByLabelText('switch off bundle Morning')).toBeTruthy());
    expect(screen.getByText('3 skills')).toBeTruthy();
    expect(screen.getByText('1 not installed')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('switch off bundle Morning'));
    await waitFor(() => expect(screen.getByRole('status').textContent)
      .toBe('switched off everywhere · Weather Intel, News · not installed: Gone'));
    expect(posts()[0].body).toEqual({ bundle: 'morning', enabled: false });
    expect(calls.filter((c) => c.url.endsWith(BUNDLES_PATH)).length).toBeGreaterThanOrEqual(2);   // re-read
  });

  it('switches a bundle on through owner approval, on one channel', async () => {
    switchReply = () => reply(202, { ok: true, status: 'pending', task_id: 9, pending: ['Weather Intel', 'News'],
      bundle: 'morning', missing: ['Gone'] });
    render(<SkillSwitchesPanel />);
    await waitFor(() => expect(screen.getByLabelText('switch on bundle Morning')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('channel'), { target: { value: 'Telegram' } });
    fireEvent.click(screen.getByLabelText('switch on bundle Morning'));
    await waitFor(() => expect(screen.getByRole('status').textContent)
      .toBe('pending owner approval · task 9 · Weather Intel, News · not installed: Gone'));
    expect(posts()[0].body).toEqual({ bundle: 'morning', enabled: true, channel: 'telegram' });
  });

  it('shows how to create one when there are none, and nothing when the route is unavailable', async () => {
    bundlesBody = { bundles: [], problems: [] };
    render(<SkillSwitchesPanel />);
    await waitFor(() => expect(screen.getByText(/no bundles · nerva skills bundles create/)).toBeTruthy());
    cleanup();
    bundlesBody = null;
    render(<SkillSwitchesPanel />);
    await waitFor(() => expect(screen.getByLabelText('switch off Weather Intel')).toBeTruthy());
    expect(screen.queryByText('BY BUNDLE')).toBeNull();
    expect(posts()).toHaveLength(0);
  });
});
