import React from 'react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Conversation } from '../cockpit';
import { SavedFacts } from '../panels/saved-facts';
import { TalkRegister } from '../home/talk/TalkRegister';
import { openComposerMenu } from '../home/talk/test-support';
import { resetPolling } from '../signals/poll';
import { loadOwnerSession } from '../api/owner-session';

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };
});
afterEach(() => vi.unstubAllGlobals());

const user = { role: 'user', text: '  I prefer local models.  ', imageNames: ['private.jpg'], vaultNames: ['Private note'] };
const messages = [user, { role: 'agent', text: 'I can remember that.' }, { role: 'user', text: '   ' }];

/* "Remember message" sits in an owner turn's More menu since the re-lay (PHASE_B_PLAN.md §5.3, §8.3):
   `offered()` counts the owner turns that carry it (the menu's items stay mounted while it is
   closed); `remember()` opens the first such turn's More, picks it, and returns that More button —
   the dialog's opener, since the picked item hides with its menu. */
const offered = () => document.querySelectorAll('[data-turn="owner"] [data-act="remember"]').length;
function remember(): HTMLElement {
  const turn = Array.from(document.querySelectorAll<HTMLElement>('[data-turn="owner"]')).find(t => t.querySelector('[data-act="remember"]'))!;
  const menu = openComposerMenu('more', turn);
  fireEvent.click(within(menu).getByRole('button', { name: 'Remember message' }));
  return menu.firstElementChild as HTMLElement;
}

