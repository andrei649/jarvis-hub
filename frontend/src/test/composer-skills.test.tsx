import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { InputBar } from '../cockpit';
import { openComposerMenu } from '../home/talk/test-support';

const props = { t: { transmit: 'Transmit', placeholder: 'Message', channel: 'Chat' }, selectedTurn: true };
// Skills is in the composer's Options menu since the re-lay (PHASE_B_PLAN.md §5.3)
const openSkills = (name = 'Skills') => { openComposerMenu('options'); fireEvent.click(screen.getByRole('button', { name })); };
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
  openSkills();
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
  openSkills();
  fireEvent.click(await screen.findByRole('button', { name: 'Summarize — /summarize' }));
  expect(field.value).toBe('/summarize my exact words');
  expect(document.activeElement).toBe(field);
  expect(submit).not.toHaveBeenCalled();
  openSkills();
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
  openSkills();
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

it('keeps the edited task but drops the picked skill when its recipient changes', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => catalog()));
  const submit = vi.fn();
  const view = render(<InputBar {...props} agent="frigga" sessionId="one" onSubmit={submit}/>);
  const field = screen.getByPlaceholderText('Message') as HTMLInputElement;
  fireEvent.change(field, { target: { value: 'first draft' } });
  openSkills();
  fireEvent.click(await screen.findByRole('button', { name: 'Summarize — /summarize' }));
  fireEvent.change(field, { target: { value: '/summarize   edited draft' } });
  view.rerender(<InputBar {...props} agent="howard" sessionId="one" onSubmit={submit}/>);
  expect(field.value).toBe('  edited draft');
  expect(submit).not.toHaveBeenCalled();
  fireEvent.change(field, { target: { value: '/summarize typed by hand' } });
  view.rerender(<InputBar {...props} agent="frigga" sessionId="two" onSubmit={submit}/>);
  expect(field.value).toBe('/summarize typed by hand');
});

it('keeps a full-length question intact when adding a skill would exceed the hub limit', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => catalog()));
  render(<InputBar {...props} agent="frigga" onSubmit={vi.fn()}/>);
  const field = screen.getByPlaceholderText('Message') as HTMLInputElement;
  fireEvent.change(field, { target: { value: '🟢'.repeat(4096) } });
  openSkills();
  fireEvent.click(await screen.findByRole('button', { name: 'Summarize — /summarize' }));
  expect(field.value).toBe('🟢'.repeat(4096));
  expect(screen.getByRole('status').textContent).toMatch(/4,096/);
});

it('finds learned skills by words in their name locally and keeps searches out of chat', async () => {
  const generated = { ...skill, name: 'copper-margin_123456', command: '/copper-margin_123456', description: 'Skill' };
  const fetcher = vi.fn(async () => catalog({ shortcuts: [skill, generated] }));
  vi.stubGlobal('fetch', fetcher);
  const submit = vi.fn();
  render(<InputBar {...props} lang="ro" agent="frigga" onSubmit={submit}/>);
  openSkills('Abilități');
  const search = await screen.findByRole('searchbox', { name: 'Caută o abilitate' });
  fireEvent.change(search, { target: { value: 'COPPER margin' } });
  expect(screen.queryByText('/summarize')).toBeNull();
  expect(screen.getByText('/copper-margin_123456')).toBeTruthy();
  fireEvent.change(search, { target: { value: 'missing' } });
  expect(screen.getByText('Nicio abilitate nu corespunde căutării.')).toBeTruthy();
  expect((screen.getByPlaceholderText('Message') as HTMLInputElement).value).toBe('');
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(submit).not.toHaveBeenCalled();
});

it('holds an edited skill over the instruction limit until the owner shortens it', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => catalog()));
  const submit = vi.fn();
  render(<InputBar {...props} onSubmit={submit}/>);
  openSkills();
  fireEvent.click(await screen.findByRole('button', { name: 'Summarize — /summarize' }));
  const field = screen.getByPlaceholderText('Message');
  fireEvent.change(field, { target: { value: '/summarize ' + '🟢'.repeat(2001) } });
  fireEvent.keyDown(field, { key: 'Enter' });
  expect(submit).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Transmit' }).hasAttribute('disabled')).toBe(true);
  const atLimit = '/summarize ' + '🟢'.repeat(2000);
  fireEvent.change(field, { target: { value: atLimit } });
  fireEvent.keyDown(field, { key: 'Enter' });
  expect(submit).toHaveBeenCalledExactlyOnceWith(atLimit);
});

it('offers owner review as a typed command only when advertised and preserves unsent drafts', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => catalog()));
  const submit = vi.fn();
  render(<InputBar {...props} onSubmit={submit}/>);
  const field = screen.getByPlaceholderText('Message') as HTMLInputElement;
  fireEvent.change(field, { target: { value: 'unsent draft' } });
  openSkills();
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
  openSkills();
  expect(await screen.findByText(/No skills are available/)).toBeTruthy();
  expect(screen.getByText(/skill list is limited/)).toBeTruthy();
  expect(screen.getByText(/Some shortcuts are unavailable/)).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Review this conversation' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Close skills' }));
  openSkills();
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
  openSkills();
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
  openComposerMenu('options');
  expect(screen.getByRole('button', { name: 'Skills' })).toBeTruthy();
  const image = new File([new Uint8Array(8)], 'photo.png', { type: 'image/png' });
  fireEvent.change(screen.getByLabelText('Attach images'), { target: { files: [image] } });
  expect(screen.queryByRole('button', { name: 'Skills' })).toBeNull();
  expect(fetcher).not.toHaveBeenCalled();
});

