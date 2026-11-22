import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { ChatHistorySearch } from '../chat-history-search';
import { apiGet, apiPost } from '../api/client';

vi.mock('../api/client', () => ({ apiGet: vi.fn(), apiPost: vi.fn(), getAdminToken: () => '', getToken: () => '' }));
vi.mock('../api/owner-session', () => ({ isNetworkedOrigin: () => false, ownerSession: () => null,
  csrfToken: () => '', onOwnerSession: () => () => {} }));

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };
});
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const hit = { session_id: 'old-session', turn: 31, role: 'assistant', timestamp: '2026-10-01T10:00:00Z',
  agent_id: 'frigga', snippet: '…the exact old decision…' };
const transcript = { schema_version: 1, session_id: 'old-session', scope: 'retained_current_history', redacted: true,
  turns: [{ turn: 31, role: 'assistant', timestamp: hit.timestamp, agent_id: 'frigga', content: 'We recorded the exact old decision here.' }] };

function open(props: { lang?: string; hasDraft?: boolean; hasAttachment?: boolean; turnActive?: boolean; canContinue?: () => boolean;
  recipient?: string; onUse?: (reference: any, role: 'user' | 'assistant') => boolean; canUse?: () => boolean } = {}) {
  const opener = document.createElement('button'); document.body.append(opener); opener.focus();
  const onClose = vi.fn();
  const view = render(<ChatHistorySearch lang={props.lang || 'en'} opener={opener} onClose={onClose}
    hasDraft={!!props.hasDraft} hasAttachment={!!props.hasAttachment} turnActive={!!props.turnActive}
    canContinue={props.canContinue} recipient={props.recipient} onUse={props.onUse} canUse={props.canUse} />);
  return { ...view, opener, onClose };
}