describe('Remember message', () => {
  it('saves the exact selected source after a fact edit and shows its later receipt', async () => {
    localStorage.setItem('hud.admin_token', 'synthetic-admin-token');
    const revision = 'a'.repeat(64);
    const source = { session_id: 's1', turn: 3, revision, role: 'user' };
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes('/sessions/s1/transcript?references=true')) return Response.json({
        schema_version: 1, session_id: 's1', scope: 'retained_current_history', redacted: true,
        turns: [{ turn: 3, role: 'user', agent_id: null, content: user.text, reference_revision: revision }],
      });
      if (url.includes('/api/dashboard/today/entries') && init?.method === 'POST') return Response.json({
        ok: true, changed: true, entry: { entry_id: 'memory:memory:aaaaaaaaaaaaaaaa', store: 'memory',
          value: 'I prefer local models for drafts.', source },
      });
      if (url.includes('/api/dashboard/today/entries?store=memory')) return Response.json({ entries: [{
        entry_id: 'memory:memory:aaaaaaaaaaaaaaaa', store: 'memory', value: 'I prefer local models for drafts.', source,
      }] });
      if (url.includes('/api/dashboard/today/entries?store=user')) return Response.json({ entries: [] });
      if (url.includes('/api/memory')) return Response.json({ injected: true });
      return Response.json({});
    });
    vi.stubGlobal('fetch', fetchMock);
    const view = render(<Conversation messages={messages} sessionId="s1" agent="jarvis" messageActionsAllowed messageScope="jarvis:s1" />);
    remember();
    fireEvent.change(screen.getByRole('textbox', { name: 'Fact to save' }), { target: { value: 'I prefer local models for drafts.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save fact' }));
    await waitFor(() => expect(screen.getByText(/Saved fact in Agent notes/)).toBeTruthy());
    const posted = fetchMock.mock.calls.find(([url, init]) => String(url).includes('/api/dashboard/today/entries') && init?.method === 'POST');
    expect(posted).toBeTruthy();
    expect(JSON.parse(String(posted![1]?.body)).source).toEqual({ session_id: 's1', turn: 3, revision, excerpt: user.text });
    expect((posted![1]?.headers as Record<string, string>)['X-Admin-Token']).toBe('synthetic-admin-token');
    view.unmount();
    render(<SavedFacts />);
    await waitFor(() => expect(screen.getByText('Chat source: s1 · message 4 · user')).toBeTruthy());
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('references=true'), expect.objectContaining({ method: 'GET' }));
    localStorage.removeItem('hud.admin_token');
  });
  it('requires an explicit manual choice when identical saved messages are ambiguous', async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes('/sessions/s1/transcript?references=true')) return Response.json({
        schema_version: 1, session_id: 's1', scope: 'retained_current_history', redacted: true,
        turns: [2, 4].map(turn => ({ turn, role: 'user', agent_id: null, content: user.text,
          reference_revision: 'a'.repeat(64) })),
      });
      if (url.includes('/api/dashboard/today/entries') && init?.method === 'POST') return Response.json({
        ok: true, changed: true, entry: { entry_id: 'memory:memory:aaaaaaaaaaaaaaaa', store: 'memory', value: user.text.trim() },
      });
      return Response.json({});
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<Conversation messages={messages} sessionId="s1" agent="jarvis" messageActionsAllowed messageScope="jarvis:s1" />);
    remember();
    fireEvent.click(screen.getByRole('button', { name: 'Save fact' }));
    await screen.findByRole('button', { name: 'Choose manual save without chat source' });
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).includes('/api/dashboard/today/entries') && init?.method === 'POST')).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Choose manual save without chat source' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save fact' }));
    await waitFor(() => expect(screen.getByText(/Saved fact in Agent notes/)).toBeTruthy());
    const post = fetchMock.mock.calls.find(([url, init]) => String(url).includes('/api/dashboard/today/entries') && init?.method === 'POST');
    expect(JSON.parse(String(post![1]?.body))).toEqual({ store: 'memory', value: user.text.trim() });
  });
  it('does not post a source after the selected session changes during lookup', async () => {
    let finish!: (value: Response) => void;
    const fetchMock = vi.fn((url: string, _init?: RequestInit) => String(url).includes('/sessions/s1/transcript?references=true')
      ? new Promise<Response>(resolve => { finish = resolve; }) : Promise.resolve(Response.json({})));
    vi.stubGlobal('fetch', fetchMock);
    const view = render(<Conversation messages={messages} sessionId="s1" agent="jarvis" messageActionsAllowed messageScope="jarvis:s1" />);
    remember();
    fireEvent.click(screen.getByRole('button', { name: 'Save fact' }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/sessions/s1/transcript?references=true'), expect.anything()));
    view.rerender(<Conversation messages={messages} sessionId="s2" agent="jarvis" messageActionsAllowed messageScope="jarvis:s2" />);
    await act(async () => finish(Response.json({ schema_version: 1, session_id: 's1',
      scope: 'retained_current_history', redacted: true, turns: [{ turn: 0, role: 'user', agent_id: null,
        content: user.text, reference_revision: 'a'.repeat(64) }] })));
    expect(fetchMock.mock.calls.some(([url, init]) => String(url).includes('/api/dashboard/today/entries') && init?.method === 'POST')).toBe(false);
  });
  it('keeps the draft and offers manual save when the source revision is refused', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes('/sessions/s1/transcript?references=true')) return Response.json({
        schema_version: 1, session_id: 's1', scope: 'retained_current_history', redacted: true,
        turns: [{ turn: 0, role: 'user', agent_id: null, content: user.text, reference_revision: 'a'.repeat(64) }],
      });
      if (url.includes('/api/dashboard/today/entries') && init?.method === 'POST')
        return Response.json({ error: 'source_changed' }, { status: 409 });
      return Response.json({});
    }));
    render(<Conversation messages={messages} sessionId="s1" agent="jarvis" messageActionsAllowed messageScope="jarvis:s1" />);
    remember();
    fireEvent.click(screen.getByRole('button', { name: 'Save fact' }));
    await screen.findByRole('button', { name: 'Choose manual save without chat source' });
    expect((screen.getByRole('textbox', { name: 'Fact to save' }) as HTMLTextAreaElement).value).toBe(user.text);
  });
  it('hides an earlier owner source while credentials change and the list refresh is pending', async () => {
    localStorage.setItem('hud.admin_token', 'first-owner');
    let pending = false;
    const source = { session_id: 's1', turn: 2, revision: 'a'.repeat(64), role: 'user' };
    const fetchMock = vi.fn((url: string) => {
      if (pending && url.includes('/api/dashboard/today/entries')) return new Promise<Response>(() => {});
      if (url.includes('/api/dashboard/today/entries?store=memory')) return Promise.resolve(Response.json({ entries: [
        { entry_id: 'memory:memory:aaaaaaaaaaaaaaaa', store: 'memory', value: 'Synthetic fact', source },
      ] }));
      if (url.includes('/api/dashboard/today/entries?store=user')) return Promise.resolve(Response.json({ entries: [] }));
      return Promise.resolve(Response.json({ injected: true }));
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<SavedFacts />);
    await screen.findByText('Chat source: s1 · message 3 · user');
    pending = true;
    localStorage.removeItem('hud.admin_token');
    await act(async () => window.dispatchEvent(new StorageEvent('storage', { key: 'hud.admin_token' })));
    expect(screen.queryByText('Chat source: s1 · message 3 · user')).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/dashboard/today/entries?store=memory'), expect.anything());
  });
  it('offers an editable draft for only a live, nonblank user text turn and reads no facts on open', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const view = render(<Conversation messages={messages} messageActionsAllowed messageScope="jarvis:s1" />);
    // one owner turn offers it: the nonblank one (not the blank turn, not the reply)
    expect(offered()).toBe(1);
    const trigger = remember();
    expect(screen.getByRole('dialog', { name: 'Remember message' })).toBeTruthy();
    expect((screen.getByRole('textbox', { name: 'Fact to save' }) as HTMLTextAreaElement).value).toBe(user.text);
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Remember message' })).toBeNull();
    expect(document.activeElement).toBe(trigger);
    view.rerender(<Conversation messages={messages} messageActionsAllowed={false} messageScope="jarvis:s1" />);
    expect(offered()).toBe(0);
    expect(screen.queryByRole('button', { name: 'Remember message' })).toBeNull();
  });

  it('closes the draft when the agent, session, or selected message changes', () => {
    const view = render(<Conversation messages={messages} messageActionsAllowed messageScope="jarvis:s1" />);
    remember();
    view.rerender(<Conversation messages={messages} messageActionsAllowed messageScope="athena:s1" />);
    expect(screen.queryByRole('dialog', { name: 'Remember message' })).toBeNull();
    view.rerender(<Conversation messages={messages} messageActionsAllowed messageScope="jarvis:s1" />);
    expect(screen.queryByRole('dialog', { name: 'Remember message' })).toBeNull();
    view.rerender(<Conversation messages={messages} messageActionsAllowed messageScope="athena:s1" />);
    remember();
    view.rerender(<Conversation messages={messages} messageActionsAllowed messageScope="athena:s2" />);
    expect(screen.queryByRole('dialog', { name: 'Remember message' })).toBeNull();
    remember();
    view.rerender(<Conversation messages={[{ ...user }, ...messages.slice(1)]} messageActionsAllowed messageScope="athena:s2" />);
    expect(screen.queryByRole('dialog', { name: 'Remember message' })).toBeNull();
  });

  it('forwards the live gate through the conversation page', () => {
    resetPolling();
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({})));
    // the conversation page as App draws it: message actions are live unless the demo sample is on
    const page = (demo: boolean) => <TalkRegister variant="chat" turns={[]} messages={messages} thinking={null} onSubmit={() => true} onStop={() => {}} onProv={() => {}}
      t={{ channel: 'Chat', transmit: 'Send', placeholder: 'Message' }} agent="jarvis" agents={[]} sessionId="s1" lang="en"
      messageScope="jarvis:s1" recipientStatus="ready" demo={demo} messageActionsAllowed={!demo} exportAllowed={!demo} selectedTurn={!demo}
      onSelectAgent={() => {}} />;
    const view = render(page(false));
    expect(offered()).toBe(1);
    remember();
    expect(screen.getByRole('dialog', { name: 'Remember message' })).toBeTruthy();
    view.rerender(page(true));
    expect(offered()).toBe(0);
    expect(screen.queryByRole('dialog', { name: 'Remember message' })).toBeNull();
    view.unmount();
    resetPolling();
  });

  it('closes Remember and drops an in-flight fact list when the owner session changes', async () => {
    let finishList!: (response: unknown) => void;
    const fetchMock = vi.fn((url: string) => url.includes('/api/auth/session')
      ? Promise.resolve({ ok: true, json: async () => ({ signed_in: true, csrf: 'new-owner-session' }) })
      : new Promise(resolve => { finishList = resolve; }));
    vi.stubGlobal('fetch', fetchMock);
    const view = render(<Conversation messages={messages} messageActionsAllowed messageScope="jarvis:s1" />);
    remember();
    fireEvent.click(screen.getByRole('button', { name: 'Replace a saved fact' }));
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/memory/core/facts?store=memory'), expect.anything());
    await act(async () => { await loadOwnerSession(true); });
    expect(screen.queryByRole('dialog', { name: 'Remember message' })).toBeNull();
    await act(async () => { finishList({ ok: true, json: async () => ({ entries: [] }) }); });
    expect(screen.queryByText('No saved facts in this store.')).toBeNull();
    view.unmount();
  });
});
