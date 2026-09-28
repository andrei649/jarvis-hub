// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { VoiceCommands, VoiceCommandCard } from '../panels/voice-commands';

let calls, status, failure;
const row = (provider_id, extra = {}) => ({ provider_id, provider_revision: 2, configured: true,
  ready: true, armed: true, reason: 'ready', argv: ['/opt/synthetic'], ...extra });
beforeEach(() => {
  cleanup(); calls = []; failure = false;
  localStorage.clear(); localStorage.setItem('hud.admin_token', 'owner');
  status = { sides: { tts: {}, stt: {} }, providers: {
    tts: [row('narrator'), row('reader', { ready: false, reason: 'changed_since_approval' })],
    stt: [row('dictation'), row('pending', { configured: false, ready: false, pending_task: 44 })],
  }, selected_stt_provider: 'dictation' };
  global.fetch = vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET';
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ url, method, body });
    const result = method === 'GET' ? status : failure ? { error: 'provider_revision_conflict' }
      : body.clear ? { cleared: true } : method === 'PUT' ? { ok: true } : { pending: 88 };
    const code = failure && method !== 'GET' ? 409 : 200;
    return { ok: code < 400, status: code, json: async () => result, text: async () => JSON.stringify(result) };
  });
});

describe('named voice providers', () => {
  it('lists independent names and submits a new name for human approval', async () => {
    render(<VoiceCommands />);
    await screen.findByTestId('voice-command-tts-narrator');
    expect(screen.getByTestId('voice-command-tts-reader').textContent).toContain('changed_since_approval');
    fireEvent.change(screen.getByLabelText('new provider name'), { target: { value: 'storyteller' } });
    fireEvent.change(screen.getByLabelText('new provider argv'), { target: { value: '["/opt/tts", "{output}"]' } });
    fireEvent.click(screen.getByRole('button', { name: 'Request named provider' }));
    await screen.findByText('Waiting for your approval in the Decision Inbox (task 88)');
    expect(calls.find(c => c.method === 'POST').body).toEqual({ side: 'tts', provider_id: 'storyteller', argv: ['/opt/tts', '{output}'] });
  });
  it('updates and clears exactly one provider, including a pending-only registration', async () => {
    render(<VoiceCommands />);
    const narrator = await screen.findByTestId('voice-command-tts-narrator');
    fireEvent.change(within(narrator).getByRole('textbox'), { target: { value: '["/opt/new", "{output}"]' } });
    fireEvent.click(within(narrator).getByRole('button', { name: 'Request' }));
    await waitFor(() => expect(calls.some(c => c.method === 'POST')).toBe(true));
    expect(calls.find(c => c.method === 'POST').body).toEqual({ side: 'tts', provider_id: 'narrator', argv: ['/opt/new', '{output}'] });
    fireEvent.click(within(screen.getByTestId('voice-command-stt-pending')).getByRole('button', { name: 'Clear' }));
    await screen.findByText('Cleared');
    expect(calls.filter(c => c.method === 'POST').at(-1).body).toEqual({ side: 'stt', provider_id: 'pending', clear: true });
  });
  it('saves the selected STT identity explicitly and keeps a missing saved pin visible', async () => {
    status.selected_stt_provider = 'removed';
    render(<VoiceCommands />);
    const selector = await screen.findByLabelText('STT command provider selection');
    await waitFor(() => expect(selector.value).toBe('removed'));
    expect(within(selector).getByText('removed (unavailable)')).toBeTruthy();
    fireEvent.change(selector, { target: { value: 'dictation' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save STT selection' }));
    await screen.findByText('STT selection saved');
    expect(calls.find(c => c.method === 'PUT')).toMatchObject({ url: '/api/admin/settings/voice',
      body: { values: { stt_command_provider: 'dictation' } } });
  });
  it('rejects malformed new names locally and displays server refusals', async () => {
    render(<VoiceCommands />);
    await screen.findByTestId('voice-command-tts-narrator');
    fireEvent.change(screen.getByLabelText('new provider name'), { target: { value: '../bad' } });
    fireEvent.click(screen.getByRole('button', { name: 'Request named provider' }));
    await screen.findByRole('alert');
    expect(calls.filter(c => c.method === 'POST')).toEqual([]);
    failure = true;
    fireEvent.click(within(screen.getByTestId('voice-command-tts-narrator')).getByRole('button', { name: 'Clear' }));
    await screen.findByText('provider_revision_conflict');
  });
  it('shows a corrupt provider catalog as unavailable instead of an empty success', async () => {
    status.error = 'provider_store_unavailable';
    status.providers = { tts: [], stt: [] };
    render(<VoiceCommands />);
    expect((await screen.findByRole('alert')).textContent).toContain('provider_store_unavailable');
  });
  it('names the exact provider and revision in the Decision Inbox', () => {
    render(<VoiceCommandCard task={{ payload: { provider_id: 'narrator', provider_revision: 3,
      preview: { side: 'tts', provider_id: 'narrator', provider_revision: 3, argv: ['/opt/tts'] } } }} />);
    expect(screen.getByTestId('voice-command-card').textContent).toContain('narrator');
    expect(screen.getByTestId('voice-command-card').textContent).toContain('revision 3');
  });
});
