import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { InputBar } from '../cockpit';
import { V2 } from '../data';

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.clear(); });

it('makes saved-text search available from the shared EN/RO composer and keeps a typed draft through Continue', async () => {
  const calls: string[] = [];
  vi.stubGlobal('fetch', vi.fn(async (path: string) => {
    calls.push(String(path));
    if (path === '/sessions/search') return Response.json({ hits: [{ session_id: 'past', turn: 25, role: 'user',
      timestamp: '2026-10-01', agent_id: null, snippet: 'old task' }], truncated: false, stopped_by: null });
    if (path === '/sessions/past/transcript?references=true') return Response.json({ schema_version: 1, session_id: 'past',
      scope: 'retained_current_history', redacted: true, turns: [{ turn: 25, role: 'user',
        timestamp: '2026-10-01', agent_id: null, content: 'Discuss the old task today.' }] });
    if (path === '/sessions/resume') return Response.json({ session: 'past', turns: [] });
    return Response.json({});
  }));
  const selected = vi.fn(); window.addEventListener('nerva:session-selected', selected);
  const props = { selectedTurn: true, agent: 'jarvis', sessionId: 'current', recipientStatus: 'ready' as const,
    onSubmit: vi.fn(), t: V2.I18N.en };
  const view = render(<InputBar {...props} />);
  const draft = screen.getByPlaceholderText(V2.I18N.en.placeholder) as HTMLInputElement;
  fireEvent.change(draft, { target: { value: 'My unsent follow-up' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search chat history' }));
  expect(screen.getByRole('dialog', { name: 'Search chat history' })).toBeTruthy();
  expect(calls).not.toContain('/sessions/resume');
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search saved message text' }), { target: { value: 'old task' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Review source' }));
  await screen.findByText('Discuss the old task today.');
  expect(draft.value).toBe('My unsent follow-up');
  expect(props.onSubmit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Continue this conversation' }));
  await waitFor(() => expect(selected).toHaveBeenCalledOnce());
  view.rerender(<InputBar {...props} sessionId="past" />);
  expect(draft.value).toBe('My unsent follow-up');
  expect(props.onSubmit).not.toHaveBeenCalled();
  expect(calls.filter(path => path === '/sessions/resume')).toHaveLength(1);
  window.removeEventListener('nerva:session-selected', selected);
});

it('shows the same search control in Romanian', () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({})));
  render(<InputBar selectedTurn agent="jarvis" sessionId="current" recipientStatus="ready" lang="ro" t={V2.I18N.ro} />);
  fireEvent.click(screen.getByRole('button', { name: 'Caută în conversații' }));
  expect(screen.getByRole('dialog', { name: 'Caută în conversații' })).toBeTruthy();
});

it('stages a sourced passage for the current recipient and keeps it after a refused send', async () => {
  vi.stubGlobal('fetch', vi.fn(async (path: string) => {
    if (path === '/sessions/search') return Response.json({ hits: [{ session_id: 'past', turn: 2, role: 'assistant',
      timestamp: '2026-10-01', agent_id: 'frigga', snippet: 'old task' }], truncated: false, stopped_by: null });
    if (path === '/sessions/past/transcript?references=true') return Response.json({ schema_version: 1, session_id: 'past',
      scope: 'retained_current_history', redacted: true, turns: [{ turn: 2, role: 'assistant',
        timestamp: '2026-10-01', agent_id: 'frigga', content: 'The old task was approved.', reference_revision: 'a'.repeat(64) }] });
    return Response.json({});
  }));
  const onSubmit = vi.fn((..._args: any[]) => true);
  const props = { selectedTurn: true, agent: 'jarvis', sessionId: 'current', recipientStatus: 'ready' as const,
    onSubmit, t: V2.I18N.en };
  const view = render(<InputBar {...props} />);
  const draft = screen.getByPlaceholderText(V2.I18N.en.placeholder) as HTMLInputElement;
  fireEvent.change(draft, { target: { value: 'What should we do next?' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search chat history' }));
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'old task' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Review source' }));
  await screen.findByRole('textbox', { name: 'Select exact text from the verified message' });
  fireEvent.click(screen.getByRole('button', { name: 'Use full message' }));
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button', { name: 'Use in this chat' }));
  await screen.findByText('Chat source: past · message 3 · assistant');
  expect(onSubmit).not.toHaveBeenCalled();
  expect(draft.value).toBe('What should we do next?');
  expect(screen.getByRole('button', { name: 'Use previous image' }).hasAttribute('disabled')).toBe(true);
  expect(screen.getByRole('button', { name: 'Attach board result' }).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: V2.I18N.en.transmit }));
  expect(onSubmit).toHaveBeenCalledOnce();
  const [message, vision, attachments, directReply, history] = onSubmit.mock.calls[0];
  expect([message, vision, attachments, directReply]).toEqual(['What should we do next?', undefined, undefined, false]);
  expect(history.reference).toEqual({ session_id: 'past', turn: 2, revision: 'a'.repeat(64),
    excerpt: 'The old task was approved.', allow_cloud: true });
  act(() => history.onResult(false));
  expect(draft.value).toBe('What should we do next?');
  expect(screen.getByRole('button', { name: 'Remove passage' })).toBeTruthy();
  localStorage.setItem('hud.admin_token', 'changed-owner');
  fireEvent.click(screen.getByRole('button', { name: V2.I18N.en.transmit }));
  expect(onSubmit).toHaveBeenCalledOnce();
  expect(screen.queryByRole('button', { name: 'Remove passage' })).toBeNull();
  view.rerender(<InputBar {...props} agent="frigga" />);
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Remove passage' })).toBeNull());
});
