// @ts-nocheck
/* H378 — a model choice the hub's selection guards ask about. The Settings panel and the
   Jobs panel send a model choice as it is; a 409 `selection_guard` opens a confirmation that
   names what the hub asks (the prices, the vendor's policy), and typing the model's name
   sends the same choice again with every flag the findings asked for. Cancel keeps the edit
   unsaved, and any other refusal still shows the hub's own reason. fetch is mocked. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup, within } from '@testing-library/react';
import { SettingsPanel } from '../gap';
import { JobsPanel } from '../panels/jobs';
import { guardFlags, guardRefusal } from '../selection-guard';

const FABLE = 'claude-fable-5';
const COST = { guard: 'cost', needs: 'confirm_expensive', setting: 'llm.claude_model', provider: 'anthropic', model: FABLE,
  message: `${FABLE} costs $10/M input and $50/M output tokens`, detail: { input: 10, output: 50, threshold: 40 } };
const TRAINS = { guard: 'data_policy', needs: 'acknowledge_training', setting: 'llm.compatible_model', provider: 'openrouter',
  model: 'x/y:free', message: 'x/y:free on OpenRouter: the vendor may train on your prompts', detail: {} };

let calls;
let putReply;

function reply(status, body) {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) };
}

const SETTINGS = {
  llm: [{ key: 'claude_model', value: 'claude-sonnet-4-6', default: 'claude-sonnet-4-6', source: 'default', label: 'Claude model', kind: 'text' }],
};

beforeEach(() => {
  cleanup();
  try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'admin-secret'); } catch { /* ignore */ }
  calls = [];
  putReply = (body) => (body.confirm_expensive ? reply(200, { updated: 1, category: 'llm', guards: [COST] })
    : reply(409, { error: 'selection_guard', detail: COST.message, needs: ['confirm_expensive'], guards: [COST] }));
  global.fetch = vi.fn(async (url, init = {}) => {
    const u = String(url).replace(/^https?:\/\/[^/]+/, '');
    const method = init.method || 'GET';
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ method, url: u, body });
    if (u === '/api/admin/settings') return reply(200, SETTINGS);
    if (u === '/api/admin/settings/resets') return reply(200, { resets: [] });
    if (u === '/api/admin/settings/llm' && method === 'PUT') return putReply(body);
    if (u === '/api/jobs' && method === 'GET') return reply(200, { jobs: [], scheduler: { alive: true }, requests: [] });
    if (u === '/api/jobs/blueprints') return reply(200, { blueprints: [{ id: 'digest', title: 'Digest', description: 'a daily digest',
      schedule_text: 'every day at 7', params: ['prompt'], fields: [], action: { type: 'ask' } }] });
    if (u === '/api/jobs/doctor') return reply(200, { toolsets: [] });
    if (u === '/api/jobs' && method === 'POST') {
      return body.confirm_expensive ? reply(201, { ok: true, job: { id: 'j1' }, confirmation: 'every day at 7' })
        : reply(409, { error: 'selection_guard', detail: COST.message, needs: ['confirm_expensive'], guards: [COST] });
    }
    return reply(404, { error: 'unexpected' });
  });
});

const puts = () => calls.filter((c) => c.method === 'PUT' && c.url === '/api/admin/settings/llm');

async function editModel() {
  render(<SettingsPanel />);
  const field = await screen.findByDisplayValue('claude-sonnet-4-6');
  fireEvent.change(field, { target: { value: FABLE } });
  fireEvent.click(screen.getByText(/save 1 change/));
  return screen.findByRole('alertdialog', { name: 'confirm the model choice' });
}

describe('selection guards — H378', () => {
  it('a guarded settings choice names the price and is sent again with the flag once the model is typed', async () => {
    const dialog = await editModel();
    expect(within(dialog).getByText(/\$50\/M output/)).toBeTruthy();
    const confirm = within(dialog).getByRole('button', { name: /choose it anyway/ });
    expect(confirm.disabled).toBe(true);                                       // typed, like a money action
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: FABLE } });
    fireEvent.click(confirm);
    await waitFor(() => expect(puts()).toHaveLength(2));
    expect(puts()[1].body).toEqual({ values: { claude_model: FABLE }, confirm_expensive: true });
    await waitFor(() => expect(screen.queryByText(/save 1 change/)).toBeNull());   // saved, the edit is gone
    expect(screen.queryByRole('alertdialog')).toBeNull();
  });

  it('cancel keeps the edit unsaved and sends nothing more', async () => {
    const dialog = await editModel();
    fireEvent.click(within(dialog).getByRole('button', { name: 'cancel' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(puts()).toHaveLength(1);
    expect(screen.getByText(/save 1 change/)).toBeTruthy();
  });

  it('a refusal that is not a guard still shows the hub’s own reason', async () => {
    putReply = () => reply(422, { error: 'invalid settings', details: ['claude_model: expected text'] });
    render(<SettingsPanel />);
    fireEvent.change(await screen.findByDisplayValue('claude-sonnet-4-6'), { target: { value: FABLE } });
    fireEvent.click(screen.getByText(/save 1 change/));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/invalid settings/));
    expect(screen.queryByRole('alertdialog')).toBeNull();
  });

  it('a job pinned to an expensive model asks before it is armed', async () => {
    render(<JobsPanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Digest' }));
    fireEvent.change(screen.getByLabelText('job model'), { target: { value: FABLE } });
    fireEvent.click(screen.getByRole('button', { name: 'arm' }));
    const dialog = await screen.findByRole('alertdialog', { name: 'confirm the model choice' });
    fireEvent.change(within(dialog).getByRole('textbox'), { target: { value: FABLE } });
    fireEvent.click(within(dialog).getByRole('button', { name: /choose it anyway/ }));
    const posts = () => calls.filter((c) => c.method === 'POST' && c.url === '/api/jobs');
    await waitFor(() => expect(posts()).toHaveLength(2));
    expect(posts()[1].body.confirm_expensive).toBe(true);
    expect(posts()[1].body.options).toEqual({ model: FABLE });
    expect(posts()[1].body.blueprint).toBe('digest');
  });

  it('every flag the findings ask for goes back, and only a guard refusal is one', () => {
    expect(guardFlags({ needs: ['acknowledge_training'], guards: [COST, TRAINS] }))
      .toEqual({ confirm_expensive: true, acknowledge_training: true });
    expect(guardRefusal({ status: 409, body: { error: 'selection_guard', needs: ['confirm_expensive'], guards: [COST] } }).guards).toHaveLength(1);
    expect(guardRefusal({ status: 409, body: { error: 'mic_busy' } })).toBeNull();
    expect(guardRefusal({ status: 409, body: { error: 'idempotency_key_reused', guards: [COST] } })).toBeNull();
    expect(guardRefusal({ status: 422, body: { error: 'selection_guard', guards: [] } })).toBeNull();
    expect(guardRefusal(null)).toBeNull();
  });
});
