import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { InputBar } from '../cockpit';

const props = { t: { transmit: 'Transmit', placeholder: 'Message', channel: 'Chat' }, selectedTurn: true };
const skill = { kind: 'skill', name: 'summarize', command: '/summarize', description: 'Summarize', tier: 'admin', usage: '[instruction]' };
const refine = { name: 'refine', command: '/refine', description: 'Review', tier: 'admin', usage: '[focus]' };
const catalog = (overrides: Record<string, unknown> = {}) => Response.json({
  ok: true, commands: [refine], shortcuts: [skill], truncated: false, shortcuts_unavailable: false, ...overrides,
});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete window.__NERVA_BASE_PATH__; });

it('loads on demand with owner credentials and shows only canonical server-visible skills', async () => {
  window.__NERVA_BASE_PATH__ = '/proxy';
  localStorage.setItem('hud.admin_token', 'owner-test');
  const fetcher = vi.fn(async (_url: string, _options: RequestInit) => catalog({ shortcuts: [skill,
    { ...skill, name: 'bad', command: '/bad;run' },
    { ...skill, name: 'wrong', command: '/other' },
    { ...skill, name: 'hidden', tier: 'user' },
    { ...skill, kind: 'bundle', name: 'other', command: '/bundle other' },
  ] }));
  vi.stubGlobal('fetch', fetcher);
  render(<InputBar {...props} agent="howard" onSubmit={vi.fn()}/>);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Skills' }));
  expect(await screen.findByRole('button', { name: 'Summarize — /summarize' })).toBeTruthy();
  expect(screen.queryByText('/bad;run')).toBeNull();
  expect(screen.queryByText('/other')).toBeNull();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][0]).toBe('/proxy/api/commands?agent=howard');
  expect(fetcher.mock.calls[0][1]).toEqual(expect.objectContaining({ signal: expect.any(AbortSignal),
    headers: expect.objectContaining({ 'X-Admin-Token': 'owner-test' }) }));
  expect(screen.getByRole('link', { name: 'Review pending skills in Console' }).getAttribute('href'))
    .toBe('/proxy/v2/console/pending-skills');
  localStorage.removeItem('hud.admin_token');
});

