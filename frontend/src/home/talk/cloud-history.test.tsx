import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { InputBar } from '../../cockpit';
import { V2 } from '../../data';

const preview = { session_id: 'session-one', agent: 'athena', provider: 'gemini', model: 'gemini-fixture', revision: 'rev-one' };
const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => Response.json(
  String(input).includes('/api/chat/cloud-history/preview') ? preview : {},
));
const renderComposer = (onSubmit: (...args: any[]) => boolean | Promise<boolean> = vi.fn(() => true)) => render(<InputBar t={V2.I18N.en} lang="en" agent="athena"
  sessionId="session-one" selectedTurn recipientStatus="ready" onSubmit={onSubmit} />);

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockImplementation(async input => Response.json(String(input).includes('/api/chat/cloud-history/preview') ? preview : {}));
  vi.stubGlobal('fetch', fetchMock);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('keeps a cloud recipient current-message-only by default and preserves the draft on cancel', async () => {
  const onSubmit = vi.fn(() => true);
  renderComposer(onSubmit);
  const field = screen.getByRole('textbox');
  fireEvent.change(field, { target: { value: 'Cloud question' } });
  expect(screen.getByText(/Current message only/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Review earlier turns' }));
  const dialog = await screen.findByRole('dialog', { name: 'Send earlier turns' });
  expect(within(dialog).getByText(/gemini.*gemini-fixture/)).toBeTruthy();
  expect(document.activeElement).toBe(within(dialog).getByRole('button', { name: 'Cancel' }));
  expect(onSubmit).not.toHaveBeenCalled();
  expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('/chat/stream'))).toHaveLength(0);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Review earlier turns' }));
  expect((field as HTMLTextAreaElement).value).toBe('Cloud question');
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  expect(onSubmit).toHaveBeenCalledExactlyOnceWith('Cloud question');
});

it('includes a preview only after confirmation and refuses a stale draft', async () => {
  const onSubmit = vi.fn(async () => true);
  const view = renderComposer(onSubmit);
  const field = screen.getByRole('textbox');
  fireEvent.change(field, { target: { value: 'Cloud question' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review earlier turns' }));
  let dialog = await screen.findByRole('dialog', { name: 'Send earlier turns' });
  fireEvent.change(field, { target: { value: 'Changed question' } });
  expect(screen.queryByRole('dialog', { name: 'Send earlier turns' })).toBeNull();
  expect(onSubmit).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole('button', { name: 'Review earlier turns' }));
  dialog = await screen.findByRole('dialog', { name: 'Send earlier turns' });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Include and send' }));
  await waitFor(() => expect(onSubmit).toHaveBeenCalledExactlyOnceWith('Changed question', undefined, undefined, false,
    { cloudHistory: preview, reviewedMessage: 'Changed question', awaitAdmission: true }));
  expect((field as HTMLTextAreaElement).value).toBe('');
  const calls = fetchMock.mock.calls.filter(([url]) => String(url).includes('/api/chat/cloud-history/preview'));
  expect(calls).toHaveLength(2);
  expect(JSON.parse((calls[1][1] as RequestInit).body as string)).toEqual({ session_id: 'session-one', agent: 'athena', message: 'Changed question' });
});

it('does not offer history disclosure to a local recipient or a new chat', () => {
  const view = render(<InputBar t={V2.I18N.en} lang="en" agent="frigga" sessionId="session-one" selectedTurn onSubmit={vi.fn()} />);
  for (const agent of ['frigga', 'ultron', 'howard']) {
    view.rerender(<InputBar t={V2.I18N.en} lang="en" agent={agent} sessionId="session-one" selectedTurn onSubmit={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Review earlier turns' })).toBeNull();
  }
  view.rerender(<InputBar t={V2.I18N.en} lang="en" agent="athena" sessionId="" selectedTurn onSubmit={vi.fn()} />);
  expect(screen.queryByRole('button', { name: 'Review earlier turns' })).toBeNull();
});

it('asks the server for a hybrid recipient and offers inclusion only when it names a cloud route', async () => {
  const hybrid = { ...preview, agent: 'jarvis' };
  fetchMock.mockImplementation(async input => Response.json(String(input).includes('/api/chat/cloud-history/preview') ? hybrid : {}));
  const onSubmit = vi.fn(async () => true);
  render(<InputBar t={V2.I18N.en} lang="en" agent="jarvis" sessionId="session-one"
    selectedTurn recipientStatus="ready" onSubmit={onSubmit} />);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Hybrid question' } });
  expect(screen.getByText(/Check the destination before including history/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Review earlier turns' }));
  const dialog = await screen.findByRole('dialog', { name: 'Send earlier turns' });
  expect(within(dialog).getByText(/gemini.*gemini-fixture/)).toBeTruthy();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Include and send' }));
  await waitFor(() => expect(onSubmit).toHaveBeenCalledExactlyOnceWith('Hybrid question', undefined, undefined, false,
    { cloudHistory: hybrid, reviewedMessage: 'Hybrid question', awaitAdmission: true }));
});

it('Escape closes the consent dialog and returns focus without a send', async () => {
  const onSubmit = vi.fn(() => true);
  renderComposer(onSubmit);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Cloud question' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review earlier turns' }));
  const dialog = await screen.findByRole('dialog', { name: 'Send earlier turns' });
  fireEvent.keyDown(within(dialog).getByRole('button', { name: 'Cancel' }), { key: 'Escape' });
  expect(screen.queryByRole('dialog', { name: 'Send earlier turns' })).toBeNull();
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Review earlier turns' }));
  expect(onSubmit).not.toHaveBeenCalled();
});

it('drops a preview when the selected session changes before confirmation', async () => {
  const onSubmit = vi.fn(() => true);
  const view = renderComposer(onSubmit);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Cloud question' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review earlier turns' }));
  await screen.findByRole('dialog', { name: 'Send earlier turns' });
  view.rerender(<InputBar t={V2.I18N.en} lang="en" agent="athena" sessionId="session-two"
    selectedTurn recipientStatus="ready" onSubmit={onSubmit} />);
  expect(screen.queryByRole('dialog', { name: 'Send earlier turns' })).toBeNull();
  expect(onSubmit).not.toHaveBeenCalled();
});

