import React from 'react';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Conversation } from '../cockpit';
import { ChatMode } from '../modes3';

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const target = { id: 'target-1', vault: 'Andrei OS', inbox: '00 Acasa/Inbox' };
const status = (captureTarget: unknown = target) => new Response(JSON.stringify({ ok: true, captureTarget }));
const saved = (source: unknown = null) => new Response(JSON.stringify({
  ok: true, relPath: '00 Acasa/Inbox/Edited.md', source,
}));
const reply = { role: 'agent', who: 'jarvis', text: '  Reply text\nsecond line  ', _complete: true, attachmentNames: ['secret'] };
const view = (messages: any[] = [{ role: 'user', text: 'hidden prompt' }, reply]) =>
  render(<Conversation messages={messages} thinking={null} messageActionsAllowed messageScope="jarvis:s1" lang="en" />);

it('uses the existing live gate on both Conversation and focused Chat', () => {
  const messages = [reply];
  const mounted = render(<Conversation messages={messages} thinking={null} messageActionsAllowed={false} messageScope="jarvis:s1" />);
  expect(screen.queryByRole('button', { name: 'Save to Obsidian' })).toBeNull();
  mounted.rerender(<Conversation messages={messages} thinking={null} messageActionsAllowed messageScope="jarvis:s1" />);
  expect(screen.getByRole('button', { name: 'Save to Obsidian' })).toBeTruthy();
  mounted.unmount();
  const props = { messages, thinking: null, agent: 'jarvis', sessionId: 's1', onSubmit: () => {},
    t: { directLine: 'Chat', focusHintChat: '', channel: 'Chat', transmit: 'Send', placeholder: 'Message' } };
  const chat = render(<ChatMode {...props} selectedTurn demo={false} />);
  expect(screen.getByRole('button', { name: 'Save to Obsidian' })).toBeTruthy();
  chat.rerender(<ChatMode {...props} selectedTurn={false} demo={false} />);
  expect(screen.queryByRole('button', { name: 'Save to Obsidian' })).toBeNull();
});

it('offers a reviewed exact reply only in a live eligible conversation and saves once', async () => {
  const calls: { path: string; init: RequestInit }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit) => {
    calls.push({ path, init });
    return path.includes('chat-note') ? saved({ vault: target.vault, file: '00 Acasa/Inbox/Edited.md', readable: true }) : status();
  }));
  const messages = [{ role: 'user', text: 'hidden prompt' }, reply, { role: 'agent', who: 'system', text: 'System' },
    { role: 'agent', text: 'still streaming', _turnId: 'turn' }, { role: 'agent', text: 'unattributed', _unattributed: true }];
  view(messages);
  expect(screen.getAllByRole('button', { name: 'Save to Obsidian' })).toHaveLength(1);
  expect(calls).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', { name: 'Save to Obsidian' }));
  await screen.findByText(target.vault);
  expect((screen.getByRole('textbox', { name: 'Note' }) as HTMLTextAreaElement).value).toBe(reply.text);
  expect((screen.getByRole('textbox', { name: 'Title' }) as HTMLInputElement).value).toBe('Reply text');
  expect(calls.filter(call => call.path.includes('chat-note'))).toHaveLength(0);
  fireEvent.change(screen.getByRole('textbox', { name: 'Title' }), { target: { value: 'Edited' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
  await screen.findByText(/Saved: 00 Acasa\/Inbox\/Edited.md/);
  const posts = calls.filter(call => call.path.includes('chat-note'));
  expect(posts).toHaveLength(1);
  expect(JSON.parse(String(posts[0].init.body))).toEqual({ targetId: target.id, requestId: expect.any(String), title: 'Edited', content: reply.text });
  expect(screen.getAllByRole('link', { name: 'Open in Obsidian' })[0].getAttribute('href'))
    .toBe('obsidian://open?vault=Andrei%20OS&file=00%20Acasa%2FInbox%2FEdited.md');
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  expect(screen.getByText(/Saved to Obsidian: 00 Acasa\/Inbox\/Edited.md/)).toBeTruthy();
});

it('keeps the reviewed request id and body on an uncertain response, then accepts source-null success', async () => {
  const posts: any[] = [];
  vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit) => {
    if (!path.includes('chat-note')) return status();
    posts.push(JSON.parse(String(init.body)));
    return posts.length === 1 ? new Response('offline', { status: 503 }) : saved();
  }));
  view();
  fireEvent.click(screen.getByRole('button', { name: 'Save to Obsidian' }));
  await screen.findByText(target.vault);
  fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
  await screen.findByRole('alert');
  expect((screen.getByRole('textbox', { name: 'Title' }) as HTMLInputElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save to Obsidian' }));
  await screen.findByText(target.vault);
  expect((screen.getByRole('textbox', { name: 'Title' }) as HTMLInputElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Retry save' }));
  await screen.findByText(/Saved: 00 Acasa\/Inbox\/Edited.md/);
  expect(posts).toHaveLength(2);
  expect(posts[1]).toEqual(posts[0]);
  expect(screen.queryByRole('link', { name: 'Open in Obsidian' })).toBeNull();
});

it('rejects a changed target before POST and malformed success receipts', async () => {
  let checks = 0;
  const posts: any[] = [];
  vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit) => {
    if (path.includes('chat-note')) { posts.push(init); return saved({ vault: 'Other vault', file: '00 Acasa/Inbox/Edited.md', readable: true }); }
    checks++;
    return status(checks === 2 ? { ...target, id: 'target-2' } : target);
  }));
  const mounted = view();
  fireEvent.click(screen.getByRole('button', { name: 'Save to Obsidian' }));
  await screen.findByText(target.vault);
  fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
  await screen.findByRole('alert');
  expect(posts).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  mounted.unmount();

  checks = 0;
  vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit) => {
    if (path.includes('chat-note')) { posts.push(init); return saved({ vault: 'Other vault', file: '00 Acasa/Inbox/Edited.md', readable: true }); }
    return status();
  }));
  view();
  fireEvent.click(screen.getByRole('button', { name: 'Save to Obsidian' }));
  await screen.findByText(target.vault);
  fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
  await screen.findByRole('alert');
  expect(screen.queryByText(/Saved: 00 Acasa/)).toBeNull();
  expect(posts).toHaveLength(1);
});

