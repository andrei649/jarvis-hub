// @ts-nocheck
/* H202 — the owner's roster beside the persona editor: the Agents roster creates an agent
   (POST /api/admin/agents) and lists the retired ones with Restore; the Dossier renames
   (POST …/rename) and retires (POST …/retire with the id as the hub's confirmation, behind
   the H168 two-step confirm). Every call carries the admin token. fetch is mocked. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { AgentProfileControls, NewAgentDialog, RetiredAgents, rosterRefusal } from '../agent-roster';
import { AgentsMode, Dossier } from '../modes';
import { V2 } from '../data';

let calls;
let routes;

const ROSTER = {
  agents: [
    { id: 'jarvis', name: 'Jarvis', status: 'active', live: true, created: false, protected: true },
    { id: 'stark', name: 'Stark', status: 'retired', live: false, created: false, reason: 'not needed' },
    { id: 'vega', name: 'Vega', status: 'retired', live: false, created: true, template: 'researcher' },
  ],
};

beforeEach(() => {
  cleanup();
  try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'adm'); } catch { /* ignore */ }
  calls = [];
  routes = {
    'GET /api/agent-templates': [200, { templates: [{ key: 'researcher', role: 'Research & OSINT analyst' }, { key: 'coder', role: 'Software engineer' }] }],
    'POST /api/admin/agents': [201, { ok: true, agent: { id: 'vega', name: 'Vega', created: true, template: 'researcher', live: true }, revision: 1 }],
    'POST /api/admin/agents/pepper/rename': [200, { ok: true, changed: true, previous: 'Pepper', agent: { id: 'pepper', name: 'Penny' } }],
    'POST /api/admin/agents/pepper/retire': [200, { ok: true, agent: { id: 'pepper', status: 'retired' }, kept: { persona: true } }],
    'GET /api/admin/agents/roster': [200, ROSTER],
    'POST /api/admin/agents/stark/restore': [200, { ok: true, agent: { id: 'stark', status: 'active' } }],
    'GET /api/agents/pepper/soul': [200, { agent_id: 'pepper', soul: 'You are Pepper.\n', description: '' }],
    'GET /api/agents/pepper/history': [200, { agent_id: 'pepper', runs: [] }],
    'GET /api/agents/vega/soul': [200, { agent_id: 'vega', soul: '---\nid: vega\n---\n# Vega — SOUL\n', description: 'Gathers sources.' }],
    'GET /api/agents/vega/history': [200, { agent_id: 'vega', runs: [] }],
  };
  global.fetch = vi.fn(async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase();
    const path = String(url).replace(/^https?:\/\/[^/]+/, '');
    calls.push({ method, path, body: init.body ? JSON.parse(init.body) : undefined, headers: init.headers || {} });
    const [status, body] = routes[`${method} ${path}`] || [404, { error: 'no route' }];
    return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) };
  });
});

const posted = (path) => calls.filter((c) => c.method === 'POST' && c.path === path);

describe('rosterRefusal — H202', () => {
  it('says why the hub refused a roster change', () => {
    expect(rosterRefusal({ body: { error: 'agent_exists', agent: 'jarvis' } })).toBe('refused: jarvis is already an agent');
    expect(rosterRefusal({ body: { error: 'reserved_id', agent: 'hermes' } })).toMatch(/reserved name/);
    expect(rosterRefusal({ body: { error: 'name_taken', agent: 'friday' } })).toBe('refused: friday already has that name');
    expect(rosterRefusal({ body: { error: 'protected' } })).toMatch(/cannot be retired/);
    expect(rosterRefusal({ body: { error: 'kernel_denied', detail: 'kernel denied: kill-switch engaged' } })).toMatch(/Action Kernel/);
    expect(rosterRefusal({ body: { error: 'too_many_agents', max_created: 32 } })).toMatch(/32 created agents/);
    expect(rosterRefusal({ body: { error: 'safe_mode' } })).toMatch(/safe mode is on/);   // the SOUL editor's words
    expect(rosterRefusal({ status: 403 })).toBe('needs the admin token');
  });
});

