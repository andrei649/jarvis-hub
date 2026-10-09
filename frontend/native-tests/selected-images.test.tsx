import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { ChatScreen } from '../../mobile/src/screens/ChatScreen';
import { records } from './support/storage';
import { foreground } from './support/native';
import { picker } from './support/picker';

const config = { baseUrl: 'https://hub.test', token: ' user ', adminToken: ' owner ' };
const png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB';
const asset = { type: 'image', base64: png, width: 1, height: 1, mimeType: 'image/jpeg' };
const review = { configured: true, reachable: null, review_token: 'r'.repeat(24), session_id: 'session-1',
  destination: 'http://127.0.0.1:11434', model: 'llava', backend: 'ollama', local: true, active_image_count: 0 };
let server: ReturnType<typeof useServer>;
function Probe() { server = useServer(); return <ChatScreen onGoToSettings={() => {}} />; }
const response = (body: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status,
  headers: { get: () => null }, text: async () => JSON.stringify(body), json: async () => body });
let fetchMock: ReturnType<typeof vi.fn>;
async function openImages() {
  await screen.findByText('Earlier');
  fireEvent.click(screen.getByLabelText('Selected images'));
  await screen.findByText(/Current session session-1/);
}
async function pickOne() {
  fireEvent.click(screen.getByLabelText('Add selected image'));
  await screen.findByText(/image\/png/);
}
beforeEach(() => {
  records.clear(); foreground('active');
  records.set('jarvis.server.config.v1', JSON.stringify({ version: 2, config, appearance: null, chatScope: 'scope-one' }));
  records.set('jarvis.chat.conversation.v2', JSON.stringify({ version: 2, scope: 'scope-one',
    sessionId: 'session-1', messages: [{ id: 'm1', role: 'user', text: 'Earlier' }] }));
  picker.launchImageLibraryAsync = vi.fn(async () => ({ canceled: false, assets: [asset] }));
  fetchMock = vi.fn(async (url: string) => url.includes('/active-images')
    ? response({ session_id: 'session-1', images: [] })
    : url.endsWith('/selected-prepare') ? response(review)
      : url.endsWith('/selected-chat') ? response({ ok: true, committed: true, response: 'Image answer',
        model: 'llava', destination: review.destination, backend: 'ollama', local: true, active_image_handle: null })
        : response({ agents: [] }));
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); foreground('active'); });

it('accepts a picker-owned background handoff and sends exact frozen bytes after durable marker write', async () => {
  render(<ServerProvider><Probe /></ServerProvider>); await openImages();
  let finish!: (result: any) => void;
  picker.launchImageLibraryAsync = vi.fn(() => new Promise(resolve => { finish = resolve; }));
  fireEvent.click(screen.getByLabelText('Add selected image'));
  await waitFor(() => expect(finish).toBeDefined());
  await act(async () => { foreground('background'); finish({ canceled: false, assets: [asset] }); });
  expect(screen.queryByText(/image\/png/)).toBeNull();
  await act(async () => foreground('active'));
  await screen.findByText(/image\/png/);
  fireEvent.change(screen.getByLabelText('Image question'), { target: { value: ' Exact? ' } });
  fireEvent.click(screen.getByLabelText('Review selected Ollama destination'));
  await screen.findByText(/Model: llava/);
  fetchMock.mockImplementation(async (url: string, init: any) => {
    if (url.endsWith('/selected-chat')) {
      expect(records.get('jarvis.chat.selected-outcome.v1')).toContain('session-1');
      expect(init.headers).toMatchObject({ 'X-User-Token': 'user', 'X-Admin-Token': 'owner' });
      expect(JSON.parse(init.body)).toMatchObject({ prompt: ' Exact? ', images: [`data:image/png;base64,${png}`],
        expected_binding: review.review_token, session_id: 'session-1', remote_ack: false });
      return response({ ok: true, committed: true, response: 'Image answer', model: 'llava',
        destination: review.destination, backend: 'ollama', local: true, active_image_handle: null });
    }
    return response(review);
  });
  fireEvent.click(screen.getByLabelText('Submit reviewed selected images'));
  await screen.findByText('Image answer');
  expect(screen.getByText(/Exact\?\s*\[1 image attached\]/)).toBeTruthy();
  await waitFor(() => expect(records.get('jarvis.chat.selected-outcome.v1')).not.toContain('session-1'));
  expect(records.get('jarvis.chat.conversation.v2')).not.toContain(png);
});

it('retains unknown delivery across close/reopen and gates a new send on explicit History acknowledgement', async () => {
  render(<ServerProvider><Probe /></ServerProvider>); await openImages(); await pickOne();
  fireEvent.change(screen.getByLabelText('Image question'), { target: { value: 'Question' } });
  fireEvent.click(screen.getByLabelText('Review selected Ollama destination'));
  await screen.findByText(/Model: llava/);
  fetchMock.mockImplementation(async (url: string) => url.endsWith('/selected-chat')
    ? new Promise(() => {}) : response(review));
  fireEvent.click(screen.getByLabelText('Submit reviewed selected images'));
  await waitFor(() => expect(records.get('jarvis.chat.selected-outcome.v1')).toContain('session-1'));
  fireEvent.click(screen.getByLabelText('Close selected images'));
  fireEvent.click(screen.getByLabelText('Selected images'));
  await screen.findByText(/Outcome unknown/);
  expect(screen.queryByLabelText('Submit reviewed selected images')).toBeNull();
  fireEvent.click(screen.getByLabelText('Inspect image conversation History'));
  fireEvent.click(screen.getByLabelText('Acknowledge possible duplicate and allow another review'));
  await waitFor(() => expect(records.get('jarvis.chat.selected-outcome.v1')).not.toContain('session-1'));
});

