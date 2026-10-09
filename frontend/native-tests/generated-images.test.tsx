import React from 'react';
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { AppearanceProvider } from '../../mobile/src/context/AppearanceContext';
import { GeneratedImages } from '../../mobile/src/screens/GeneratedImages';
import { records, storage } from './support/storage';
import { deleted, copied, written } from './support/files';

const api = vi.hoisted(() => ({
  status: vi.fn(), propose: vi.fn(), task: vi.fn(), png: vi.fn(),
}));
vi.mock('../../mobile/src/api/generatedImages', () => ({
  fetchGeneratedImageStatus: api.status,
  proposeGeneratedImage: api.propose,
  fetchGeneratedTask: api.task,
  fetchGeneratedPng: api.png,
}));

const config = { baseUrl: 'https://fixture.test', token: 'user-secret', adminToken: 'admin-secret' };
function seed(scope = 'scope-one') {
  records.set('jarvis.server.config.v1', JSON.stringify({ version: 2, config, appearance: null, chatScope: scope }));
}
function mount(onGoToApprovals = vi.fn()) {
  return render(<ServerProvider><AppearanceProvider><GeneratedImages onGoToApprovals={onGoToApprovals} /></AppearanceProvider></ServerProvider>);
}
function HubSwitch() {
  const { updateConfig } = useServer();
  return <button onClick={() => void updateConfig({ ...config, baseUrl: 'https://other.test' })}>Change hub</button>;
}
beforeEach(() => {
  records.clear(); deleted.length = 0; copied.length = 0; written.length = 0; seed();
  api.status.mockReset().mockResolvedValue({ configured: true, reachable: null, reason: 'not_probed' });
  api.propose.mockReset().mockResolvedValue({ kind: 'queued', taskId: 42 });
  api.task.mockReset().mockResolvedValue({ taskId: 42, state: 'awaiting_approval', artifact: null });
  api.png.mockReset().mockResolvedValue('iVBORw0KGgoAAAANSUhEUg==');
  global.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ configured: true, preferences: { accent: 'cyan', look: 'obsidian', font: 'theme' } }) }));
});
afterEach(() => { vi.restoreAllMocks(); cleanup(); });

it('keeps local configuration honest and requires an explicit exact-prompt proposal', async () => {
  const approvals = vi.fn();
  const ui = mount(approvals);
  await waitFor(() => expect(ui.getByText(/configured, not probed/i)).toBeTruthy());
  const input = ui.getByLabelText('Image prompt');
  fireEvent.change(input, { target: { value: '  amber moon  ' } });
  expect(api.propose).not.toHaveBeenCalled();
  fireEvent.click(ui.getByText('Request approval'));
  await waitFor(() => expect(ui.getByText(/Task 42.*awaiting approval/i)).toBeTruthy());
  expect(api.propose.mock.calls[0][1]).toBe('  amber moon  ');
  fireEvent.click(ui.getByText('Open Approvals'));
  expect(approvals).toHaveBeenCalledTimes(1);
  ui.unmount();
  const returned = mount();
  await waitFor(() => expect(returned.getByText(/Task 42.*awaiting approval/i)).toBeTruthy());
  expect((returned.getByLabelText('Image prompt') as HTMLInputElement).value).toBe('  amber moon  ');
  expect(api.propose).toHaveBeenCalledTimes(1);
});

it('restores unknown POST delivery across unmount and does not silently invite a duplicate', async () => {
  api.propose.mockImplementation(() => new Promise(() => {}));
  const ui = mount();
  await waitFor(() => expect(ui.getByText(/configured, not probed/i)).toBeTruthy());
  fireEvent.change(ui.getByLabelText('Image prompt'), { target: { value: 'moon' } });
  fireEvent.click(ui.getByText('Request approval'));
  await waitFor(() => expect(records.get('jarvis.generated-image.scope-one')).toContain('"unknown"'));
  const startNew = ui.getByText('Start new request').closest('button') as HTMLButtonElement;
  expect(startNew.disabled).toBe(true);
  fireEvent.click(startNew);
  expect(records.get('jarvis.generated-image.scope-one')).toContain('"unknown"');
  ui.unmount();
  const returned = mount();
  await waitFor(() => expect(returned.getByText(/delivery is unknown.*Check Approvals/i)).toBeTruthy());
  expect(returned.queryByText('Request approval')).toBeNull();
  expect(api.propose).toHaveBeenCalledTimes(1);
});