it('edits only advertised procedures and links the exact reviewed proposal without changing chat', async () => {
  const command = 'weekly-shelf-count-ae03b689e1fb';
  const display = 'Weekly Shelf Count Ae03b689e1fb';
  const editable = { ...skill, name: command, command: '/' + command, editable_procedure: true };
  const fetcher = vi.fn(async (url: string, options: RequestInit) => {
    if (url.includes('/api/commands')) return catalog({ shortcuts: [editable, { ...skill, name: 'other', command: '/other' }] });
    if (options.method === 'GET') return Response.json({ skill: display, steps: ['First', 'Second'], base_hash: 'a'.repeat(64) });
    return Response.json({ proposal_id: 'proposal-7', skill: display }, { status: 202 });
  });
  vi.stubGlobal('fetch', fetcher);
  render(<InputBar {...props} agent="howard" onSubmit={vi.fn()}/>);
  const field = screen.getByPlaceholderText('Message') as HTMLInputElement;
  fireEvent.change(field, { target: { value: 'unsent words' } });
  openSkills();
  await screen.findByRole('button', { name: `Weekly Shelf Count — /${command}` });
  expect(screen.getAllByRole('button', { name: 'Edit steps for Weekly Shelf Count' })).toHaveLength(1);
  fireEvent.click(screen.getByRole('button', { name: 'Edit steps for Weekly Shelf Count' }));
  const first = await screen.findByRole('textbox', { name: 'Step 1' });
  fireEvent.change(first, { target: { value: 'First\nSecond' } });
  expect((first as HTMLTextAreaElement).value).toBe('First');
  fireEvent.change(first, { target: { value: 'Revised first' } });
  fireEvent.click(screen.getByRole('button', { name: 'Propose revised steps' }));
  await screen.findByRole('link', { name: 'Review proposal proposal-7' });
  const post = fetcher.mock.calls.find(([url, options]) => url.includes('/api/skills/procedures/revision') && options.method === 'POST');
  expect(post?.[0]).toBe('/api/skills/procedures/revision');
  expect(JSON.parse(String(post?.[1].body))).toEqual({ agent: 'howard', command,
    steps: ['Revised first', 'Second'], base_hash: 'a'.repeat(64) });
  expect(screen.getByRole('link', { name: 'Review proposal proposal-7' }).getAttribute('href'))
    .toBe('/v2/console/pending-skills#proposal=proposal-7');
  expect(field.value).toBe('unsent words');
});

it('keeps edited steps after a stale refusal, but clears them when the agent changes', async () => {
  const editable = { ...skill, editable_procedure: true };
  const fetcher = vi.fn(async (url: string, options: RequestInit) => {
    if (url.includes('/api/commands')) return catalog({ shortcuts: [editable] });
    if (options.method === 'GET') return Response.json({ skill: 'Summarize', steps: ['Original'], base_hash: 'b'.repeat(64) });
    return Response.json({ detail: 'stale procedure' }, { status: 409 });
  });
  vi.stubGlobal('fetch', fetcher);
  const view = render(<InputBar {...props} agent="howard" onSubmit={vi.fn()}/>);
  openSkills();
  fireEvent.click(await screen.findByRole('button', { name: 'Edit steps for Summarize' }));
  const step = await screen.findByRole('textbox', { name: 'Step 1' }) as HTMLTextAreaElement;
  fireEvent.change(step, { target: { value: 'Keep my work' } });
  fireEvent.click(screen.getByRole('button', { name: 'Propose revised steps' }));
  expect((await screen.findByRole('alert')).textContent).toMatch(/changed.*copy.*reopen/i);
  expect(step.value).toBe('Keep my work');
  expect(screen.queryByRole('link', { name: /Review proposal/ })).toBeNull();
  view.rerender(<InputBar {...props} agent="frigga" onSubmit={vi.fn()}/>);
  expect(screen.queryByRole('textbox', { name: 'Step 1' })).toBeNull();
});

it('rejects mismatched procedure data and clears a loaded draft when owner credentials change', async () => {
  const editable = { ...skill, editable_procedure: true };
  const fetcher = vi.fn(async (url: string) => url.includes('/api/commands')
    ? catalog({ shortcuts: [editable] })
    : Response.json({ skill: 'Other procedure', steps: ['Private step'], base_hash: 'c'.repeat(64) }));
  vi.stubGlobal('fetch', fetcher);
  render(<InputBar {...props} agent="howard" onSubmit={vi.fn()}/>);
  openSkills();
  fireEvent.click(await screen.findByRole('button', { name: 'Edit steps for Summarize' }));
  expect((await screen.findByRole('alert')).textContent).toMatch(/could not be loaded/i);
  expect(screen.queryByText('Private step')).toBeNull();
  fetcher.mockImplementation(async (url: string) => url.includes('/api/commands')
    ? catalog({ shortcuts: [editable] })
    : Response.json({ skill: 'Summarize', steps: ['Owner step'], base_hash: 'c'.repeat(64) }));
  fireEvent.click(screen.getByRole('button', { name: 'Edit steps for Summarize' }));
  expect((await screen.findByRole('textbox', { name: 'Step 1' }) as HTMLInputElement).value).toBe('Owner step');
  localStorage.setItem('hud.admin_token', 'new-owner');
  fireEvent(window, new Event('storage'));
  await waitFor(() => expect(screen.queryByText('Owner step')).toBeNull());
  expect(screen.queryByRole('region', { name: 'Available chat skills' })).toBeNull();
  localStorage.removeItem('hud.admin_token');
});
