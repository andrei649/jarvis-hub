import React from 'react';
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Conversation } from '../cockpit';
import { TalkRegister } from '../home/talk/TalkRegister';
import { openComposerMenu } from '../home/talk/test-support';
import { resetPolling } from '../signals/poll';
import * as ownerSession from '../api/owner-session';

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); });

const reply = (status: number, body: unknown) => ({
  ok: status >= 200 && status < 300, status, json: async () => body,
});
const message = (text = 'Find the source.\nSummarize the result.') =>
  ({ role: 'agent', who: 'frigga', text, _turnId: 1, _complete: true });

/* "Teach skill" sits in a reply's More menu since the re-lay (PHASE_B_PLAN.md §5.3, §8.3); the
   menu's items stay mounted while it is closed. `teachItem()` opens the More of the reply that
   offers it and returns the item; the dialog's opener is that More button, since the picked item
   hides with its menu. */
const offered = () => document.querySelectorAll('[data-turn="reply"] [data-act="teach"]').length;
function teachMenu(): HTMLElement {
  const turn = Array.from(document.querySelectorAll<HTMLElement>('[data-turn="reply"]')).find(t => t.querySelector('[data-act="teach"]'))!;
  return openComposerMenu('more', turn);
}
const teachItem = (name = 'Teach skill') => within(teachMenu()).getByRole('button', { name });

function open(messages: any[] = [message()], scope = 'frigga:s1') {
  const view = render(<Conversation messages={messages} thinking={null} messageActionsAllowed messageScope={scope} lang="en" />);
  const menu = teachMenu();
  const trigger = menu.firstElementChild as HTMLElement;
  fireEvent.click(within(menu).getByRole('button', { name: 'Teach skill' }));
  return { ...view, trigger, dialog: screen.getByRole('dialog') };
}

function fill(description = 'Research a question') {
  fireEvent.change(screen.getByRole('textbox', { name: 'When is this skill useful?' }), { target: { value: description } });
}
const submitButton = () => within(screen.getByRole('dialog')).getByRole('button', { name: 'Teach skill' });
const triggerButton = () => teachItem();

it('offers only completed genuine assistant text on a scoped live Chat/Cockpit, with no request on open or cancel', () => {
  const fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  const done = message();
  const messages = [
    { role: 'user', text: 'My private note' }, done,
    { role: 'agent', who: 'system', text: 'System notice' },
    { role: 'agent', who: 'frigga', text: 'Streaming', _turnId: 2 },
    { role: 'agent', who: 'jarvis', text: 'Imported unknown source', _unattributed: true },
    { role: 'vision', text: 'Vision output' },
  ];
  const { dialog, trigger, rerender } = open(messages);
  // one reply offers it: the completed, attributed one (not the system line, the reply still being
  // written, the unattributed import or the vision analysis)
  expect(offered()).toBe(1);
  expect(within(dialog).getByRole('textbox', { name: "Steps from frigga's reply" })).toHaveProperty('value', done.text);
  expect(document.activeElement).toBe(within(dialog).getByRole('textbox', { name: 'When is this skill useful?' }));
  expect(fetchMock).not.toHaveBeenCalled();
  fireEvent.keyDown(dialog, { key: 'Escape' });
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(document.activeElement).toBe(trigger);
  expect(fetchMock).not.toHaveBeenCalled();
  rerender(<Conversation messages={messages} messageActionsAllowed messageScope="frigga:s1" />);
  fireEvent.click(triggerButton());
  rerender(<Conversation messages={messages} messageActionsAllowed messageScope="frigga:s2" />);
  expect(screen.queryByRole('dialog')).toBeNull();
  rerender(<Conversation messages={messages} messageActionsAllowed={false} messageScope="frigga:s2" />);
  expect(offered()).toBe(0);
  expect(screen.queryByRole('button', { name: 'Teach skill' })).toBeNull();
});

it('uses the shared live gate on the conversation page', () => {
  resetPolling();
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({})));
  // the conversation page as App draws it: message actions are live unless the demo sample is on
  const page = (demo: boolean) => <TalkRegister variant="chat" turns={[]} messages={[message()]} thinking={null} onSubmit={() => true} onStop={() => {}} onProv={() => {}}
    t={{ channel: 'Chat', transmit: 'Send', placeholder: 'Message' }} agent="frigga" agents={[]} sessionId="s1" lang="en"
    messageScope="frigga:s1" recipientStatus="ready" demo={demo} messageActionsAllowed={!demo} exportAllowed={!demo} selectedTurn={!demo}
    onSelectAgent={() => {}} />;
  const view = render(page(false));
  expect(offered()).toBe(1);
  expect(teachItem()).toBeTruthy();
  view.rerender(page(true));
  expect(offered()).toBe(0);
  expect(screen.queryByRole('button', { name: 'Teach skill' })).toBeNull();
  view.unmount();
  resetPolling();
});

