// @ts-nocheck
/* H227 — the Inspector panel reads GET /api/admin/inspector for an agent as a chosen
   principal and shows the status line, then folding sections for the offered tools, the
   prompt's skills, the MCP servers and the resolved prompt. fetch is mocked. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { INSPECTOR_VIEWS, InspectorPanel, inspectorPath, statusLine } from './inspector';
import { CONSOLE_PANELS } from '../console-routes';

let reply;
let calls;
let heads;

const PAYLOAD = {
  agent: 'jarvis', view: 'owner', posture: 'operator/owner',
  status: { version: '1.0.0', backend: 'lmstudio', model: 'qwen3-8b', model_state: 'ready', loaded_model: 'qwen3-8b',
    context_tokens: 0, tool_loop: true, safe_mode: false },
  tools: { loop_enabled: true, wired: true, registry: 3,
    offered: [
      { name: 'file_write', gated: true, untrusted_output: false, description: 'Write one file' },
      { name: 'web_search', gated: false, untrusted_output: true, description: 'Search the web' },
    ],
    withheld: ['memory'] },
  skills: { in_prompt: true, count: 1, rows: [{ skill: 'weather', command: 'weather', description: 'run weather' }] },
  mcp: { connected: 1, servers: [
    { name: 'notes', transport: 'streamable-http', trust: 'read-only', connected: true, tools: 2, tool_names: ['search', 'read'] },
    { name: 'fs', transport: 'stdio', trust: 'full', connected: false, tools: 0, tool_names: [] },
  ] },
  system_prompt: { system: 'You are Jarvis.', turn: 'Available skills:\n  - weather: run weather', bytes: 60, tokens: 15, cap: 65536,
    truncated: false, withheld: false },
};

beforeEach(() => {
  cleanup();
  try { localStorage.clear(); } catch { /* ignore */ }
  calls = [];
  heads = [];
  reply = { status: 200, body: PAYLOAD };
  global.fetch = vi.fn(async (url, init) => {
    calls.push(String(url));
    heads.push((init || {}).headers || {});
    return { ok: reply.status < 400, status: reply.status, json: async () => reply.body, text: async () => JSON.stringify(reply.body) };
  });
});

describe('InspectorPanel — H227', () => {
  it('shows the status line and every section of the payload', async () => {
    try { localStorage.setItem('hud.admin_token', 'adm'); } catch { /* ignore */ }
    render(<InspectorPanel />);
    await waitFor(() => expect(screen.getByText(
      'backend lmstudio · model qwen3-8b · ready (qwen3-8b) · context budget 75% of the model window · tool loop on')).toBeTruthy());
    expect(calls[0].endsWith('/api/admin/inspector?agent=jarvis&view=owner')).toBe(true);
    expect(heads[0]['X-Admin-Token']).toBe('adm');
    expect(screen.getByText('jarvis · operator/owner')).toBeTruthy();
    expect(screen.getByText('file_write')).toBeTruthy();
    expect(screen.getByText('gated')).toBeTruthy();
    expect(screen.getByText('untrusted output')).toBeTruthy();
    expect(screen.getByText('withheld (1): memory')).toBeTruthy();
    expect(screen.getByText(/2 offered of 3/)).toBeTruthy();
    expect(screen.getByText('weather')).toBeTruthy();
    expect(screen.getByText('notes')).toBeTruthy();
    expect(screen.getByText('connected')).toBeTruthy();
    expect(screen.getByText('down')).toBeTruthy();
    expect(screen.getByText('2 tools: search, read')).toBeTruthy();
    expect(screen.getByLabelText('System part').textContent).toBe('You are Jarvis.');
    expect(screen.getByLabelText('Turn part').textContent).toContain('Available skills:');
    expect(screen.getByText(/about 15 tokens before any history · 60 bytes/)).toBeTruthy();
  });

  it('asks again as another principal, and for another agent', async () => {
    render(<InspectorPanel />);
    await waitFor(() => expect(calls.length).toBe(1));
    fireEvent.click(screen.getByText('stranger · channel'));
    await waitFor(() => expect(calls.some((u) => u.endsWith('view=inbound'))).toBe(true));
    fireEvent.change(screen.getByLabelText('Agent'), { target: { value: 'friday' } });
    fireEvent.submit(screen.getByLabelText('Agent').closest('form'));
    await waitFor(() => expect(calls.some((u) => u.includes('agent=friday&view=inbound'))).toBe(true));
  });

  it('says when the tool loop is off, when the prompt is withheld and when the agent is unknown', async () => {
    reply = { status: 200, body: { ...PAYLOAD,
      tools: { ...PAYLOAD.tools, loop_enabled: false },
      system_prompt: { system: '', turn: '', bytes: 0, cap: 65536, truncated: false, withheld: true } } };
    render(<InspectorPanel />);
    await waitFor(() => expect(screen.getByText(/the tool loop is off/)).toBeTruthy());
    expect(screen.getByText('withheld: the secret redactor could not be loaded')).toBeTruthy();
    cleanup();
    reply = { status: 404, body: { error: 'unknown_agent', agent: 'jarvis' } };
    render(<InspectorPanel />);
    await waitFor(() => expect(screen.getByText('no agent named jarvis')).toBeTruthy());
  });

  it('builds its path and status line, and is an admin console panel', () => {
    expect(INSPECTOR_VIEWS).toEqual(['owner', 'guest', 'inbound-owner', 'inbound', 'internal']);
    expect(inspectorPath('  ', 'guest')).toBe('/api/admin/inspector?agent=jarvis&view=guest');
    expect(inspectorPath('friday', 'inbound-owner')).toBe('/api/admin/inspector?agent=friday&view=inbound-owner');
    expect(statusLine({ backend: 'lmstudio', model: 'm', model_state: 'ready', context_tokens: 24000, tool_loop: false, safe_mode: true }))
      .toBe('backend lmstudio · model m · ready · context budget 24000 · tool loop off · SAFE MODE');
    expect(statusLine(null)).toBe('');
    expect(CONSOLE_PANELS.find((p) => p.component === 'InspectorPanel')?.group).toBe('Admin');
  });
});
