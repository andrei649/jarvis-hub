import React from 'react';
import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ServerProvider } from '../../mobile/src/context/ServerContext';
import { StatusScreen } from '../../mobile/src/screens/StatusScreen';
import { records } from './support/storage';

vi.mock('react-native', async importOriginal => {
  const native = await importOriginal<typeof import('react-native')>();
  const react = await import('react');
  return {
    ...native,
    ScrollView: ({ refreshControl, children, ...props }: any) => react.createElement(
      native.ScrollView,
      props,
      refreshControl ? react.createElement('button', {
        onClick: refreshControl.props.onRefresh,
        'data-refreshing': String(refreshControl.props.refreshing),
      }, 'Pull to refresh') : null,
      children,
    ),
  };
});

const config = { baseUrl: 'https://hub.test', token: 'reader', adminToken: 'owner' };
const storageKey = 'jarvis.server.config.v1';
const response = (body: unknown, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
}) as Response;
function deferred() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>(finish => { resolve = finish; });
  return { promise, resolve };
}
const callsTo = (suffix: string) => (fetch as ReturnType<typeof vi.fn>).mock.calls
  .filter(([url]) => String(url).endsWith(suffix));
const mount = () => render(<ServerProvider><StatusScreen onGoToSettings={() => {}} /></ServerProvider>);
const pull = (view: ReturnType<typeof render>) => fireEvent.click(view.getByText('Pull to refresh'));
const refreshing = (view: ReturnType<typeof render>) => view.getByText('Pull to refresh').getAttribute('data-refreshing');

beforeEach(() => {
  records.clear();
  records.set(storageKey, JSON.stringify({ version: 2, config, appearance: null, chatScope: 'scope' }));
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it('ignores an old first-batch model and does not start its downstream reads', async () => {
  const old = deferred();
  let statusReads = 0;
  global.fetch = vi.fn((url: string) => String(url).endsWith('/status')
    ? ++statusReads === 1 ? old.promise : Promise.resolve(response({ model_state: 'ready', loaded_model: 'new model' }))
    : Promise.resolve(response({}))) as any;
  const view = mount();
  await waitFor(() => expect(callsTo('/status')).toHaveLength(1));
  pull(view);
  await waitFor(() => expect(view.getByText('new model')).toBeTruthy());
  expect(callsTo('/api/security/posture')).toHaveLength(1);
  await act(async () => old.resolve(response({ model_state: 'ready', loaded_model: 'old model' })));
  expect(view.getByText('new model')).toBeTruthy();
  expect(view.queryByText('old model')).toBeNull();
  expect(callsTo('/api/security/posture')).toHaveLength(1);
});

it('ignores an old Trust result and does not launch its brief read', async () => {
  const old = deferred();
  let postureReads = 0;
  global.fetch = vi.fn((url: string) => String(url).endsWith('/api/security/posture')
    ? ++postureReads === 1 ? old.promise : Promise.resolve(response({ secrets: { encrypted_at_rest: true, backend: 'new-vault' } }))
    : Promise.resolve(response({}))) as any;
  const view = mount();
  await waitFor(() => expect(callsTo('/api/security/posture')).toHaveLength(1));
  pull(view);
  await waitFor(() => expect(view.getByText('new-vault')).toBeTruthy());
  expect(callsTo('/autonomy/brief?kind=morning')).toHaveLength(1);
  await act(async () => old.resolve(response({ secrets: { encrypted_at_rest: true, backend: 'old-vault' } })));
  expect(view.getByText('new-vault')).toBeTruthy();
  expect(view.queryByText('old-vault')).toBeNull();
  expect(callsTo('/autonomy/brief?kind=morning')).toHaveLength(1);
});

it('ignores an old brief after a newer brief is visible', async () => {
  const old = deferred();
  let briefReads = 0;
  global.fetch = vi.fn((url: string) => String(url).endsWith('/autonomy/brief?kind=morning')
    ? ++briefReads === 1 ? old.promise : Promise.resolve(response({ text: 'New brief' }))
    : Promise.resolve(response({}))) as any;
  const view = mount();
  await waitFor(() => expect(callsTo('/autonomy/brief?kind=morning')).toHaveLength(1));
  pull(view);
  await waitFor(() => expect(view.getByText('New brief')).toBeTruthy());
  await act(async () => old.resolve(response({ text: 'Old brief' })));
  expect(view.getByText('New brief')).toBeTruthy();
  expect(view.queryByText('Old brief')).toBeNull();
});

it('keeps the newer refresh loading and existing data when an older refresh fails', async () => {
  const old = deferred(); const current = deferred();
  let statusReads = 0;
  global.fetch = vi.fn((url: string) => String(url).endsWith('/status')
    ? ++statusReads === 1 ? Promise.resolve(response({ model_state: 'ready', loaded_model: 'stable model' }))
      : statusReads === 2 ? old.promise : current.promise
    : Promise.resolve(response({}))) as any;
  const view = mount();
  await waitFor(() => expect(view.getByText('stable model')).toBeTruthy());
  await waitFor(() => expect(refreshing(view)).toBe('false'));
  pull(view);
  await waitFor(() => expect(callsTo('/status')).toHaveLength(2));
  pull(view);
  await waitFor(() => expect(callsTo('/status')).toHaveLength(3));
  await act(async () => old.resolve(response({}, 400)));
  expect(refreshing(view)).toBe('true');
  expect(view.getByText('stable model')).toBeTruthy();
  expect(view.queryByText('Server returned HTTP 400')).toBeNull();
  await act(async () => current.resolve(response({ model_state: 'ready', loaded_model: 'current model' })));
  await waitFor(() => expect(view.getByText('current model')).toBeTruthy());
  await waitFor(() => expect(refreshing(view)).toBe('false'));
});

it('does not launch second-batch requests after unmount', async () => {
  const old = deferred();
  global.fetch = vi.fn((url: string) => String(url).endsWith('/status')
    ? old.promise : Promise.resolve(response({}))) as any;
  const view = mount();
  await waitFor(() => expect(callsTo('/status')).toHaveLength(1));
  view.unmount();
  await act(async () => old.resolve(response({ model_state: 'ready', loaded_model: 'late model' })));
  expect(callsTo('/api/security/posture')).toHaveLength(0);
  expect(view.container.textContent).toBe('');
});
