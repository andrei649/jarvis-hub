// @ts-nocheck
/* DRA-28 — the v2 Console had no way to CREATE or EDIT a workflow: the old
   read-only `StepGenPanel` generated a step config and rendered it as JSON with
   a caption telling the owner to "paste into the workflow builder" — a builder
   that only existed in the legacy v1 surface. `WorkflowBuilderPanel` closes the
   loop: generate → add to draft → save (POST/PUT, admin). fetch is mocked, like
   workflows-panel.test.tsx. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { WorkflowBuilderPanel } from '../gap';

const listed = {
  workflows: [{
    id: 'daily-brief',
    name: 'Daily Brief',
    description: 'the morning pass',
    steps: [{ id: 'a', agent_id: 'jarvis', prompt_template: '{_input}', depends_on: [] }],
  }],
  total: 1,
};

let generated = { ok: true, step: { kind: 'agent', agent: 'vision', prompt: 'summarize the week', source: 'ai' } };

function response(payload, ok = true, status = 200) {
  return Promise.resolve({ ok, status, json: async () => payload });
}

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
  localStorage.setItem('hud.admin_token', 'owner-token');
  generated = { ok: true, step: { kind: 'agent', agent: 'vision', prompt: 'summarize the week', source: 'ai' } };
  global.fetch = vi.fn((url, options) => {
    const u = String(url);
    if (u.includes('/api/workflows/step/generate')) return response(generated);
    if (u.includes('/api/workflows/')) return response({ id: 'daily-brief', name: 'Renamed', steps: [] });
    if (u.includes('/api/workflows') && options?.method === 'POST') return response({ id: 'mine', name: '', steps: [] });
    return response(listed);
  });
});

const steps = () => JSON.parse(screen.getByLabelText('workflow draft steps').value);

describe('WorkflowBuilderPanel (DRA-28)', () => {
  it('lands the generated step in the draft as a real WorkflowStep', async () => {
    render(<WorkflowBuilderPanel />);
    await waitFor(() => expect(screen.getByLabelText('workflow draft steps')).toBeTruthy());

    fireEvent.change(screen.getByLabelText('workflow step description'), { target: { value: 'summarize the week' } });
    fireEvent.click(screen.getByRole('button', { name: /generate step/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /add step to draft/i }).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: /add step to draft/i }));

    await waitFor(() => expect(steps()).toEqual([
      { id: 's1', agent_id: 'vision', prompt_template: 'summarize the week', depends_on: [] },
    ]));

    // a second step chains onto the first, so the DAG is valid on the first save
    fireEvent.click(screen.getByRole('button', { name: /add step to draft/i }));
    await waitFor(() => expect(steps()[1]).toEqual({
      id: 's2', agent_id: 'vision', prompt_template: 'summarize the week', depends_on: ['s1'],
    }));
  });

  it('keeps a transform step\'s op in the WorkflowStep shape', async () => {
    generated = { ok: true, step: { kind: 'transform', transform: 'json_extract', prompt: 'pull the field', agent: 'jarvis', source: 'heuristic' } };
    render(<WorkflowBuilderPanel />);
    await waitFor(() => expect(screen.getByLabelText('workflow draft steps')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('workflow step description'), { target: { value: 'pull the field' } });
    fireEvent.click(screen.getByRole('button', { name: /generate step/i }));
    await waitFor(() => expect(screen.getByRole('button', { name: /add step to draft/i }).disabled).toBe(false));
    fireEvent.click(screen.getByRole('button', { name: /add step to draft/i }));

    await waitFor(() => expect(steps()[0]).toMatchObject({
      kind: 'transform', transform: { op: 'json_extract' }, prompt_template: 'pull the field',
    }));
  });

  it('creates a new workflow with POST /api/workflows', async () => {
    render(<WorkflowBuilderPanel />);
    await waitFor(() => expect(screen.getByLabelText('workflow draft steps')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('workflow draft id'), { target: { value: 'mine' } });
    fireEvent.change(screen.getByLabelText('workflow draft steps'), {
      target: { value: '[{"id":"s1","agent_id":"vision","prompt_template":"{_input}","depends_on":[]}]' },
    });
    fireEvent.click(screen.getByRole('button', { name: /save workflow/i }));

    await waitFor(() => expect(screen.getByText(/saved · mine/i)).toBeTruthy());
    const call = vi.mocked(global.fetch).mock.calls.find(([u, o]) => String(u) === '/api/workflows' && o?.method === 'POST');
    expect(call).toBeTruthy();
    expect(JSON.parse(call[1].body)).toEqual({
      id: 'mine', name: '', description: '',
      steps: [{ id: 's1', agent_id: 'vision', prompt_template: '{_input}', depends_on: [] }],
    });
    expect(call[1].headers['X-Admin-Token']).toBe('owner-token');
  });

  it('updates an existing workflow with PUT, not a duplicate POST', async () => {
    render(<WorkflowBuilderPanel />);
    await waitFor(() => expect(screen.getByLabelText('workflow to edit')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('workflow to edit'), { target: { value: 'daily-brief' } });
    await waitFor(() => expect(screen.getByLabelText('workflow draft name').value).toBe('Daily Brief'));
    expect(steps()).toEqual(listed.workflows[0].steps);

    fireEvent.change(screen.getByLabelText('workflow draft name'), { target: { value: 'Renamed' } });
    fireEvent.click(screen.getByRole('button', { name: /save workflow/i }));

    await waitFor(() => expect(screen.getByText(/saved · daily-brief/i)).toBeTruthy());
    const put = vi.mocked(global.fetch).mock.calls.find(([u, o]) => o?.method === 'PUT');
    expect(String(put[0])).toBe('/api/workflows/daily-brief');
    expect(JSON.parse(put[1].body).name).toBe('Renamed');
    expect(vi.mocked(global.fetch).mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(0);
  });

  it('never sends invalid steps JSON to the network', async () => {
    render(<WorkflowBuilderPanel />);
    await waitFor(() => expect(screen.getByLabelText('workflow draft steps')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('workflow draft id'), { target: { value: 'mine' } });
    fireEvent.change(screen.getByLabelText('workflow draft steps'), { target: { value: 'not json' } });
    fireEvent.click(screen.getByRole('button', { name: /save workflow/i }));

    await waitFor(() => expect(screen.getByText(/steps must be a JSON array/i)).toBeTruthy());
    expect(vi.mocked(global.fetch).mock.calls.filter(([, o]) => o?.method === 'POST' || o?.method === 'PUT')).toHaveLength(0);
  });

  it('renders an admin refusal instead of reading as a silent save', async () => {
    global.fetch = vi.fn((url, options) => (options?.method === 'POST' && String(url) === '/api/workflows'
      ? response({ detail: 'invalid workflow definition' }, false, 422)
      : response(listed)));
    render(<WorkflowBuilderPanel />);
    await waitFor(() => expect(screen.getByLabelText('workflow draft steps')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('workflow draft id'), { target: { value: 'mine' } });
    fireEvent.click(screen.getByRole('button', { name: /save workflow/i }));

    await waitFor(() => expect(screen.getByText(/refused ·.*422/i)).toBeTruthy());
    expect(screen.queryByText(/saved ·/i)).toBeNull();
  });
});
