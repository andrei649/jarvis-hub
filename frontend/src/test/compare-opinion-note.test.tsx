import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { CompareAgentsDialog } from '../compare-agents';

const listeners = vi.hoisted(() => new Set<() => void>());
vi.mock('../api/owner-session', () => ({
  isNetworkedOrigin: () => false,
  loadOwnerSession: vi.fn(),
  ownerSession: () => null,
  csrfToken: () => '',
  onOwnerSession: (listener: () => void) => { listeners.add(listener); return () => listeners.delete(listener); },
  requireSignIn: vi.fn(),
}));

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.clear(); listeners.clear(); document.querySelectorAll('[data-test-opener]').forEach(node => node.remove()); });

const target = { id: 'fixture-target', vault: 'Fixture Vault', inbox: 'Inbox' };
const agents = [{ id: 'alpha', name: 'Alpha', role: 'Research' }, { id: 'beta', name: 'Beta', role: 'Review' }];
const opinion = (agent: string, text: string) => ({ agent, ok: true, text, model: `model-${agent}`, route: 'local' });
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const status = () => json({ ok: true, captureTarget: target });
const saved = (title = 'Reply') => json({ ok: true, relPath: `Inbox/${title}.md`,
  source: { vault: target.vault, file: `Inbox/${title}.md`, readable: true } });

function open(lang = 'en', question = 'Can we verify this?') {
  const opener = document.createElement('button');
  opener.setAttribute('data-test-opener', '');
  document.body.append(opener);
  opener.focus();
  const onClose = vi.fn();
  const view = render(<CompareAgentsDialog question={question} agent="alpha" agents={agents}
    lang={lang} opener={opener} onClose={onClose} />);
  return { ...view, opener, onClose };
}

function requests(respond: (path: string, init: RequestInit) => Response | Promise<Response>) {
  const calls: { path: string; init: RequestInit }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit) => {
    const path = String(url);
    expect(new URL(path, window.location.href).origin).toBe(window.location.origin);
    expect(init).toMatchObject({ credentials: 'same-origin', redirect: 'error', cache: 'no-store' });
    calls.push({ path, init });
    return respond(path, init);
  }));
  return calls;
}

const notes = (calls: { path: string; init: RequestInit }[]) => calls.filter(call => call.path.endsWith('/api/os/brain/chat-note'));
const vaultReads = (calls: { path: string; init: RequestInit }[]) => calls.filter(call => call.path.endsWith('/api/os/status'));
const cards = () => screen.getAllByRole('article');

it('offers a per-card save only for a real answer and sends exactly the reviewed note', async () => {
  const calls = requests((path, init) => path.endsWith('/api/agents/opinions')
    ? json({ opinions: [opinion('alpha', 'Alpha answer'), { agent: 'beta', ok: false, reason: 'timed_out' }] })
    : path.endsWith('/api/os/status') ? status()
      : path.endsWith('/api/os/brain/chat-note') ? saved('Reviewed') : json({}, 404));
  const view = open();
  expect(calls).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', { name: 'Compare answers' }));
  await screen.findByText('Alpha answer');
  expect(vaultReads(calls)).toHaveLength(0);
  expect(notes(calls)).toHaveLength(0);
  expect(within(cards()[0]).getByRole('button', { name: 'Save to Obsidian' })).toBeTruthy();
  expect(within(cards()[1]).queryByRole('button', { name: 'Save to Obsidian' })).toBeNull();
  const trigger = within(cards()[0]).getByRole('button', { name: 'Save to Obsidian' });
  fireEvent.click(trigger);
  await screen.findByText(target.vault);
  expect(vaultReads(calls)).toHaveLength(1);
  expect(notes(calls)).toHaveLength(0);
  expect(screen.getByRole('dialog', { name: 'Save to Obsidian' }).querySelector('dl div:nth-child(2) dd')?.textContent).toBe('Inbox');
  const content = screen.getByRole('textbox', { name: 'Note' }) as HTMLTextAreaElement;
  for (const part of ['Can we verify this?', 'Alpha', 'model-alpha', 'local', 'Alpha answer']) {
    expect(content.value).toContain(part);
  }
  expect(content.value).not.toContain('Beta answer');
  const reviewed = `${content.value}\nOwner edit`;
  fireEvent.change(content, { target: { value: reviewed } });
  const title = screen.getByRole('textbox', { name: 'Title' }) as HTMLInputElement;
  fireEvent.change(title, { target: { value: 'Reviewed' } });
  expect(notes(calls)).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
  await screen.findByText(/Saved: Inbox\/Reviewed.md/);
  expect(notes(calls)).toHaveLength(1);
  expect(JSON.parse(String(notes(calls)[0].init.body))).toEqual({
    targetId: target.id, requestId: expect.any(String), title: 'Reviewed', content: reviewed,
  });
  expect(within(screen.getByRole('dialog', { name: 'Save to Obsidian' })).getByRole('link', { name: 'Open in Obsidian' }).getAttribute('href'))
    .toBe('obsidian://open?vault=Fixture%20Vault&file=Inbox%2FReviewed.md');
  fireEvent.keyDown(screen.getByRole('dialog', { name: 'Save to Obsidian' }), { key: 'Escape' });
  expect(screen.queryByRole('dialog', { name: 'Save to Obsidian' })).toBeNull();
  await waitFor(() => expect(document.activeElement).toBe(trigger));
  expect(within(cards()[0]).getByText(/Inbox\/Reviewed.md/)).toBeTruthy();
  expect(within(cards()[1]).queryByText(/Inbox\/Reviewed.md/)).toBeNull();
  view.unmount();
});

