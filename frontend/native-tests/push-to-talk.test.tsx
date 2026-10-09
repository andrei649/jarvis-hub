import React from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { PushToTalk } from '../../mobile/src/components/PushToTalk';
import { ServerProvider } from '../../mobile/src/context/ServerContext';
import { foreground } from './support/native';
import { audioRecorder, resetAudio, setNativeRecording, setPermissionResponse } from './support/audio';
import { deletedFiles } from './support/files';
import { records } from './support/storage';

const api = vi.hoisted(() => ({
  trust: vi.fn(async () => {}), arm: vi.fn(async () => {}), release: vi.fn(async () => {}),
  stt: vi.fn(async () => 'spoken words'),
}));
vi.mock('../../mobile/src/api/pushToTalk', () => ({
  readMicTrust: api.trust, armMobileMic: api.arm,
  releaseMobileMic: api.release, transcribeRecording: api.stt,
}));

const config = { baseUrl: 'https://hub.test', token: 'user', adminToken: 'owner' };
function mount(props: Partial<React.ComponentProps<typeof PushToTalk>> = {}) {
  const onTranscript = vi.fn(); const onState = vi.fn(); const onStart = vi.fn();
  const ui = render(<ServerProvider><PushToTalk contextKey="one" disabled={false}
    onTranscript={onTranscript} onState={onState} onStart={onStart} {...props} /></ServerProvider>);
  return { ...ui, onTranscript, onState, onStart };
}
async function readyButton(label = 'Hold to dictate') {
  await vi.waitFor(() => expect(screen.getByLabelText(label).hasAttribute('disabled')).toBe(false));
  return screen.getByLabelText(label);
}

beforeEach(() => {
  records.clear();
  records.set('jarvis.server.config.v1', JSON.stringify({ version: 2, config, appearance: null, chatScope: 'scope-one' }));
  foreground('active'); resetAudio(); deletedFiles.length = 0;
  api.trust.mockReset().mockResolvedValue(undefined);
  api.arm.mockReset().mockResolvedValue(undefined);
  api.release.mockReset().mockResolvedValue(undefined);
  api.stt.mockReset().mockResolvedValue('spoken words');
});
afterEach(() => { cleanup(); });

it('requests permission only on press, confirms native recording, and appends only after release', async () => {
  const ui = mount();
  expect(audioRecorder.requestPermission).not.toHaveBeenCalled();
  fireEvent.mouseDown(await readyButton());
  await vi.waitFor(() => expect(screen.getByText('Listening…')).toBeTruthy());
  expect(api.trust).toHaveBeenCalledWith(config, expect.anything());
  expect(audioRecorder.record).toHaveBeenCalledWith({ forDuration: 15 });
  expect(ui.onState).toHaveBeenCalledWith({ status: 'listening', level: 0.1 });
  expect(ui.onTranscript).not.toHaveBeenCalled();
  fireEvent.mouseUp(screen.getByLabelText('Hold to dictate'));
  await vi.waitFor(() => expect(ui.onTranscript).toHaveBeenCalledWith('spoken words'));
  expect(api.stt).toHaveBeenCalledTimes(1);
  expect(deletedFiles).toContain('file:///fixture/clip.m4a');
});

it('release during delayed permission never prepares or records', async () => {
  let permit!: (value: { granted: boolean }) => void;
  setPermissionResponse(new Promise(resolve => { permit = resolve; }));
  const ui = mount();
  const button = await readyButton();
  fireEvent.mouseDown(button);
  fireEvent.mouseUp(button);
  await act(async () => { permit({ granted: true }); await Promise.resolve(); });
  expect(audioRecorder.prepare).not.toHaveBeenCalled();
  expect(audioRecorder.record).not.toHaveBeenCalled();
  expect(ui.onTranscript).not.toHaveBeenCalled();
});

it('background discards recording without STT output', async () => {
  const ui = mount();
  fireEvent.mouseDown(await readyButton());
  await vi.waitFor(() => expect(screen.getByText('Listening…')).toBeTruthy());
  act(() => foreground('background'));
  await vi.waitFor(() => expect(audioRecorder.stop).toHaveBeenCalledTimes(1));
  expect(api.stt).not.toHaveBeenCalled();
  expect(ui.onTranscript).not.toHaveBeenCalled();
});

