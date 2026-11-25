/* TalkRegister (PHASE_B_PLAN.md §5.3, §2.1): the conversation register of Home and the chat page,
   and the floating window's conversation. The global approval mode is the shared hook's (mocked
   here); the recipient's own mode is read from GET /autonomy/policy through the shared poller. */
import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

const LIVE_AUTO = { state: 'live', value: { mode: 'auto' }, checkedAt: 1, lastGoodAt: 1 };
const mode = vi.hoisted(() => ({ asked: [] as unknown[], reading: null as any }));
vi.mock('../../signals/hooks', () => ({
  useApprovalMode: (opts: unknown) => { mode.asked.push(opts); return { ...mode.reading, refresh: async () => {} }; },
}));
const hub = vi.hoisted(() => ({ policy: null as unknown, status: 200, asked: 0 }));

import { TalkRegister } from './TalkRegister';
import { V2 } from '../../data';
import { resetPolling } from '../../signals/poll';
import type { TalkRegisterProps } from './types';
import { composerField } from './test-support';

const roster = [
  { id: 'jarvis', name: 'Jarvis', rosterSource: 'api', chat_routing: 'orchestrated', enabled: true, role: 'Prime Orchestrator' },
  { id: 'frigga', name: 'Frigga', rosterSource: 'api', chat_routing: 'local', enabled: true },
];
const messages = [
  { role: 'user', text: 'Hello', ts: '08:02' },
  { role: 'agent', who: 'jarvis', ts: '08:02', text: 'Good morning.', _turnId: 1, _complete: true },
];

function props(extra: Partial<TalkRegisterProps> = {}): TalkRegisterProps {
  return {
    messages, thinking: null, onStop: vi.fn(), onProv: vi.fn(), lang: 'en', t: V2.I18N.en, messageScope: 'jarvis:s',
    messageActionsAllowed: true, exportAllowed: true, onSubmit: vi.fn(() => true), agent: 'jarvis', agents: roster,
    recipientStatus: 'ready', sessionId: 's', selectedTurn: true, onSelectAgent: vi.fn(), variant: 'home', turns: [], ...extra,
  } as TalkRegisterProps;
}

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };
});
beforeEach(() => {
  resetPolling();
  mode.asked.length = 0;
  mode.reading = LIVE_AUTO;
  hub.policy = { global: 'auto', agents: {}, looser: {} };
  hub.status = 200;
  hub.asked = 0;
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (!String(url).includes('/autonomy/policy')) return Response.json({});
    hub.asked += 1;
    return Response.json(hub.policy, { status: hub.status });
  }));
});
afterEach(() => { cleanup(); resetPolling(); vi.unstubAllGlobals(); });
const modeOf = () => document.querySelector('[data-register="talk"] [data-mode]') as HTMLElement;

