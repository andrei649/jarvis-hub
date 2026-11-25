import React from 'react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { Conversation } from '../cockpit';
import { ChatMode } from '../modes3';
import { loadOwnerSession } from '../api/owner-session';

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };
});
afterEach(() => vi.unstubAllGlobals());

const user = { role: 'user', text: '  I prefer local models.  ', imageNames: ['private.jpg'], vaultNames: ['Private note'] };
const messages = [user, { role: 'agent', text: 'I can remember that.' }, { role: 'user', text: '   ' }];

describe('Remember message', () => {
  it('offers an editable draft for only a live, nonblank user text turn and reads no facts on open', () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const view = render(<Conversation messages={messages} messageActionsAllowed messageScope="jarvis:s1" />);
    const trigger = screen.getByRole('button', { name: 'Remember message' });
    expect(screen.getAllByRole('button', { name: 'Remember message' })).toHaveLength(1);
    fireEvent.click(trigger);
    expect(screen.getByRole('dialog', { name: 'Remember message' })).toBeTruthy();
    expect((screen.getByRole('textbox', { name: 'Fact to save' }) as HTMLTextAreaElement).value).toBe(user.text);
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Remember message' })).toBeNull();
    expect(document.activeElement).toBe(trigger);
    view.rerender(<Conversation messages={messages} messageActionsAllowed={false} messageScope="jarvis:s1" />);
    expect(screen.queryByRole('button', { name: 'Remember message' })).toBeNull();
  });

  it('closes the draft when the agent, session, or selected message changes', () => {
    const view = render(<Conversation messages={messages} messageActionsAllowed messageScope="jarvis:s1" />);
    fireEvent.click(screen.getByRole('button', { name: 'Remember message' }));
    view.rerender(<Conversation messages={messages} messageActionsAllowed messageScope="athena:s1" />);
    expect(screen.queryByRole('dialog', { name: 'Remember message' })).toBeNull();
    view.rerender(<Conversation messages={messages} messageActionsAllowed messageScope="jarvis:s1" />);
    expect(screen.queryByRole('dialog', { name: 'Remember message' })).toBeNull();
    view.rerender(<Conversation messages={messages} messageActionsAllowed messageScope="athena:s1" />);
    fireEvent.click(screen.getByRole('button', { name: 'Remember message' }));
    view.rerender(<Conversation messages={messages} messageActionsAllowed messageScope="athena:s2" />);
    expect(screen.queryByRole('dialog', { name: 'Remember message' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Remember message' }));
    view.rerender(<Conversation messages={[{ ...user }, ...messages.slice(1)]} messageActionsAllowed messageScope="athena:s2" />);
    expect(screen.queryByRole('dialog', { name: 'Remember message' })).toBeNull();
  });

  it('forwards the live gate through focused Chat', () => {
    const props = { messages, thinking: null, onSubmit: () => {}, t: { channel: 'Chat', transmit: 'Send', placeholder: 'Message' }, agent: 'jarvis', sessionId: 's1' };
    const view = render(<ChatMode {...props} selectedTurn />);
    expect(screen.getByRole('button', { name: 'Remember message' })).toBeTruthy();
    view.rerender(<ChatMode {...props} selectedTurn={false} />);
    expect(screen.queryByRole('button', { name: 'Remember message' })).toBeNull();
  });

  it('closes Remember and drops an in-flight fact list when the owner session changes', async () => {
    let finishList!: (response: unknown) => void;
    const fetchMock = vi.fn((url: string) => url.includes('/api/auth/session')
      ? Promise.resolve({ ok: true, json: async () => ({ signed_in: true, csrf: 'new-owner-session' }) })
      : new Promise(resolve => { finishList = resolve; }));
    vi.stubGlobal('fetch', fetchMock);
    const view = render(<Conversation messages={messages} messageActionsAllowed messageScope="jarvis:s1" />);
    fireEvent.click(screen.getByRole('button', { name: 'Remember message' }));
    fireEvent.click(screen.getByRole('button', { name: 'Replace a saved fact' }));
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/memory/core/facts?store=memory'), expect.anything());
    await act(async () => { await loadOwnerSession(true); });
    expect(screen.queryByRole('dialog', { name: 'Remember message' })).toBeNull();
    await act(async () => { finishList({ ok: true, json: async () => ({ entries: [] }) }); });
    expect(screen.queryByText('No saved facts in this store.')).toBeNull();
    view.unmount();
  });
});