it('drops a stale picker result after the owner scope changes', async () => {
  render(<ServerProvider><Probe /></ServerProvider>); await openImages();
  let finish!: (result: any) => void;
  picker.launchImageLibraryAsync = vi.fn(() => new Promise(resolve => { finish = resolve; }));
  fireEvent.click(screen.getByLabelText('Add selected image'));
  await waitFor(() => expect(finish).toBeDefined());
  await act(async () => server.updateConfig({ ...config, token: 'new-user' }));
  await act(async () => finish({ canceled: false, assets: [asset] }));
  expect(screen.queryByText(/image\/png/)).toBeNull();
  expect(records.get('jarvis.chat.conversation.v2')).not.toContain(png);
});

it('background revokes stalled prepare and send, clears busy, and preserves post-dispatch uncertainty', async () => {
  render(<ServerProvider><Probe /></ServerProvider>); await openImages(); await pickOne();
  fireEvent.change(screen.getByLabelText('Image question'), { target: { value: 'Question' } });
  fetchMock.mockImplementation(async (url: string) => url.endsWith('/selected-prepare')
    ? new Promise(() => {}) : response(review));
  fireEvent.click(screen.getByLabelText('Review selected Ollama destination'));
  await act(async () => { foreground('background'); foreground('active'); });
  expect(screen.queryByText(/Model: llava/)).toBeNull();
  expect((screen.getByLabelText('Add selected image') as HTMLButtonElement).disabled).toBe(false);
  await pickOne();
  fetchMock.mockImplementation(async () => response(review));
  fireEvent.click(screen.getByLabelText('Review selected Ollama destination'));
  await screen.findByText(/Model: llava/);
  fetchMock.mockImplementation(async (url: string) => url.endsWith('/selected-chat')
    ? new Promise(() => {}) : response(review));
  fireEvent.click(screen.getByLabelText('Submit reviewed selected images'));
  await screen.findByText(/Sending reviewed images/);
  expect(screen.queryByLabelText('Acknowledge possible duplicate and allow another review')).toBeNull();
  await waitFor(() => expect(records.get('jarvis.chat.selected-outcome.v1')).toContain('session-1'));
  await act(async () => { foreground('background'); foreground('active'); });
  await screen.findByText(/Outcome unknown/);
  expect((screen.getByLabelText('Refresh active images') as HTMLButtonElement).disabled).toBe(false);
});

it('reviews a process-local active handle and sends it without inventing a thumbnail or image bytes', async () => {
  const handle = 'h'.repeat(24);
  fetchMock.mockImplementation(async (url: string, init: any) => {
    if (url.includes('/active-images')) return response({ session_id: 'session-1',
      images: [{ handle, count: 2, question: 'Earlier cats' }] });
    if (url.endsWith('/selected-prepare')) {
      expect(JSON.parse(init.body)).toMatchObject({ image_digests: [], active_image_handles: [handle] });
      return response({ ...review, active_image_count: 2 });
    }
    if (url.endsWith('/selected-chat')) {
      expect(JSON.parse(init.body)).toMatchObject({ images: [], active_image_handles: [handle] });
      return response({ ok: true, committed: true, response: 'Prior answer', model: 'llava',
        destination: review.destination, backend: 'ollama', local: true, active_image_handle: null });
    }
    return response({ agents: [] });
  });
  render(<ServerProvider><Probe /></ServerProvider>); await openImages();
  await screen.findByText(/Earlier cats · 2 image/);
  fireEvent.click(screen.getByLabelText('Select prior image: Earlier cats'));
  fireEvent.change(screen.getByLabelText('Image question'), { target: { value: 'Follow up' } });
  fireEvent.click(screen.getByLabelText('Review selected Ollama destination'));
  await screen.findByText(/2 image\(s\)/);
  fireEvent.click(screen.getByLabelText('Submit reviewed selected images'));
  await screen.findByText('Prior answer');
  expect(screen.getByText(/Follow up\s*\[2 images attached\]/)).toBeTruthy();
  expect(records.get('jarvis.chat.conversation.v2')).not.toContain(handle);
});

it('does not describe an unavailable active-history feed as a verified empty list', async () => {
  fetchMock.mockImplementation(async (url: string) => {
    if (url.includes('/active-images')) throw new Error('network details');
    return response({ agents: [] });
  });
  render(<ServerProvider><Probe /></ServerProvider>); await openImages();
  await screen.findByText(/Active image history unavailable; its state is unknown/);
  expect(screen.queryByText('No active image handles available.')).toBeNull();
});
