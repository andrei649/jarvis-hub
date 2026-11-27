import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Conversation } from '../cockpit';
import { V2 } from '../data';

const answer = 'My favorite color is blue.';
const revision = 'a'.repeat(64);
const source = { session_id: 'older-chat', turn: 2, role: 'user', revision };
const requests: string[] = [];
let servedRevision = revision;
let failFacts = false;
const fact = (value: string, receipt: typeof source | null = source, store: 'memory' | 'user' = 'memory') => ({ entry_id: `${store}:1`, store, value, source: receipt });

function mount(text = answer, lang: 'en' | 'ro' = 'en', allowed = true) {
  return render(<Conversation messages={[{ role: 'agent', who: 'jarvis', text, _complete: true }]} thinking={null}
    onStop={vi.fn()} onProv={vi.fn()} messageActionsAllowed={allowed} messageScope="jarvis:now"
    sessionId="now" agent="jarvis" lang={lang} t={V2.I18N[lang]} />);
}

function openMore() { fireEvent.click(screen.getByRole('button', { name: 'More actions for this reply' })); }

beforeEach(() => {
  HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };
  localStorage.clear();
  localStorage.setItem('hud.admin_token', 'owner');
  requests.length = 0;
  servedRevision = revision;
  failFacts = false;
  vi.stubGlobal('fetch', vi.fn(async (path: string) => {
    requests.push(String(path));
    if (failFacts && String(path).includes('/api/dashboard/today/entries?')) return Response.json({}, { status: 503 });
    if (String(path).includes('store=memory')) return Response.json({ entries: [fact(answer), fact(answer, null)] });
    if (String(path).includes('store=user')) return Response.json({ entries: [fact(answer, { ...source, turn: 3 }, 'user')] });
    if (String(path).includes('/transcript?references=true')) return Response.json({ schema_version: 1, session_id: 'older-chat',
      scope: 'retained_current_history', redacted: true, turns: [{ turn: 2, role: 'user', reference_revision: servedRevision, content: 'I told Jarvis my favorite color is blue.' }] });
    return Response.json({});
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('reads both curated rings only after the completed reply owner clicks, then verifies an original', async () => {
  mount();
  expect(requests).toEqual([]);
  openMore();
  fireEvent.click(screen.getByRole('button', { name: 'Find saved source' }));
  const dialog = await screen.findByRole('dialog', { name: 'Find saved source' });
  await within(dialog).findByText('Matching saved facts');
  expect(requests.filter(path => path.includes('/api/dashboard/today/entries?store='))).toHaveLength(2);
  expect(requests.every(path => !path.includes('/sessions/search'))).toBe(true);
  expect(within(dialog).getAllByText(answer)).toHaveLength(3);
  expect(within(dialog).getByText('Source: saved fact · Agent notes')).toBeTruthy();
  const open = within(dialog).getAllByRole('button', { name: 'Open original' });
  expect(open).toHaveLength(2);
  fireEvent.click(open[0]);
  await within(dialog).findByText('I told Jarvis my favorite color is blue.');
  expect(requests.some(path => path.includes('/sessions/older-chat/transcript?references=true'))).toBe(true);
});

it('limits a narrowed phrase to the reply, reports no matches, and does not read for basic or demo', async () => {
  const view = mount('I remember that my favorite color is blue.');
  openMore(); fireEvent.click(screen.getByRole('button', { name: 'Find saved source' }));
  const dialog = await screen.findByRole('dialog', { name: 'Find saved source' });
  await within(dialog).findByText('No matching saved facts.');
  fireEvent.change(within(dialog).getByRole('textbox', { name: 'Exact phrase from this reply' }), { target: { value: 'favorite color is blue.' } });
  await within(dialog).findByText('Matching saved facts');
  fireEvent.change(within(dialog).getByRole('textbox', { name: 'Exact phrase from this reply' }), { target: { value: 'not in the reply' } });
  expect(within(dialog).getByText('Choose an exact phrase from this reply.')).toBeTruthy();
  fireEvent.keyDown(dialog, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  view.unmount();
  localStorage.removeItem('hud.admin_token'); localStorage.setItem('hud.user_token', 'basic');
  mount();
  expect(screen.queryByRole('button', { name: 'Find saved source' })).toBeNull();
  cleanup();
  localStorage.setItem('hud.admin_token', 'owner');
  mount(answer, 'en', false);
  expect(screen.queryByRole('button', { name: 'Find saved source' })).toBeNull();
});

it('refuses a changed revision before showing source text', async () => {
  mount(); openMore(); fireEvent.click(screen.getByRole('button', { name: 'Find saved source' }));
  const dialog = await screen.findByRole('dialog', { name: 'Find saved source' });
  await within(dialog).findByText('Matching saved facts');
  servedRevision = 'b'.repeat(64);
  fireEvent.click(within(dialog).getAllByRole('button', { name: 'Open original' })[0]);
  await within(dialog).findByText('The original changed or cannot be verified.');
  expect(within(dialog).queryByText('I told Jarvis my favorite color is blue.')).toBeNull();
});

it('reports a failed fact read without showing references', async () => {
  failFacts = true;
  mount(); openMore(); fireEvent.click(screen.getByRole('button', { name: 'Find saved source' }));
  const dialog = await screen.findByRole('dialog', { name: 'Find saved source' });
  await within(dialog).findByText('Saved facts unavailable. Try again later.');
  expect(within(dialog).queryByRole('button', { name: 'Open original' })).toBeNull();
});

it('removes references after owner signout', async () => {
  mount(); openMore(); fireEvent.click(screen.getByRole('button', { name: 'Find saved source' }));
  const dialog = await screen.findByRole('dialog', { name: 'Find saved source' });
  await within(dialog).findByText('Matching saved facts');
  localStorage.removeItem('hud.admin_token');
  window.dispatchEvent(new StorageEvent('storage', { key: 'hud.admin_token' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(screen.queryByText('Chat source: older-chat · message 3 · user')).toBeNull();
});