async function findHit() {
  fireEvent.change(screen.getByRole('searchbox', { name: 'Search saved message text' }), { target: { value: 'old decision' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
  await screen.findByText('…the exact old decision…');
}

it('searches saved message text, verifies the exact source, and resumes only on explicit Continue', async () => {
  vi.mocked(apiPost).mockImplementation(async path => path === '/sessions/search'
    ? { hits: [hit], truncated: false, stopped_by: null } : { session: hit.session_id, turns: [] });
  vi.mocked(apiGet).mockResolvedValue(transcript);
  const selected = vi.fn(); window.addEventListener('nerva:session-selected', selected);
  const view = open({ hasDraft: true });
  await findHit();
  expect(apiPost).toHaveBeenCalledWith('/sessions/search', { query: 'old decision', limit: 20 }, { admin: true });
  expect(apiGet).not.toHaveBeenCalled();
  expect(selected).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Review source' }));
  await screen.findByText('We recorded the exact old decision here.');
  expect(apiGet).toHaveBeenCalledWith('/sessions/old-session/transcript?references=true', { admin: true });
  expect(screen.getByText(/typed message will stay/)).toBeTruthy();
  expect(apiPost).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Continue this conversation' }));
  await waitFor(() => expect(selected).toHaveBeenCalledOnce());
  expect(apiGet).toHaveBeenCalledTimes(2);
  expect(apiPost).toHaveBeenCalledWith('/sessions/resume', { session_id: 'old-session' }, { admin: true });
  expect((selected.mock.calls[0][0] as CustomEvent).detail).toEqual({ sessionId: 'old-session', turns: [] });
  window.removeEventListener('nerva:session-selected', selected);
  view.unmount(); view.opener.remove();
});

it('keeps results reviewable but blocks continuation while an attachment is scoped to the old chat', async () => {
  vi.mocked(apiPost).mockResolvedValue({ hits: [hit], truncated: false, stopped_by: null });
  vi.mocked(apiGet).mockResolvedValue(transcript);
  const view = open({ lang: 'ro', hasAttachment: true });
  fireEvent.change(screen.getByRole('searchbox', { name: 'Caută în mesajele salvate' }), { target: { value: 'decision' } });
  fireEvent.click(screen.getByRole('button', { name: 'Caută' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Vezi sursa' }));
  await screen.findByText('We recorded the exact old decision here.');
  expect(screen.getByRole('button', { name: 'Continuă această conversație' }).hasAttribute('disabled')).toBe(true);
  expect(screen.getByText(/Trimite sau elimină atașamentul/)).toBeTruthy();
  expect(apiPost).toHaveBeenCalledTimes(1);
  view.unmount(); view.opener.remove();
});

it('refuses a changed turn and clears stale review on query change or close', async () => {
  vi.mocked(apiPost).mockResolvedValue({ hits: [hit], truncated: false, stopped_by: null });
  vi.mocked(apiGet).mockResolvedValue({ ...transcript, turns: [{ ...transcript.turns[0], content: 'Different text' }] });
  const view = open();
  await findHit();
  fireEvent.click(screen.getByRole('button', { name: 'Review source' }));
  await screen.findByRole('alert');
  expect(screen.queryByRole('button', { name: 'Continue this conversation' })).toBeNull();
  expect(apiPost).toHaveBeenCalledTimes(1);
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'new topic' } });
  expect(screen.queryByText('…the exact old decision…')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  expect(view.onClose).toHaveBeenCalledOnce();
  view.unmount(); expect(document.activeElement).toBe(view.opener); view.opener.remove();
});

it('rechecks the source before Continue and refuses a changed result', async () => {
  vi.mocked(apiPost).mockResolvedValue({ hits: [hit], truncated: false, stopped_by: null });
  vi.mocked(apiGet).mockResolvedValueOnce(transcript)
    .mockResolvedValueOnce({ ...transcript, turns: [{ ...transcript.turns[0], agent_id: 'howard' }] });
  const view = open();
  await findHit();
  fireEvent.click(screen.getByRole('button', { name: 'Review source' }));
  await screen.findByText('We recorded the exact old decision here.');
  fireEvent.click(screen.getByRole('button', { name: 'Continue this conversation' }));
  await screen.findByRole('alert');
  expect(screen.queryByText('We recorded the exact old decision here.')).toBeNull();
  expect(apiPost).toHaveBeenCalledTimes(1);
  view.unmount(); view.opener.remove();
});

it('refuses Continue when text outside the unchanged search snippet changed after review', async () => {
  const reviewed = { ...transcript, turns: [{ ...transcript.turns[0],
    content: 'We recorded the exact old decision here. The original trailing note.' }] };
  const changed = { ...transcript, turns: [{ ...reviewed.turns[0],
    content: 'We recorded the exact old decision here. A revised trailing note.' }] };
  vi.mocked(apiPost).mockResolvedValue({ hits: [hit], truncated: false, stopped_by: null });
  vi.mocked(apiGet).mockResolvedValueOnce(reviewed).mockResolvedValueOnce(changed);
  const view = open();
  await findHit();
  fireEvent.click(screen.getByRole('button', { name: 'Review source' }));
  await screen.findByText(reviewed.turns[0].content);
  fireEvent.click(screen.getByRole('button', { name: 'Continue this conversation' }));
  expect((await screen.findByRole('alert')).textContent).toContain('This saved turn changed');
  expect(screen.queryByText(reviewed.turns[0].content)).toBeNull();
  expect(apiPost).toHaveBeenCalledTimes(1);
  view.unmount(); view.opener.remove();
});

it('ignores an old search response after the query changes', async () => {
  let finish!: (value: any) => void;
  vi.mocked(apiPost).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const view = open();
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'old' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'new' } });
  await act(async () => finish({ hits: [hit], truncated: false, stopped_by: null }));
  expect(screen.queryByText('…the exact old decision…')).toBeNull();
  view.unmount(); view.opener.remove();
});

it('accepts a codepoint-bounded snippet with emoji and gives an owner-only refusal to guests', async () => {
  const emoji = '😀'.repeat(200);
  vi.mocked(apiPost).mockResolvedValueOnce({ hits: [{ ...hit, snippet: emoji }], truncated: true, stopped_by: 'limit' });
  const view = open();
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'emoji' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
  await screen.findByText(emoji);
  expect(screen.getByText(/Results are limited/)).toBeTruthy();
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'next' } });
  vi.mocked(apiPost).mockRejectedValueOnce(Object.assign(new Error('denied'), { status: 403 }));
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Only the owner');
  view.unmount(); view.opener.remove();
});