describe('Home and the chat page', () => {
  it('heads the register with the recipient, their role and the declared routing policy', () => {
    render(<TalkRegister {...props()} />);
    const register = document.querySelector('[data-register="talk"]') as HTMLElement;
    expect(within(register).getByRole('heading', { level: 2 }).textContent).toBe('Conversation');
    expect(register.querySelector('.n-talk__with')?.textContent).toBe('with Jarvis · Prime Orchestrator · Orchestrated');
    expect(register.querySelector('.n-talk__with b')?.textContent).toBe('Jarvis');
    expect(register.querySelector('.n-talk__policy')?.getAttribute('title')).toContain('Declared policy before sending');
  });

  it('holds the Ledger transcript and the composer with its picker, the mode and no outcome strip', async () => {
    render(<TalkRegister {...props({ outcome: { latency_ms: 40 } })} />);
    const register = document.querySelector('[data-register="talk"]') as HTMLElement;
    expect(within(register).getByRole('log').hasAttribute('data-transcript')).toBe(true);
    expect(register.querySelectorAll('[data-turn]')).toHaveLength(2);
    expect(register.contains(composerField())).toBe(true);
    expect(within(register).getByRole('combobox', { name: 'To' })).toBeTruthy();
    await waitFor(() => expect(modeOf().getAttribute('data-mode')).toBe('auto'));
    expect(modeOf().getAttribute('data-mode-source')).toBe('global');
    expect(mode.asked).toContainEqual({ demo: false });
    expect(register.querySelector('[data-composer-variant="home"]')).toBeTruthy();
    expect(screen.queryByLabelText('Turn outcome')).toBeNull();   // in the newest reply's Turn details instead
  });

  it('shows the recipient\'s own approval mode, as the hub resolves it', async () => {
    hub.policy = { global: 'ask', agents: { frigga: 'auto' }, looser: { frigga: 'auto' } };
    mode.reading = { ...LIVE_AUTO, value: { mode: 'ask' } };
    const view = render(<TalkRegister {...props({ agent: 'frigga' })} />);
    // the global dial says Ask, but Frigga runs on its own Auto: never "anything waits for you"
    await waitFor(() => expect(modeOf().getAttribute('data-mode')).toBe('auto'));
    expect(modeOf().getAttribute('data-mode-source')).toBe('agent');
    expect(modeOf().textContent).toBe('Mode Auto — each action is decided by its risk tier · Frigga’s own setting');
    // an agent without an override runs at the global mode
    view.rerender(<TalkRegister {...props({ agent: 'jarvis' })} />);
    expect(modeOf().getAttribute('data-mode')).toBe('ask');
    expect(modeOf().getAttribute('data-mode-source')).toBe('global');
  });

  it('keeps a global Off as the floor no override loosens', async () => {
    hub.policy = { global: 'off', agents: { frigga: 'auto' }, looser: {} };
    mode.reading = { ...LIVE_AUTO, value: { mode: 'off' } };
    render(<TalkRegister {...props({ agent: 'frigga' })} />);
    await waitFor(() => expect(hub.asked).toBeGreaterThan(0));
    await waitFor(() => expect(modeOf().getAttribute('data-mode')).toBe('off'));
    expect(modeOf().getAttribute('data-mode-source')).toBe('global');
  });

  it('does not guess the recipient\'s mode when the overrides cannot be read', async () => {
    hub.status = 403;
    hub.policy = { detail: 'admin token required' };
    const view = render(<TalkRegister {...props({ agent: 'frigga' })} />);
    await waitFor(() => expect(modeOf().getAttribute('data-mode')).toBe('unknown'));
    expect(modeOf().textContent).toBe('Mode unknown — needs the owner credential');
    // …except a global Off, the floor for everyone
    mode.reading = { ...LIVE_AUTO, value: { mode: 'off' } };
    view.rerender(<TalkRegister {...props({ agent: 'frigga' })} />);
    expect(modeOf().getAttribute('data-mode')).toBe('off');
  });

  it('opens the chat-history search from "Search earlier conversations", as the Options item does', () => {
    render(<TalkRegister {...props()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Search earlier conversations' }));
    expect(screen.getByRole('dialog', { name: 'Search chat history' })).toBeTruthy();
  });

  it('chooses the recipient through onSelectAgent, never the Dossier', () => {
    const select = vi.fn();
    render(<TalkRegister {...props({ onSelectAgent: select })} />);
    fireEvent.change(screen.getByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
    expect(select).toHaveBeenCalledExactlyOnceWith('frigga');
  });

  it('labels demo, and offers no search of saved conversations there', () => {
    render(<TalkRegister {...props({ demo: true, selectedTurn: false, agents: [] })} />);
    const register = document.querySelector('[data-register="talk"]') as HTMLElement;
    expect(register.querySelector('.n-talk__with')?.textContent).toBe('with Jarvis · Prime Orchestrator · Demo sample');
    expect(screen.queryByRole('button', { name: 'Search earlier conversations' })).toBeNull();
    expect(mode.asked).toContainEqual({ demo: true });
  });

  it('says a recipient the roster does not offer is unavailable', () => {
    render(<TalkRegister {...props({ agent: 'ghost' })} />);
    expect(document.querySelector('.n-talk__with')?.textContent).toBe('with Ghost · Unavailable');
  });

  // The fixture hub, or a hub whose /api/agents did not answer: the roster is built from /status and
  // the seed, so nothing says what policy an agent declared — which is not "Unavailable".
  it('says the policy is not known, never "Unavailable", when the hub did not serve the roster', () => {
    const seed = [{ id: 'jarvis', name: 'Jarvis', role: 'Prime Orchestrator' }, { id: 'frigga', name: 'Frigga' }];
    const view = render(<TalkRegister {...props({ agents: seed as any })} />);
    const policyEl = () => document.querySelector('.n-talk__policy') as HTMLElement;
    expect(document.querySelector('.n-talk__with')?.textContent).toBe('with Jarvis · Routing policy unknown');
    expect(policyEl().getAttribute('data-policy')).toBe('not-served');
    expect(policyEl().getAttribute('title')).toBe('The hub did not serve the agent roster, so the declared routing policy is not known.');
    view.rerender(<TalkRegister {...props({ agents: seed as any, lang: 'ro', t: V2.I18N.ro })} />);
    expect(document.querySelector('.n-talk__with')?.textContent).toBe('cu Jarvis · Politica de rutare necunoscută');
    // a served roster keeps its words, and its "Unavailable" for an agent it does not offer
    view.rerender(<TalkRegister {...props()} />);
    expect(policyEl().getAttribute('data-policy')).toBeNull();
    expect(policyEl().getAttribute('title')).toContain('Declared policy before sending');
  });

  it('draws the To\'s question App keeps, and hands the answer to App', () => {
    const answer = vi.fn();
    const select = vi.fn();
    render(<TalkRegister {...props({ onSelectAgent: select, onRecipientSwitch: answer,
      recipientSwitch: { id: 'frigga', from: 'jarvis', demo: false, at: 1 } })} />);
    expect(screen.getByRole('alert').textContent).toContain('The reply from Jarvis has ended. Write to Frigga?');
    fireEvent.click(screen.getByRole('button', { name: 'Write to Frigga' }));
    expect(answer).toHaveBeenCalledExactlyOnceWith(null);
    expect(select).toHaveBeenCalledExactlyOnceWith('frigga');
  });

  it('says when there is no recipient, never "with  · Unavailable", and hands the reason to the composer', () => {
    const view = render(<TalkRegister {...props({ agent: '', recipientStatus: 'checking' })} />);
    const withLine = () => document.querySelector('.n-talk__with') as HTMLElement;
    expect(withLine().textContent).toBe('checking the selected agent…');
    expect(withLine().getAttribute('data-recipient-state')).toBe('checking');
    expect(document.querySelector('.n-talk__policy')).toBeNull();
    view.rerender(<TalkRegister {...props({ agent: '', recipientStatus: 'choose', recipientRefusal: { reason: 'unavailable', agent: 'frigga' } })} />);
    expect(withLine().textContent).toBe('no agent chosen');
    expect(withLine().getAttribute('data-recipient-state')).toBe('none');
    expect(document.querySelector('[data-recipient-reason="unavailable"]')?.textContent)
      .toBe('Frigga is not available now. Nothing is sent until you choose who to write to.');
    view.rerender(<TalkRegister {...props({ agent: '', recipientStatus: 'choose', lang: 'ro', t: V2.I18N.ro })} />);
    expect(withLine().textContent).toBe('niciun agent ales');
    // the composer's own sentence, starting in lower case: one wording in each language
    view.rerender(<TalkRegister {...props({ agent: '', recipientStatus: 'checking', lang: 'ro', t: V2.I18N.ro })} />);
    expect(withLine().textContent).toBe('se verifică agentul selectat…');
    expect(document.querySelector('[data-recipient-state="checking"].n-composer__recipient')?.textContent).toBe('Se verifică agentul selectat…');
    // an agent App still holds but will not send to is not named as the one written to
    view.rerender(<TalkRegister {...props({ agent: 'frigga', recipientStatus: 'choose', recipientRefusal: { reason: 'signin' } })} />);
    expect(withLine().textContent).toBe('no agent chosen');
    view.rerender(<TalkRegister {...props({ agent: 'frigga', recipientStatus: 'checking' })} />);
    expect(withLine().textContent).toBe('checking the selected agent…');
  });

  // A selected agent App keeps but cannot confirm (a poll completed without the hub's roster): named
  // "not confirmed", the composer's sentence in the tooltip, never "checking" for good
  it('names a selected agent the roster could not confirm as not confirmed, with the reason in its tooltip', () => {
    const seed = [{ id: 'jarvis', name: 'Jarvis' }, { id: 'frigga', name: 'Frigga' }];
    const SENTENCE = 'The hub did not serve the agent roster, so Frigga Allmother cannot be confirmed until it does. Nothing is sent until then, unless you choose Jarvis.';
    const view = render(<TalkRegister {...props({ agent: '', agents: seed as any, recipientStatus: 'checking',
      recipientHold: { agent: 'frigga', name: 'Frigga Allmother' } })} />);
    const withLine = () => document.querySelector('.n-talk__with') as HTMLElement;
    expect(withLine().textContent).toBe('with Frigga Allmother · not confirmed');
    expect(withLine().getAttribute('data-recipient-state')).toBe('unconfirmed');
    expect(document.querySelector('.n-talk__unconfirmed')?.getAttribute('title')).toBe(SENTENCE);
    // the composer says it, the To names her and offers Jarvis
    expect(document.querySelector('.n-composer__recipient')?.textContent).toBe(SENTENCE);
    expect(Array.from((screen.getByRole('combobox', { name: 'To' }) as HTMLSelectElement).options).map((o) => o.textContent))
      .toEqual(['Frigga Allmother · not confirmed', 'Jarvis · Routing policy unknown']);
    view.rerender(<TalkRegister {...props({ agent: 'frigga', agents: seed as any, recipientStatus: 'checking', lang: 'ro', t: V2.I18N.ro,
      recipientHold: { agent: 'frigga' } })} />);
    expect(withLine().textContent).toBe('cu Frigga · neconfirmat');
    // while it is still being checked (no poll has completed), it says so
    view.rerender(<TalkRegister {...props({ agent: '', agents: seed as any, recipientStatus: 'checking', recipientHold: null })} />);
    expect(withLine().textContent).toBe('checking the selected agent…');
  });

  it('hands the line about a dropped question to the composer, and its Dismiss to App', () => {
    const dismiss = vi.fn();
    render(<TalkRegister {...props({ recipientSwitch: null, onRecipientSwitch: vi.fn(),
      recipientSwitchDropped: { id: 'frigga', from: 'jarvis', demo: false }, onRecipientSwitchDropped: dismiss })} />);
    const line = document.querySelector('[data-recipient-dropped="frigga"]') as HTMLElement;
    expect(line.textContent).toContain('Frigga is not available now, so the change to Frigga was dropped. Messages still go to Jarvis.');
    fireEvent.click(within(line).getByRole('button', { name: 'Dismiss' }));
    expect(dismiss).toHaveBeenCalledOnce();
  });

  it('writes Romanian', () => {
    render(<TalkRegister {...props({ lang: 'ro', t: V2.I18N.ro })} />);
    const register = document.querySelector('[data-register="talk"]') as HTMLElement;
    expect(within(register).getByRole('heading', { level: 2 }).textContent).toBe('Conversație');
    expect(register.querySelector('.n-talk__with')?.textContent).toBe('cu Jarvis · Prime Orchestrator · Orchestrat');
    expect(screen.getByRole('button', { name: 'Caută în conversațiile anterioare' })).toBeTruthy();
  });

  it('derives "a reply is in flight" for the picker when App does not pass turnActive', () => {
    const select = vi.fn();
    render(<TalkRegister {...props({ onSelectAgent: select, turns: [{ turnId: 9, agent: 'jarvis', askedAt: 1, startedAt: null, firstTokenAt: null }] })} />);
    fireEvent.change(screen.getByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
    expect(select).not.toHaveBeenCalled();
    expect(screen.getByRole('alert').textContent).toContain('stops the reply in progress');
  });
});

describe('the floating window', () => {
  it('is the conversation alone: no register head, the transcript and a compact composer', () => {
    render(<TalkRegister {...props({ variant: 'floating' })} />);
    const talk = document.querySelector('[data-register="talk"]') as HTMLElement;
    expect(talk.tagName).toBe('SECTION');
    expect(talk.getAttribute('aria-label')).toBe('Conversation');
    expect(within(talk).queryByRole('heading')).toBeNull();
    expect(talk.querySelector('.n-talk__with')).toBeNull();
    expect(within(talk).getByRole('log', { name: 'Conversation transcript' })).toBeTruthy();
    expect(talk.querySelectorAll('[data-turn]')).toHaveLength(2);
    expect(talk.querySelector('[data-composer-variant="floating"]')).toBeTruthy();
    expect(talk.contains(composerField())).toBe(true);
    expect(within(talk).getByRole('combobox', { name: 'To' })).toBeTruthy();
    // signing stays in the main window: nothing here decides
    expect(within(talk).queryByRole('button', { name: /^Sign/ })).toBeNull();
  });

  it('keeps the working reply and its stop', () => {
    const stop = vi.fn();
    const inFlight = { role: 'agent', who: 'jarvis', ts: '10:51', text: '', _turnId: 4, _askedAt: Date.now() };
    render(<TalkRegister {...props({ variant: 'floating', onStop: stop, messages: [...messages, inFlight],
      turns: [{ turnId: 4, agent: 'jarvis', askedAt: Date.now(), startedAt: null, firstTokenAt: null }] })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Stop this reply' }));
    expect(stop).toHaveBeenCalledOnce();
  });
});
