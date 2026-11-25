import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { Conversation } from '../cockpit';
import { ArtifactsPanel } from '../artifacts';
import { TalkRegister } from '../home/talk/TalkRegister';
import { openComposerMenu } from '../home/talk/test-support';
import { resetPolling } from '../signals/poll';
import { _resetOwnerSessionForTests, signIn } from '../api/owner-session';

const file = new Blob(['office-bytes'], { type: 'application/octet-stream' });
const mime = {
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
};
const ok = (format: 'docx' | 'xlsx' = 'docx') => ({ ok: true, status: 200,
  headers: { get: () => mime[format] }, blob: async () => file });
const clicked: { href: string; name: string }[] = [];
let oldCreate: typeof URL.createObjectURL;
let oldRevoke: typeof URL.revokeObjectURL;

beforeEach(() => {
  localStorage.clear();
  _resetOwnerSessionForTests();
  oldCreate = URL.createObjectURL;
  oldRevoke = URL.revokeObjectURL;
  URL.createObjectURL = vi.fn(() => 'blob:office-test');
  URL.revokeObjectURL = vi.fn();
  clicked.length = 0;
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () {
    clicked.push({ href: this.href, name: this.download });
  });
});
afterEach(() => {
  URL.createObjectURL = oldCreate;
  URL.revokeObjectURL = oldRevoke;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  _resetOwnerSessionForTests();
  localStorage.clear();
});

const reply = { role: 'agent', who: 'jarvis', text: 'Full **reply**\n\n| a | b |\n| --- | --- |\n| one | 1 |\n\n| x | y |\n| --- | --- |\n| two | 2 |', _turnId: 1, _complete: true };

/* Since the re-lay (PHASE_B_PLAN.md §5.3, §8.3) "Download Word" and "Photoshop" sit in a reply's
   More menu, whose items stay mounted while it is closed; a table's "Download Excel" stays beside
   its table in the reply's words. `more()` opens the first reply's More and returns it. */
const more = () => openComposerMenu('more', document.querySelector('[data-turn="reply"]') as HTMLElement);
const offered = (key: 'word' | 'photoshop') => document.querySelectorAll(`[data-turn="reply"] [data-act="${key}"]`).length;

