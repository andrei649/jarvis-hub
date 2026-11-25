import React from 'react';
import { webcrypto } from 'node:crypto';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App from '../app';
import { Dossier } from '../modes';
import { composerField, composerSend, openComposerMenu } from '../home/talk/test-support';

const sent = vi.hoisted(() => [] as Array<{ message: string; agent: string; board_references?: any[]; attachments?: any[]; allow_board_cloud?: boolean; _admin?: boolean }>);
const refusal = vi.hoisted(() => ({ enabled: false, attachmentLimit: false }));
/* A held stream keeps a reply being written: it starts, then waits until released (it ends) or
   aborted (the reply was stopped). `signals` are the turns' abort signals, in order. */
const stream = vi.hoisted(() => ({ hold: false, signals: [] as AbortSignal[], release: [] as Array<() => void> }));
const historyTurns = vi.hoisted(() => [] as Array<{ role: string; content: string; agent_id?: string }>);
const roster = [
  { id: 'jarvis', name: 'Jarvis', rosterSource: 'api', chat_routing: 'orchestrated', enabled: true },
  { id: 'frigga', name: 'Frigga', rosterSource: 'api', chat_routing: 'local', enabled: true },
];
const liveRoster = vi.hoisted(() => ({ agents: [] as any[], refresh: null as null | (() => Promise<void>) }));
const savedCredential = () => JSON.parse(sessionStorage.getItem('nerva.chat.recipient') || 'null')?.credential;
/* PHASE_B_PLAN.md §5.3: the recipient is the composer's To (RecipientPicker, a native select whose
   options read "<Agent> · <declared policy>"); the conversation register's head repeats the declared
   routing policy ("with Jarvis · Orchestrated"). The floating window has no register head. */
const POLICY_TITLE = 'Declared policy before sending; actual model use appears after the reply.';
const policy = () => document.querySelector(`[data-register="talk"] header [title="${POLICY_TITLE}"]`)?.textContent ?? null;
const chosen = (picker: HTMLElement) => (picker as HTMLSelectElement).selectedOptions[0]?.textContent ?? null;
/* The hands-free voice loop: App hands useVoice its `onTurn` (a spoken turn); the latest one is kept. */
const voiceLoop = vi.hoisted(() => ({ onTurn: null as null | ((text: string) => Promise<string>) }));
vi.mock('../voice', () => ({ useVoice: ({ onTurn }: any) => { voiceLoop.onTurn = onTurn; return { active: false, toggle: () => {} }; } }));
vi.mock('../mesh', () => ({ NeuralMesh: () => null, isExecutingAgent: () => false }));
vi.mock('../analytics', () => ({ initAnalytics: () => {}, trackPageview: () => {} }));
vi.mock('../gap', () => ({ FirstRunGate: () => null }));
vi.mock('../api/live', () => ({ PREVIEW_MODE_LIVE_KEYS: {}, useLiveModes: () => ({ live: {} }) }));
vi.mock('../api/loaders', () => ({
  loadJarvisData: async (demo: boolean) => ({
    agents: demo ? [] : liveRoster.agents, ticker: [], tasks: [], calendar: [], heartbeat: [], weather: null,
    sys: null, live: !demo, serverUp: true, sources: { agents: !demo, tasks: false, trust: false },
    llm: { state: 'unknown', model: null, residents: [] }, trust: { mic: 'on', strict_local: false },
  }),
  createLatestRefreshRunner: ({ loadData, commitData }: any) => {
    const refresh = async () => commitData(await loadData());
    liveRoster.refresh = refresh;
    return { refresh, stop: () => {} };
  },
}));
vi.mock('../api/client', async importOriginal => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return { ...actual, apiGet: async (path: string, options: any) => path === '/memory' ? { turns: historyTurns } : path.startsWith('/api/kanban') ? actual.apiGet(path, options) : {}, postStream: async (_url: string, body: any, event: (frame: any) => void, options: any) => {
    sent.push({ ...body, _admin: options?.admin });
    if (refusal.attachmentLimit) throw { body: { detail: 'attachment_limit' }, status: 413 };
    if (refusal.enabled) throw { body: { detail: 'chat_agent_unavailable' }, status: 409 };
    if (stream.hold) {
      const signal: AbortSignal | undefined = options?.signal;
      if (signal) stream.signals.push(signal);
      event({ type: 'start', agent: body.agent });
      await new Promise<void>((resolve, reject) => {
        stream.release.push(resolve);
        signal?.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
      });
    }
    event({ type: 'end', text: 'Done', agent: body.agent,
      ...(body.board_references ? { board_sources: body.board_references.map(({ board, task_id, source, sha256 }: any) => ({ board, task_id, source, sha256 })) } : {}) });
  } };
});

beforeEach(() => {
  vi.stubGlobal('crypto', webcrypto);
  localStorage.clear();
  sessionStorage.clear();
  liveRoster.agents = roster;
  liveRoster.refresh = null;
  history.replaceState(null, '', '/v2/chat');
  sent.length = 0;
  historyTurns.length = 0;
  refusal.enabled = false;
  refusal.attachmentLimit = false;
  stream.hold = false;
  stream.signals.length = 0;
  stream.release.length = 0;
  voiceLoop.onTurn = null;
});

/** The line over the composer that Send's description points at while no recipient is ready. */
const sendWhy = () => document.getElementById(composerSend().getAttribute('aria-describedby') || '')?.textContent ?? null;
/** The conversation register's head: "with <agent> · <policy>", or why there is no recipient. */
const head = () => document.querySelector('[data-register="talk"] .n-talk__with')?.textContent ?? null;
const UNAVAILABLE_FRIGGA = 'Frigga is not available now. Nothing is sent until you choose who to write to.';
const SIGNIN_CHANGED = 'The sign-in changed, so the agent chosen before is not used. Nothing is sent until you choose who to write to.';

it('keeps a reviewed Office passage and the question after a size refusal and sends them on explicit retry', async () => {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => String(url).includes('/office-preview')
    ? Response.json({ kind: 'docx', total_segments: 1, segments: [{ label: 'Document', text: 'Private neighbor. Approved cost: 93.', truncated: false }] })
    : Response.json({})));
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  const input = document.querySelector<HTMLInputElement>('[data-composer="1"]')!;
  fireEvent.change(input, { target: { value: 'What did we approve?' } });
  fireEvent.change(document.querySelector('input.office-file-input')!, {
    target: { files: [new File(['sample'], 'Approval.docx')] },
  });
  const area = await screen.findByRole('textbox', { name: 'Select a passage' }) as HTMLTextAreaElement;
  area.setSelectionRange(area.value.indexOf('Approved'), area.value.length);
  fireEvent.click(screen.getByRole('button', { name: 'Attach selected text' }));
  fireEvent.click(screen.getByRole('button', { name: 'Done reviewing' }));
  refusal.attachmentLimit = true;
  fireEvent.keyDown(input, { key: 'Enter' });
  const limit = await screen.findByText(/attachment limit/i);
  expect(limit).toBeTruthy();
  expect(input.value).toBe('What did we approve?');
  expect(sent[0]).toMatchObject({ message: input.value, require_full_attachments: true,
    attachments: [{ name: 'Approval.docx', text: 'Approved cost: 93.' }] });
  refusal.attachmentLimit = false;
  fireEvent.keyDown(input, { key: 'Enter' });
  await waitFor(() => expect(input.value).toBe(''));
  expect(sent).toHaveLength(2);
  expect(sent[1]).toEqual(sent[0]);
});

