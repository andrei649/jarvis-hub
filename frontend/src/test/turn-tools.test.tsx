/* H137 — tool cards and queued approvals inline with the reply in the browser chat. */
import React from 'react';
import { webcrypto } from 'node:crypto';
import { render, screen, act, cleanup, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../app';
import { approvalIds, mergeToolEvent } from '../turn-tools';

let submit: any;
vi.mock('../voice', () => ({ useVoice: () => ({ active: false, toggle: () => {} }) }));
vi.mock('../mesh', () => ({ NeuralMesh: () => null, isExecutingAgent: () => false }));
vi.mock('../api/loaders', () => ({ loadJarvisData: async () => ({}), createLatestRefreshRunner: () => ({ refresh: () => {}, stop: () => {} }) }));
vi.mock('../api/live', () => ({ PREVIEW_MODE_LIVE_KEYS: {}, useLiveModes: () => ({ live: {} }) }));
vi.mock('../analytics', () => ({ initAnalytics: () => {}, trackPageview: () => {} }));
vi.mock('../gap', () => ({ FirstRunGate: () => null }));
vi.mock('../modes3', async () => {
  const { Conversation, InputBar } = await import('../cockpit');
  return { ChatMode: (props: any) => { submit = props.onSubmit; return <><Conversation {...props} /><InputBar onSubmit={props.onSubmit} t={props.t} /></>; } };
});

const frame = (o: any) => `data: ${JSON.stringify(o)}\n\n`;
let requests: any[] = [];

beforeEach(() => {
  vi.stubGlobal('crypto', webcrypto);
  localStorage.clear(); sessionStorage.clear(); history.replaceState(null, '', '/v2/chat'); requests = [];
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (path: string, init: any) => {
    requests.push({ path, ...init });
    if (path === '/chat/stream') {
      return new Response(
        frame({ type: 'start', agent: 'jarvis' })
        + frame({ type: 'tool', event: { event: 'tool_requested', tool: 'web_search', call_id: 'c1' } })
        + frame({ type: 'tool', event: { event: 'tool_started', tool: 'web_search', call_id: 'c1' } })
        + frame({ type: 'tool', event: { event: 'tool_requested', tool: 'file_write', call_id: 'c2' } })
        + frame({ type: 'tool', event: { event: 'tool_result', tool: 'web_search', call_id: 'c1', status: 'ok' } })
        + frame({ type: 'tool', event: { event: 'tool_failed', tool: 'file_write', call_id: 'c2' } })
        + frame({ type: 'tool', event: { event: 'tool_profile' } })
        + frame({ type: 'token', text: 'Searched.' })
        + frame({ type: 'end', text: 'Searched and asked.', agent: 'jarvis', pending_approvals: [17, 'x', -3, 18] }));
    }
    return new Response(JSON.stringify({ configured: false, revision: '0', preferences: {} }));
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('browser chat shows what the turn ran and what it queued', () => {
  it('asks for tool events, renders one card per call and lists the queued approvals', async () => {
    render(<App />);
    await act(async () => {});
    act(() => submit('look it up and save it'));
    await screen.findByText('Searched and asked.');
    expect(JSON.parse(requests.find((r) => r.path === '/chat/stream').body).tool_events).toBe(true);
    const list = screen.getByRole('list', { name: 'tools this turn ran' });
    const cards = within(list).getAllByRole('listitem');
    expect(cards).toHaveLength(2);
    expect(cards[0].textContent).toContain('web_search');
    expect(cards[0].getAttribute('data-state')).toBe('done');
    expect(cards[1].textContent).toContain('file_write');
    expect(cards[1].getAttribute('data-state')).toBe('failed');
    const note = screen.getByRole('note');
    expect(note.textContent).toContain('2 actions wait');
    expect(note.textContent).toContain('card #17');
    expect(note.textContent).toContain('card #18');
    expect(note.textContent).not.toContain('#-3');
    expect(within(note).getByRole('link').getAttribute('href')).toContain('/v2/console/decision-inbox');
  });
});

describe('mergeToolEvent', () => {
  it('keeps a finished call finished on a late heartbeat and bounds the list', () => {
    let cards = mergeToolEvent([], { event: 'tool_result', tool: 't', call_id: 'a' });
    cards = mergeToolEvent(cards, { event: 'tool_heartbeat', tool: 't', call_id: 'a' });
    expect(cards[0].state).toBe('done');
    for (let i = 0; i < 40; i++) cards = mergeToolEvent(cards, { event: 'tool_started', tool: 't', call_id: `x${i}` });
    expect(cards.length).toBe(24);
    expect(mergeToolEvent(cards, null)).toBe(cards);
    expect(mergeToolEvent([], { event: 'tool_cap_reached', tool: 'loop', call_id: 'z' })[0].state).toBe('stopped');
  });
  it('approvalIds keeps positive integers only', () => {
    expect(approvalIds([1, '2', 0, 3.5, 4])).toEqual([1, 4]);
    expect(approvalIds(null)).toEqual([]);
  });
});
