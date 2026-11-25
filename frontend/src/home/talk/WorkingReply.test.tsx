/* The working reply (PHASE_B_PLAN.md §5.3, §9.4 E5): steps from the three stamps, the tools and
   the writing; the elapsed time; the stop label. Never the routed steps the stream does not report. */
import React from 'react';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PendingReply, WorkingReply, elapsedWords, wordCount } from './WorkingReply';
import type { TalkMessage } from './types';

afterEach(() => { cleanup(); });

const asked = new Date(2026, 10, 23, 10, 48, 0).getTime();
const reply = (extra: Partial<TalkMessage> = {}): TalkMessage => ({ role: 'agent', who: 'jarvis', text: '', _turnId: 7, _askedAt: asked, ...extra });
const steps = () => Array.from(document.querySelectorAll('[data-step]')).map((node) => `${node.getAttribute('data-step')}:${node.getAttribute('data-state')}`);
const status = () => document.querySelector('[data-working-status]')?.textContent;

function draw(message: TalkMessage, props: Partial<React.ComponentProps<typeof WorkingReply>> = {}) {
  return render(<WorkingReply message={message} agentName="Jarvis" inFlight={1} showStop latest lang="en" now={asked + 5_000}
    onStop={vi.fn()} {...props} />);
}

describe('steps from the stamps', () => {
  it('reads Sent, then waits for the agent asked to start', () => {
    draw(reply());
    expect(steps()).toEqual(['sent:done', 'started:now', 'writing:todo']);
    expect(screen.getByRole('list', { name: 'Steps of this reply' })).toBeTruthy();
    expect(document.querySelector('[data-step="started"]')?.textContent).toContain('Started — asked Jarvis');
    expect(document.querySelector('[data-step="started"]')?.getAttribute('aria-current')).toBe('step');
    expect(status()).toBe('Waiting for Jarvis to start…');
  });

  it('marks Started on the first start frame and waits for the first words', () => {
    draw(reply({ _startedAt: asked + 1_000 }));
    expect(steps()).toEqual(['sent:done', 'started:done', 'writing:now']);
    expect(status()).toBe('Started — waiting for the first words…');
  });

  it('counts the words once the first token arrived', () => {
    draw(reply({ _startedAt: asked + 1_000, _firstTokenAt: asked + 2_000, text: 'Trei proiecte au termene' }));
    expect(steps()).toEqual(['sent:done', 'started:done', 'writing:now']);
    expect(status()).toBe('Writing — 4 words so far');
    cleanup();
    draw(reply({ _startedAt: asked + 1_000, _firstTokenAt: asked + 2_000, text: 'Gata' }));
    expect(status()).toBe('Writing — 1 word so far');
  });

  it('falls back to this tab\'s turn record for a stamp the bubble does not carry', () => {
    draw(reply({ _askedAt: undefined }), { turn: { turnId: 7, agent: 'jarvis', askedAt: asked, startedAt: asked + 1_000, firstTokenAt: null } });
    expect(steps()).toEqual(['sent:done', 'started:done', 'writing:now']);
    expect(document.querySelector('[data-working-elapsed]')?.textContent).toBe('asked 10:48 · 5 s so far');
  });

  it('adds a Tools step only when tool cards exist, with each call\'s state as a mark and a word', () => {
    draw(reply({ _startedAt: asked + 1_000, tools: [
      { key: 'c1', tool: 'web_search', state: 'running', event: 'tool_started' },
      { key: 'c2', tool: 'file_write', state: 'failed', event: 'tool_failed' },
    ] }));
    expect(steps()).toEqual(['sent:done', 'started:done', 'tools:now', 'writing:todo']);
    expect(status()).toBe('Running web_search…');
    const tools = screen.getByRole('list', { name: 'Tools this reply is running' });
    expect(within(tools).getAllByRole('listitem').map((row) => [row.getAttribute('data-state'), row.textContent])).toEqual([
      ['running', 'web_searchrunning'], ['failed', 'file_writefailed'],
    ]);
    expect(tools.querySelector('[data-mark="work"]')).toBeTruthy();
    expect(tools.querySelector('[data-mark="problem"]')).toBeTruthy();
  });

  it('says how many tools run at once, names a requested one, and resumes writing when they finish', () => {
    const running = { key: 'a', tool: 'web_search', state: 'running' as const, event: 'tool_started' };
    draw(reply({ _startedAt: asked + 1, tools: [running, { ...running, key: 'b', tool: 'calendar' }, { ...running, key: 'c', tool: 'mail' }] }));
    expect(status()).toBe('Running web_search and 2 more…');
    cleanup();
    draw(reply({ _startedAt: asked + 1, tools: [{ key: 'a', tool: 'web_search', state: 'requested', event: 'tool_requested' }] }));
    expect(status()).toBe('Calling web_search…');
    cleanup();
    draw(reply({ _startedAt: asked + 1, _firstTokenAt: asked + 2, text: 'Found it', tools: [{ ...running, state: 'done' }] }));
    expect(steps()).toEqual(['sent:done', 'started:done', 'tools:done', 'writing:now']);
    expect(status()).toBe('Writing — 2 words so far');
  });

  it('waits for the owner\'s answer when a question from this turn is open', () => {
    draw(reply({ _startedAt: asked + 1 }), { awaitingAnswer: true });
    expect(status()).toBe('Waiting for your answer');
  });

  it('never draws the routed steps the stream does not report', () => {
    draw(reply({ _startedAt: asked + 1, _firstTokenAt: asked + 2, text: 'x' }));
    const text = document.querySelector('[data-working]')?.textContent || '';
    for (const word of ['Classify', 'Route', 'Gather', 'Synthesize', 'asking']) expect(text).not.toContain(word);
  });
});