it('keeps the entire raw text and gives actionable limits without posting or truncating', () => {
  const fetchMock = vi.fn();
  vi.stubGlobal('fetch', fetchMock);
  const long = Array.from({ length: 21 }, (_, i) => `Step ${i + 1}`).join('\n');
  open([message(long)]);
  fill();
  expect(screen.getByRole('alert').textContent).toMatch(/21 lines/);
  expect(screen.getByRole('textbox', { name: "Steps from frigga's reply" })).toHaveProperty('value', long);
  expect(submitButton()).toHaveProperty('disabled', true);
  fireEvent.change(screen.getByRole('textbox', { name: "Steps from frigga's reply" }), { target: { value: 'One\n\nTwo' } });
  expect(screen.getByRole('alert').textContent).toMatch(/Step 2 is empty/);
  fireEvent.change(screen.getByRole('textbox', { name: "Steps from frigga's reply" }), { target: { value: '😀'.repeat(301) } });
  expect(screen.getByRole('alert').textContent).toMatch(/Step 1 exceeds 300/);
  fireEvent.change(screen.getByRole('textbox', { name: "Steps from frigga's reply" }), { target: { value: '😀'.repeat(300) } });
  fill('x'.repeat(301));
  expect(screen.getByRole('alert').textContent).toMatch(/description to 300/);
  expect(screen.getByRole('textbox', { name: 'When is this skill useful?' })).toHaveProperty('value', 'x'.repeat(301));
  fill('x'.repeat(300));
  expect(submitButton()).toHaveProperty('disabled', false);
  fireEvent.change(screen.getByRole('textbox', { name: "Steps from frigga's reply" }), { target: { value: Array(20).fill('😀'.repeat(300)).join('\n') } });
  expect(submitButton()).toHaveProperty('disabled', false);
  expect(fetchMock).not.toHaveBeenCalled();
});

it('posts one admin request with the reply author, exact steps, and a 32-hex key; success links to exact review', async () => {
  const fetchMock = vi.fn().mockResolvedValue(reply(202, { ok: true, pending: true, skill: 'research notes' }));
  vi.stubGlobal('fetch', fetchMock);
  localStorage.setItem('hud.admin_token', 'admin-test');
  open([message('First\nSecond')]);
  fill();
  fireEvent.click(submitButton());
  await screen.findByRole('status');
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [path, init] = fetchMock.mock.calls[0];
  expect(String(path)).toContain('/api/skills/procedures');
  expect(init.method).toBe('POST');
  expect(init.headers['X-Admin-Token']).toBe('admin-test');
  expect(init.redirect).toBe('error');
  expect(JSON.parse(init.body)).toMatchObject({ agent: 'frigga', description: 'Research a question', steps: ['First', 'Second'], request_id: expect.stringMatching(/^[0-9a-f]{32}$/) });
  expect(screen.getByRole('status').textContent).toMatch(/pending owner review/);
  expect(screen.getByRole('link', { name: 'Review pending skills' }).getAttribute('href')).toContain('/v2/console/pending-skills#skill=research%20notes');
});

it('preserves the same payload and key across an uncertain failure, close, and retry', async () => {
  const fetchMock = vi.fn().mockRejectedValueOnce(new Error('lost reply')).mockResolvedValueOnce(reply(202, { ok: true, pending: true, skill: 'new skill' }));
  vi.stubGlobal('fetch', fetchMock);
  open();
  fill();
  fireEvent.click(submitButton());
  await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/could not be confirmed/));
  expect(screen.getByRole('textbox', { name: 'When is this skill useful?' })).toHaveProperty('disabled', true);
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  fireEvent.click(triggerButton());
  expect(screen.getByRole('status').textContent).toMatch(/same content and request ID/);
  fireEvent.click(screen.getByRole('button', { name: 'Retry same request' }));
  await screen.findByRole('status');
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(fetchMock.mock.calls[1][1].body).toBe(fetchMock.mock.calls[0][1].body);
});

it('allows edited input with a new key after definitive rejection and stops retrying decided requests', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(reply(422, { detail: 'invalid step' }))
    .mockResolvedValueOnce(reply(409, { reason: 'procedure_decided', error: 'already reviewed' }));
  vi.stubGlobal('fetch', fetchMock);
  open();
  fill();
  fireEvent.click(submitButton());
  await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/invalid step/));
  fireEvent.change(screen.getByRole('textbox', { name: "Steps from frigga's reply" }), { target: { value: 'Corrected step' } });
  fireEvent.click(submitButton());
  await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/already approved or discarded/));
  expect(JSON.parse(fetchMock.mock.calls[0][1].body).request_id).not.toBe(JSON.parse(fetchMock.mock.calls[1][1].body).request_id);
  expect(screen.queryByRole('button', { name: 'Retry same request' })).toBeNull();
});