it('does not send a proposal if its preflight unknown marker cannot be stored', async () => {
  const original = storage.setItem;
  vi.spyOn(storage, 'setItem').mockImplementation(async (key, value) => {
    if (key.startsWith('jarvis.generated-image.')) throw new Error('storage unavailable');
    return original(key, value);
  });
  const ui = mount();
  await waitFor(() => expect(ui.getByText(/configured, not probed/i)).toBeTruthy());
  fireEvent.change(ui.getByLabelText('Image prompt'), { target: { value: 'moon' } });
  fireEvent.click(ui.getByText('Request approval'));
  await waitFor(() => expect(ui.getByText(/No proposal was sent/i)).toBeTruthy());
  expect(api.propose).not.toHaveBeenCalled();
});

it('shows refusal and uncertain separately and writes preview only on explicit request', async () => {
  api.propose.mockResolvedValueOnce({ kind: 'queued', taskId: 42 });
  api.task.mockResolvedValueOnce({ taskId: 42, state: 'uncertain', artifact: null });
  const ui = mount();
  await waitFor(() => expect(ui.getByText(/configured, not probed/i)).toBeTruthy());
  fireEvent.change(ui.getByLabelText('Image prompt'), { target: { value: 'moon' } });
  fireEvent.click(ui.getByText('Request approval'));
  await waitFor(() => expect(ui.getByText(/Task 42.*uncertain/i)).toBeTruthy());
  expect(written).toHaveLength(0);
  expect(api.png).not.toHaveBeenCalled();
});

it('previews authenticated PNG and saves an explicit app-private copy', async () => {
  const artifact = { id: 'a'.repeat(32), bytes: 18, width: 512, height: 512 };
  api.task.mockResolvedValue({ taskId: 42, state: 'ready', artifact });
  const ui = mount();
  await waitFor(() => expect(ui.getByText(/configured, not probed/i)).toBeTruthy());
  fireEvent.change(ui.getByLabelText('Image prompt'), { target: { value: 'moon' } });
  fireEvent.click(ui.getByText('Request approval'));
  await waitFor(() => expect(ui.getByText('Preview PNG')).toBeTruthy());
  fireEvent.click(ui.getByText('Preview PNG'));
  await waitFor(() => expect(written).toHaveLength(1));
  expect(api.png.mock.calls[0][1]).toBe(artifact.id);
  fireEvent.click(ui.getByText('Save copy'));
  await waitFor(() => expect(copied).toHaveLength(1));
  expect(ui.getByText(/Saved in app files/i)).toBeTruthy();
  ui.unmount();
  await waitFor(() => expect(deleted).toHaveLength(1));
  expect(deleted[0]).toBe(written[0]);
  expect(copied[0].to).not.toBe(written[0]);
});

it('allows status refresh after an off result and retains an existing exact prompt while off', async () => {
  records.set('jarvis.generated-image.scope-one', JSON.stringify({ kind: 'task', taskId: 77, prompt: '  original prompt  ' }));
  api.status.mockResolvedValueOnce({ configured: false, reachable: null, reason: 'disabled' })
    .mockResolvedValueOnce({ configured: true, reachable: null, reason: 'not_probed' });
  api.task.mockResolvedValueOnce({ taskId: 77, state: 'rejected', artifact: null });
  const ui = mount();
  await waitFor(() => expect(ui.getByText(/off or unavailable: disabled/i)).toBeTruthy());
  expect((ui.getByLabelText('Image prompt') as HTMLInputElement).value).toBe('  original prompt  ');
  expect(ui.getByText(/Task 77.*rejected by owner/i)).toBeTruthy();
  fireEvent.click(ui.getByText('Refresh image configuration'));
  await waitFor(() => expect(ui.getByText(/configured, not probed/i)).toBeTruthy());
  expect(api.propose).not.toHaveBeenCalled();
});