it('drops a preview when the recipient changes before confirmation', async () => {
  const onSubmit = vi.fn(() => true);
  const view = renderComposer(onSubmit);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Cloud question' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review earlier turns' }));
  await screen.findByRole('dialog', { name: 'Send earlier turns' });
  view.rerender(<InputBar t={V2.I18N.en} lang="en" agent="frigga" sessionId="session-one"
    selectedTurn recipientStatus="ready" onSubmit={onSubmit} />);
  expect(screen.queryByRole('dialog', { name: 'Send earlier turns' })).toBeNull();
  expect(onSubmit).not.toHaveBeenCalled();
});

it('keeps the draft and grants no history permission when preview is unavailable', async () => {
  fetchMock.mockImplementation(async input => String(input).includes('/api/chat/cloud-history/preview')
    ? Response.json({ detail: 'cloud_history_route_unavailable' }, { status: 409 }) : Response.json({}));
  const onSubmit = vi.fn(() => true);
  renderComposer(onSubmit);
  const field = screen.getByRole('textbox');
  fireEvent.change(field, { target: { value: 'Cloud question' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review earlier turns' }));
  await screen.findByRole('alert');
  expect((field as HTMLTextAreaElement).value).toBe('Cloud question');
  expect(screen.queryByRole('dialog', { name: 'Send earlier turns' })).toBeNull();
  expect(onSubmit).not.toHaveBeenCalled();
});

it('does not retry a refused history send or clear its draft', async () => {
  const onSubmit = vi.fn(async () => false);
  renderComposer(onSubmit);
  const field = screen.getByRole('textbox');
  fireEvent.change(field, { target: { value: 'Cloud question' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review earlier turns' }));
  const dialog = await screen.findByRole('dialog', { name: 'Send earlier turns' });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Include and send' }));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/draft is kept/i));
  expect((field as HTMLTextAreaElement).value).toBe('Cloud question');
  expect(onSubmit).toHaveBeenCalledTimes(1);
});