it('only offers to teach from restored assistant turns with a recorded author', async () => {
  sessionStorage.removeItem('nerva.chat.session_id');
  historyTurns.push({ role: 'system', agent_id: 'jarvis', content: 'Session notice' },
    { role: 'assistant', content: 'Legacy turn' }, { role: 'assistant', agent_id: 'frigga', content: 'Check the printed proofs' });
  render(<App />);
  await screen.findByText('Legacy turn');
  // Teach skill is in each reply's More menu since the re-lay (§5.3): open every reply's
  const replies = Array.from(document.querySelectorAll<HTMLElement>('[data-turn="reply"]'));
  expect(replies).toHaveLength(3);
  for (const reply of replies) if (reply.querySelector('[data-talk-menu="more"]')) openComposerMenu('more', reply);
  const teach = screen.getAllByRole('button', { name: 'Teach skill' });
  expect(teach).toHaveLength(1);
  expect(teach[0].closest('[data-turn]')?.textContent).toContain('Check the printed proofs');
});

it('sends two reviewed board references as structured owner input and renders their recorded source controls', async () => {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
  const digest = 'a'.repeat(64);
  const cards = [
    { id: 't_one', title: 'Same title', status: 'done', result: 'South', board_source_sha256: digest },
    { id: 't_two', title: 'Same title', status: 'done', latest_summary: 'North', board_source_sha256: digest },
  ];
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.endsWith('/api/kanban/boards')) return Response.json({ current: 'alpha', boards: [{ slug: 'alpha', name: 'Alpha' }] });
    if (url.includes('/api/kanban/board?')) return Response.json({ columns: [{ name: 'done', tasks: cards }] });
    const card = cards.find(item => url.includes('/tasks/' + item.id + '?'));
    return Response.json(card ? { task: card } : {});
  }));
  render(<App />);
  const picker = await screen.findByRole('combobox', { name: 'To' });
  fireEvent.change(picker, { target: { value: 'frigga' } });
  openComposerMenu('attach');   // Board result is in the composer's Attach menu since the re-lay
  await waitFor(() => expect((screen.getByRole('button', { name: 'Attach board result' }) as HTMLButtonElement).disabled).toBe(false));
  for (const card of cards) {
    fireEvent.click(screen.getByRole('button', { name: 'Attach board result' }));
    const taskPicker = await screen.findByRole('combobox', { name: 'Completed task' });
    await waitFor(() => expect((taskPicker as HTMLSelectElement).disabled).toBe(false));
    fireEvent.change(taskPicker, { target: { value: card.id } });
    fireEvent.click(await screen.findByRole('button', { name: 'Attach full result' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Attach completed task result' })).toBeNull());
  }
  const draft = document.querySelector<HTMLInputElement>('[data-composer="1"]')!;
  fireEvent.change(draft, { target: { value: 'Compare sources' } });
  fireEvent.keyDown(draft, { key: 'Enter' });
  await waitFor(() => expect(sent).toHaveLength(1));
  expect(sent[0]).toMatchObject({ _admin: true, message: 'Compare sources', agent: 'frigga',
    board_references: [
      { board: 'alpha', task_id: 't_one', source: 'result', excerpt: 'South', sha256: digest },
      { board: 'alpha', task_id: 't_two', source: 'latest_summary', excerpt: 'North', sha256: digest },
    ] });
  expect(sent[0].attachments).toBeUndefined();
  expect(sent[0].allow_board_cloud).toBeUndefined();
  expect(await screen.findByRole('button', { name: 'Recorded result · alpha/t_one' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Latest summary · alpha/t_two' })).toBeTruthy();
});

it('shows the specific unavailable-agent refusal with a next action', async () => {
  refusal.enabled = true;
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  const draft = document.querySelector<HTMLInputElement>('[data-composer="1"]')!;
  fireEvent.change(draft, { target: { value: 'Please help' } });
  fireEvent.keyDown(draft, { key: 'Enter' });
  await waitFor(() => expect(screen.getByText(/selected agent is no longer available/)).toBeTruthy());
  expect(screen.getByText(/choose an enabled agent, and send again/)).toBeTruthy();
  expect(screen.queryByText(/model backend is unreachable/)).toBeNull();
});

it('drops the live picker and policy immediately across Demo and live loading boundaries', async () => {
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  expect(policy()).toBe('Orchestrated');
  history.replaceState(null, '', '/v2/chat?demo=1');
  fireEvent.popState(window);
  await waitFor(() => expect(policy()).toBe('Demo sample'));
  expect(screen.queryByRole('combobox', { name: 'To' })).toBeNull();
  // the composer's To names the demo recipient as a sample too, never a live policy
  expect(document.querySelector('[data-composer-root] [data-recipient]')?.textContent).toContain('Demo sample');
  history.replaceState(null, '', '/v2/chat');
  fireEvent.popState(window);
  await waitFor(() => expect(policy()).not.toBe('Demo sample'));
  const picker = await screen.findByRole('combobox', { name: 'To' });
  expect(policy()).toBe('Orchestrated');
  expect(chosen(picker)).toBe('Jarvis · Orchestrated');
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it.each([false, true])('selects an authenticated agent from %s floating Chat and sends to it without losing the draft', async floating => {
  render(<App floating={floating} />);
  const picker = await screen.findByRole('combobox', { name: 'To' });
  const draft = document.querySelector<HTMLInputElement>('[data-composer="1"]')!;
  fireEvent.change(draft, { target: { value: 'Keep this draft' } });
  fireEvent.change(picker, { target: { value: 'frigga' } });
  expect(draft.value).toBe('Keep this draft');
  expect(chosen(picker)).toBe('Frigga · Local');
  // the register head says it too, except in the floating window, which has no head
  expect(policy()).toBe(floating ? null : 'Local');
  expect(screen.queryByRole('dialog', { name: /Frigga/i })).toBeNull();
  fireEvent.keyDown(draft, { key: 'Enter' });
  await waitFor(() => expect(sent).toEqual([expect.objectContaining({ message: 'Keep this draft', agent: 'frigga' })]));
});

it('restores the exact next recipient after a same-tab reload and sends to it', async () => {
  const first = render(<App />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
  await waitFor(() => expect(savedCredential()).toHaveLength(64));
  first.unmount();
  render(<App />);
  await waitFor(() => expect((screen.getByRole('combobox', { name: 'To' }) as HTMLSelectElement).value).toBe('frigga'));
  const draft = document.querySelector<HTMLInputElement>('[data-composer="1"]')!;
  fireEvent.change(draft, { target: { value: 'Continue with Frigga' } });
  fireEvent.keyDown(draft, { key: 'Enter' });
  await waitFor(() => expect(sent[sent.length - 1]?.agent).toBe('frigga'));
});

it('does not reuse a saved recipient across guest credentials', async () => {
  localStorage.setItem('hud.user_token', 'guest-one');
  const first = render(<App />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
  await waitFor(() => expect(savedCredential()).toHaveLength(64));
  first.unmount();
  localStorage.setItem('hud.user_token', 'guest-two');
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  await waitFor(() => expect((screen.getByRole('combobox', { name: 'To' }) as HTMLSelectElement).value).not.toBe('frigga'));
  expect(localStorage.getItem('nerva.chat.recipient')).toBeNull();
  // the refusal says the sign-in changed, without naming what another sign-in chose
  await waitFor(() => expect(sendWhy()).toBe(SIGNIN_CHANGED));
  expect(document.body.textContent).not.toContain('Frigga is not available');
  expect(head()).toBe('no agent chosen');
});

it('requires a new choice when a saved recipient leaves the authenticated roster, and says so at once', async () => {
  const first = render(<App />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
  await waitFor(() => expect(savedCredential()).toHaveLength(64));
  first.unmount();
  liveRoster.agents = [roster[0]];
  render(<App />);
  const picker = await screen.findByRole('combobox', { name: 'To' }) as HTMLSelectElement;
  // The saved choice is refused once it is checked: clearRecipient takes it out of storage. The
  // refusal is drawn by that same update (React's own pending work, no poll and no other redraw),
  // never left at "Checking the selected agent…" with Send held for no stated reason.
  await waitFor(() => expect(sessionStorage.getItem('nerva.chat.recipient')).toBeNull());
  await act(async () => {});
  expect(screen.queryByText('Checking the selected agent…')).toBeNull();
  // Send is held, and its description says which agent is unavailable and that the message goes
  // to no one else: nothing is sent until a new choice
  expect(composerSend().disabled).toBe(true);
  const why = document.getElementById(composerSend().getAttribute('aria-describedby') || '');
  expect(why?.getAttribute('role')).toBe('status');
  expect(why?.textContent).toBe(UNAVAILABLE_FRIGGA);
  // the To asks for a choice, and the register head names no recipient
  expect(picker.value).toBe('');
  expect(picker.selectedOptions[0].textContent).toBe('Choose an agent');
  expect(head()).toBe('no agent chosen');
  const draft = document.querySelector<HTMLInputElement>('[data-composer="1"]')!;
  fireEvent.change(draft, { target: { value: 'Do not silently send' } });
  fireEvent.keyDown(draft, { key: 'Enter' });
  expect(sent).toHaveLength(0);
  fireEvent.change(picker, { target: { value: 'jarvis' } });
  // a new choice ends the refusal
  expect(screen.queryByText(UNAVAILABLE_FRIGGA)).toBeNull();
  expect(head()).toBe('with Jarvis · Orchestrated');
  fireEvent.keyDown(draft, { key: 'Enter' });
  await waitFor(() => expect(sent).toEqual([expect.objectContaining({ agent: 'jarvis' })]));
});

it('says at once when the agent written to leaves the roster during the session', async () => {
  render(<App />);
  const picker = await screen.findByRole('combobox', { name: 'To' }) as HTMLSelectElement;
  fireEvent.change(picker, { target: { value: 'frigga' } });
  expect(head()).toBe('with Frigga · Local');
  liveRoster.agents = [roster[0]];
  await act(async () => { await liveRoster.refresh?.(); });
  expect(picker.value).toBe('');
  expect(sendWhy()).toBe(UNAVAILABLE_FRIGGA);
  expect(composerSend().disabled).toBe(true);
  expect(head()).toBe('no agent chosen');
});

it('requires a new choice when guest credentials change in the same tab', async () => {
  localStorage.setItem('hud.user_token', 'guest-one');
  render(<App />);
  const picker = await screen.findByRole('combobox', { name: 'To' }) as HTMLSelectElement;
  fireEvent.change(picker, { target: { value: 'frigga' } });
  await waitFor(() => expect(savedCredential()).toHaveLength(64));
  localStorage.setItem('hud.user_token', 'guest-two');
  const draft = document.querySelector<HTMLInputElement>('[data-composer="1"]')!;
  fireEvent.change(draft, { target: { value: 'Still here' } });
  fireEvent.keyDown(draft, { key: 'Enter' });
  await waitFor(() => expect(picker.value).toBe(''));
  expect(sent).toHaveLength(0);
  expect(sendWhy()).toBe(SIGNIN_CHANGED);
  expect(draft.value).toBe('Still here');
  fireEvent.change(picker, { target: { value: 'jarvis' } });
  fireEvent.keyDown(draft, { key: 'Enter' });
  await waitFor(() => expect(sent).toEqual([expect.objectContaining({ agent: 'jarvis' })]));
});

it.each(['/v2/chat', '/v2/cockpit'])('shows pending recipient verification and preserves the draft in %s', async path => {
  const first = render(<App />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
  await waitFor(() => expect(savedCredential()).toHaveLength(64));
  first.unmount();
  liveRoster.agents = [];
  history.replaceState(null, '', path);
  render(<App />);
  const draft = document.querySelector<HTMLInputElement>('[data-composer="1"]')!;
  fireEvent.change(draft, { target: { value: 'Keep the draft while checking' } });
  const send = composerSend();
  expect(send.disabled).toBe(true);
  expect(screen.getByText('Checking the selected agent…')).toBeTruthy();
  expect(send.getAttribute('aria-describedby')).toBe(screen.getByText('Checking the selected agent…').id);
  // the register head does not call an agent no one has named "Unavailable" while it is checked
  expect(head()).toBe('checking the selected agent…');
  liveRoster.agents = roster;
  await act(async () => { await liveRoster.refresh?.(); });
  await waitFor(() => expect(send.disabled).toBe(false));
  expect(draft.value).toBe('Keep the draft while checking');
  expect(head()).toBe('with Frigga · Local');
});

it('refuses a saved recipient it cannot verify at once, instead of checking for ever', async () => {
  const first = render(<App />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
  await waitFor(() => expect(savedCredential()).toHaveLength(64));
  first.unmount();
  // no digest on this connection (crypto.subtle exists only on a secure origin)
  vi.stubGlobal('crypto', { subtle: { digest: async () => { throw new Error('crypto.subtle is unavailable'); } } });
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  await waitFor(() => expect(sessionStorage.getItem('nerva.chat.recipient')).toBeNull());
  await act(async () => {});
  expect(screen.queryByText('Checking the selected agent…')).toBeNull();
  expect(sendWhy()).toBe('The agent chosen before could not be verified, so it is not used. Nothing is sent until you choose who to write to.');
  expect(composerSend().disabled).toBe(true);
});

it('keeps the choice the owner makes while a saved one is still being checked', async () => {
  const first = render(<App />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
  await waitFor(() => expect(savedCredential()).toHaveLength(64));
  first.unmount();
  // checking the saved choice takes a while
  const checks: Array<() => void> = [];
  vi.stubGlobal('crypto', { subtle: { digest: (alg: string, data: Uint8Array<ArrayBuffer>) =>
    new Promise<ArrayBuffer>((resolve) => { checks.push(() => resolve(webcrypto.subtle.digest(alg, data))); }) } });
  render(<App />);
  const picker = await screen.findByRole('combobox', { name: 'To' }) as HTMLSelectElement;
  await waitFor(() => expect(checks.length).toBeGreaterThan(0));
  expect(screen.getByText('Checking the selected agent…')).toBeTruthy();
  // the owner chooses meanwhile, and the next roster poll comes before the check ends
  fireEvent.change(picker, { target: { value: 'jarvis' } });
  liveRoster.agents = [...roster];
  await act(async () => { await liveRoster.refresh?.(); });
  await act(async () => { checks.forEach((done) => done()); });
  await act(async () => { checks.forEach((done) => done()); });
  // the saved choice neither comes back over the owner's nor refuses it
  expect(picker.value).toBe('jarvis');
  expect(head()).toBe('with Jarvis · Orchestrated');
  fireEvent.change(composerField(), { target: { value: 'To Jarvis' } });
  fireEvent.keyDown(composerField(), { key: 'Enter' });
  await waitFor(() => expect(sent[sent.length - 1]).toMatchObject({ message: 'To Jarvis', agent: 'jarvis' }));
});

it('clears the saved recipient on an explicit conversation switch', async () => {
  const first = render(<App />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
  await waitFor(() => expect(savedCredential()).toHaveLength(64));
  act(() => window.dispatchEvent(new CustomEvent('nerva:session-selected', { detail: { sessionId: 'another', turns: [] } })));
  // the choice belonged to the conversation left behind, and the composer says so
  expect(sendWhy()).toBe('No agent is chosen for this conversation. Nothing is sent until you choose who to write to.');
  first.unmount();
  render(<App />);
  await waitFor(() => expect((screen.getByRole('combobox', { name: 'To' }) as HTMLSelectElement).value).not.toBe('frigga'));
});

/* "Write to <Agent>" from the search sheet or the Dossier changes the recipient as the composer's
   To does (PHASE_B_PLAN.md §5.3): at once when no reply is being written; while one is, it asks
   first in the To's words and stops nothing until the owner confirms. Send waits for the answer
   meanwhile, so a message written then does not go to the recipient being replaced. */
const sheet = () => screen.queryByRole('dialog', { name: 'Search or run a command' }) as HTMLElement | null;
/** Ctrl K, find `query`, run the command `id` as the owner clicks it. */
function runCommand(query: string, id: string) {
  fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
  const open = sheet();
  expect(open, 'the sheet is open').not.toBeNull();
  fireEvent.change(within(open as HTMLElement).getByRole('combobox'), { target: { value: query } });
  const row = (open as HTMLElement).querySelector(`[data-command="${id}"]`) as HTMLElement | null;
  expect(row, `${id} is found by "${query}"`).not.toBeNull();
  fireEvent.click(row as HTMLElement);
  expect(sheet()).toBeNull();
}
const sheetWriteTo = async (_name: string, id: string) => { runCommand(`write to ${id}`, `agent:write:${id}`); };
/** The Dossier's "Write to <Agent>", the Dossier opened from the sheet's "Open <Agent>". */
async function dossierWriteTo(name: string, id: string) {
  runCommand(`open ${id}`, `agent:open:${id}`);
  fireEvent.click(await screen.findByRole('button', { name: `Write to ${name}` }));
}
/** Sends `text` and holds its reply open: it is being written until released or stopped. */
async function replyInFlight(text: string) {
  stream.hold = true;
  const field = composerField();
  fireEvent.change(field, { target: { value: text } });
  fireEvent.keyDown(field, { key: 'Enter' });
  await waitFor(() => expect(stream.signals).toHaveLength(1));
  await screen.findByRole('button', { name: 'Stop this reply' });
}
const switchQuestion = () => document.querySelector('[data-recipient-switch]') as HTMLElement | null;
const picker = () => screen.getByRole('combobox', { name: 'To' }) as HTMLSelectElement;
const reply = () => document.querySelector('[data-turn="reply"] [data-turn-body]')?.textContent ?? null;

it.each([
  ['the search sheet', sheetWriteTo],
  ['the Dossier', dossierWriteTo],
])('asks before "Write to" from %s stops a reply in progress, and stops nothing until confirmed', async (_from, writeTo) => {
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  await replyInFlight('Think this through');
  expect(sent[0]).toMatchObject({ message: 'Think this through', agent: 'jarvis' });
  await writeTo('Frigga', 'frigga');
  // the To's own question, in its words and with its two steps
  await waitFor(() => expect(switchQuestion()).not.toBeNull());
  expect(switchQuestion()!.getAttribute('role')).toBe('alert');
  expect(switchQuestion()!.textContent).toContain('Writing to Frigga stops the reply in progress.');
  // nothing is stopped and the recipient has not changed
  expect(stream.signals[0].aborted).toBe(false);
  expect(picker().value).toBe('jarvis');
  expect(screen.getByRole('button', { name: 'Stop this reply' })).toBeTruthy();
  // Send waits for the answer and says why: a message written now would go to Jarvis
  fireEvent.change(composerField(), { target: { value: 'For Frigga' } });
  expect(composerSend().disabled).toBe(true);
  expect(sendWhy()).toBe('Writing to Frigga stops the reply in progress.');
  fireEvent.keyDown(composerField(), { key: 'Enter' });
  expect(sent).toHaveLength(1);
  // the owner confirms: the reply stops, and only then does the recipient change
  fireEvent.click(within(switchQuestion()!).getByRole('button', { name: 'Stop it and write to Frigga' }));
  expect(stream.signals[0].aborted).toBe(true);
  await waitFor(() => expect(picker().value).toBe('frigga'));
  expect(switchQuestion()).toBeNull();
  expect(screen.queryByRole('button', { name: 'Stop this reply' })).toBeNull();
  stream.hold = false;
  fireEvent.keyDown(composerField(), { key: 'Enter' });
  await waitFor(() => expect(sent[sent.length - 1]).toMatchObject({ message: 'For Frigga', agent: 'frigga' }));
});

it.each([
  ['the search sheet', sheetWriteTo],
  ['the Dossier', dossierWriteTo],
])('keeps the reply and the recipient when "Write to" from %s is declined', async (_from, writeTo) => {
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  await replyInFlight('Keep going');
  await writeTo('Frigga', 'frigga');
  await waitFor(() => expect(switchQuestion()).not.toBeNull());
  fireEvent.click(within(switchQuestion()!).getByRole('button', { name: 'Keep writing to Jarvis' }));
  expect(switchQuestion()).toBeNull();
  expect(stream.signals[0].aborted).toBe(false);
  expect(picker().value).toBe('jarvis');
  // the reply is written to its end, to the recipient kept
  await act(async () => { stream.release.forEach((release) => release()); });
  await waitFor(() => expect(reply()).toContain('Done'));
  expect(picker().value).toBe('jarvis');
});

/* PHASE_B_PLAN.md §12 item 11: a change of recipient asked for during a reply and still unanswered
   when that reply ends is not made by itself. The question stays, without its "stops the reply"
   clause; Send waits for it; the reply that ended keeps its Turn details (turn-outcome-app). */
const ENDED = 'The reply from Jarvis has ended. Write to Frigga?';

it('keeps a "Write to" asked during a reply open when that reply ends: nothing switches by itself', async () => {
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  await replyInFlight('Finish first');
  runCommand('write to frigga', 'agent:write:frigga');
  await waitFor(() => expect(switchQuestion()).not.toBeNull());
  // the owner leaves the question open; the reply is written to its end
  await act(async () => { stream.release.forEach((release) => release()); });
  await waitFor(() => expect(reply()).toContain('Done'));
  // nothing switched: the recipient is Jarvis, and the question stays, reworded
  expect(picker().value).toBe('jarvis');
  expect(stream.signals[0].aborted).toBe(false);
  expect(switchQuestion()!.getAttribute('data-recipient-switch-state')).toBe('ended');
  expect(switchQuestion()!.textContent).toContain(ENDED);
  expect(switchQuestion()!.textContent).not.toContain('stops the reply');
  // Send still waits for the answer, and points at the question
  fireEvent.change(composerField(), { target: { value: 'Now to Frigga' } });
  expect(composerSend().disabled).toBe(true);
  expect(sendWhy()).toBe(ENDED);
  fireEvent.keyDown(composerField(), { key: 'Enter' });
  expect(sent).toHaveLength(1);
  // the owner answers
  fireEvent.click(within(switchQuestion()!).getByRole('button', { name: 'Write to Frigga' }));
  await waitFor(() => expect(picker().value).toBe('frigga'));
  expect(switchQuestion()).toBeNull();
  expect(head()).toBe('with Frigga · Local');
  stream.hold = false;
  fireEvent.keyDown(composerField(), { key: 'Enter' });
  await waitFor(() => expect(sent[sent.length - 1]).toMatchObject({ message: 'Now to Frigga', agent: 'frigga' }));
});

it('keeps a pick in the To made during a reply open when that reply ends, and "Stay with Jarvis" changes nothing', async () => {
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  await replyInFlight('Keep going');
  fireEvent.change(picker(), { target: { value: 'frigga' } });
  await waitFor(() => expect(switchQuestion()).not.toBeNull());
  await act(async () => { stream.release.forEach((release) => release()); });
  await waitFor(() => expect(reply()).toContain('Done'));
  expect(picker().value).toBe('jarvis');
  expect(switchQuestion()!.textContent).toContain(ENDED);
  fireEvent.click(within(switchQuestion()!).getByRole('button', { name: 'Stay with Jarvis' }));
  expect(switchQuestion()).toBeNull();
  expect(picker().value).toBe('jarvis');
  stream.hold = false;
  fireEvent.change(composerField(), { target: { value: 'Still Jarvis' } });
  fireEvent.keyDown(composerField(), { key: 'Enter' });
  await waitFor(() => expect(sent[sent.length - 1]).toMatchObject({ message: 'Still Jarvis', agent: 'jarvis' }));
});

it.each([
  ['"Write to" from the search sheet', async () => { runCommand('write to frigga', 'agent:write:frigga'); }],
  ['a pick in the To', async () => { fireEvent.change(picker(), { target: { value: 'frigga' } }); }],
])('keeps the question for %s when the owner leaves the conversation and comes back', async (_how, ask) => {
  history.replaceState(null, '', '/v2/cockpit');
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  await replyInFlight('Long answer');
  await ask();
  await waitFor(() => expect(switchQuestion()).not.toBeNull());
  // All pages: no composer there
  history.pushState(null, '', '/v2/console');
  fireEvent.popState(window);
  await waitFor(() => expect(document.querySelector('[data-composer]')).toBeNull());
  // back on Home, the reply still being written: the same question, still asking first
  history.pushState(null, '', '/v2/cockpit');
  fireEvent.popState(window);
  await waitFor(() => expect(switchQuestion()).not.toBeNull());
  expect(switchQuestion()!.getAttribute('data-recipient-switch')).toBe('frigga');
  expect(switchQuestion()!.textContent).toContain('Writing to Frigga stops the reply in progress.');
  expect(composerSend().disabled).toBe(true);
  // away again while the reply ends, and back: the question is there, in its ended form
  history.pushState(null, '', '/v2/console');
  fireEvent.popState(window);
  await waitFor(() => expect(document.querySelector('[data-composer]')).toBeNull());
  await act(async () => { stream.release.forEach((release) => release()); });
  history.pushState(null, '', '/v2/cockpit');
  fireEvent.popState(window);
  await waitFor(() => expect(switchQuestion()).not.toBeNull());
  expect(switchQuestion()!.textContent).toContain(ENDED);
  expect(stream.signals[0].aborted).toBe(false);
  expect(picker().value).toBe('jarvis');
  expect(sendWhy()).toBe(ENDED);
  fireEvent.click(within(switchQuestion()!).getByRole('button', { name: 'Write to Frigga' }));
  await waitFor(() => expect(picker().value).toBe('frigga'));
  expect(switchQuestion()).toBeNull();
});

it('drops the question when the recipient moves some other way', async () => {
  render(<App />);
  // Frigga is chosen (no reply in flight: at once), and a reply to her is being written
  fireEvent.change(await screen.findByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
  await replyInFlight('To Frigga');
  runCommand('write to jarvis', 'agent:write:jarvis');
  await waitFor(() => expect(switchQuestion()).not.toBeNull());
  expect(switchQuestion()!.textContent).toContain('Writing to Jarvis stops the reply in progress.');
  // Frigga leaves the roster: App drops the recipient, and with it the question about replacing her
  liveRoster.agents = [roster[0]];
  await act(async () => { await liveRoster.refresh?.(); });
  expect(switchQuestion()).toBeNull();
  expect(head()).toBe('no agent chosen');
  expect(sendWhy()).toBe(UNAVAILABLE_FRIGGA);
  // nothing switched to Jarvis by itself, now or when the reply ends
  await act(async () => { stream.release.forEach((release) => release()); });
  expect(switchQuestion()).toBeNull();
  expect(picker().value).toBe('');
});

it('drops the question at the demo boundary, and does not bring it back', async () => {
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  await replyInFlight('Live reply');
  runCommand('write to frigga', 'agent:write:frigga');
  await waitFor(() => expect(switchQuestion()).not.toBeNull());
  history.replaceState(null, '', '/v2/chat?demo=1');
  fireEvent.popState(window);
  await waitFor(() => expect(policy()).toBe('Demo sample'));
  expect(switchQuestion()).toBeNull();
  history.replaceState(null, '', '/v2/chat');
  fireEvent.popState(window);
  await screen.findByRole('combobox', { name: 'To' });
  expect(switchQuestion()).toBeNull();
  expect(picker().value).toBe('jarvis');
});

/* The hub does not serve the roster (GET /api/agents did not answer: the loader builds one from
   /status and the seed, as the fixture hub does): Jarvis is ready, and nothing says which routing
   policy any agent declared. */
const NOT_SERVED = [{ id: 'jarvis', name: 'Jarvis' }, { id: 'frigga', name: 'Frigga' }];

it('says the routing policy is not known, never "Unavailable", when the roster is not served, and sends to Jarvis', async () => {
  liveRoster.agents = NOT_SERVED;
  render(<App />);
  await waitFor(() => expect(head()).toBe('with Jarvis · Routing policy unknown'));
  expect(document.body.textContent).not.toContain('Unavailable');
  expect(screen.queryByRole('combobox', { name: 'To' })).toBeNull();
  fireEvent.change(composerField(), { target: { value: 'Hello' } });
  expect(composerSend().disabled).toBe(false);
  fireEvent.keyDown(composerField(), { key: 'Enter' });
  await waitFor(() => expect(sent).toEqual([expect.objectContaining({ message: 'Hello', agent: 'jarvis' })]));
});

it('says what is true after a refusal when the roster is no longer served: no agent chosen, and one can be', async () => {
  render(<App />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
  liveRoster.agents = [roster[0]];
  await act(async () => { await liveRoster.refresh?.(); });
  expect(sendWhy()).toBe(UNAVAILABLE_FRIGGA);
  // the next poll does not get the hub's roster
  liveRoster.agents = NOT_SERVED;
  await act(async () => { await liveRoster.refresh?.(); });
  // no "Checking the selected agent…": no agent is selected
  expect(screen.queryByText('Checking the selected agent…')).toBeNull();
  expect(head()).toBe('no agent chosen');
  expect(sendWhy()).toBe(UNAVAILABLE_FRIGGA);
  expect(composerSend().disabled).toBe(true);
  // choosing is still possible: Jarvis, App's default, needs no roster
  const fallback = screen.getByRole('combobox', { name: 'To' }) as HTMLSelectElement;
  expect(Array.from(fallback.options).map((o) => o.textContent)).toEqual(['Choose an agent', 'Jarvis · Routing policy unknown']);
  fireEvent.change(fallback, { target: { value: 'jarvis' } });
  expect(head()).toBe('with Jarvis · Routing policy unknown');
  expect(document.activeElement).toBe(composerField());
  fireEvent.change(composerField(), { target: { value: 'To Jarvis' } });
  fireEvent.keyDown(composerField(), { key: 'Enter' });
  await waitFor(() => expect(sent).toEqual([expect.objectContaining({ message: 'To Jarvis', agent: 'jarvis' })]));
});

it('says the sign-in changed, not that the agent waits for the roster, when it changes while the roster is not served', async () => {
  localStorage.setItem('hud.user_token', 'guest-one');
  render(<App />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
  await waitFor(() => expect(savedCredential()).toHaveLength(64));
  liveRoster.agents = NOT_SERVED;
  await act(async () => { await liveRoster.refresh?.(); });
  // Frigga is still the one chosen, and the poll that has completed did not bring the roster that
  // could confirm her: that is what is said, not "checking" for ever
  expect(head()).toBe('with Frigga · not confirmed');
  expect(sendWhy()).toBe(UNCONFIRMED_FRIGGA);
  localStorage.setItem('hud.user_token', 'guest-two');
  act(() => { window.dispatchEvent(new Event('focus')); });
  await waitFor(() => expect(sendWhy()).toBe(SIGNIN_CHANGED));
  expect(head()).toBe('no agent chosen');
  expect(screen.queryByText('Checking the selected agent…')).toBeNull();
  expect(screen.queryByText(UNCONFIRMED_FRIGGA)).toBeNull();
});

/* A selected agent the hub's roster cannot confirm because a poll has completed without the roster
   being served: never "Checking the selected agent…" for good. The composer says what is true in the
   hub's terms, the head names the agent "not confirmed", the To offers Jarvis (App's default, which
   needs no roster), the choice is kept and confirmed once a served roster offers the agent, and
   nothing switches by itself. */
const UNCONFIRMED_FRIGGA = 'The hub did not serve the agent roster, so Frigga cannot be confirmed until it does. Nothing is sent until then, unless you choose Jarvis.';

it('holds a saved recipient the hub never serves the roster for: says why, offers Jarvis, and confirms her once served', async () => {
  const first = render(<App />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
  await waitFor(() => expect(savedCredential()).toHaveLength(64));
  first.unmount();
  liveRoster.agents = NOT_SERVED;
  render(<App />);
  // before the first poll has answered, checking is what is true
  expect(sendWhy()).toBe('Checking the selected agent…');
  // once a poll has completed without the hub's roster, what is true is said
  await waitFor(() => expect(sendWhy()).toBe(UNCONFIRMED_FRIGGA));
  expect(screen.queryByText('Checking the selected agent…')).toBeNull();
  expect(document.querySelector('.n-composer__recipient')?.getAttribute('data-recipient-state')).toBe('unconfirmed');
  expect(head()).toBe('with Frigga · not confirmed');
  expect(document.querySelector('.n-talk__unconfirmed')?.getAttribute('title')).toBe(UNCONFIRMED_FRIGGA);
  // the To names her as not confirmed and offers Jarvis; Send is held and sends nothing
  const to = screen.getByRole('combobox', { name: 'To' }) as HTMLSelectElement;
  expect(Array.from(to.options).map((o) => o.textContent)).toEqual(['Frigga · not confirmed', 'Jarvis · Routing policy unknown']);
  expect(to.value).toBe('');
  fireEvent.change(composerField(), { target: { value: 'Held for Frigga' } });
  expect(composerSend().disabled).toBe(true);
  fireEvent.keyDown(composerField(), { key: 'Enter' });
  expect(sent).toHaveLength(0);
  // another poll without the roster: nothing switched by itself, and the choice is kept
  await act(async () => { await liveRoster.refresh?.(); });
  expect(sendWhy()).toBe(UNCONFIRMED_FRIGGA);
  expect(JSON.parse(sessionStorage.getItem('nerva.chat.recipient') || 'null')?.agent).toBe('frigga');
  expect(sent).toHaveLength(0);
  // a served roster that offers her confirms her
  liveRoster.agents = roster;
  await act(async () => { await liveRoster.refresh?.(); });
  await waitFor(() => expect(to.value).toBe('frigga'));
  expect(head()).toBe('with Frigga · Local');
  expect(document.querySelector('.n-composer__recipient')).toBeNull();
  fireEvent.keyDown(composerField(), { key: 'Enter' });
  await waitFor(() => expect(sent).toEqual([expect.objectContaining({ message: 'Held for Frigga', agent: 'frigga' })]));
});

it('lets the owner write to Jarvis instead while a saved recipient cannot be confirmed, and that choice stands', async () => {
  const first = render(<App />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
  await waitFor(() => expect(savedCredential()).toHaveLength(64));
  first.unmount();
  liveRoster.agents = [];
  history.replaceState(null, '', '/v2/cockpit');
  render(<App />);
  await waitFor(() => expect(sendWhy()).toBe(UNCONFIRMED_FRIGGA));
  const to = screen.getByRole('combobox', { name: 'To' }) as HTMLSelectElement;
  fireEvent.change(to, { target: { value: 'jarvis' } });
  expect(head()).toBe('with Jarvis · Routing policy unknown');
  expect(document.activeElement).toBe(composerField());
  expect(sessionStorage.getItem('nerva.chat.recipient')).toBeNull();
  fireEvent.change(composerField(), { target: { value: 'To Jarvis then' } });
  fireEvent.keyDown(composerField(), { key: 'Enter' });
  await waitFor(() => expect(sent).toEqual([expect.objectContaining({ message: 'To Jarvis then', agent: 'jarvis' })]));
  // the roster served again: the owner's choice stands, the saved one does not come back
  liveRoster.agents = roster;
  await act(async () => { await liveRoster.refresh?.(); });
  expect((screen.getByRole('combobox', { name: 'To' }) as HTMLSelectElement).value).toBe('jarvis');
});

it('says the same, in Romanian, of an agent chosen before the roster stopped being served', async () => {
  localStorage.setItem('hud.appearance.v1:/', JSON.stringify({ version: 2, preferences: { lang: 'ro' } }));
  render(<App />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'Către' }), { target: { value: 'frigga' } });
  liveRoster.agents = NOT_SERVED;
  await act(async () => { await liveRoster.refresh?.(); });
  expect(sendWhy()).toBe('Hubul nu a trimis lista agenților, așa că agentul Frigga nu poate fi confirmat până nu o trimite. Nu se trimite nimic până atunci, decât dacă îl alegi pe Jarvis.');
  expect(head()).toBe('cu Frigga · neconfirmat');
  expect(Array.from((screen.getByRole('combobox', { name: 'Către' }) as HTMLSelectElement).options).map((o) => o.textContent))
    .toEqual(['Frigga · neconfirmat', 'Jarvis · Politica de rutare necunoscută']);
});

/* A poll that did not get the hub's roster (GET /api/agents failed once: the loader's rows from
   /status carry no roster) says nothing about the agent asked for. The question stays until the
   owner answers it (§12 item 11), as the recipient App holds stays: Send stays held, so the next
   message cannot go to the recipient the owner asked to replace, and its "Write to" waits for a
   served roster, saying why. Only a roster the hub served that no longer offers the agent drops it. */
const HELD_FRIGGA = 'The hub did not serve the agent roster, so Frigga cannot be chosen until it does.';

it('keeps a "Write to" question through roster polls the hub did not serve, holding Send and the switch until a served roster', async () => {
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  await replyInFlight('Keep going');
  runCommand('write to frigga', 'agent:write:frigga');
  await waitFor(() => expect(switchQuestion()).not.toBeNull());
  fireEvent.change(composerField(), { target: { value: 'For Frigga' } });
  // one poll gets only the /status rows, the next no rows at all
  for (const unserved of [NOT_SERVED, []]) {
    liveRoster.agents = unserved;
    await act(async () => { await liveRoster.refresh?.(); });
    expect(switchQuestion()?.getAttribute('data-recipient-switch')).toBe('frigga');
    // Send still waits for the answer: a message now would go to Jarvis, whom the owner asked to replace
    expect(composerSend().disabled).toBe(true);
    expect(sendWhy()).toBe('Writing to Frigga stops the reply in progress.');
    fireEvent.keyDown(composerField(), { key: 'Enter' });
    expect(sent).toHaveLength(1);
    // the switch waits for a served roster and says why; it stops nothing meanwhile
    const take = within(switchQuestion()!).getByRole('button', { name: 'Stop it and write to Frigga' }) as HTMLButtonElement;
    expect(take.disabled).toBe(true);
    expect(document.getElementById(take.getAttribute('aria-describedby') || '')?.textContent).toBe(HELD_FRIGGA);
    fireEvent.click(take);
    expect(stream.signals[0].aborted).toBe(false);
    expect(switchQuestion()).not.toBeNull();
  }
  // the reply ends meanwhile: nothing switched, and the question stays in its ended form, still held
  await act(async () => { stream.release.forEach((release) => release()); });
  await waitFor(() => expect(reply()).toContain('Done'));
  expect(switchQuestion()!.textContent).toContain(ENDED);
  expect((within(switchQuestion()!).getByRole('button', { name: 'Write to Frigga' }) as HTMLButtonElement).disabled).toBe(true);
  expect(composerSend().disabled).toBe(true);
  // the hub serves the roster again, Frigga in it: the owner's answer is taken
  liveRoster.agents = roster;
  await act(async () => { await liveRoster.refresh?.(); });
  expect(within(switchQuestion()!).queryByText(HELD_FRIGGA)).toBeNull();
  fireEvent.click(within(switchQuestion()!).getByRole('button', { name: 'Write to Frigga' }));
  await waitFor(() => expect(picker().value).toBe('frigga'));
  expect(switchQuestion()).toBeNull();
  stream.hold = false;
  fireEvent.keyDown(composerField(), { key: 'Enter' });
  await waitFor(() => expect(sent[sent.length - 1]).toMatchObject({ message: 'For Frigga', agent: 'frigga' }));
});

it('lets the owner answer "Keep writing to Jarvis" while the roster is not served', async () => {
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  await replyInFlight('Keep going');
  runCommand('write to frigga', 'agent:write:frigga');
  await waitFor(() => expect(switchQuestion()).not.toBeNull());
  liveRoster.agents = NOT_SERVED;
  await act(async () => { await liveRoster.refresh?.(); });
  fireEvent.click(within(switchQuestion()!).getByRole('button', { name: 'Keep writing to Jarvis' }));
  expect(switchQuestion()).toBeNull();
  expect(stream.signals[0].aborted).toBe(false);
  // answered: Send is free again, to the recipient kept
  await act(async () => { stream.release.forEach((release) => release()); });
  await waitFor(() => expect(reply()).toContain('Done'));
  stream.hold = false;
  fireEvent.change(composerField(), { target: { value: 'Still Jarvis' } });
  fireEvent.keyDown(composerField(), { key: 'Enter' });
  await waitFor(() => expect(sent[sent.length - 1]).toMatchObject({ message: 'Still Jarvis', agent: 'jarvis' }));
});

it('drops the question only when a roster the hub served no longer offers the agent asked for, and switches nothing', async () => {
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  await replyInFlight('Keep going');
  runCommand('write to frigga', 'agent:write:frigga');
  await waitFor(() => expect(switchQuestion()).not.toBeNull());
  liveRoster.agents = [roster[0]];
  await act(async () => { await liveRoster.refresh?.(); });
  expect(switchQuestion()).toBeNull();
  expect(stream.signals[0].aborted).toBe(false);
  expect(picker().value).toBe('jarvis');
  // nor does a later roster that offers her again bring the question back
  liveRoster.agents = roster;
  await act(async () => { await liveRoster.refresh?.(); });
  expect(switchQuestion()).toBeNull();
  expect(picker().value).toBe('jarvis');
});

/* A question dropped because a roster the hub served no longer offers the agent asked for says why,
   on one line in the composer, until the next send, a change of recipient, or Dismiss; Send is free. */
const DROPPED_FRIGGA = 'Frigga is not available now, so the change to Frigga was dropped. Messages still go to Jarvis.';
const droppedLine = () => document.querySelector('[data-recipient-dropped]') as HTMLElement | null;

it('says why a question was dropped, and that messages still go to the recipient kept, until the next send', async () => {
  history.replaceState(null, '', '/v2/cockpit');
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  await replyInFlight('Keep going');
  runCommand('write to frigga', 'agent:write:frigga');
  await waitFor(() => expect(switchQuestion()).not.toBeNull());
  liveRoster.agents = [roster[0]];
  await act(async () => { await liveRoster.refresh?.(); });
  expect(switchQuestion()).toBeNull();
  expect(droppedLine()?.getAttribute('data-recipient-dropped')).toBe('frigga');
  expect(droppedLine()?.getAttribute('role')).toBe('status');
  expect(within(droppedLine()!).getByText(DROPPED_FRIGGA)).toBeTruthy();
  // it outlives the composer, as the question did: away from Home and back
  history.pushState(null, '', '/v2/console');
  fireEvent.popState(window);
  await waitFor(() => expect(document.querySelector('[data-composer]')).toBeNull());
  history.pushState(null, '', '/v2/cockpit');
  fireEvent.popState(window);
  await waitFor(() => expect(droppedLine()).not.toBeNull());
  // Send is free: nothing waits on the line, and the next send ends it
  await act(async () => { stream.release.forEach((release) => release()); });
  await waitFor(() => expect(reply()).toContain('Done'));
  stream.hold = false;
  fireEvent.change(composerField(), { target: { value: 'Still Jarvis' } });
  expect(composerSend().disabled).toBe(false);
  expect(composerSend().hasAttribute('aria-describedby')).toBe(false);
  fireEvent.keyDown(composerField(), { key: 'Enter' });
  await waitFor(() => expect(sent[sent.length - 1]).toMatchObject({ message: 'Still Jarvis', agent: 'jarvis' }));
  expect(droppedLine()).toBeNull();
});

it('ends the line about a dropped question on Dismiss, or when the recipient changes', async () => {
  const howard = { id: 'howard', name: 'Howard', rosterSource: 'api', chat_routing: 'local', enabled: true };
  liveRoster.agents = [...roster, howard];
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  const dropOnce = async (text: string) => {
    liveRoster.agents = [...roster, howard];
    await act(async () => { await liveRoster.refresh?.(); });
    await replyInFlight(text);
    runCommand('write to frigga', 'agent:write:frigga');
    await waitFor(() => expect(switchQuestion()).not.toBeNull());
    liveRoster.agents = [roster[0], howard];
    await act(async () => { await liveRoster.refresh?.(); });
    expect(droppedLine()).not.toBeNull();
    await act(async () => { stream.release.forEach((release) => release()); });
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Stop this reply' })).toBeNull());
    stream.signals.length = 0;
    stream.release.length = 0;
  };
  await dropOnce('First reply');
  fireEvent.click(within(droppedLine()!).getByRole('button', { name: 'Dismiss' }));
  expect(droppedLine()).toBeNull();
  await dropOnce('Second reply');
  fireEvent.change(picker(), { target: { value: 'howard' } });
  expect(picker().value).toBe('howard');
  expect(droppedLine()).toBeNull();
  expect(sent.map((m) => m.agent)).toEqual(['jarvis', 'jarvis']);
});

it('says it in Romanian', async () => {
  localStorage.setItem('hud.appearance.v1:/', JSON.stringify({ version: 2, preferences: { lang: 'ro' } }));
  render(<App />);
  const to = await screen.findByRole('combobox', { name: 'Către' }) as HTMLSelectElement;
  stream.hold = true;
  fireEvent.change(composerField(), { target: { value: 'Gândește-te' } });
  fireEvent.keyDown(composerField(), { key: 'Enter' });
  await waitFor(() => expect(stream.signals).toHaveLength(1));
  fireEvent.change(to, { target: { value: 'frigga' } });
  await waitFor(() => expect(switchQuestion()).not.toBeNull());
  liveRoster.agents = [roster[0]];
  await act(async () => { await liveRoster.refresh?.(); });
  expect(within(droppedLine()!).getByText('Agentul Frigga nu este disponibil acum, așa că schimbarea către Frigga a fost anulată. Mesajele merg în continuare către Jarvis.')).toBeTruthy();
  expect(within(droppedLine()!).getByRole('button', { name: 'Închide' })).toBeTruthy();
});

/* "Until the next send" counts every turn sent, typed or hands-free voice (PHASE_B_INTERFACES.md §7).
   A voice turn goes to the recipient the head names and leaves an open question open (PHASE_B_PLAN.md
   §12 item 12); one refused because a reply is still being written sends nothing and ends nothing. */
async function speak(text: string): Promise<string> {
  let said = 'not settled';
  await act(async () => { said = await voiceLoop.onTurn!(text); });
  return said;
}

it('ends the line about a dropped question on a hands-free voice turn that is sent, and on nothing else', async () => {
  history.replaceState(null, '', '/v2/cockpit');
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  await replyInFlight('Keep going');
  runCommand('write to frigga', 'agent:write:frigga');
  await waitFor(() => expect(switchQuestion()).not.toBeNull());
  liveRoster.agents = [roster[0]];
  await act(async () => { await liveRoster.refresh?.(); });
  expect(droppedLine()).not.toBeNull();
  // spoken while the reply is still being written: refused, nothing is sent, the line stays
  expect(await speak('Too early')).toBe('');
  expect(sent).toHaveLength(1);
  expect(droppedLine()).not.toBeNull();
  // the reply ending is not a send either
  await act(async () => { stream.release.forEach((release) => release()); });
  await waitFor(() => expect(reply()).toContain('Done'));
  expect(droppedLine()).not.toBeNull();
  // a voice turn that is sent goes to the recipient kept, and ends the line
  stream.hold = false;
  expect(await speak('Spoken to Jarvis')).toBe('Done');
  expect(sent).toHaveLength(2);
  expect(sent[1]).toMatchObject({ message: 'Spoken to Jarvis', agent: 'jarvis' });
  expect(droppedLine()).toBeNull();
});

it('ends the line on a voice turn sent while another question is open, which goes to the recipient the head names and leaves that question open', async () => {
  const howard = { id: 'howard', name: 'Howard', rosterSource: 'api', chat_routing: 'local', enabled: true };
  liveRoster.agents = [...roster, howard];
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  await replyInFlight('Keep going');
  runCommand('write to frigga', 'agent:write:frigga');
  await waitFor(() => expect(switchQuestion()).not.toBeNull());
  liveRoster.agents = [roster[0], howard];
  await act(async () => { await liveRoster.refresh?.(); });
  expect(droppedLine()).not.toBeNull();
  // a new question, for Howard, asked while the reply is written; the reply then ends, unanswered
  runCommand('write to howard', 'agent:write:howard');
  await waitFor(() => expect(switchQuestion()?.getAttribute('data-recipient-switch')).toBe('howard'));
  await act(async () => { stream.release.forEach((release) => release()); });
  await waitFor(() => expect(reply()).toContain('Done'));
  expect(switchQuestion()?.getAttribute('data-recipient-switch-state')).toBe('ended');
  expect(droppedLine()).not.toBeNull();
  expect(composerSend().disabled).toBe(true);
  stream.hold = false;
  expect(await speak('Spoken while asked')).toBe('Done');
  expect(sent[sent.length - 1]).toMatchObject({ message: 'Spoken while asked', agent: 'jarvis' });
  expect(head()).toBe('with Jarvis · Orchestrated');
  expect(picker().value).toBe('jarvis');
  expect(switchQuestion()?.getAttribute('data-recipient-switch')).toBe('howard');
  expect(droppedLine()).toBeNull();
});

/* While the roster is not served, the question names the agent by the last name the hub's roster
   gave it (App keeps it with the question), never by a /status or seed row or the bare id. */
it('names the agent of a question held for the roster as the hub last named it', async () => {
  liveRoster.agents = [roster[0], { ...roster[1], name: 'Frigga Allmother' }];
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  await replyInFlight('Keep going');
  runCommand('write to frigga', 'agent:write:frigga');
  await waitFor(() => expect(switchQuestion()).not.toBeNull());
  expect(switchQuestion()!.textContent).toContain('Writing to Frigga Allmother stops the reply in progress.');
  // a poll the hub did not serve: its /status rows call her "Frigga"
  liveRoster.agents = NOT_SERVED;
  await act(async () => { await liveRoster.refresh?.(); });
  expect(switchQuestion()!.textContent).toContain('Writing to Frigga Allmother stops the reply in progress.');
  expect(within(switchQuestion()!).getByText('The hub did not serve the agent roster, so Frigga Allmother cannot be chosen until it does.')).toBeTruthy();
  expect(within(switchQuestion()!).getByRole('button', { name: 'Stop it and write to Frigga Allmother' })).toBeTruthy();
  expect(sendWhy()).toBe('Writing to Frigga Allmother stops the reply in progress.');
  // …and in its ended form
  await act(async () => { stream.release.forEach((release) => release()); });
  await waitFor(() => expect(reply()).toContain('Done'));
  expect(switchQuestion()!.textContent).toContain('The reply from Jarvis has ended. Write to Frigga Allmother?');
});

it('names a recipient held for the roster as the hub last named her, after a reload too', async () => {
  liveRoster.agents = [roster[0], { ...roster[1], name: 'Frigga Allmother' }];
  const first = render(<App />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
  await waitFor(() => expect(savedCredential()).toHaveLength(64));
  first.unmount();
  liveRoster.agents = NOT_SERVED;
  render(<App />);
  await waitFor(() => expect(sendWhy()).toBe(UNCONFIRMED_FRIGGA.replace(/Frigga/, 'Frigga Allmother')));
  expect(head()).toBe('with Frigga Allmother · not confirmed');
  expect((screen.getByRole('combobox', { name: 'To' }) as HTMLSelectElement).options[0].textContent).toBe('Frigga Allmother · not confirmed');
});

it('names an agent that left the roster by the name the hub gave it, in the session and after a reload', async () => {
  const named = [roster[0], { ...roster[1], name: 'Frigga Allmother' }];
  const REFUSED = 'Frigga Allmother is not available now. Nothing is sent until you choose who to write to.';
  liveRoster.agents = named;
  const first = render(<App />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
  await waitFor(() => expect(savedCredential()).toHaveLength(64));
  expect(JSON.parse(sessionStorage.getItem('nerva.chat.recipient') || 'null')?.name).toBe('Frigga Allmother');
  // after a reload, with Frigga gone from the roster: named as the owner knew her, not "Frigga"
  first.unmount();
  liveRoster.agents = [roster[0]];
  const second = render(<App />);
  await waitFor(() => expect(sendWhy()).toBe(REFUSED));
  second.unmount();
  // in the session: she leaves the roster while she is the one written to
  liveRoster.agents = named;
  render(<App />);
  fireEvent.change(await screen.findByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
  liveRoster.agents = [roster[0]];
  await act(async () => { await liveRoster.refresh?.(); });
  expect(sendWhy()).toBe(REFUSED);
});

it('words the Dossier\'s "Write to <Agent>" in the owner\'s language', () => {
  const onWriteTo = vi.fn();
  render(<Dossier id="frigga" onClose={() => {}} onOpen={() => {}} agents={roster} onWriteTo={onWriteTo} lang="ro" />);
  fireEvent.click(screen.getByRole('button', { name: 'Scrie-i lui Frigga' }));
  expect(onWriteTo).toHaveBeenCalledExactlyOnceWith('frigga');
});

it.each([
  ['the search sheet', sheetWriteTo],
  ['the Dossier', dossierWriteTo],
])('switches at once on "Write to" from %s when no reply is being written', async (_from, writeTo) => {
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  await writeTo('Frigga', 'frigga');
  await waitFor(() => expect(picker().value).toBe('frigga'));
  expect(switchQuestion()).toBeNull();
  expect(head()).toBe('with Frigga · Local');
  // the composer takes the focus, to write to the new recipient
  await waitFor(() => expect(document.activeElement).toBe(composerField()));
  fireEvent.change(composerField(), { target: { value: 'Hello Frigga' } });
  fireEvent.keyDown(composerField(), { key: 'Enter' });
  await waitFor(() => expect(sent).toEqual([expect.objectContaining({ message: 'Hello Frigga', agent: 'frigga' })]));
});

it('takes a "Write to" made on a page without a composer Home, and asks there while a reply is being written', async () => {
  render(<App />);
  await screen.findByRole('combobox', { name: 'To' });
  await replyInFlight('Long answer');
  // All pages: no composer on the page, the reply still being written
  history.pushState(null, '', '/v2/console');
  fireEvent.popState(window);
  await waitFor(() => expect(document.querySelector('[data-composer]')).toBeNull());
  runCommand('write to frigga', 'agent:write:frigga');
  await waitFor(() => expect(location.pathname).toBe('/v2/cockpit'));
  await waitFor(() => expect(switchQuestion()).not.toBeNull());
  expect(switchQuestion()!.textContent).toContain('Writing to Frigga stops the reply in progress.');
  expect(stream.signals[0].aborted).toBe(false);
  expect(picker().value).toBe('jarvis');
  fireEvent.click(within(switchQuestion()!).getByRole('button', { name: 'Stop it and write to Frigga' }));
  expect(stream.signals[0].aborted).toBe(true);
  await waitFor(() => expect(picker().value).toBe('frigga'));
});
