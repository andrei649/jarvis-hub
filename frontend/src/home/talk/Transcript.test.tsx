/* The Ledger transcript (PHASE_B_PLAN.md §5.3, §1.3): one labelled, focusable log region; turns
   carry data-turn="owner|reply|system|vision" and their words data-turn-body; a reply of this tab
   in flight is the working reply, a stopped one is drawn as far as it was written; each finished
   reply has its footnote, slip and action budget; there is no other transcript since the stage 5
   cleanup deleted the classic one. */
import React from 'react';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Conversation } from '../../cockpit';
import { V2 } from '../../data';
import type { TalkMessage } from './types';

beforeEach(() => {
  HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({})));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const roster = [{ id: 'jarvis', name: 'Jarvis', rosterSource: 'api' }, { id: 'stark', name: 'Stark', rosterSource: 'api' }];
const asked = new Date(2026, 10, 23, 10, 48).getTime();
const base = [
  { role: 'user', text: 'Morning Jarvis — what does my day look like?\nAnd the weather?', ts: '08:02' },
  { role: 'agent', who: 'jarvis', role_label: 'Prime Orchestrator', ts: '08:02', text: 'Good morning. **Three** meetings today.',
    _turnId: 1, _complete: true, prov: { models: [{ provider: 'ollama', model: 'gemma-4-31b' }] },
    tools: [{ key: 'c1', tool: 'web_search', state: 'done', event: 'tool_result' }], approvals: [17] },
  { role: 'agent', who: 'system', ts: '08:03', text: '⚠ The board source was not used.' },
  { role: 'vision', ts: '08:04', text: 'A screenshot of a chart.', model: 'vision-test', backend: 'custom', destination: 'http://127.0.0.1:1234/v1', local: true, warning: 'Low resolution' },
] as TalkMessage[];

function draw(messages: TalkMessage[], extra: Record<string, unknown> = {}) {
  return render(<Conversation messages={messages} thinking={null} onStop={vi.fn()} onProv={vi.fn()} lang="en" t={V2.I18N.en}
    messageScope="jarvis:s" messageActionsAllowed exportAllowed onArtifactSaved={vi.fn()} variant="home" turns={[]} agents={roster} {...extra} />);
}
const turns = () => Array.from(document.querySelectorAll('[data-turn]')) as HTMLElement[];
const body = (turn: HTMLElement) => (turn.querySelector('[data-turn-body]') as HTMLElement).textContent;
/** A control's visible words: a menu holder's are its button's (its panel stays mounted, hidden). */
const label = (node: Element) => ((node.matches('[data-talk-menu]') ? node.firstElementChild : node)?.textContent || '').trim();