it('context remount aborts a pending STT result without transcript insertion', async () => {
  let finish!: (value: string) => void;
  api.stt.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  const ui = mount();
  const button = await readyButton();
  fireEvent.mouseDown(button);
  await vi.waitFor(() => expect(screen.getByText('Listening…')).toBeTruthy());
  fireEvent.mouseUp(button);
  await vi.waitFor(() => expect(screen.getByText('Transcribing…')).toBeTruthy());
  ui.rerender(<ServerProvider><PushToTalk contextKey="new-session" disabled={false}
    onTranscript={ui.onTranscript} onState={ui.onState} /></ServerProvider>);
  await act(async () => { finish('stale transcript'); await Promise.resolve(); });
  expect(ui.onTranscript).not.toHaveBeenCalled();
});

it('keeps the old native recorder owned and shows stopping across a keyed remount', async () => {
  const ui = mount();
  fireEvent.mouseDown(await readyButton());
  await vi.waitFor(() => expect(screen.getByText('Listening…')).toBeTruthy());
  let finish!: () => void;
  audioRecorder.stop.mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve; }));
  await act(async () => { ui.rerender(<ServerProvider><PushToTalk contextKey="new-session" disabled={false}
    onTranscript={ui.onTranscript} onState={ui.onState} /></ServerProvider>); });
  expect(screen.getByText('Stopping microphone…')).toBeTruthy();
  expect(audioRecorder.release).not.toHaveBeenCalled();
  await vi.waitFor(() => expect(audioRecorder.stop).toHaveBeenCalledTimes(1));
  await act(async () => { setNativeRecording(false); finish(); await Promise.resolve(); });
  await vi.waitFor(() => expect(screen.queryByText('Stopping microphone…')).toBeNull());
  expect(audioRecorder.release).toHaveBeenCalledTimes(1);
  expect(ui.onTranscript).not.toHaveBeenCalled();
});

it('shows an unconfirmed-stop warning in the new context while old cleanup hangs', async () => {
  const ui = mount();
  fireEvent.mouseDown(await readyButton());
  await vi.waitFor(() => expect(screen.getByText('Listening…')).toBeTruthy());
  let finish!: () => void;
  audioRecorder.stop.mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve; }));
  vi.useFakeTimers();
  try {
    await act(async () => { ui.rerender(<ServerProvider><PushToTalk contextKey="new-session" disabled={false}
      onTranscript={ui.onTranscript} onState={ui.onState} /></ServerProvider>); });
    expect(screen.getByText('Stopping microphone…')).toBeTruthy();
    act(() => vi.advanceTimersByTime(3000));
    expect(screen.getByText(/Microphone stop unconfirmed/)).toBeTruthy();
    await act(async () => { setNativeRecording(false); finish(); await Promise.resolve(); });
  } finally { vi.useRealTimers(); }
});

it('disabled during recording stops and discards audio', async () => {
  const ui = mount();
  fireEvent.mouseDown(await readyButton());
  await vi.waitFor(() => expect(screen.getByText('Listening…')).toBeTruthy());
  await act(async () => { ui.rerender(<ServerProvider><PushToTalk contextKey="one" disabled
    onTranscript={ui.onTranscript} onState={ui.onState} /></ServerProvider>); });
  await vi.waitFor(() => expect(audioRecorder.stop).toHaveBeenCalledTimes(1));
  expect(api.stt).not.toHaveBeenCalled();
  expect(ui.onTranscript).not.toHaveBeenCalled();
});

it('offers an explicit accessible tap start and finish path', async () => {
  const ui = mount();
  fireEvent.click(await readyButton('Start dictation without holding'));
  await vi.waitFor(() => expect(screen.getByText('Listening…')).toBeTruthy());
  fireEvent.click(screen.getByLabelText('Finish dictation'));
  await vi.waitFor(() => expect(ui.onTranscript).toHaveBeenCalledWith('spoken words'));
  expect(audioRecorder.record).toHaveBeenCalledWith({ forDuration: 15 });
});

it('shows a no-speech result without draft insertion', async () => {
  api.stt.mockResolvedValue('');
  const ui = mount();
  const button = await readyButton();
  fireEvent.mouseDown(button);
  await vi.waitFor(() => expect(screen.getByText('Listening…')).toBeTruthy());
  fireEvent.mouseUp(button);
  await vi.waitFor(() => expect(screen.getByText('No speech detected.')).toBeTruthy());
  expect(ui.onTranscript).not.toHaveBeenCalled();
});
