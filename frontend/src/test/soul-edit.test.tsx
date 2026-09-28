// @ts-nocheck
/* H156 — the Dossier edits an agent's persona and makes it live (PUT
   /api/admin/agents/{id}/soul), previews the change against the live SOUL, and asks the
   local model for a description it can put in the front-matter. fetch is mocked. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { SoulEditor, refusalText, withDescription } from '../soul-edit';
import { Dossier } from '../modes';

let calls;
let routes;

beforeEach(() => {
  cleanup();
  try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'adm'); } catch { /* ignore */ }
  calls = [];
  routes = {
    'GET /api/agents/jarvis/soul': [200, { agent_id: 'jarvis', soul: 'You are Jarvis.\n', description: 'Runs the house.' }],
    'GET /api/agents/jarvis/history': [200, { agent_id: 'jarvis', runs: [] }],
    'PUT /api/admin/agents/jarvis/soul': [200, { agent_id: 'jarvis', version: { version: 3 }, guard: { flags: [], blocked: false }, live: true }],
    'POST /api/admin/prompts/jarvis/preview': [200, { added_lines: 1, removed_lines: 1, valid: true, diff: '' }],
    'POST /api/admin/agents/jarvis/description/draft': [200, { agent_id: 'jarvis', draft: 'Jarvis runs the house.' }],
  };
  global.fetch = vi.fn(async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase();
    const path = String(url).replace(/^https?:\/\/[^/]+/, '');
    calls.push({ method, path, body: init.body ? JSON.parse(init.body) : undefined, headers: init.headers || {} });
    const [status, body] = routes[`${method} ${path}`] || [404, { error: 'no route' }];
    return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) };
  });
});

describe('withDescription — H156', () => {
  it('adds, replaces and quotes the front-matter description', () => {
    expect(withDescription('You are Jarvis.\n', 'Runs the house.')).toBe('---\ndescription: "Runs the house."\n---\nYou are Jarvis.\n');
    expect(withDescription('---\ntier: core\n---\nbody\n', 'A: "b"')).toBe('---\ntier: core\ndescription: "A: \\"b\\""\n---\nbody\n');
    expect(withDescription('---\ndescription: old\ntier: core\n---\nbody', 'new')).toBe('---\ntier: core\ndescription: "new"\n---\nbody');
    expect(withDescription('---\ndescription: >\n  folded\n  lines\ntier: core\n---\nbody', 'new')).toBe('---\ntier: core\ndescription: "new"\n---\nbody');
    expect(withDescription('x', '  one \n two  ')).toBe('---\ndescription: "one two"\n---\nx');
  });

  it('says why the hub refused', () => {
    expect(refusalText({ body: { error: 'soul_blocked', guard: { flags: ['override'] } } })).toBe('refused: the SOUL guard would drop this persona (override)');
    expect(refusalText({ body: { error: 'soul_blocked', guard: {} } })).toBe('refused: the SOUL guard would drop this persona');
    expect(refusalText({ body: { error: 'safe_mode' } })).toMatch(/safe mode is on/);
    expect(refusalText({ body: { error: 'too_large' } })).toMatch(/256 KiB/);
    expect(refusalText({ body: { error: 'unknown_agent' } })).toMatch(/not loaded/);
    expect(refusalText({ body: { error: 'no_local_model' } })).toBe('no local model to draft with');
    expect(refusalText({ body: { error: 'empty_draft' } })).toMatch(/nothing/);
    expect(refusalText({ status: 401 })).toBe('needs the admin token');
    expect(refusalText({ message: 'boom' })).toBe('failed: boom');
  });
});

describe('SoulEditor — H156', () => {
  it('applies the edited persona through the admin route', async () => {
    const onApplied = vi.fn();
    render(<SoulEditor id="jarvis" live={'You are Jarvis.\n'} onApplied={onApplied} onCancel={() => {}} />);
    const apply = screen.getByText('Apply');
    expect(apply.disabled).toBe(true);                    // nothing changed yet
    fireEvent.change(screen.getByLabelText('Persona'), { target: { value: 'You are Jarvis, terse.\n' } });
    fireEvent.change(screen.getByLabelText('Change note'), { target: { value: 'shorter' } });
    fireEvent.click(screen.getByText('Apply'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('applied as v3'));
    const put = calls.find((c) => c.method === 'PUT');
    expect(put.path).toBe('/api/admin/agents/jarvis/soul');
    expect(put.body).toEqual({ content: 'You are Jarvis, terse.\n', message: 'shorter' });
    expect(put.headers['X-Admin-Token']).toBe('adm');
    expect(onApplied).toHaveBeenCalledWith('You are Jarvis, terse.\n');
  });

  it('names quarantined lines, and shows a refusal', async () => {
    routes['PUT /api/admin/agents/jarvis/soul'] = [200, { version: { version: 4 }, guard: { flags: ['exfil'], blocked: false } }];
    render(<SoulEditor id="jarvis" live="a" onApplied={() => {}} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText('Persona'), { target: { value: 'b' } });
    fireEvent.click(screen.getByText('Apply'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('applied as v4 · 1 line(s) quarantined: exfil'));
    cleanup();
    routes['PUT /api/admin/agents/jarvis/soul'] = [422, { error: 'soul_blocked', guard: { flags: ['override'], blocked: true } }];
    const onApplied = vi.fn();
    render(<SoulEditor id="jarvis" live="a" onApplied={onApplied} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText('Persona'), { target: { value: 'bad' } });
    fireEvent.click(screen.getByText('Apply'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('refused: the SOUL guard would drop this persona (override)'));
    expect(onApplied).not.toHaveBeenCalled();
  });

  it('previews against the live persona, and drafts a description into the front-matter', async () => {
    render(<SoulEditor id="jarvis" live={'You are Jarvis.\n'} onApplied={() => {}} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText('Persona'), { target: { value: 'You are Jarvis, terse.\n' } });
    fireEvent.click(screen.getByText('Preview'));
    await waitFor(() => expect(screen.getByText('+1 −1')).toBeTruthy());
    expect(calls.find((c) => c.path === '/api/admin/prompts/jarvis/preview').body)
      .toEqual({ proposed: 'You are Jarvis, terse.\n', current: 'You are Jarvis.\n' });
    fireEvent.click(screen.getByText('Draft description'));
    await waitFor(() => expect(screen.getByText('Jarvis runs the house.')).toBeTruthy());
    fireEvent.click(screen.getByText('Use it'));
    expect(screen.getByLabelText('Persona').value).toBe('---\ndescription: "Jarvis runs the house."\n---\nYou are Jarvis, terse.\n');
    routes['POST /api/admin/agents/jarvis/description/draft'] = [503, { error: 'no_local_model' }];
    fireEvent.click(screen.getByText('Draft description'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('no local model to draft with'));
  });
});

describe('Dossier — H156', () => {
  it('shows the description and opens the persona editor on the live SOUL', async () => {
    render(<Dossier id="jarvis" onClose={() => {}} onOpen={() => {}} />);
    await waitFor(() => expect(screen.getByText('Runs the house.')).toBeTruthy());
    fireEvent.click(screen.getByText('Edit persona'));
    expect(screen.getByLabelText('Persona').value).toBe('You are Jarvis.\n');
    fireEvent.click(screen.getByText('Close'));
    expect(screen.queryByLabelText('Persona')).toBeNull();
    expect(screen.getByText('Edit persona')).toBeTruthy();
  });
});