describe('the log region', () => {
  it('is one labelled, focusable log with a hook on every turn and its words', () => {
    draw(base);
    const log = screen.getByRole('log', { name: 'Conversation transcript' });
    expect(log.tabIndex).toBe(0);
    expect(log.hasAttribute('data-transcript')).toBe(true);
    expect(document.querySelector('.convo')).toBeNull();
    expect(document.querySelectorAll('.msg, .bubble')).toHaveLength(0);
    expect(turns().map((turn) => turn.getAttribute('data-turn'))).toEqual(['owner', 'reply', 'system', 'vision']);
    const [owner, reply, system, vision] = turns();
    expect(body(owner)).toBe('Morning Jarvis — what does my day look like?\nAnd the weather?');
    expect(owner.querySelector('.n-turn__who')?.textContent).toBe('You');
    expect(owner.querySelector('time')?.textContent).toBe('08:02');
    expect(body(reply)).toBe('Good morning. Three meetings today.');
    expect(reply.querySelector('[data-turn-body] strong')?.textContent).toBe('Three');
    expect(reply.querySelector('.n-turn__who')?.textContent).toBe('Jarvis');
    expect(reply.querySelector('.n-turn__who')?.getAttribute('title')).toBe('Jarvis — Prime Orchestrator');
    expect(system.querySelector('.n-turn__who')?.textContent).toBe('System');
    expect(body(system)).toBe('⚠ The board source was not used.');
    // the narrow who column takes the short word; the full name is its title
    expect(vision.querySelector('.n-turn__who')?.textContent).toBe('Vision');
    expect(vision.querySelector('.n-turn__who')?.getAttribute('title')).toBe('Vision analysis');
    expect(vision.querySelector('.n-turn__ran')?.textContent).toBe('vision-test · custom · http://127.0.0.1:1234/v1 · loopback');
    expect(vision.querySelector('.n-turn__warn')?.textContent).toBe('Low resolution');
  });

  // The classic `.convo` bubbles were deleted with ChatMode at the stage 5 cleanup (PHASE_B_PLAN.md
  // §9.3, §8.3): a transcript drawn without a variant is the Ledger's.
  it('draws the Ledger transcript when no variant is given, never the classic bubbles', () => {
    render(<Conversation messages={base} thinking={null} lang="en" t={V2.I18N.en} />);
    const log = screen.getByRole('log', { name: 'Conversation transcript' });
    expect(log.hasAttribute('data-transcript')).toBe(true);
    expect(log.classList.contains('convo')).toBe(false);
    expect(document.querySelectorAll('.convo, .msg, .bubble')).toHaveLength(0);
    expect(turns().map((turn) => turn.getAttribute('data-turn'))).toEqual(['owner', 'reply', 'system', 'vision']);
  });
});

describe('a finished reply', () => {
  it('carries its footnote, its slip and the action budget on the newest reply', () => {
    draw(base);
    const reply = turns()[1];
    expect(reply.hasAttribute('data-newest')).toBe(true);
    expect(reply.querySelector('[data-footnote]')?.getAttribute('data-marker')).toBe('localRunner');
    expect(within(reply).getByRole('note').hasAttribute('data-slip')).toBe(true);
    const acts = within(reply).getByRole('group', { name: 'Actions for this reply' });
    expect(Array.from(acts.children).map(label)).toEqual(['Copy', '⬒ save', 'Read aloud', 'Create task', 'More']);
    const more = reply.querySelector('[data-talk-menu="more"]') as HTMLElement;
    fireEvent.click(within(more).getByRole('button', { name: 'More actions for this reply' }));
    expect(within(more).getAllByRole('button').slice(1).map((node) => node.textContent)).toEqual(
      ['Download Word', 'Photoshop', 'Save to Obsidian', 'Teach skill']);
  });

  it('opens a dialog from More with the More button as its opener', () => {
    draw(base);
    const more = turns()[1].querySelector('[data-talk-menu="more"]') as HTMLElement;
    const button = within(more).getByRole('button', { name: 'More actions for this reply' });
    fireEvent.click(button);
    fireEvent.click(within(more).getByRole('button', { name: 'Teach skill' }));
    expect(more.querySelector('[role="group"]')?.hasAttribute('hidden')).toBe(true);
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(document.activeElement === button || screen.getByRole('dialog').contains(document.activeElement)).toBe(true);
  });

  it('copies the reply text and says so', async () => {
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    draw(base);
    fireEvent.click(within(turns()[1]).getByRole('button', { name: 'Copy' }));
    expect(writeText).toHaveBeenCalledExactlyOnceWith('Good morning. **Three** meetings today.');
    expect(await within(turns()[1]).findByRole('button', { name: 'Copied' })).toBeTruthy();
  });

  it('moves the turn\'s outcome lines into Turn details on the newest reply', () => {
    draw(base, { outcome: { latency_ms: 1250 } });
    expect(screen.queryByLabelText('Turn duration')).toBeNull();
    const more = turns()[1].querySelector('[data-talk-menu="more"]') as HTMLElement;
    fireEvent.click(within(more).getByRole('button', { name: 'More actions for this reply' }));
    fireEvent.click(within(more).getByRole('button', { name: 'Turn details' }));
    expect(screen.getByLabelText('Turn duration').textContent).toContain('1.25 s');
    expect(turns()[1].querySelector('[data-turn-details]')).toBeTruthy();
  });

  it('names the full agent in the who column\'s title', () => {
    draw([{ role: 'agent', who: 'longname', ts: '09:00', text: 'Hi.', _turnId: 1, _complete: true } as TalkMessage],
      { agents: [{ id: 'longname', name: 'Aurelian the Archivist', rosterSource: 'api' }] });
    const who = turns()[0].querySelector('.n-turn__who') as HTMLElement;
    expect(who.textContent).toBe('Aurelian the Archivist');
    expect(who.getAttribute('title')).toBe('Aurelian the Archivist');
  });

  it('gives an owner turn only More, with Remember message and Create task', () => {
    draw(base);
    const owner = turns()[0];
    const acts = within(owner).getByRole('group', { name: 'Actions for your message' });
    fireEvent.click(within(acts).getByRole('button', { name: 'More actions for your message' }));
    expect(within(acts).getAllByRole('button').slice(1).map((node) => node.textContent)).toEqual(['Remember message', 'Create task']);
  });

  it('draws no action budget where actions are not allowed (demo), but keeps Copy and Read aloud', () => {
    render(<Conversation messages={base} thinking={null} lang="en" t={V2.I18N.en} variant="home" turns={[]} agents={roster} />);
    const reply = turns()[1];
    const acts = within(reply).getByRole('group', { name: 'Actions for this reply' });
    expect(Array.from(acts.children).map(label)).toEqual(['Copy', 'Read aloud']);
    expect(within(turns()[0]).queryByRole('group', { name: 'Actions for your message' })).toBeNull();
  });
});