describe('elapsed time, where it runs and the stop', () => {
  it('reads "asked 10:48 · 3 min so far" and ticks once a second while in flight', () => {
    vi.useFakeTimers();
    vi.setSystemTime(asked + 179_000);
    try {
      render(<WorkingReply message={reply()} agentName="Jarvis" inFlight={1} showStop latest lang="en" onStop={vi.fn()} />);
      expect(document.querySelector('[data-working-elapsed]')?.textContent).toBe('asked 10:48 · 2 min so far');
      act(() => { vi.advanceTimersByTime(1_000); });
      expect(document.querySelector('[data-working-elapsed]')?.textContent).toBe('asked 10:48 · 3 min so far');
      expect(document.querySelector('[data-working-elapsed] time')?.getAttribute('dateTime')).toBe(new Date(asked).toISOString());
    } finally { vi.useRealTimers(); }
  });

  it('formats seconds, minutes and hours', () => {
    expect(elapsedWords(42_000, 'en')).toBe('42 s');
    expect(elapsedWords(3 * 60_000 + 59_000, 'en')).toBe('3 min');
    expect(elapsedWords(65 * 60_000, 'ro')).toBe('1 h 5 min');
    expect(elapsedWords(-5, 'en')).toBe('0 s');
    expect(wordCount('  two   words ')).toBe(2);
    expect(wordCount(undefined)).toBe(0);
  });

  it('says where it runs is reported at the end, or names the model the live outcome reported', () => {
    const view = draw(reply({ _startedAt: asked + 1 }));
    expect(document.querySelector('[data-working-where]')?.textContent).toBe('where it runs is reported when the reply ends');
    view.rerender(<WorkingReply message={reply({ _startedAt: asked + 1 })} agentName="Jarvis" inFlight={1} showStop latest lang="en"
      now={asked + 5_000} outcome={{ model: 'gemma-4-31b' }} />);
    expect(document.querySelector('[data-working-where]')?.textContent).toBe('model gemma-4-31b (reported)');
    expect(document.querySelector('[data-working-where] code')?.textContent).toBe('gemma-4-31b');
    view.rerender(<WorkingReply message={reply({ _startedAt: asked + 1 })} agentName="Jarvis" inFlight={1} showStop latest={false} lang="en"
      now={asked + 5_000} outcome={{ model: 'gemma-4-31b' }} />);
    expect(document.querySelector('[data-working-where]')?.textContent).toBe('where it runs is reported when the reply ends');
  });

  it('offers one stop: "Stop this reply", or "Stop the replies" when the tab has more than one in flight', () => {
    const stop = vi.fn();
    const view = draw(reply(), { onStop: stop });
    fireEvent.click(screen.getByRole('button', { name: 'Stop this reply' }));
    expect(stop).toHaveBeenCalledOnce();
    view.rerender(<WorkingReply message={reply()} agentName="Jarvis" inFlight={2} showStop latest lang="en" now={asked} onStop={stop} />);
    expect(screen.getByRole('button', { name: 'Stop the replies' })).toBeTruthy();
    view.rerender(<WorkingReply message={reply()} agentName="Jarvis" inFlight={2} showStop={false} latest lang="en" now={asked} onStop={stop} />);
    expect(screen.queryByRole('button', { name: /Stop/ })).toBeNull();
  });

  it('is not a live region: its words change on every token', () => {
    draw(reply());
    expect(document.querySelector('[data-working]')?.getAttribute('aria-live')).toBe('off');
  });

  it('writes Romanian', () => {
    draw(reply({ _startedAt: asked + 1, _firstTokenAt: asked + 2, text: Array(20).fill('cuvânt').join(' ') }), { lang: 'ro', inFlight: 2 });
    expect(status()).toBe('Scrie — 20 de cuvinte până acum');
    expect(document.querySelector('[data-step="started"]')?.textContent).toContain('Început — l-ai întrebat pe Jarvis');
    expect(document.querySelector('[data-working-elapsed]')?.textContent).toBe('întrebat la 10:48 · 5 s până acum');
    expect(screen.getByRole('button', { name: 'Oprește răspunsurile' })).toBeTruthy();
  });
});

describe('a turn with no reply bubble', () => {
  it('waits honestly and still offers the stop', () => {
    const stop = vi.fn();
    render(<PendingReply who="Vision analysis" onStop={stop} lang="en" />);
    const turn = document.querySelector('[data-turn="reply"]') as HTMLElement;
    expect(turn.hasAttribute('data-pending')).toBe(true);
    expect(within(turn).getByText('Waiting for the reply…')).toBeTruthy();
    fireEvent.click(within(turn).getByRole('button', { name: 'Stop this reply' }));
    expect(stop).toHaveBeenCalledOnce();
  });
});
