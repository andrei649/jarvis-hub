/// <reference types="node" />
import React, { useState } from 'react';
import { BroadcastChannel } from 'node:worker_threads';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { notifyDesktopConversation, useDesktopConversation } from '../desktop';

beforeEach(() => {
  (window as any).__TAURI__ = { core: { invoke: vi.fn() } };
  vi.stubGlobal('BroadcastChannel', BroadcastChannel);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete (window as any).__TAURI__; });
const deliver = () => new Promise(resolve => setTimeout(resolve, 40));

it('overlapping native window turns converge after both finish without a focus event', async () => {
  let persisted: Array<{ role: string; content: string }> = [];
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ turns: persisted.slice() }) })));
  const finish: Record<string, () => Promise<void>> = {};
  function ChatWindow({ name }: { name: string }) {
    const [busy, setBusy] = useState(true);
    const [messages, setMessages] = useState<any[]>([]);
    useDesktopConversation(setMessages, busy, false);
    finish[name] = () => {
      setMessages([{ text: name }]);
      setBusy(false);
      return Promise.resolve().finally(notifyDesktopConversation);
    };
    return <output data-testid={name}>{messages.map(message => message.text).join('|')}</output>;
  }
  render(<><ChatWindow name="floating reply" /><ChatWindow name="main reply" /></>);
  persisted = [{ role: 'assistant', content: 'floating reply' }];
  await React.act(async () => { await finish['floating reply'](); await deliver(); });
  expect(screen.getByTestId('main reply').textContent).toBe('');
  persisted.push({ role: 'assistant', content: 'main reply' });
  await React.act(async () => { await finish['main reply'](); await deliver(); });
  await waitFor(() => {
    expect(screen.getByTestId('floating reply').textContent).toBe('floating reply|main reply');
    expect(screen.getByTestId('main reply').textContent).toBe('floating reply|main reply');
  });
});

it('coalesces busy invalidations into one refresh after returning idle', async () => {
  const fetch = vi.fn(async () => ({ ok: true, json: async () => ({ turns: [] }) }));
  vi.stubGlobal('fetch', fetch);
  const setMessages = vi.fn();
  function Window({ busy }: { busy: boolean }) { useDesktopConversation(setMessages, busy, false); return null; }
  const view = render(<Window busy />);
  await React.act(async () => {
    notifyDesktopConversation(); notifyDesktopConversation(); notifyDesktopConversation();
    await deliver();
  });
  expect(fetch).not.toHaveBeenCalled();
  view.rerender(<Window busy={false} />);
  await waitFor(() => expect(setMessages).toHaveBeenCalledWith([]));
  expect(fetch).toHaveBeenCalledTimes(1);
});