it('drops the draft on scope change and never posts a late status response', async () => {
  let resolve!: (value: Response) => void;
  const fetcher = vi.fn(() => new Promise<Response>(done => { resolve = done; }));
  vi.stubGlobal('fetch', fetcher);
  const mounted = view();
  fireEvent.click(screen.getByRole('button', { name: 'Save to Obsidian' }));
  mounted.rerender(<Conversation messages={[{ role: 'user', text: 'hidden prompt' }, reply]} thinking={null}
    messageActionsAllowed messageScope="jarvis:s2" lang="en" />);
  expect(screen.queryByRole('dialog')).toBeNull();
  resolve(status());
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
});

it('labels Romanian review, destination, and unavailable state', async () => {
  const fetcher = vi.fn(async () => status(null));
  vi.stubGlobal('fetch', fetcher);
  render(<Conversation messages={[reply]} thinking={null} messageActionsAllowed messageScope="jarvis:s1" lang="ro" />);
  fireEvent.click(screen.getByRole('button', { name: 'Salvează în Obsidian' }));
  expect(screen.getByRole('dialog', { name: 'Salvează în Obsidian' })).toBeTruthy();
  expect(screen.getByRole('textbox', { name: 'Titlu' })).toBeTruthy();
  expect(screen.getByRole('textbox', { name: 'Notă' })).toBeTruthy();
  await screen.findByText('Destinație indisponibilă.');
  expect(screen.getByRole('button', { name: 'Salvează nota' }).hasAttribute('disabled')).toBe(true);
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it('corrects an explicit title collision with an edited title and a new UUID while retaining the prior receipt', async () => {
  const posts: any[] = [];
  vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit) => {
    if (!path.includes('chat-note')) return status();
    posts.push(JSON.parse(String(init.body)));
    if (posts.length === 2) return new Response(JSON.stringify({ ok: false, code: 'title_conflict', error: 'title exists' }), { status: 409 });
    const name = posts.length === 1 ? 'Reply text.md' : 'New title.md';
    return new Response(JSON.stringify({ ok: true, relPath: `${target.inbox}/${name}`, source: null }));
  }));
  view();
  fireEvent.click(screen.getByRole('button', { name: 'Save to Obsidian' }));
  await screen.findByText(target.vault);
  fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
  await screen.findByText(/Saved: 00 Acasa\/Inbox\/Reply text.md/);
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save to Obsidian' }));
  await screen.findByText(target.vault);
  fireEvent.change(screen.getByRole('textbox', { name: 'Note' }), { target: { value: 'Edited body' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
  await screen.findByRole('alert');
  expect(screen.getByRole('alert').textContent).toContain('Change the title');
  expect((screen.getByRole('textbox', { name: 'Title' }) as HTMLInputElement).disabled).toBe(false);
  expect((screen.getByRole('textbox', { name: 'Note' }) as HTMLTextAreaElement).value).toBe('Edited body');
  expect(screen.getByRole('button', { name: 'Save note' }).hasAttribute('disabled')).toBe(true);
  expect(screen.getByText(/Saved to Obsidian: 00 Acasa\/Inbox\/Reply text.md/)).toBeTruthy();
  fireEvent.change(screen.getByRole('textbox', { name: 'Title' }), { target: { value: 'New title' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
  await screen.findByText(/Saved: 00 Acasa\/Inbox\/New title.md/);
  expect(posts).toHaveLength(3);
  expect(posts[2]).toMatchObject({ targetId: target.id, title: 'New title', content: 'Edited body' });
  expect(posts[2].requestId).not.toBe(posts[1].requestId);
});

it('keeps separate receipts for two replies in the same conversation', async () => {
  const messages = [{ ...reply, text: 'Reply A' }, { ...reply, text: 'Reply B' }];
  vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit) => {
    if (!path.includes('chat-note')) return status();
    const body = JSON.parse(String(init.body));
    return new Response(JSON.stringify({ ok: true, relPath: `${target.inbox}/${body.title}.md`, source: null }));
  }));
  view(messages);
  fireEvent.click(screen.getAllByRole('button', { name: 'Save to Obsidian' })[0]);
  await screen.findByText(target.vault);
  fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
  await screen.findByText(/Saved: 00 Acasa\/Inbox\/Reply A.md/);
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  fireEvent.click(screen.getAllByRole('button', { name: 'Save to Obsidian' })[1]);
  await screen.findByText(target.vault);
  fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
  await screen.findByText(/Saved: 00 Acasa\/Inbox\/Reply B.md/);
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  expect(screen.getByText(/Saved to Obsidian: 00 Acasa\/Inbox\/Reply A.md/)).toBeTruthy();
  expect(screen.getByText(/Saved to Obsidian: 00 Acasa\/Inbox\/Reply B.md/)).toBeTruthy();
  fireEvent.click(screen.getAllByRole('button', { name: 'Save to Obsidian' })[0]);
  await screen.findByText(target.vault);
  expect(screen.getByText(/Saved to Obsidian: 00 Acasa\/Inbox\/Reply A.md/)).toBeTruthy();
});

it('retains reply A uncertain intent while reply B is saved', async () => {
  const messages = [{ ...reply, text: 'Reply A' }, { ...reply, text: 'Reply B' }];
  const posts: any[] = [];
  vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit) => {
    if (!path.includes('chat-note')) return status();
    const body = JSON.parse(String(init.body));
    posts.push(body);
    if (body.title === 'Reply A' && posts.length === 1) return new Response('offline', { status: 503 });
    return new Response(JSON.stringify({ ok: true, relPath: `${target.inbox}/${body.title}.md`, source: null }));
  }));
  view(messages);
  fireEvent.click(screen.getAllByRole('button', { name: 'Save to Obsidian' })[0]);
  await screen.findByText(target.vault);
  fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
  await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  fireEvent.click(screen.getAllByRole('button', { name: 'Save to Obsidian' })[1]);
  await screen.findByText(target.vault);
  fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
  await screen.findByText(/Saved: 00 Acasa\/Inbox\/Reply B.md/);
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  fireEvent.click(screen.getAllByRole('button', { name: 'Save to Obsidian' })[0]);
  await screen.findByText(target.vault);
  expect((screen.getByRole('textbox', { name: 'Title' }) as HTMLInputElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Retry save' }));
  await screen.findByText(/Saved: 00 Acasa\/Inbox\/Reply A.md/);
  expect(posts[2]).toEqual(posts[0]);
  expect(screen.getByText(/Saved to Obsidian: 00 Acasa\/Inbox\/Reply B.md/)).toBeTruthy();
});

it('prefills a Unicode-safe 120-codepoint title and uses secure UUID fallback', async () => {
  const fullTitle = '😀'.repeat(121);
  const posts: any[] = [];
  vi.stubGlobal('crypto', { getRandomValues: (array: Uint8Array) => array.fill(1) });
  vi.stubGlobal('fetch', vi.fn(async (path: string, init: RequestInit) => {
    if (!path.includes('chat-note')) return status();
    posts.push(JSON.parse(String(init.body)));
    return saved();
  }));
  view([{ ...reply, text: `${fullTitle}\nbody` }]);
  fireEvent.click(screen.getByRole('button', { name: 'Save to Obsidian' }));
  await screen.findByText(target.vault);
  expect((screen.getByRole('textbox', { name: 'Title' }) as HTMLInputElement).value).toBe('😀'.repeat(120));
  fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
  await screen.findByText(/Saved: 00 Acasa\/Inbox\/Edited.md/);
  expect(posts[0].title).toBe('😀'.repeat(120));
  expect(posts[0].requestId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
});