describe('replies in flight', () => {
  const working = { role: 'agent', who: 'stark', ts: '10:51', text: 'Trei proiecte', _turnId: 2, _askedAt: asked, _startedAt: asked + 1, _firstTokenAt: asked + 2 } as TalkMessage;

  it('draws a reply this tab has in flight as the working reply, with its streamed words', () => {
    draw([...base, { role: 'user', text: 'Ce proiecte?', ts: '10:48' } as TalkMessage, working],
      { turns: [{ turnId: 2, agent: 'stark', askedAt: asked, startedAt: asked + 1, firstTokenAt: asked + 2 }] });
    const reply = turns()[5];
    expect(reply.hasAttribute('data-working')).toBe(true);
    expect(reply.querySelector('[data-working]')).toBeTruthy();
    expect(body(reply)).toBe('Trei proiecte');
    expect(reply.querySelector('[data-footnote]')).toBeNull();
    expect(within(reply).queryByRole('group', { name: 'Actions for this reply' })).toBeNull();
    expect(within(reply).getByRole('button', { name: 'Stop this reply' })).toBeTruthy();
    expect(reply.querySelector('[data-step="started"]')?.textContent).toContain('Started — asked Stark');
    // the newest finished reply keeps the action budget at rest
    expect(turns()[1].hasAttribute('data-newest')).toBe(true);
  });

  it('carries one stop on the newest of several, reading "Stop the replies"', () => {
    const second = { ...working, _turnId: 3, text: '' } as TalkMessage;
    draw([working, second], { turns: [
      { turnId: 2, agent: 'stark', askedAt: asked, startedAt: null, firstTokenAt: null },
      { turnId: 3, agent: 'stark', askedAt: asked, startedAt: null, firstTokenAt: null }] });
    expect(screen.getAllByRole('button', { name: 'Stop the replies' })).toHaveLength(1);
    expect(turns()[1].contains(screen.getByRole('button', { name: 'Stop the replies' }))).toBe(true);
  });

  it('draws a stopped reply as far as it was written, and drops one stopped before any word', () => {
    draw([working, { ...working, _turnId: 3, text: '' } as TalkMessage], { turns: [] });
    expect(turns()).toHaveLength(1);
    expect(turns()[0].hasAttribute('data-working')).toBe(false);
    expect(body(turns()[0])).toBe('Trei proiecte');
    expect(turns()[0].querySelector('[data-footnote]')?.getAttribute('data-marker')).toBe('notReported');
  });

  it('waits honestly for a turn without a reply bubble (a vision analysis) and offers the stop', () => {
    const stop = vi.fn();
    draw(base, { thinking: { label: 'Vision analysis', route: null }, onStop: stop });
    const pending = document.querySelector('[data-pending]') as HTMLElement;
    expect(pending.querySelector('.n-turn__who')?.textContent).toBe('Vision');
    expect(pending.querySelector('.n-turn__who')?.getAttribute('title')).toBe('Vision analysis');
    fireEvent.click(within(pending).getByRole('button', { name: 'Stop this reply' }));
    expect(stop).toHaveBeenCalledOnce();
  });

  it('reads "Waiting for your answer" while a question from this tab is open', () => {
    draw([working], { turns: [{ turnId: 2, agent: 'stark', askedAt: asked, startedAt: asked + 1, firstTokenAt: asked + 2 }], awaitingAnswer: true });
    expect(document.querySelector('[data-working-status]')?.textContent).toBe('Waiting for your answer');
  });

  it('draws the wait on the turn that asked, and on no reply when it cannot tell which one did', () => {
    const second = { role: 'agent', who: 'stark', ts: '10:51', text: '', _turnId: 3, _askedAt: asked, _startedAt: asked + 1 } as TalkMessage;
    const both = [
      { turnId: 2, agent: 'stark', askedAt: asked, startedAt: asked + 1, firstTokenAt: asked + 2 },
      { turnId: 3, agent: 'stark', askedAt: asked, startedAt: asked + 1, firstTokenAt: null }];
    const view = draw([working, second], { turns: both, awaitingAnswer: 2 });
    const status = () => Array.from(document.querySelectorAll('[data-working-status]')).map((node) => node.textContent);
    expect(status()).toEqual(['Waiting for your answer', 'Started — waiting for the first words…']);
    view.rerender(<Conversation messages={[working, second]} thinking={null} onStop={vi.fn()} onProv={vi.fn()} lang="en" t={V2.I18N.en}
      variant="home" turns={both} agents={roster} awaitingAnswer />);
    expect(status()).toEqual(['Writing — 2 words so far', 'Started — waiting for the first words…']);
  });
});