it('inserts a typed skill before existing text, keeps conflicting slash drafts, and sends only on Transmit', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => catalog()));
  const submit = vi.fn();
  render(<InputBar {...props} onSubmit={submit}/>);
  const field = screen.getByPlaceholderText('Message') as HTMLInputElement;
  fireEvent.change(field, { target: { value: 'my exact words' } });
  fireEvent.click(screen.getByRole('button', { name: 'Skills' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Summarize — /summarize' }));
  expect(field.value).toBe('/summarize my exact words');
  expect(document.activeElement).toBe(field);
  expect(submit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Skills' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Summarize — /summarize' }));
  expect(field.value).toBe('/summarize my exact words');
  expect(screen.getByText(/slash command is already drafted/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  expect(submit).toHaveBeenCalledExactlyOnceWith('/summarize my exact words');
});

it('shows generated skills by readable title while retaining the exact slash command', async () => {
  const generated = { ...skill, name: 'copper-margin-generate-excelready-133619',
    command: '/copper-margin-generate-excelready-133619', description: 'Skill' };
  vi.stubGlobal('fetch', vi.fn(async () => catalog({ shortcuts: [generated] })));
  const submit = vi.fn();
  render(<InputBar {...props} onSubmit={submit}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Skills' }));
  const choice = await screen.findByRole('button', {
    name: 'Copper Margin Generate Excelready — /copper-margin-generate-excelready-133619',
  });
  expect(screen.getByText('Copper Margin Generate Excelready')).toBeTruthy();
  expect(screen.getByText('/copper-margin-generate-excelready-133619')).toBeTruthy();
  expect(screen.queryByText('Skill')).toBeNull();
  fireEvent.click(choice);
  expect((screen.getByPlaceholderText('Message') as HTMLInputElement).value)
    .toBe('/copper-margin-generate-excelready-133619 ');
  expect(submit).not.toHaveBeenCalled();
});

it('offers owner review as a typed command only when advertised and preserves unsent drafts', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => catalog()));
  const submit = vi.fn();
  render(<InputBar {...props} onSubmit={submit}/>);
  const field = screen.getByPlaceholderText('Message') as HTMLInputElement;
  fireEvent.change(field, { target: { value: 'unsent draft' } });
  fireEvent.click(screen.getByRole('button', { name: 'Skills' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Review this conversation' }));
  expect(screen.getByText(/After you approve a new procedure, any agent can use it/)).toBeTruthy();
  expect(field.value).toBe('unsent draft');
  expect(screen.getByText(/Send or clear your draft/)).toBeTruthy();
  fireEvent.change(field, { target: { value: '' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review this conversation' }));
  expect(field.value).toBe('/refine ');
  expect(document.activeElement).toBe(field);
  expect(submit).not.toHaveBeenCalled();
  fireEvent.change(field, { target: { value: '/refine contracts' } });
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  expect(submit).toHaveBeenCalledExactlyOnceWith('/refine contracts');
});

it('reports partial, empty, unavailable, and refused catalogs without inventing skills or review', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(catalog({ commands: [], shortcuts: [], truncated: true, shortcuts_unavailable: true }))
    .mockResolvedValueOnce(Response.json({ ok: false, commands: [], shortcuts: [] }, { status: 503 }));
  vi.stubGlobal('fetch', fetcher);
  render(<InputBar {...props} onSubmit={vi.fn()}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Skills' }));
  expect(await screen.findByText(/No skills are available/)).toBeTruthy();
  expect(screen.getByText(/skill list is limited/)).toBeTruthy();
  expect(screen.getByText(/Some shortcuts are unavailable/)).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Review this conversation' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Close skills' }));
  fireEvent.click(screen.getByRole('button', { name: 'Skills' }));
  expect(await screen.findByText(/Skills are unavailable/)).toBeTruthy();
  fireEvent.keyDown(screen.getByRole('button', { name: 'Close skills' }), { key: 'Escape' });
  expect(screen.queryByRole('region', { name: 'Available chat skills' })).toBeNull();
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Skills' }));
});

it('aborts pending discovery on session, agent, or live-scope change and hides in demo', async () => {
  let finish!: (response: Response) => void;
  const fetcher = vi.fn((_url: string, _options: RequestInit) => new Promise<Response>(resolve => { finish = resolve; }));
  vi.stubGlobal('fetch', fetcher);
  const view = render(<InputBar {...props} agent="jarvis" sessionId="a" onSubmit={vi.fn()}/>);
  fireEvent.click(screen.getByRole('button', { name: 'Skills' }));
  const signal = fetcher.mock.calls[0][1].signal as AbortSignal;
  view.rerender(<InputBar {...props} agent="howard" sessionId="b" onSubmit={vi.fn()}/>);
  expect(signal.aborted).toBe(true);
  expect(screen.queryByRole('region', { name: 'Available chat skills' })).toBeNull();
  await act(async () => finish(catalog()));
  expect(screen.queryByText('/summarize')).toBeNull();
  view.rerender(<InputBar {...props} selectedTurn={false} agent="howard" sessionId="b" onSubmit={vi.fn()}/>);
  expect(screen.queryByRole('button', { name: 'Skills' })).toBeNull();
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it('hides the picker while an image draft is being prepared', () => {
  const fetcher = vi.fn();
  vi.stubGlobal('fetch', fetcher);
  render(<InputBar {...props} onSubmit={vi.fn()}/>);
  expect(screen.getByRole('button', { name: 'Skills' })).toBeTruthy();
  const image = new File([new Uint8Array(8)], 'photo.png', { type: 'image/png' });
  fireEvent.change(screen.getByLabelText('Attach images'), { target: { files: [image] } });
  expect(screen.queryByRole('button', { name: 'Skills' })).toBeNull();
  expect(fetcher).not.toHaveBeenCalled();
});