it('refuses to resume if a reply starts while source verification is pending', async () => {
  let active = false;
  let finish!: (value: any) => void;
  vi.mocked(apiPost).mockResolvedValue({ hits: [hit], truncated: false, stopped_by: null });
  vi.mocked(apiGet).mockResolvedValueOnce(transcript).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const view = open({ canContinue: () => !active });
  await findHit();
  fireEvent.click(screen.getByRole('button', { name: 'Review source' }));
  await screen.findByText('We recorded the exact old decision here.');
  fireEvent.click(screen.getByRole('button', { name: 'Continue this conversation' }));
  await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(2));
  active = true;
  await act(async () => finish(transcript));
  expect((await screen.findByRole('alert')).textContent).toContain('Finish or stop the current reply');
  expect(apiPost).toHaveBeenCalledTimes(1);
  view.unmount(); view.opener.remove();
});

it('stages only a selected, verified passage in the current chat without resuming', async () => {
  const sourced = { ...transcript, turns: [{ ...transcript.turns[0], reference_revision: 'a'.repeat(64) }] };
  vi.mocked(apiPost).mockResolvedValue({ hits: [hit], truncated: false, stopped_by: null });
  vi.mocked(apiGet).mockResolvedValue(sourced);
  const onUse = vi.fn((_reference: any) => true);
  const view = open({ recipient: 'frigga', onUse });
  await findHit();
  fireEvent.click(screen.getByRole('button', { name: 'Review source' }));
  const area = await screen.findByRole('textbox', { name: 'Select exact text from the verified message' }) as HTMLTextAreaElement;
  area.setSelectionRange(16, 34);
  fireEvent.click(screen.getByRole('button', { name: 'Select exact text from the verified message' }));
  expect(screen.getByText('exact old decision')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Use in this chat' }));
  await waitFor(() => expect(onUse).toHaveBeenCalledWith({ session_id: 'old-session', turn: 31,
    revision: 'a'.repeat(64), excerpt: 'exact old decision', allow_cloud: false }, 'assistant'));
  expect(apiPost).toHaveBeenCalledTimes(1);
  view.unmount(); view.opener.remove();
});

it('requires recipient consent and rejects a changed source before staging', async () => {
  const sourced = { ...transcript, turns: [{ ...transcript.turns[0], reference_revision: 'a'.repeat(64) }] };
  vi.mocked(apiPost).mockResolvedValue({ hits: [hit], truncated: false, stopped_by: null });
  vi.mocked(apiGet).mockResolvedValueOnce(sourced).mockResolvedValueOnce({ ...sourced, turns: [{ ...sourced.turns[0], reference_revision: 'b'.repeat(64) }] });
  const onUse = vi.fn(() => true);
  const view = open({ recipient: 'athena', onUse });
  await findHit(); fireEvent.click(screen.getByRole('button', { name: 'Review source' }));
  await screen.findByRole('textbox', { name: 'Select exact text from the verified message' });
  fireEvent.click(screen.getByRole('button', { name: 'Use full message' }));
  expect(screen.getByRole('button', { name: 'Use in this chat' }).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button', { name: 'Use in this chat' }));
  expect((await screen.findByRole('alert')).textContent).toContain('changed');
  expect(onUse).not.toHaveBeenCalled();
  view.unmount(); view.opener.remove();
});

it('allows a short contiguous selection from a source longer than the excerpt cap', async () => {
  const long = `We recorded the exact old decision here. ${'Later details. '.repeat(700)}`;
  const sourced = { ...transcript, turns: [{ ...transcript.turns[0], content: long, reference_revision: 'a'.repeat(64) }] };
  vi.mocked(apiPost).mockResolvedValue({ hits: [hit], truncated: false, stopped_by: null });
  vi.mocked(apiGet).mockResolvedValue(sourced);
  const onUse = vi.fn((_reference: any) => true);
  const view = open({ recipient: 'frigga', onUse });
  await findHit(); fireEvent.click(screen.getByRole('button', { name: 'Review source' }));
  const area = await screen.findByRole('textbox', { name: 'Select exact text from the verified message' }) as HTMLTextAreaElement;
  expect(screen.getByRole('button', { name: 'Use full message' }).hasAttribute('disabled')).toBe(true);
  area.setSelectionRange(16, 34);
  fireEvent.click(screen.getByRole('button', { name: 'Select exact text from the verified message' }));
  fireEvent.click(screen.getByRole('button', { name: 'Use in this chat' }));
  await waitFor(() => expect(onUse).toHaveBeenCalledOnce());
  expect(onUse.mock.calls[0]?.[0].excerpt).toBe('exact old decision');
  view.unmount(); view.opener.remove();
});
