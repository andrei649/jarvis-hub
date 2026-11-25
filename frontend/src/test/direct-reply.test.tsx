import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App from '../app';
import { InputBar } from '../cockpit';
import { V2 } from '../data';
import { openComposerMenu } from '../home/talk/test-support';

const voice = vi.hoisted(() => ({ onTurn: null as null | ((text: string) => Promise<string>) }));
vi.mock('../voice', () => ({ useVoice: ({ onTurn }: any) => {
  voice.onTurn = onTurn;
  return { active: false, toggle: () => {} };
} }));
vi.mock('../mesh', () => ({ NeuralMesh: () => null, isExecutingAgent: () => false }));
vi.mock('../analytics', () => ({ initAnalytics: () => {}, trackPageview: () => {} }));
vi.mock('../gap', () => ({ FirstRunGate: () => null }));
vi.mock('../api/live', () => ({ PREVIEW_MODE_LIVE_KEYS: {}, useLiveModes: () => ({ live: {} }) }));
vi.mock('../api/loaders', () => ({
  loadJarvisData: async () => ({
    agents: [
      { id: 'jarvis', name: 'Jarvis', rosterSource: 'api', chat_routing: 'orchestrated', enabled: true },
      { id: 'frigga', name: 'Frigga', rosterSource: 'api', chat_routing: 'local', enabled: true },
    ],
    ticker: [], tasks: [], calendar: [], heartbeat: [], weather: null, sys: null,
    live: true, serverUp: true, sources: { agents: true, tasks: false, trust: false },
    llm: { state: 'unknown', model: null, residents: [] }, trust: { mic: 'on', strict_local: false },
  }),
  createLatestRefreshRunner: ({ loadData, commitData }: any) => ({ refresh: async () => commitData(await loadData()), stop: () => {} }),
}));