it('clears old scope data immediately on a hub change while a PNG load is pending', async () => {
  api.task.mockResolvedValue({ taskId: 42, state: 'ready', artifact: { id: 'a'.repeat(32), bytes: 18, width: 512, height: 512 } });
  api.png.mockImplementationOnce(() => new Promise(() => {}));
  const ui = render(<ServerProvider><AppearanceProvider><HubSwitch /><GeneratedImages onGoToApprovals={vi.fn()} /></AppearanceProvider></ServerProvider>);
  await waitFor(() => expect(ui.getByText(/configured, not probed/i)).toBeTruthy());
  fireEvent.change(ui.getByLabelText('Image prompt'), { target: { value: 'old private prompt' } });
  fireEvent.click(ui.getByText('Request approval'));
  await waitFor(() => expect(ui.getByText('Preview PNG')).toBeTruthy());
  fireEvent.click(ui.getByText('Preview PNG'));
  fireEvent.click(ui.getByText('Change hub'));
  expect(ui.queryByText(/Task 42/)).toBeNull();
  expect(ui.queryByDisplayValue('old private prompt')).toBeNull();
  await waitFor(() => expect(ui.getByText(/configured, not probed/i)).toBeTruthy());
  expect(written).toHaveLength(0);
});

it('invalidates a preview when a refreshed ready task points at another artifact', async () => {
  const first = { id: 'a'.repeat(32), bytes: 18, width: 512, height: 512 };
  const second = { ...first, id: 'b'.repeat(32) };
  api.task.mockResolvedValueOnce({ taskId: 42, state: 'ready', artifact: first })
    .mockResolvedValueOnce({ taskId: 42, state: 'ready', artifact: second });
  const ui = mount();
  await waitFor(() => expect(ui.getByText(/configured, not probed/i)).toBeTruthy());
  fireEvent.change(ui.getByLabelText('Image prompt'), { target: { value: 'moon' } });
  fireEvent.click(ui.getByText('Request approval'));
  await waitFor(() => expect(ui.getByText('Preview PNG')).toBeTruthy());
  fireEvent.click(ui.getByText('Preview PNG'));
  await waitFor(() => expect(ui.getByText('Save copy')).toBeTruthy());
  const oldUri = written[0];
  fireEvent.click(ui.getByText('Refresh task'));
  await waitFor(() => expect(ui.queryByText('Save copy')).toBeNull());
  expect(deleted).toContain(oldUri);
  fireEvent.click(ui.getByText('Preview PNG'));
  await waitFor(() => expect(written).toHaveLength(2));
  expect(written[1]).not.toBe(oldUri);
  expect(api.png.mock.calls[1][1]).toBe(second.id);
});

it('removes a preview that fails native image decoding before it can be saved', async () => {
  const artifact = { id: 'a'.repeat(32), bytes: 18, width: 512, height: 512 };
  api.task.mockResolvedValue({ taskId: 42, state: 'ready', artifact });
  const ui = mount();
  await waitFor(() => expect(ui.getByText(/configured, not probed/i)).toBeTruthy());
  fireEvent.change(ui.getByLabelText('Image prompt'), { target: { value: 'moon' } });
  fireEvent.click(ui.getByText('Request approval'));
  await waitFor(() => expect(ui.getByText('Preview PNG')).toBeTruthy());
  fireEvent.click(ui.getByText('Preview PNG'));
  await waitFor(() => expect(ui.getByLabelText('Generated PNG preview')).toBeTruthy());
  fireEvent.error(ui.getByLabelText('Generated PNG preview'));
  await waitFor(() => expect(ui.queryByText('Save copy')).toBeNull());
  expect(deleted).toContain(written[0]);
  expect(ui.getByText(/could not be displayed/i)).toBeTruthy();
});
