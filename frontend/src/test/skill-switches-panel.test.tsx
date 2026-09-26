// @ts-nocheck
/* H329 — the owner switches a skill off (everywhere or on one channel) and back on; an
   essential skill has no switch; a refusal is shown and the list re-read. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import { SKILLS_PATH, SWITCH_PATH, SkillSwitchesPanel } from '../panels/skill-switches';
import { CONSOLE_PANELS } from '../console-routes';

let calls;
let body;
let switchReply;

function reply(status, data) {
  return { ok: status < 400, status, json: async () => data, text: async () => JSON.stringify(data) };
}

beforeEach(() => {
  cleanup();
  calls = [];
  body = { skills: {
    'Weather Intel': { name: 'Weather Intel', essential: false, disabled: false, disabled_channels: [], category: 'info' },
    'Spotify': { name: 'Spotify', essential: false, disabled: false, disabled_channels: ['telegram'], category: '' },
    'Security Monitor': { name: 'Security Monitor', essential: true, disabled: false, disabled_channels: [], category: '' },
    'Notes': { name: 'Notes', essential: false, disabled: false, disabled_channels: [], category: '',
               readiness: 'unsupported', readiness_reason: 'unsupported on linux (it declares macos)' },
  } };
  switchReply = () => reply(200, { ok: true, changed: ['Weather Intel'], unchanged: [], essential: [], audited: true });
  global.fetch = vi.fn(async (url, init = {}) => {
    const u = String(url);
    calls.push({ url: u, method: init.method || 'GET', body: init.body ? JSON.parse(init.body) : undefined });
    if (u.endsWith(SWITCH_PATH)) return switchReply();
    if (u.endsWith(SKILLS_PATH)) return reply(200, body);
    return reply(404, {});
  });
});

const posts = () => calls.filter((c) => c.url.endsWith(SWITCH_PATH));

describe('SkillSwitchesPanel — H329', () => {
  it('switches a skill off everywhere and re-reads the list', async () => {
    render(<SkillSwitchesPanel />);
    await waitFor(() => expect(screen.getByLabelText('switch off Weather Intel')).toBeTruthy());
    expect(screen.getByText('off on telegram')).toBeTruthy();
    expect(screen.queryByLabelText('switch off Security Monitor')).toBeNull();   // essential
    expect(screen.getByText('always on')).toBeTruthy();
    expect(screen.getByText('unsupported on linux (it declares macos)')).toBeTruthy();   // H328
    fireEvent.click(screen.getByLabelText('switch off Weather Intel'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('switched off everywhere · Weather Intel'));
    expect(posts()[0].body).toEqual({ skill: 'Weather Intel', enabled: false });
    expect(calls.filter((c) => c.url.endsWith(SKILLS_PATH)).length).toBeGreaterThanOrEqual(2);
  });

  it('switches on one channel only, and turns a skill off there back on', async () => {
    switchReply = () => reply(200, { ok: true, changed: ['Spotify'], unchanged: [], essential: [], audited: true });
    render(<SkillSwitchesPanel />);
    await waitFor(() => expect(screen.getByLabelText('switch off Spotify')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('channel'), { target: { value: 'Telegram' } });
    fireEvent.click(screen.getByLabelText('switch on Spotify'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('switched on on telegram · Spotify'));
    expect(posts()[0].body).toEqual({ skill: 'Spotify', enabled: true, channel: 'telegram' });
  });

  it('refuses a malformed channel before posting', async () => {
    render(<SkillSwitchesPanel />);
    await waitFor(() => expect(screen.getByLabelText('switch off Weather Intel')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('channel'), { target: { value: 'tele gram' } });
    expect(screen.getByRole('alert').textContent).toContain('lower-case');
    fireEvent.click(screen.getByLabelText('switch off Weather Intel'));
    expect(posts()).toHaveLength(0);
  });

  it('shows a refusal and an unrecorded switch-off, and switches a category', async () => {
    switchReply = () => reply(503, { error: 'switching a skill back on is recorded in the intent log, which is not available', reason: 'audit_unavailable' });
    render(<SkillSwitchesPanel />);
    await waitFor(() => expect(screen.getByLabelText('switch on category info')).toBeTruthy());
    fireEvent.click(screen.getByLabelText('switch on category info'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('not switched'));
    expect(posts()[0].body).toEqual({ category: 'info', enabled: true });
    switchReply = () => reply(200, { ok: true, changed: ['Weather Intel'], unchanged: [], essential: [], audited: false });
    fireEvent.click(screen.getByLabelText('switch off category info'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('not recorded in the intent log'));
    expect(CONSOLE_PANELS.find((p) => p.component === 'SkillSwitchesPanel')?.group).toBe('Trust');
  });
});