describe('NewAgentDialog — H202', () => {
  it('creates an agent from a template through the admin route', async () => {
    const onCreated = vi.fn();
    render(<NewAgentDialog onCreated={onCreated} onCancel={() => {}} />);
    await waitFor(() => expect(screen.getByText('researcher — Research & OSINT analyst')).toBeTruthy());
    expect(screen.getByText('Create').disabled).toBe(true);                    // a name is required
    fireEvent.change(screen.getByLabelText('Agent name'), { target: { value: ' Vega ' } });
    fireEvent.change(screen.getByLabelText('Template'), { target: { value: 'researcher' } });
    fireEvent.click(screen.getByText('Create'));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ id: 'vega', created: true })));
    const [post] = posted('/api/admin/agents');
    expect(post.body).toEqual({ name: 'Vega', template: 'researcher' });
    expect(post.headers['X-Admin-Token']).toBe('adm');
  });

  it('starts blank with an id and a tier, and shows a refusal', async () => {
    routes['POST /api/admin/agents'] = [409, { error: 'agent_exists', agent: 'owl' }];
    const onCreated = vi.fn();
    render(<NewAgentDialog onCreated={onCreated} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText('Agent name'), { target: { value: 'Night Owl' } });
    fireEvent.change(screen.getByLabelText('Agent id'), { target: { value: 'OWL' } });
    fireEvent.change(screen.getByLabelText('Tier'), { target: { value: 'tech' } });
    fireEvent.click(screen.getByText('Create'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('refused: owl is already an agent'));
    expect(posted('/api/admin/agents')[0].body).toEqual({ name: 'Night Owl', template: '', agent_id: 'owl', tier: 'tech' });
    expect(onCreated).not.toHaveBeenCalled();
  });
});

describe('AgentProfileControls — H202', () => {
  it('renames for good through the admin route', async () => {
    const onRenamed = vi.fn();
    render(<AgentProfileControls id="pepper" name="Pepper" onRenamed={onRenamed} onRetired={() => {}} />);
    fireEvent.click(screen.getByText('Rename'));
    expect(screen.getByRole('dialog', { name: 'Rename Pepper' })).toBeTruthy();
    fireEvent.change(screen.getByLabelText('New name'), { target: { value: 'Penny' } });
    fireEvent.click(screen.getByText('Save name'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('renamed to Penny · kept across restarts'));
    expect(posted('/api/admin/agents/pepper/rename')[0].body).toEqual({ name: 'Penny' });
    expect(onRenamed).toHaveBeenCalledWith('Penny');
    expect(screen.queryByLabelText('New name')).toBeNull();
  });

  it('says a taken name, and keeps the dialog open', async () => {
    routes['POST /api/admin/agents/pepper/rename'] = [409, { error: 'name_taken', agent: 'friday' }];
    const onRenamed = vi.fn();
    render(<AgentProfileControls id="pepper" name="Pepper" onRenamed={onRenamed} onRetired={() => {}} />);
    fireEvent.click(screen.getByText('Rename'));
    fireEvent.change(screen.getByLabelText('New name'), { target: { value: 'Friday' } });
    fireEvent.keyDown(screen.getByLabelText('New name'), { key: 'Enter' });
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('refused: friday already has that name'));
    expect(onRenamed).not.toHaveBeenCalled();
    expect(screen.getByLabelText('New name')).toBeTruthy();
  });

  it('retires only after the confirm dialog, sending the id as the hub’s confirmation', async () => {
    const onRetired = vi.fn();
    render(<AgentProfileControls id="pepper" name="Pepper" onRenamed={() => {}} onRetired={onRetired} />);
    fireEvent.click(screen.getByText('Retire'));
    expect(screen.getByText(/Nothing is deleted/)).toBeTruthy();                 // what is kept, before the click
    fireEvent.click(screen.getByText('Keep'));
    expect(posted('/api/admin/agents/pepper/retire')).toEqual([]);
    fireEvent.click(screen.getByText('Retire'));
    fireEvent.click(screen.getByText('Retire Pepper'));
    await waitFor(() => expect(onRetired).toHaveBeenCalled());
    expect(posted('/api/admin/agents/pepper/retire')[0].body).toEqual({ confirm: 'pepper' });
  });

  it('shows a refused retire and stays armed', async () => {
    routes['POST /api/admin/agents/pepper/retire'] = [409, { error: 'protected' }];
    const onRetired = vi.fn();
    render(<AgentProfileControls id="pepper" name="Pepper" onRenamed={() => {}} onRetired={onRetired} />);
    fireEvent.click(screen.getByText('Retire'));
    fireEvent.click(screen.getByText('Retire Pepper'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/cannot be retired/));
    expect(onRetired).not.toHaveBeenCalled();
    expect(screen.getByText('Retire Pepper')).toBeTruthy();
  });
});

