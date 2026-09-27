// @ts-nocheck
/* H613 — Settings → Voice: the voice picker offers the hub's Piper voices (and the command
   provider when it is ready), the two command-provider rows are read-only with the route
   that changes them, and the Command providers block asks the hub: a set goes to the
   Decision Inbox ("Waiting for your approval … (task N)"), a refusal shows the hub's
   problems. fetch is mocked. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import { SettingsPanel } from '../gap';
import { commandNote, commandRefusal, parseArgv } from '../panels/voice-commands';

const ROUTE = 'Console → Voice → Command providers (POST /api/admin/voice/commands)';
let calls;
let postReply;

function reply(status, body) {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) };
}

const SETTINGS = {
  voice: [
    { key: 'tts_voice', value: 'en-GB-RyanNeural', default: 'en-GB-RyanNeural', source: 'default', label: 'TTS voice', kind: 'text' },
    { key: 'tts_command', value: {}, default: {}, source: 'default', label: 'TTS command provider', kind: 'json', written_by: ROUTE },
    { key: 'stt_command', value: {}, default: {}, source: 'default', label: 'STT command provider', kind: 'json', written_by: ROUTE },
  ],
};
const STATUS = { sides: {
  tts: { configured: false, armed: true, ready: false, reason: 'not_configured', pending_task: null },
  stt: { configured: true, armed: true, ready: false, reason: 'changed_since_approval', exe: '/opt/stt', pending_task: null },
} };

beforeEach(() => {
  cleanup();
  try { localStorage.clear(); localStorage.setItem('hud.admin_token', 'admin-secret'); } catch { /* ignore */ }
  calls = [];
  postReply = (body) => reply(202, { pending: 9, side: body.side });
  global.fetch = vi.fn(async (url, init = {}) => {
    const u = String(url).replace(/^https?:\/\/[^/]+/, '');
    const method = init.method || 'GET';
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ method, url: u, body, headers: init.headers });
    if (u === '/api/admin/settings') return reply(200, SETTINGS);
    if (u === '/api/admin/settings/resets') return reply(200, { resets: [] });
    if (u === '/api/voice/capabilities') return reply(200, { voices: ['piper:ro_RO-mihai-medium', 'piper:en_US-amy-low', 'command'] });
    if (u === '/api/admin/voice/commands' && method === 'GET') return reply(200, STATUS);
    if (u === '/api/admin/voice/commands' && method === 'POST') return postReply(body);
    return reply(404, { error: 'unexpected' });
  });
});

describe('Settings → Voice — H613', () => {
  it('the voice picker lists the Piper voices and the command provider', async () => {
    render(<SettingsPanel />);
    await screen.findByText('TTS voice');
    const list = await screen.findByTestId('suggest-tts_voice');
    await waitFor(() => expect(list.querySelectorAll('option').length).toBe(3));
    expect([...list.querySelectorAll('option')].map((o) => o.getAttribute('value')))
      .toEqual(['piper:ro_RO-mihai-medium', 'piper:en_US-amy-low', 'command']);
    expect(screen.getByLabelText('value of tts_voice').getAttribute('list')).toBe('suggest-tts_voice');
  });

  it('the command rows are read-only and name the route that changes them', async () => {
    render(<SettingsPanel />);
    await screen.findByText('TTS command provider');
    expect(screen.getAllByText(`change it in ${ROUTE}`)).toHaveLength(2);
    expect(screen.queryByLabelText('json value of tts_command')).toBeNull();
    expect(screen.queryByLabelText('json value of stt_command')).toBeNull();
  });

  it('Request posts the argv as JSON and says it waits for approval', async () => {
    render(<SettingsPanel />);
    const box = await screen.findByLabelText('tts command argv');
    const argv = ['/opt/tts/bin/say', '--out', '{output}'];
    fireEvent.change(box, { target: { value: JSON.stringify(argv) } });
    fireEvent.click(screen.getAllByText('Request')[0]);
    expect(await screen.findByText('Waiting for your approval in the Decision Inbox (task 9)')).toBeTruthy();
    const post = calls.find((c) => c.method === 'POST');
    expect(post.body).toEqual({ side: 'tts', argv });
    expect(post.headers['Content-Type']).toBe('application/json');
  });

  it('a refusal shows the hub’s problems, and bad JSON never reaches the hub', async () => {
    postReply = () => reply(422, { error: 'invalid_command', problems: ['argv[0]: sh runs other programs'] });
    render(<SettingsPanel />);
    const box = await screen.findByLabelText('tts command argv');
    fireEvent.change(box, { target: { value: 'sh -c id' } });
    fireEvent.click(screen.getAllByText('Request')[0]);
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
    fireEvent.change(box, { target: { value: '["/bin/sh", "{output}"]' } });
    fireEvent.click(screen.getAllByText('Request')[0]);
    expect(await screen.findByText('argv[0]: sh runs other programs')).toBeTruthy();
  });

  it('a configured side shows why it is not running and can be cleared', async () => {
    postReply = () => reply(200, { ok: true, side: 'stt', cleared: true });
    render(<SettingsPanel />);
    const row = await screen.findByTestId('voice-command-stt');
    await waitFor(() => expect(row.textContent).toContain('not running: changed_since_approval'));
    fireEvent.click(screen.getByText('Clear'));
    expect(await screen.findByText('Cleared')).toBeTruthy();
    expect(calls.find((c) => c.method === 'POST').body).toEqual({ side: 'stt', argv: null });
  });

  it('the helpers', () => {
    expect(parseArgv('["/x", "{output}"]')).toEqual({ argv: ['/x', '{output}'] });
    expect(parseArgv('[]').error).toBeTruthy();
    expect(parseArgv('[1]').error).toBeTruthy();
    expect(commandNote({ pending: 3 })).toContain('task 3');
    expect(commandRefusal({ body: { detail: 'set JARVIS_VOICE_COMMANDS=1' } })).toBe('set JARVIS_VOICE_COMMANDS=1');
  });
});