/* App's `outcome` is the outcome of App's newest turn (runTurn clears it when a turn starts; that
   turn's outcome_progress and end frames set it), so it belongs to that turn's reply alone. */
describe('whose outcome', () => {
  const owner = (text: string) => ({ role: 'user', text, ts: '10:40' }) as TalkMessage;
  const one = { role: 'agent', who: 'jarvis', ts: '10:40', text: 'Turn one, written.', _turnId: 1, _complete: true } as TalkMessage;
  const twoInFlight = { role: 'agent', who: 'jarvis', ts: '10:48', text: '', _turnId: 2, _askedAt: asked, _startedAt: asked + 1 } as TalkMessage;
  const twoTurn = { turnId: 2, agent: 'jarvis', askedAt: asked, startedAt: asked + 1, firstTokenAt: null };
  const outcome = { latency_ms: 4321, model: 'turn-two-model',
    usage_detail: { input_tokens: 0, output_tokens: 0, estimated_cost_usd: 0, usage_basis: 'measured_zero', cost_basis: 'measured_zero' } };
  const rerender = (view: ReturnType<typeof draw>, messages: TalkMessage[], extra: Record<string, unknown> = {}) =>
    view.rerender(<Conversation messages={messages} thinking={null} onStop={vi.fn()} onProv={vi.fn()} lang="en" t={V2.I18N.en}
      messageScope="jarvis:s" messageActionsAllowed exportAllowed onArtifactSaved={vi.fn()} variant="home" turns={[]} agents={roster}
      outcome={outcome} {...extra} />);
  const moreItems = (turn: HTMLElement) => {
    const more = turn.querySelector('[data-talk-menu="more"]') as HTMLElement | null;
    if (!more) return [];
    fireEvent.click(within(more).getByRole('button', { name: /^More actions/ }));
    const items = within(more).getAllByRole('button').slice(1).map((node) => node.textContent);
    fireEvent.click(within(more).getByRole('button', { name: /^More actions/ }));
    return items;
  };

  it('never draws the newest turn\'s outcome on an earlier reply while that turn is in flight', () => {
    draw([owner('one'), one, owner('two'), twoInFlight], { outcome, turns: [twoTurn] });
    const first = turns()[1];
    // turn one had no model-call receipt: "not reported", never turn two's "No model call"
    expect(first.querySelector('[data-footnote]')?.getAttribute('data-marker')).toBe('notReported');
    expect(first.textContent).not.toContain('No model call');
    expect(moreItems(first)).not.toContain('Turn details');
    expect(screen.queryByLabelText('Turn duration')).toBeNull();
    expect(document.body.textContent).not.toContain('Turn usage');
    // the working reply of turn two reports the model it was told about
    expect(turns()[3].querySelector('[data-working-where]')?.textContent).toBe('model turn-two-model (reported)');
  });

  it('gives the outcome to its own reply, even one written empty, and keeps it off the earlier one', () => {
    const view = draw([owner('one'), one, owner('two'), twoInFlight], { outcome, turns: [twoTurn] });
    rerender(view, [owner('one'), one, owner('two'), { ...twoInFlight, _complete: true } as TalkMessage]);
    const [, first, , second] = turns();
    expect(first.querySelector('[data-footnote]')?.getAttribute('data-marker')).toBe('notReported');
    expect(moreItems(first)).not.toContain('Turn details');
    expect(second.querySelector('[data-footnote]')?.getAttribute('data-marker')).toBe('noModelCall');
    // an empty reply has nothing to copy or read, but its turn's details stay reachable
    const acts = within(second).getByRole('group', { name: 'Actions for this reply' });
    expect(within(acts).queryByRole('button', { name: 'Copy' })).toBeNull();
    expect(second.hasAttribute('data-newest')).toBe(true);
    const more = second.querySelector('[data-talk-menu="more"]') as HTMLElement;
    fireEvent.click(within(more).getByRole('button', { name: 'More actions for this reply' }));
    fireEvent.click(within(more).getByRole('button', { name: 'Turn details' }));
    expect(screen.getByLabelText('Turn duration').textContent).toContain('4.32 s');
    expect(second.querySelector('[data-turn-details]')).toBeTruthy();
  });

  it('keeps the outcome off every reply when its turn\'s bubble was removed (a source the hub did not use)', () => {
    const view = draw([owner('one'), one, owner('two'), twoInFlight], { outcome, turns: [twoTurn] });
    rerender(view, [owner('one'), one, { role: 'agent', who: 'system', ts: '10:49', text: '⚠ The board source was not used.' } as TalkMessage]);
    const first = turns()[1];
    expect(first.querySelector('[data-footnote]')?.getAttribute('data-marker')).toBe('notReported');
    expect(moreItems(first)).not.toContain('Turn details');
    expect(document.body.textContent).not.toContain('No model call');
  });

  it('follows App when it names the outcome\'s turn', () => {
    const view = draw([owner('one'), one], { outcome, outcomeTurnId: 7 });
    expect(turns()[1].querySelector('[data-footnote]')?.getAttribute('data-marker')).toBe('notReported');
    rerender(view, [owner('one'), one], { outcomeTurnId: 1 });
    expect(turns()[1].querySelector('[data-footnote]')?.getAttribute('data-marker')).toBe('noModelCall');
    rerender(view, [owner('one'), one], { outcomeTurnId: null });
    expect(turns()[1].querySelector('[data-footnote]')?.getAttribute('data-marker')).toBe('notReported');
  });
});

describe('the floating window', () => {
  it('hands the slip the floating variant, so it never navigates in place', () => {
    draw(base, { variant: 'floating' });
    const slip = within(turns()[1]).getByRole('note');
    // no desktop bridge in the test: its links load the full HUD (a full navigation)
    expect(slip.getAttribute('data-slip-mode')).toBe('navigate');
  });
});
