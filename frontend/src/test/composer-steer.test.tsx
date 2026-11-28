import React from 'react';
import { webcrypto } from 'node:crypto';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from '../app';
import { InputBar } from '../cockpit';

vi.mock('../voice', () => ({ useVoice: () => ({ active: false, toggle: () => {} }) }));
vi.mock('../mesh', () => ({ NeuralMesh: () => null, isExecutingAgent: () => false }));
vi.mock('../api/loaders', () => ({
  loadJarvisData: async () => ({}),
  createLatestRefreshRunner: () => ({ refresh: () => {}, stop: () => {} }),
}));
vi.mock('../api/live', () => ({ PREVIEW_MODE_LIVE_KEYS: {}, useLiveModes: () => ({ live: {} }) }));
vi.mock('../analytics', () => ({ initAnalytics: () => {}, trackPageview: () => {} }));
vi.mock('../gap', () => ({ FirstRunGate: () => null }));

const AGENTS = [
  { id: 'jarvis', name: 'Jarvis', enabled: true, chat_routing: 'orchestrated', rosterSource: 'api' as const },
];

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('Mid-turn composer Steer button (H395)', () => {
  it('shows Steer while a turn is active, calls onSteer, and clears the draft on success', async () => {
    const onSteer = vi.fn().mockResolvedValue(true);
    const onSubmit = vi.fn().mockReturnValue(true);

    const { rerender } = render(
      <InputBar
        onSubmit={onSubmit}
        onSteer={onSteer}
        turnActive={true}
        selectedTurn={true}
        recipientStatus="ready"
        agent="jarvis"
        agents={AGENTS as any}
        sessionId="sess_123"
        t={{ placeholder: 'Write to {agent}', transmit: 'Send' }}
        lang="en"
      />,
    );

    const textarea = screen.getByRole('textbox');
    expect(screen.queryByRole('button', { name: 'Steer' })).toBeNull();

    fireEvent.change(textarea, { target: { value: 'check src/core instead' } });
    const steerBtn = screen.getByRole('button', { name: 'Steer' });
    expect(steerBtn).toBeTruthy();

    fireEvent.click(steerBtn);
    await waitFor(() => expect(onSteer).toHaveBeenCalledWith('check src/core instead'));
    await waitFor(() => expect((textarea as HTMLTextAreaElement).value).toBe(''));
    expect(onSubmit).not.toHaveBeenCalled();

    // Slash commands do not show the plain-text Steer button.
    fireEvent.change(textarea, { target: { value: '/status' } });
    expect(screen.queryByRole('button', { name: 'Steer' })).toBeNull();

    // Once turnActive is false, Steer disappears.
    fireEvent.change(textarea, { target: { value: 'next question' } });
    rerender(
      <InputBar
        onSubmit={onSubmit}
        onSteer={onSteer}
        turnActive={false}
        selectedTurn={true}
        recipientStatus="ready"
        agent="jarvis"
        agents={AGENTS as any}
        sessionId="sess_123"
        t={{ placeholder: 'Write to {agent}', transmit: 'Send' }}
        lang="en"
      />,
    );
    expect(screen.queryByRole('button', { name: 'Steer' })).toBeNull();
  });

  it('targets the first live turn via X-Nerva-Turn-Id before session_id hydration completes', async () => {
    vi.stubGlobal('crypto', webcrypto);
    localStorage.clear();
    sessionStorage.clear();
    history.replaceState(null, '', '/v2/chat');

    const requests: Array<{ path: string; headers?: any; body?: any }> = [];
    let releaseStream: ((r: Response) => void) | null = null;
    let releaseMemory: ((r: Response) => void) | null = null;

    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input);
        requests.push({ path, headers: init?.headers, body: init?.body });
        if (path === '/memory') {
          return new Promise<Response>((resolve) => {
            releaseMemory = resolve;
          });
        }
        if (path === '/chat/stream') {
          return new Promise<Response>((resolve) => {
            releaseStream = resolve;
          });
        }
        if (path === '/chat/steer') {
          return new Response(JSON.stringify({ ok: true, status: 'queued', pending: 1 }), { status: 200 });
        }
        return new Response(JSON.stringify({ configured: false, revision: '0', preferences: {} }), { status: 200 });
      }),
    );

    render(<App />);
    await screen.findByLabelText('Attach images');
    const composer = document.querySelector('[data-composer]') as HTMLTextAreaElement;
    expect(composer).toBeTruthy();

    fireEvent.change(composer, { target: { value: 'inspect runtime loop' } });
    fireEvent.keyDown(composer, { key: 'Enter', code: 'Enter' });

    await waitFor(() => expect(requests.some((r) => r.path === '/chat/stream')).toBe(true));
    const streamReq = requests.find((r) => r.path === '/chat/stream')!;
    const turnIdHeader = streamReq.headers?.['X-Nerva-Turn-Id'];
    expect(turnIdHeader).toMatch(/^[0-9a-f]{32}$/);

    fireEvent.change(composer, { target: { value: 'preserve budget cap' } });
    const steerBtn = await screen.findByRole('button', { name: 'Steer' });
    fireEvent.click(steerBtn);

    await waitFor(() => expect(requests.some((r) => r.path === '/chat/steer')).toBe(true));
    const steerReq = requests.find((r) => r.path === '/chat/steer')!;
    expect(JSON.parse(String(steerReq.body))).toEqual({
      message: 'preserve budget cap',
      turn_id: turnIdHeader,
    });
    await screen.findByText('[Steer] preserve budget cap');

    await act(async () => {
      releaseStream?.(
        new Response('data: {"type":"end","text":"Done","agent":"jarvis","session_id":"sess_real"}\n\n'),
      );
      releaseMemory?.(new Response(JSON.stringify({ session: 'sess_real', turns: [] })));
    });
  });
});
