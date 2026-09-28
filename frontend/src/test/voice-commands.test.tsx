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

const ROUTE = 'Console → Admin → Settings → Voice → Command providers (POST /api/admin/voice/commands)';
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
    expect(calls.find((c) => c.method === 'POST').body).toEqual({ side: 'stt', clear: true });
  });

  it('the helpers', () => {
    expect(parseArgv('["/x", "{output}"]')).toEqual({ argv: ['/x', '{output}'] });
    expect(parseArgv('[]').error).toBeTruthy();
    expect(parseArgv('[1]').error).toBeTruthy();
    expect(commandNote({ pending: 3 })).toContain('task 3');
    expect(commandRefusal({ body: { detail: 'set JARVIS_VOICE_COMMANDS=1' } })).toBe('set JARVIS_VOICE_COMMANDS=1');
  });
});

describe('H613 review — the Decision Inbox card, an explicit clear, sentinels', () => {
  const PY = '/usr/bin/python3.11';
  const SCRIPT = '/opt/tts/say.py';
  const TASK = { id: 77, kind: 'settings.voice_command', risk_tier: 3, status: 'blocked',
    title: `Run ${PY} as the TTS voice provider`,
    payload: { side: 'tts', argv: [PY, SCRIPT, '--out', '{output}'], reversible: false,
      preview: { kind: 'tts', side: 'tts', program: PY, runs_as: 'andrei', timeout_s: 30,
        argv: [PY, SCRIPT, '--out', '{output}'],
        files: [{ path: PY, size: 14328, sha256: 'a'.repeat(16) + 'b'.repeat(48) },
                { path: SCRIPT, size: 212, sha256: 'c'.repeat(16) + 'd'.repeat(48) }] } } };

  function inbox(tasks) {
    global.fetch = vi.fn(async (url) => {
      const u = String(url);
      if (u.includes('/autonomy/tasks')) return reply(200, { tasks });
      return reply(200, {});
    });
  }

  it('shows the kind, every bound file with its size and sha256 prefix, the argv and who it runs as', async () => {
    const { DecisionInboxPanel } = await import('../gap');
    inbox([TASK]);
    render(<DecisionInboxPanel />);
    const card = await screen.findByTestId('voice-command-card');
    expect(card.textContent).toContain('TTS');
    const files = screen.getAllByTestId('voice-command-file').map((f) => f.textContent);
    expect(files).toEqual([`${PY} · 14328 bytes · sha256 ${'a'.repeat(16)}`,
                           `${SCRIPT} · 212 bytes · sha256 ${'c'.repeat(16)}`]);
    const argv = [...screen.getByTestId('voice-command-argv').querySelectorAll('li')].map((li) => li.textContent);
    expect(argv).toEqual([PY, SCRIPT, '--out', '{output} (filled in by the hub)']);
    expect(screen.getAllByTestId('voice-command-placeholder')).toHaveLength(1);
    expect(card.textContent).toContain('runs on this machine as the hub user; cannot be undone by the hub');
    expect(card.textContent).toContain('andrei');
  });

  it('offers no edit on a voice command card (other cards keep it)', async () => {
    const { DecisionInboxPanel } = await import('../gap');
    inbox([TASK, { id: 78, kind: 'tool.rpc', risk_tier: 2, status: 'blocked', title: 'other', payload: {} }]);
    render(<DecisionInboxPanel />);
    await screen.findByTestId('voice-command-card');
    expect(screen.getAllByTitle('edit')).toHaveLength(1);
    expect(screen.getAllByTitle('accept')).toHaveLength(2);
  });

  it('an older card with only the program still names it', async () => {
    const { DecisionInboxPanel } = await import('../gap');
    inbox([{ ...TASK, payload: { preview: { side: 'stt', program: '/opt/stt', argv: ['/opt/stt', '{audio}'] } } }]);
    render(<DecisionInboxPanel />);
    await screen.findByTestId('voice-command-card');
    expect(screen.getByTestId('voice-command-file').textContent).toContain('/opt/stt');
  });

  it('Clear sends an explicit clear, never an empty argv', async () => {
    postReply = () => reply(200, { ok: true, side: 'stt', cleared: true });
    render(<SettingsPanel />);
    await screen.findByTestId('voice-command-stt');
    await waitFor(() => expect(screen.getByText('Clear')).toBeTruthy());
    fireEvent.click(screen.getByText('Clear'));
    await screen.findByText('Cleared');
    expect(calls.find((c) => c.method === 'POST').body).toEqual({ side: 'stt', clear: true });
  });

  it('only the exact sentinels are silence; other brackets are speech', async () => {
    const { isSttSentinel } = await import('../voice');
    for (const s of ['[silence]', '[STT unavailable]', '[STT error: command exited 3]']) expect(isSttSentinel(s)).toBe(true);
    for (const s of ['[laughs] hello', '[music]', 'hello', '']) expect(isSttSentinel(s)).toBe(false);
  });
});
