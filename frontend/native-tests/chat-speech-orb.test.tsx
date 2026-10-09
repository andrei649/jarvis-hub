import React from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { ChatScreen } from '../../mobile/src/screens/ChatScreen';
import { records } from './support/storage';

const speech = vi.hoisted(() => {
  let state = { status: 'off' };
  const listeners = new Set<() => void>();
  return {
    getState: () => state,
    subscribe: (listener: () => void) => { listeners.add(listener); return () => listeners.delete(listener); },
    emit: (status: string) => { state = { status }; listeners.forEach(listener => listener()); },
    speak: vi.fn(), stop: vi.fn(),
  };
});
vi.mock('../../mobile/src/audio/tts', () => ({
  getSpeechState: speech.getState, subscribeSpeech: speech.subscribe,
  speak: speech.speak, stopSpeaking: speech.stop,
}));
vi.mock('../../mobile/src/components/VoiceOrb', () => ({
  VoiceOrb: ({ status, level }: { status: string; level?: number }) =>
    <div data-testid="speech-orb" data-status={status} data-level={level} />,
}));

const config = { baseUrl: 'https://hub.test', token: 'user', adminToken: 'owner' };
let server: ReturnType<typeof useServer>;
function Probe() { server = useServer(); return <ChatScreen onGoToSettings={() => {}} />; }
const mount = () => render(<ServerProvider><Probe /></ServerProvider>);

beforeEach(() => {
  records.clear();
  records.set('jarvis.server.config.v1', JSON.stringify({ version: 2, config, appearance: null, chatScope: 'scope-one' }));
  records.set('jarvis.chat.conversation.v2', JSON.stringify({ version: 2, scope: 'scope-one', sessionId: 'saved',
    messages: [{ id: 'answer', role: 'assistant', text: 'A saved reply.' }] }));
  speech.emit('off');
  speech.speak.mockReset().mockImplementation(async () => { speech.emit('preparing'); });
  speech.stop.mockReset().mockImplementation(() => { speech.emit('off'); });
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ agents: [] }) })));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('shows preparing separately and only the confirmed playback state drives speaking', async () => {
  mount();
  fireEvent.click(await screen.findByLabelText('Speak message'));
  expect(await screen.findByText('Preparing speech…')).toBeTruthy();
  expect(screen.getByTestId('speech-orb').getAttribute('data-status')).toBe('idle');
  expect(screen.getByTestId('speech-orb').hasAttribute('data-level')).toBe(false);
  await act(async () => speech.emit('speaking'));
  expect(screen.getByTestId('speech-orb').getAttribute('data-status')).toBe('speaking');
  fireEvent.click(screen.getByLabelText('Stop speaking'));
  expect(screen.getByTestId('speech-orb').getAttribute('data-status')).toBe('off');
});

it('surfaces a playback error without claiming microphone activity', async () => {
  mount();
  await screen.findByLabelText('Speak message');
  await act(async () => speech.emit('error'));
  expect(screen.getByTestId('speech-orb').getAttribute('data-status')).toBe('error');
  expect(screen.getByText('Speech playback unavailable. Try speaking again.')).toBeTruthy();
  expect(screen.getByTestId('speech-orb').hasAttribute('data-level')).toBe(false);
});

it('stops speech and resets the indicator when the hub changes or Chat unmounts', async () => {
  const ui = mount();
  await screen.findByLabelText('Speak message');
  await act(async () => speech.emit('speaking'));
  await act(async () => server.updateConfig({ ...config, baseUrl: 'https://other.test' }));
  expect(speech.stop).toHaveBeenCalled();
  expect(screen.getByTestId('speech-orb').getAttribute('data-status')).toBe('off');
  speech.stop.mockClear();
  ui.unmount();
  expect(speech.stop).toHaveBeenCalledTimes(1);
});