it('treats an unconfirmed 503 as retryable and a key/body conflict as definitive', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(reply(503, { reason: 'procedure_unavailable' }))
    .mockResolvedValueOnce(reply(409, { reason: 'request_conflict', error: 'changed body' }));
  vi.stubGlobal('fetch', fetchMock);
  open();
  fill();
  fireEvent.click(submitButton());
  await waitFor(() => expect(screen.getByRole('button', { name: 'Retry same request' })).toBeTruthy());
  fireEvent.click(screen.getByRole('button', { name: 'Retry same request' }));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/used with different content/));
  expect(fetchMock.mock.calls[1][1].body).toBe(fetchMock.mock.calls[0][1].body);
  expect(screen.queryByRole('button', { name: 'Retry same request' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Close' })).toBeTruthy();
});

it('shows the Romanian action and review copy', async () => {
  const fetchMock = vi.fn().mockResolvedValue(reply(202, { ok: true, pending: true, skill: 'rezumat' }));
  vi.stubGlobal('fetch', fetchMock);
  render(<Conversation messages={[message('Primul pas')]} thinking={null} messageActionsAllowed messageScope="frigga:s1" lang="ro" />);
  fireEvent.click(teachItem('Învață abilitate'));
  expect(screen.getByRole('dialog', { name: 'Învață o abilitate din răspunsul lui frigga' })).toBeTruthy();
  fireEvent.change(screen.getByRole('textbox', { name: 'Când este utilă această abilitate?' }), { target: { value: 'Rezumat de cercetare' } });
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Învață abilitatea' }));
  expect((await screen.findByRole('status')).textContent).toMatch(/așteaptă verificarea proprietarului/);
});

it('allows correction after a definitive generation refusal and names an unavailable agent', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(reply(409, { reason: 'generation_refused', error: 'refused' }))
    .mockResolvedValueOnce(reply(422, { reason: 'agent_unavailable', error: 'agent is not active' }));
  vi.stubGlobal('fetch', fetchMock);
  open();
  fill();
  fireEvent.click(submitButton());
  await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/generator refused/));
  expect(screen.getByRole('textbox', { name: "Steps from frigga's reply" })).toHaveProperty('disabled', false);
  fireEvent.change(screen.getByRole('textbox', { name: "Steps from frigga's reply" }), { target: { value: 'Revised step' } });
  fireEvent.click(submitButton());
  await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/frigga is inactive or disabled/));
  expect(JSON.parse(fetchMock.mock.calls[0][1].body).request_id).not.toBe(JSON.parse(fetchMock.mock.calls[1][1].body).request_id);
  expect(screen.getByRole('textbox', { name: "Steps from frigga's reply" })).toHaveProperty('value', 'Revised step');
});

it('prompts owner sign-in for networked 401/403 and preserves the edited draft across closing', async () => {
  vi.spyOn(ownerSession, 'isNetworkedOrigin').mockReturnValue(true);
  const signIn = vi.spyOn(ownerSession, 'requireSignIn').mockImplementation(() => {});
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(reply(401, { detail: 'admin token required' }))
    .mockResolvedValueOnce(reply(403, { detail: 'owner required' }));
  vi.stubGlobal('fetch', fetchMock);
  open();
  fill('A private draft');
  fireEvent.change(screen.getByRole('textbox', { name: "Steps from frigga's reply" }), { target: { value: 'Edited step' } });
  fireEvent.click(submitButton());
  await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/Sign in as the owner/));
  expect(signIn).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('textbox', { name: "Steps from frigga's reply" })).toHaveProperty('disabled', false);
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  fireEvent.click(triggerButton());
  expect(screen.getByRole('textbox', { name: 'When is this skill useful?' })).toHaveProperty('value', 'A private draft');
  expect(screen.getByRole('textbox', { name: "Steps from frigga's reply" })).toHaveProperty('value', 'Edited step');
  fireEvent.click(submitButton());
  await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/Owner access is required/));
  expect(signIn).toHaveBeenCalledTimes(2);
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it('keeps an earlier uncertain request locked through an auth refusal and retries the same request after sign-in', async () => {
  vi.spyOn(ownerSession, 'isNetworkedOrigin').mockReturnValue(true);
  const signIn = vi.spyOn(ownerSession, 'requireSignIn').mockImplementation(() => {});
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(reply(503, { reason: 'procedure_unavailable' }))
    .mockResolvedValueOnce(reply(401, { detail: 'admin token required' }))
    .mockResolvedValueOnce(reply(403, { detail: 'owner required' }))
    .mockResolvedValueOnce(reply(202, { ok: true, pending: true, skill: 'safe procedure' }));
  vi.stubGlobal('fetch', fetchMock);
  open();
  fill('Careful draft');
  fireEvent.click(submitButton());
  await waitFor(() => expect(screen.getByRole('button', { name: 'Retry same request' })).toBeTruthy());
  fireEvent.click(screen.getByRole('button', { name: 'Retry same request' }));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/original request and ID are preserved/));
  expect(signIn).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('textbox', { name: 'When is this skill useful?' })).toHaveProperty('disabled', true);
  fireEvent.click(screen.getByRole('button', { name: 'Retry same request' }));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/original request and ID are preserved/));
  expect(signIn).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  fireEvent.click(triggerButton());
  expect(screen.getByRole('textbox', { name: 'When is this skill useful?' })).toHaveProperty('disabled', true);
  fireEvent.click(screen.getByRole('button', { name: 'Retry same request' }));
  await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/pending owner review/));
  expect(fetchMock).toHaveBeenCalledTimes(4);
  expect(new Set(fetchMock.mock.calls.map(call => call[1].body)).size).toBe(1);
});