describe('RetiredAgents — H202', () => {
  it('lists the retired agents and restores one', async () => {
    const onRestored = vi.fn();
    render(<RetiredAgents onRestored={onRestored} />);
    await waitFor(() => expect(screen.getByText('Stark')).toBeTruthy());
    expect(screen.queryByText('Jarvis')).toBeNull();                              // only the retired
    expect(screen.getByText('stark · not needed')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Restore Stark'));
    await waitFor(() => expect(onRestored).toHaveBeenCalledWith('stark'));
    expect(posted('/api/admin/agents/stark/restore')).toHaveLength(1);
    expect(calls.filter((c) => c.path === '/api/admin/agents/roster').length).toBe(2);   // reloaded
  });

  it('asks before loading without an admin token, so the roster never prompts by itself', async () => {
    localStorage.removeItem('hud.admin_token');
    render(<RetiredAgents onRestored={() => {}} />);
    expect(calls).toEqual([]);
    fireEvent.click(screen.getByText('Show retired agents'));
    await waitFor(() => expect(screen.getByText('Vega')).toBeTruthy());
  });
});

describe('the roster and the Dossier host the dialogs — H202', () => {
  const AGENTS = [{ id: 'jarvis', name: 'Jarvis', tier: 'CNS', status: 'active', role: 'Prime' }];

  it('the Agents roster opens New agent and refreshes the live data when it lands', async () => {
    const onChanged = vi.fn();
    const { container } = render(<AgentsMode agents={AGENTS} onOpen={() => {}} t={V2.I18N.en} onChanged={onChanged} />);
    expect(container.querySelectorAll('.acard button').length).toBe(0);         // the cards stay click targets
    fireEvent.click(screen.getByText('+ New agent'));
    fireEvent.change(screen.getByLabelText('Agent name'), { target: { value: 'Vega' } });
    fireEvent.click(screen.getByText('Create'));
    await waitFor(() => expect(screen.getByText('created Vega · kept across restarts')).toBeTruthy());
    expect(onChanged).toHaveBeenCalled();
    expect(screen.queryByRole('dialog', { name: 'New agent' })).toBeNull();
    await waitFor(() => expect(screen.getByLabelText('Restore Stark')).toBeTruthy());   // the retired, below
  });

  it('the Dossier renames beside the persona editor, and retires then closes', async () => {
    const onChanged = vi.fn();
    const onClose = vi.fn();
    render(<Dossier id="pepper" onClose={onClose} onOpen={() => {}} onChanged={onChanged} />);
    await waitFor(() => expect(screen.getByText('Edit persona')).toBeTruthy());
    fireEvent.click(screen.getByText('Rename'));
    fireEvent.change(screen.getByLabelText('New name'), { target: { value: 'Penny' } });
    fireEvent.click(screen.getByText('Save name'));
    await waitFor(() => expect(document.querySelector('.dossier-head .nm').textContent).toBe('Penny'));
    expect(onChanged).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText('Retire'));
    fireEvent.click(screen.getByText('Retire Penny'));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(onChanged).toHaveBeenCalledTimes(2);
  });

  it('a created agent the seed corpus never knew still has a dossier', async () => {
    const live = [{ id: 'vega', name: 'Vega', tier: 'BIZ', role: 'Research & OSINT analyst', status: 'idle' }];
    render(<Dossier id="vega" onClose={() => {}} onOpen={() => {}} agents={live} />);
    expect(document.querySelector('.dossier-head .nm').textContent).toBe('Vega');
    await waitFor(() => expect(screen.getByText('Gathers sources.')).toBeTruthy());
    expect(screen.getByText('Rename')).toBeTruthy();
    // and without the live roster an unknown id still renders nothing
    cleanup();
    const { container } = render(<Dossier id="vega" onClose={() => {}} onOpen={() => {}} />);
    expect(container.innerHTML).toBe('');
  });
});