it('keeps one uncertain submission per result and retries the exact UUID after reopening', async () => {
  const posts: any[] = [];
  const calls = requests((path, init) => {
    if (path.endsWith('/api/agents/opinions')) return json({ opinions: [opinion('alpha', 'Alpha answer'), opinion('beta', 'Beta answer')] });
    if (path.endsWith('/api/os/status')) return status();
    if (path.endsWith('/api/os/brain/chat-note')) {
      const body = JSON.parse(String(init.body));
      posts.push(body);
      return posts.length === 1 ? json({ error: 'unconfirmed' }, 503) : saved(body.title);
    }
    return json({}, 404);
  });
  const view = open();
  fireEvent.click(screen.getByRole('button', { name: 'Compare answers' }));
  await screen.findByText('Beta answer');
  fireEvent.click(within(cards()[0]).getByRole('button', { name: 'Save to Obsidian' }));
  await screen.findByText(target.vault);
  fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
  await screen.findByRole('alert');
  fireEvent.click(within(screen.getByRole('dialog', { name: 'Save to Obsidian' })).getByRole('button', { name: 'Close' }));
  expect(within(cards()[1]).queryByText(/Saved to Obsidian/)).toBeNull();
  fireEvent.click(within(cards()[0]).getByRole('button', { name: 'Save to Obsidian' }));
  await screen.findByText(target.vault);
  expect((screen.getByRole('textbox', { name: 'Note' }) as HTMLTextAreaElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Retry save' }));
  await screen.findByText(/Saved: Inbox\//);
  expect(posts).toHaveLength(2);
  expect(posts[1]).toEqual(posts[0]);
  fireEvent.click(within(screen.getByRole('dialog', { name: 'Save to Obsidian' })).getByRole('button', { name: 'Close' }));
  fireEvent.click(within(cards()[1]).getByRole('button', { name: 'Save to Obsidian' }));
  await screen.findByText(target.vault);
  expect((screen.getByRole('textbox', { name: 'Note' }) as HTMLTextAreaElement).value).toContain('Beta answer');
  expect((screen.getByRole('textbox', { name: 'Note' }) as HTMLTextAreaElement).value).not.toContain('Alpha answer');
  expect(notes(calls)).toHaveLength(2);
  view.unmount();
});

it('invalidates a saved card on a new question and refuses an old pending target after owner or scope change', async () => {
  let completeTarget: ((value: Response) => void) | null = null;
  const calls = requests(path => path.endsWith('/api/agents/opinions')
    ? json({ opinions: [opinion('alpha', 'Current answer'), opinion('beta', 'Other answer')] })
    : path.endsWith('/api/os/status')
      ? completeTarget ? status() : new Promise<Response>(resolve => { completeTarget = resolve; })
      : path.endsWith('/api/os/brain/chat-note') ? saved() : json({}, 404));
  localStorage.setItem('hud.admin_token', 'owner-one');
  const view = open();
  fireEvent.click(screen.getByRole('button', { name: 'Compare answers' }));
  await screen.findByText('Current answer');
  fireEvent.click(within(cards()[0]).getByRole('button', { name: 'Save to Obsidian' }));
  expect(vaultReads(calls)).toHaveLength(1);
  localStorage.setItem('hud.admin_token', 'owner-two');
  fireEvent.focus(window);
  expect(screen.queryByText('Current answer')).toBeNull();
  await act(async () => completeTarget?.(status()));
  expect(notes(calls)).toHaveLength(0);
  view.unmount();

  const next = open('en', 'New comparison');
  fireEvent.click(screen.getByRole('button', { name: 'Compare answers' }));
  await screen.findByText('Current answer');
  fireEvent.change(screen.getByRole('textbox', { name: 'Question' }), { target: { value: 'Edited question' } });
  expect(screen.queryByText('Current answer')).toBeNull();
  expect(screen.queryByRole('button', { name: 'Save to Obsidian' })).toBeNull();
  expect(notes(calls)).toHaveLength(0);
  next.unmount();

  completeTarget = null;
  const scoped = open('en', 'Scope will close');
  fireEvent.click(screen.getByRole('button', { name: 'Compare answers' }));
  await screen.findByText('Current answer');
  fireEvent.click(within(cards()[0]).getByRole('button', { name: 'Save to Obsidian' }));
  expect(vaultReads(calls)).toHaveLength(2);
  scoped.unmount();
  await act(async () => completeTarget?.(status()));
  expect(notes(calls)).toHaveLength(0);
});

it('rejects a stale card before any vault lookup when the owner credential changes silently', async () => {
  const calls = requests(path => path.endsWith('/api/agents/opinions')
    ? json({ opinions: [opinion('alpha', 'Alpha answer'), opinion('beta', 'Beta answer')] })
    : path.endsWith('/api/os/status') ? status() : json({}, 404));
  localStorage.setItem('hud.admin_token', 'owner-one');
  const view = open();
  fireEvent.click(screen.getByRole('button', { name: 'Compare answers' }));
  await screen.findByText('Alpha answer');
  localStorage.setItem('hud.admin_token', 'owner-two');
  fireEvent.click(within(cards()[0]).getByRole('button', { name: 'Save to Obsidian' }));
  expect(vaultReads(calls)).toHaveLength(0);
  expect(screen.queryByRole('dialog', { name: 'Save to Obsidian' })).toBeNull();
  view.unmount();
});

it('rechecks the owner credential after the second target lookup and before the POST', async () => {
  let resolveSecond: ((response: Response) => void) | null = null;
  let targetReads = 0;
  const calls = requests(path => {
    if (path.endsWith('/api/agents/opinions')) return json({ opinions: [opinion('alpha', 'Alpha answer'), opinion('beta', 'Beta answer')] });
    if (path.endsWith('/api/os/status')) {
      targetReads += 1;
      return targetReads === 1 ? status() : new Promise<Response>(resolve => { resolveSecond = resolve; });
    }
    return path.endsWith('/api/os/brain/chat-note') ? saved() : json({}, 404);
  });
  localStorage.setItem('hud.admin_token', 'owner-one');
  const view = open();
  fireEvent.click(screen.getByRole('button', { name: 'Compare answers' }));
  await screen.findByText('Alpha answer');
  fireEvent.click(within(cards()[0]).getByRole('button', { name: 'Save to Obsidian' }));
  await screen.findByText(target.vault);
  fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
  await waitFor(() => expect(targetReads).toBe(2));
  expect(notes(calls)).toHaveLength(0);
  localStorage.setItem('hud.admin_token', 'owner-two');
  await act(async () => resolveSecond?.(status()));
  expect(notes(calls)).toHaveLength(0);
  expect(screen.queryByText(/Saved to Obsidian: Inbox/)).toBeNull();
  view.unmount();
});

it('clears a successful receipt when the same question and pair are compared again', async () => {
  const calls = requests((path, init) => path.endsWith('/api/agents/opinions')
    ? json({ opinions: [opinion('alpha', 'Alpha answer'), opinion('beta', 'Beta answer')] })
    : path.endsWith('/api/os/status') ? status()
      : path.endsWith('/api/os/brain/chat-note') ? saved(JSON.parse(String(init.body)).title) : json({}, 404));
  const view = open();
  fireEvent.click(screen.getByRole('button', { name: 'Compare answers' }));
  await screen.findByText('Alpha answer');
  fireEvent.click(within(cards()[0]).getByRole('button', { name: 'Save to Obsidian' }));
  await screen.findByText(target.vault);
  fireEvent.click(screen.getByRole('button', { name: 'Save note' }));
  await screen.findByText(/Saved: Inbox\//);
  fireEvent.click(within(screen.getByRole('dialog', { name: 'Save to Obsidian' })).getByRole('button', { name: 'Close' }));
  expect(within(cards()[0]).getByText(/Saved to Obsidian: Inbox\//)).toBeTruthy();
  const reads = vaultReads(calls).length;
  fireEvent.click(screen.getByRole('button', { name: 'Compare answers' }));
  await screen.findByText('Alpha answer');
  expect(screen.queryByText(/Saved to Obsidian: Inbox\//)).toBeNull();
  expect(within(cards()[0]).getByRole('button', { name: 'Save to Obsidian' })).toBeTruthy();
  expect(vaultReads(calls)).toHaveLength(reads);
  expect(notes(calls)).toHaveLength(1);
  view.unmount();
});

it('offers the Romanian action only on a successful card', async () => {
  const calls = requests(path => path.endsWith('/api/agents/opinions')
    ? json({ opinions: [opinion('alpha', 'Răspuns bun'), { agent: 'beta', ok: true, text: '' }] })
    : path.endsWith('/api/os/status') ? status() : json({}, 404));
  const view = open('ro', 'Este corect?');
  fireEvent.click(screen.getByRole('button', { name: 'Compară răspunsurile' }));
  await screen.findByText('Răspuns bun');
  expect(within(cards()[0]).getByRole('button', { name: 'Salvează în Obsidian' })).toBeTruthy();
  expect(within(cards()[1]).queryByRole('button', { name: 'Salvează în Obsidian' })).toBeNull();
  expect(vaultReads(calls)).toHaveLength(0);
  view.unmount();
});
