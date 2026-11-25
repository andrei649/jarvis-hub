import React from 'react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { Conversation } from '../cockpit';
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