const requests: Array<{ path: string; body?: any }> = [];
const event = (payload: unknown) => `data: ${JSON.stringify(payload)}\n\n`;
beforeEach(() => {
  HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };
  localStorage.clear(); sessionStorage.clear();
  localStorage.setItem('hud.seen', '1');
  history.replaceState(null, '', '/v2/chat');
  requests.length = 0;
  vi.stubGlobal('fetch', vi.fn(async (path: string, init?: { body?: string }) => {
    const body = init?.body ? JSON.parse(init.body) : undefined;
    requests.push({ path: String(path), body });
    if (String(path).endsWith('/chat/stream')) return new Response(event({ type: 'end', agent: body.agent, text: 'Done', session_id: 'session-a' }),
      { headers: { 'Content-Type': 'text/event-stream' } });
    if (String(path).includes('/api/os/brain/retrieve')) return Response.json({ ok: true,
      attachments: [{ name: 'Note.md', text: 'Reviewed excerpt' }] });
    return Response.json({});
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); voice.onTurn = null; });
const sent = () => requests.filter(request => request.path.endsWith('/chat/stream')).map(request => request.body);
const draft = () => document.querySelector<HTMLInputElement>('[data-composer="1"]')!;
async function mount() {
  render(<App />);
  // the recipient is the composer's To (RecipientPicker, PHASE_B_PLAN.md §5.3)
  await screen.findByRole('combobox', { name: 'To' });
}
async function send(text: string) {
  fireEvent.change(draft(), { target: { value: text } });
  fireEvent.keyDown(draft(), { key: 'Enter' });
  await waitFor(() => expect(sent()[sent().length - 1]?.message).toBe(text));
}

it.each(['chat', 'cockpit'])('compares a live %s draft without sending it and preserves it on close', async mode => {
  history.replaceState(null, '', '/v2/' + mode);
  render(<App />);
  // Compare agents is in the composer's Options menu since the re-lay (PHASE_B_PLAN.md §5.3)
  await waitFor(() => expect(document.querySelector('[data-composer]')).toBeTruthy());
  openComposerMenu('options');
  const trigger = await screen.findByRole('button', { name: 'Compare agents' });
  expect((trigger as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(draft(), { target: { value: 'How should we organize a garden?' } });
  fireEvent.click(trigger);
  const dialog = await screen.findByRole('dialog');
  expect((dialog.querySelector('textarea') as HTMLTextAreaElement).value).toBe('How should we organize a garden?');
  expect(requests.some(request => request.path.endsWith('/opinions'))).toBe(false);
  fireEvent.keyDown(dialog, { key: 'Escape' });
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(draft().value).toBe('How should we organize a garden?');
  expect(sent()).toEqual([]);
});

it('closes comparison on session change and excludes commands and demo recipients', () => {
  const props = { selectedTurn: true, agent: 'jarvis', t: V2.I18N.en, agents: [
    { id: 'jarvis', rosterSource: 'api' }, { id: 'frigga', rosterSource: 'api' },
  ] };
  const view = render(<InputBar {...props} sessionId="one" />);
  fireEvent.change(draft(), { target: { value: 'One question' } });
  openComposerMenu('options');
  fireEvent.click(screen.getByRole('button', { name: 'Compare agents' }));
  expect(screen.getByRole('dialog')).toBeTruthy();
  view.rerender(<InputBar {...props} sessionId="two" />);
  expect(screen.queryByRole('dialog')).toBeNull();
  view.rerender(<InputBar {...props} sessionId="one" />);
  expect(screen.queryByRole('dialog')).toBeNull();
  openComposerMenu('options');   // the absences below are checked with the menu open
  fireEvent.change(draft(), { target: { value: '/help' } });
  expect(screen.queryByRole('button', { name: 'Compare agents' })).toBeNull();
  fireEvent.change(draft(), { target: { value: 'Plain question' } });
  expect(screen.getByRole('button', { name: 'Compare agents' })).toBeTruthy();
  view.rerender(<InputBar {...props} agents={[props.agents[0], { id: 'preview', rosterSource: 'demo' }]} />);
  expect(screen.queryByRole('button', { name: 'Compare agents' })).toBeNull();
});

it('sends reasoning none only for the checked text turn and consumes the choice', async () => {
  await mount();
  openComposerMenu('options');   // Direct reply is in the composer's Options menu since the re-lay
  const choice = screen.getByRole('button', { name: 'Direct reply' });
  expect(choice.getAttribute('aria-pressed')).toBe('false');
  const help = screen.getByText('Ask supported models to skip extended thinking for this message');
  expect(choice.getAttribute('aria-describedby')).toBe(help.id);
  await send('Normal turn');
  expect(sent()[0]).not.toHaveProperty('reasoning');
  fireEvent.click(choice);
  await send('Quick turn');
  expect(sent()[1]).toMatchObject({ message: 'Quick turn', reasoning: 'none' });
  expect(choice.getAttribute('aria-pressed')).toBe('false');
  await send('Normal again');
  expect(sent()[2]).not.toHaveProperty('reasoning');
});

it('keeps direct reply in the current draft and out of voice, commands, and another agent', async () => {
  await mount();
  openComposerMenu('options');
  const choice = screen.getByRole('button', { name: 'Direct reply' });
  fireEvent.click(choice);
  await voice.onTurn!('Spoken turn');
  expect(sent()[0]).not.toHaveProperty('reasoning');
  expect(choice.getAttribute('aria-pressed')).toBe('true');
  fireEvent.change(draft(), { target: { value: '/new' } });
  expect(choice.getAttribute('aria-pressed')).toBe('false');
  expect((choice as HTMLButtonElement).disabled).toBe(true);
  await send('/new');
  expect(sent()[1]).not.toHaveProperty('reasoning');
  fireEvent.change(draft(), { target: { value: 'Keep draft' } });
  fireEvent.click(choice);
  // the /new turn has ended (the picker would otherwise ask before stopping it, §5.3)
  await waitFor(() => expect(screen.queryByRole('button', { name: /^Stop (this reply|the replies)$/ })).toBeNull());
  fireEvent.change(screen.getByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
  expect(draft().value).toBe('Keep draft');
  expect(choice.getAttribute('aria-pressed')).toBe('false');
  fireEvent.keyDown(draft(), { key: 'Enter' });
  await waitFor(() => expect(sent()[sent().length - 1]).toMatchObject({ message: 'Keep draft', agent: 'frigga' }));
  expect(sent()[sent().length - 1]).not.toHaveProperty('reasoning');
});

it('sends only explicitly reviewed vault text with the choice and never adds a prompt suffix', async () => {
  await mount();
  fireEvent.change(draft(), { target: { value: 'Use my note' } });
  openComposerMenu('attach');
  fireEvent.click(screen.getByRole('button', { name: 'Find vault notes' }));
  fireEvent.click(await screen.findByRole('checkbox', { name: 'Note.md' }));
  openComposerMenu('options');
  fireEvent.click(screen.getByRole('button', { name: 'Direct reply' }));
  fireEvent.click(screen.getByRole('button', { name: /transmit|send/i }));
  await waitFor(() => expect(sent()).toHaveLength(1));
  expect(sent()[0]).toMatchObject({ message: 'Use my note', reasoning: 'none',
    attachments: [{ name: 'Note.md', text: 'Reviewed excerpt' }] });
});

it('retains the text draft and choice when the submit callback refuses it', () => {
  const submit = vi.fn(() => false);
  render(<InputBar onSubmit={submit} selectedTurn agent="jarvis" sessionId="a"
    t={{ transmit: 'Send', placeholder: 'Message', channel: 'Chat' }} />);
  fireEvent.change(draft(), { target: { value: 'Try again' } });
  openComposerMenu('options');
  const choice = screen.getByRole('button', { name: 'Direct reply' });
  fireEvent.click(choice);
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  expect(submit).toHaveBeenCalledWith('Try again', undefined, undefined, true);
  expect(draft().value).toBe('Try again');
  expect(choice.getAttribute('aria-pressed')).toBe('true');
});

it('uses the Romanian HUD label and help text and toggles the scoped choice', () => {
  const submit = vi.fn();
  render(<InputBar onSubmit={submit} selectedTurn agent="jarvis" sessionId="a" t={V2.I18N.ro} />);
  openComposerMenu('options');
  const choice = screen.getByRole('button', { name: 'Răspuns direct' });
  const help = screen.getByText('Cere modelelor compatibile să sară peste gândirea extinsă pentru acest mesaj.');
  expect(choice.getAttribute('aria-describedby')).toBe(help.id);
  fireEvent.change(draft(), { target: { value: 'Salut' } });
  fireEvent.click(choice);
  expect(choice.getAttribute('aria-pressed')).toBe('true');
  fireEvent.click(choice);
  expect(choice.getAttribute('aria-pressed')).toBe('false');
  fireEvent.click(choice);
  fireEvent.click(screen.getByRole('button', { name: V2.I18N.ro.transmit }));
  expect(submit).toHaveBeenCalledWith('Salut', undefined, undefined, true);
  expect(choice.getAttribute('aria-pressed')).toBe('false');
});

it('drops the choice when the session changes or an image enters the draft', async () => {
  const props = { onSubmit: vi.fn(), selectedTurn: true, agent: 'jarvis',
    t: { transmit: 'Send', placeholder: 'Message', channel: 'Chat' } };
  const view = render(<InputBar {...props} sessionId="first" />);
  openComposerMenu('options');
  const choice = screen.getByRole('button', { name: 'Direct reply' });
  fireEvent.change(draft(), { target: { value: 'Keep this text' } });
  fireEvent.click(choice);
  view.rerender(<InputBar {...props} sessionId="next" />);
  expect(choice.getAttribute('aria-pressed')).toBe('false');
  expect(draft().value).toBe('Keep this text');
  fireEvent.click(choice);
  view.rerender(<InputBar {...props} selectedTurn={false} sessionId="next" />);
  expect(screen.queryByRole('button', { name: 'Direct reply' })).toBeNull();
  view.rerender(<InputBar {...props} sessionId="next" />);
  const currentChoice = screen.getByRole('button', { name: 'Direct reply' });
  expect(currentChoice.getAttribute('aria-pressed')).toBe('false');
  fireEvent.click(currentChoice);
  vi.stubGlobal('URL', Object.assign(class extends URL {}, { createObjectURL: () => 'blob:preview', revokeObjectURL: () => {} }));
  fireEvent.change(screen.getByLabelText('Attach images'), { target: { files: [new File(['image'], 'a.png', { type: 'image/png' })] } });
  await waitFor(() => expect((currentChoice as HTMLButtonElement).disabled).toBe(true));
  expect(currentChoice.getAttribute('aria-pressed')).toBe('false');
});

it('sends a reviewed history reference as a top-level owner request with a plain question', async () => {
  localStorage.setItem('hud.user_token', 'user-token');
  localStorage.setItem('hud.admin_token', 'admin-token');
  const sentRequests: Array<{ body: any; headers: Record<string, string> }> = [];
  vi.stubGlobal('fetch', vi.fn(async (path: string, init?: RequestInit) => {
    if (path === '/sessions/search') return Response.json({ hits: [{ session_id: 'past', turn: 2, role: 'assistant',
      timestamp: '2026-10-01', agent_id: 'frigga', snippet: 'old task' }], truncated: false, stopped_by: null });
    if (path === '/sessions/past/transcript?references=true') return Response.json({ schema_version: 1, session_id: 'past',
      scope: 'retained_current_history', redacted: true, turns: [{ turn: 2, role: 'assistant',
        timestamp: '2026-10-01', agent_id: 'frigga', content: 'The old task was approved.', reference_revision: 'a'.repeat(64) }] });
    if (path === '/chat/stream') {
      const used = sentRequests.length > 0;
      sentRequests.push({ body: JSON.parse(String(init?.body)), headers: init?.headers as Record<string, string> });
      return new Response(event({ type: 'end', agent: 'jarvis', text: used ? 'Done' : 'Busy',
        session_id: 'session-a', history_source_used: used }),
        { headers: { 'Content-Type': 'text/event-stream' } });
    }
    return Response.json({});
  }));
  await mount();
  fireEvent.change(draft(), { target: { value: 'What next?' } });
  openComposerMenu('options');
  fireEvent.click(screen.getByRole('button', { name: 'Search chat history' }));
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'old task' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Review source' }));
  await screen.findByRole('textbox', { name: 'Select exact text from the verified message' });
  fireEvent.click(screen.getByRole('button', { name: 'Use full message' }));
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button', { name: 'Use in this chat' }));
  await screen.findByRole('button', { name: 'Remove passage' });
  expect(sentRequests).toHaveLength(0);
  fireEvent.click(screen.getByRole('button', { name: /transmit|send/i }));
  await waitFor(() => expect(sentRequests).toHaveLength(1));
  expect(sentRequests[0].body).toMatchObject({ message: 'What next?', agent: 'jarvis', history_reference: {
    session_id: 'past', turn: 2, revision: 'a'.repeat(64), excerpt: 'The old task was approved.', allow_cloud: true } });
  expect(sentRequests[0].body).not.toHaveProperty('attachments');
  expect(sentRequests[0].headers['X-Admin-Token']).toBe('admin-token');
  await waitFor(() => expect(screen.getByRole('button', { name: 'Remove passage' })).toBeTruthy());
  expect(draft().value).toBe('What next?');
  expect(screen.queryByText('Busy')).toBeNull();
  // the draft stays in the composer (a textarea since the re-lay, whose text is its value): the
  // refused turn must not be in the transcript
  expect(within(screen.getByRole('log')).queryByText('What next?')).toBeNull();
  fireEvent.change(draft(), { target: { value: 'What after source?' } });
  fireEvent.click(screen.getByRole('button', { name: /transmit|send/i }));
  await waitFor(() => expect(sentRequests).toHaveLength(2));
  await screen.findByText('Done');
  expect(screen.getByText('What after source?')).toBeTruthy();
  expect(screen.getAllByText('Done')).toHaveLength(1);
});