describe('Office export from normal chat', () => {
  it('shows exports on the conversation page only for a live turn, never in the demo sample', () => {
    resetPolling();
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({})));
    // the conversation page as App draws it: exports and message actions are live unless the demo sample is on
    const page = (demo: boolean) => <TalkRegister variant="chat" turns={[]} messages={[reply]} thinking={null} onSubmit={() => true} onStop={() => {}} onProv={() => {}}
      t={{ channel: 'Chat', transmit: 'Send', placeholder: 'Message' }} lang="en" agent="jarvis" agents={[]} sessionId="s"
      messageScope="jarvis:s" recipientStatus="ready" demo={demo} exportAllowed={!demo} messageActionsAllowed={!demo} selectedTurn={!demo}
      onSelectAgent={() => {}} />;
    const view = render(page(false));
    expect(within(more()).getByRole('button', { name: 'Download Word' })).toBeTruthy();
    expect(within(more()).getByRole('button', { name: 'Photoshop' })).toBeTruthy();
    expect(screen.getAllByRole('button', { name: 'Download Excel' })).toHaveLength(2);
    view.rerender(page(true));
    expect(offered('word')).toBe(0);
    expect(offered('photoshop')).toBe(0);
    expect(screen.queryByRole('button', { name: 'Download Word' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Download Excel' })).toBeNull();
    resetPolling();
  });

  it('posts the full reply and each distinct table, then downloads fixed filenames with the user token', async () => {
    localStorage.setItem('hud.user_token', 'owner-token');
    const fetchMock = vi.fn(async (_path: string, init: RequestInit) => ok(JSON.parse(init.body as string).format));
    vi.stubGlobal('fetch', fetchMock);
    render(<Conversation messages={[{ role: 'user', text: 'private prompt' }, reply]} thinking={null} exportAllowed lang="en" />);
    const buttons = screen.getAllByRole('button', { name: 'Download Excel' });
    expect(buttons).toHaveLength(2);
    fireEvent.click(within(more()).getByRole('button', { name: 'Download Word' }));
    fireEvent.click(buttons[0]);
    fireEvent.click(buttons[1]);
    await waitFor(() => expect(clicked).toHaveLength(3));
    expect(clicked).toEqual([
      { href: 'blob:office-test', name: 'Nerva reply.docx' },
      { href: 'blob:office-test', name: 'Nerva table.xlsx' },
      { href: 'blob:office-test', name: 'Nerva table.xlsx' },
    ]);
    expect(fetchMock.mock.calls.map(([path, init]) => ({ path, method: init.method, credentials: init.credentials, body: JSON.parse(init.body as string), token: (init.headers as Record<string, string>)['X-User-Token'] }))).toEqual([
      { path: '/api/canvas/export', method: 'POST', credentials: 'same-origin', body: { format: 'docx', text: reply.text }, token: 'owner-token' },
      { path: '/api/canvas/export', method: 'POST', credentials: 'same-origin', body: { format: 'xlsx', rows: [['a', 'b'], ['one', '1']] }, token: 'owner-token' },
      { path: '/api/canvas/export', method: 'POST', credentials: 'same-origin', body: { format: 'xlsx', rows: [['x', 'y'], ['two', '2']] }, token: 'owner-token' },
    ]);
    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledTimes(3), { timeout: 1800 });
  });

  it('sends the signed-in owner CSRF token with a cookie-backed export', async () => {
    const fetchMock = vi.fn(async (path: string, _init: RequestInit) => String(path) === '/api/auth/login'
      ? { ok: true, status: 200, json: async () => ({ signed_in: true, csrf: 'csrf-office' }) }
      : ok());
    vi.stubGlobal('fetch', fetchMock);
    expect(await signIn('test-secret')).toEqual({ ok: true });
    render(<Conversation messages={[reply]} thinking={null} exportAllowed lang="en" />);
    fireEvent.click(within(more()).getByRole('button', { name: 'Download Word' }));
    await waitFor(() => expect(clicked).toHaveLength(1));
    const [, init] = fetchMock.mock.calls.find(([path]) => String(path) === '/api/canvas/export')!;
    expect(init.credentials).toBe('same-origin');
    expect((init.headers as Record<string, string>)['X-CSRF-Token']).toBe('csrf-office');
    expect((init.headers as Record<string, string>)['X-User-Token']).toBeUndefined();
  });

  it('hides exports for demo, user, system, empty, and unfinished or aborted stream bubbles', () => {
    const messages = [
      { role: 'user', text: '| mine |\n| --- |' },
      { role: 'agent', who: 'system', text: 'notice' },
      { role: 'agent', who: 'jarvis', text: '' },
      { ...reply, _complete: false },
    ];
    const view = render(<Conversation messages={messages} thinking={null} exportAllowed messageActionsAllowed lang="en" />);
    expect(offered('word')).toBe(0);
    expect(offered('photoshop')).toBe(0);
    expect(screen.queryByRole('button', { name: 'Download Excel' })).toBeNull();
    view.rerender(<Conversation messages={[reply]} thinking={null} exportAllowed={false} lang="en" />);
    expect(offered('word')).toBe(0);
    expect(screen.queryByRole('button', { name: 'Download Excel' })).toBeNull();
  });

  it('shows a translated, retryable refusal and locks duplicate requests while pending', async () => {
    let resolve!: (value: any) => void;
    const fetchMock = vi.fn().mockImplementationOnce(() => new Promise(r => { resolve = r; }))
      .mockImplementationOnce(async () => ok());
    vi.stubGlobal('fetch', fetchMock);
    render(<Conversation messages={[reply]} thinking={null} exportAllowed lang="ro" />);
    const menu = more();
    fireEvent.click(within(menu).getByRole('button', { name: 'Descarcă Word' }));
    fireEvent.click(within(menu).getByRole('button', { name: 'Descarcă Word' }));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolve({ ok: false, status: 403, json: async () => ({ detail: 'denied' }) });
    const retry = await screen.findByRole('button', { name: 'Descarcă Word — eșuat, reîncearcă' });
    expect(clicked).toHaveLength(0);
    fireEvent.click(retry);
    await waitFor(() => expect(clicked).toHaveLength(1));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('rejects a successful HTML response and gives non-retry guidance for content refusals', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({ ...ok(), headers: { get: () => 'text/html' } })
      .mockResolvedValueOnce({ ok: false, status: 413, json: async () => ({ detail: 'too large' }) });
    vi.stubGlobal('fetch', fetchMock);
    render(<Conversation messages={[reply]} thinking={null} exportAllowed lang="en" />);
    fireEvent.click(within(more()).getByRole('button', { name: 'Download Word' }));
    const retry = await screen.findByRole('button', { name: 'Download Word — failed, retry' });
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    fireEvent.click(retry);
    const content = await screen.findByRole('button', { name: 'Content too large or unsupported' });
    expect(content.hasAttribute('disabled')).toBe(true);
    expect(clicked).toHaveLength(0);
  });
});

describe('Office export from saved Canvas', () => {
  it('uses the saved markdown and table payloads, and hides exports in demo', async () => {
    const elements = [
      { id: 'm', agent: 'jarvis', type: 'markdown', payload: { body: '# Saved' } },
      { id: 't', agent: 'jarvis', type: 'table', payload: { columns: ['task', 'owner'], rows: [['ship', 'me']] } },
    ];
    const fetchMock = vi.fn(async (path, init) => String(path) === '/api/canvas/export' ? ok(JSON.parse(init.body).format)
      : String(path) === '/api/artifacts' ? { ok: true, status: 200, json: async () => ({ enabled: false, items: [] }) }
      : { ok: true, status: 200, json: async () => ({ elements }) });
    vi.stubGlobal('fetch', fetchMock);
    const view = render(<ArtifactsPanel lang="en" />);
    await screen.findByText('Saved');
    fireEvent.click(screen.getByRole('button', { name: 'Download Word' }));
    fireEvent.click(screen.getByRole('button', { name: 'Download Excel' }));
    await waitFor(() => expect(clicked).toHaveLength(2));
    const bodies = fetchMock.mock.calls.filter(([path]) => String(path) === '/api/canvas/export').map(([, init]) => JSON.parse(init.body));
    expect(bodies).toEqual([{ format: 'docx', text: '# Saved' }, { format: 'xlsx', rows: [['task', 'owner'], ['ship', 'me']] }]);
    view.rerender(<ArtifactsPanel lang="en" exportAllowed={false} />);
    expect(screen.queryByRole('button', { name: 'Download Word' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Download Excel' })).toBeNull();
  });
});
