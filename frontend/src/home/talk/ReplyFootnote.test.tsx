/* The reply footnote (PHASE_B_PLAN.md §5.3; gap-5 §7.1): where the reply was SENT, from E3's
   replyMarker() (the least private pair, "+N more" opening the provenance modal, a cloud-named
   model's warning, "No model call", "not reported"), and what it called. */
import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ReplyFootnote } from './ReplyFootnote';
import type { TalkMessage } from './types';

afterEach(() => { cleanup(); });

const footnote = () => document.querySelector('[data-footnote]') as HTMLElement;
const where = () => footnote().querySelector('.n-footnote__where') as HTMLElement;
const reply = (extra: Partial<TalkMessage> = {}): TalkMessage => ({ role: 'agent', who: 'jarvis', text: 'Done.', _complete: true, ...extra });

describe('where it was sent', () => {
  it('says a local runner was sent the prompt and that where it ran is not verified', () => {
    render(<ReplyFootnote message={reply({ prov: { models: [{ provider: 'ollama', model: 'qwen-7b' }] } })} lang="en" />);
    expect(footnote().getAttribute('data-marker')).toBe('localRunner');
    expect(where().textContent).toBe('Sent to Ollama on this computer · qwen-7b · where it ran is not verified');
    expect(where().querySelector('[data-mark="here"]')).toBeTruthy();
    expect(where().getAttribute('data-basis')).toBe('measured');
    expect(screen.getByRole('group', { name: 'Where this reply ran and what it called' })).toBe(footnote());
  });

  it('shows the least private of several pairs and opens the provenance modal for the rest', () => {
    const prov = { models: [{ provider: 'ollama', model: 'qwen-7b' }, { provider: 'anthropic', model: 'claude-x' }, { provider: 'lm-studio', model: 'gemma' }] };
    const onProv = vi.fn();
    render(<ReplyFootnote message={reply({ prov })} onProv={onProv} lang="en" />);
    expect(footnote().getAttribute('data-marker')).toBe('cloud');
    expect(where().textContent).toBe('Sent to Anthropic (cloud) · claude-x+2 more');
    fireEvent.click(screen.getByRole('button', { name: 'Show all 3 model calls' }));
    expect(onProv).toHaveBeenCalledExactlyOnceWith(prov);
  });

  it('warns when a local runner\'s model id names a cloud model', () => {
    render(<ReplyFootnote message={reply({ prov: { models: [{ provider: 'ollama', model: 'gpt-oss:120b-cloud' }] } })} lang="en" />);
    expect(footnote().getAttribute('data-marker')).toBe('cloudName');
    const warning = footnote().querySelector('.n-footnote__warn') as HTMLElement;
    expect(warning.textContent).toContain('gpt-oss:120b-cloud');
    expect(warning.querySelector('[data-mark="attn"]')).toBeTruthy();
    expect(warning.getAttribute('title')).toContain('cannot see');
  });

  it('says "No model call" only for a measured zero, and "not reported" without a receipt', () => {
    const view = render(<ReplyFootnote message={reply()} outcome={{ usage_detail: { input_tokens: 0, output_tokens: 0,
      estimated_cost_usd: 0, usage_basis: 'measured_zero', cost_basis: 'measured_zero' } }} lang="en" />);
    expect(where().textContent).toBe('No model call');
    view.rerender(<ReplyFootnote message={reply()} lang="en" />);
    expect(footnote().getAttribute('data-marker')).toBe('notReported');
    expect(where().textContent).toBe('Where it ran: not reported');
    expect(where().querySelector('[data-mark="unknown"]')).toBeTruthy();
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('writes Romanian', () => {
    render(<ReplyFootnote message={reply()} lang="ro" />);
    expect(where().textContent).toBe('Unde a rulat: neraportat');
    expect(screen.getByRole('group', { name: 'Unde a rulat acest răspuns și ce a apelat' })).toBeTruthy();
  });
});

describe('what it called', () => {
  it('counts the calls and gives each its mark and word', () => {
    render(<ReplyFootnote lang="en" message={reply({ tools: [
      { key: 'c1', tool: 'web_search', state: 'done', event: 'tool_result' },
      { key: 'c2', tool: 'file_write', state: 'failed', event: 'tool_failed' },
    ] })} />);
    const tools = footnote().querySelector('[data-footnote-tools]') as HTMLElement;
    expect(tools.textContent).toBe('2 tool callsweb_searchdonefile_writefailed');
    expect(tools.querySelector('[data-state="done"] [data-mark="done"]')).toBeTruthy();
    expect(tools.querySelector('[data-state="failed"] [data-mark="problem"]')).toBeTruthy();
  });

  it('keeps the hub\'s recorded tool accounting', () => {
    render(<ReplyFootnote lang="en" message={reply({ toolActivity: { proposed: 1, queued: 0, executed: 1, failures: 0, basis: 'observed' } })} />);
    expect(screen.getByLabelText('Agent tool activity').textContent).toContain('Agent tool calls recorded: 1');
  });

  it('draws no tool line when the reply called nothing', () => {
    render(<ReplyFootnote lang="en" message={reply()} />);
    expect(footnote().querySelector('[data-footnote-tools]')).toBeNull();
  });
});
