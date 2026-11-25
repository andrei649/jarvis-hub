import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { InputBar } from '../cockpit';
import { openComposerMenu } from '../home/talk/test-support';

// Vault notes is in the composer's Attach menu since the re-lay (PHASE_B_PLAN.md §5.3)
const findVaultNotes = () => { openComposerMenu('attach'); fireEvent.click(screen.getByRole('button', { name: 'Find vault notes' })); };
const excerpt ={ name: 'Projects/Workshop.md', text: 'Choose oak for the workbench.' };
const other = { name: 'Archive/Workshop.md', text: 'Older plans.' };
const reply = (attachments: typeof excerpt[]) => Response.json({ok: true, attachments, focus: null});
const source = { vault: 'My Vault', file: 'Projects/Workshop.md', readable: true };
const sourced = (attachments = [excerpt], sources: Record<string, unknown> = { [excerpt.name]: source }) =>
  Response.json({ok: true, attachments, sources, focus: null});
const note = (body: string) => Response.json({ok: true, title: 'Workshop', body});
const props = { t: { transmit: 'Send', placeholder: 'Message', channel: 'Chat' }, selectedTurn: true };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

async function review() {
  fireEvent.change(screen.getByPlaceholderText('Message'), { target: { value: 'Workshop plans' } });
  findVaultNotes();
  fireEvent.click(await screen.findByRole('checkbox', { name: excerpt.name }));
}

const saved = { path: 'Inbox/Teal.md', title: 'Teal', view: 'robot' as const };
const sceneReply = (color: string) => Response.json({ok:true, ...saved, summary:'Robot shell ' + color,
  project:{version:1,view:'robot',state:{shellColor:color}}});

it('prepares a named project before typing and shares only the reviewed version for one turn', async () => {
  const request = vi.fn(async () => sceneReply('#009977'));
  const submit = vi.fn();
  vi.stubGlobal('fetch', request);
  render(<InputBar {...props} projectForChat={saved} onSubmit={submit}/>);
  const box = await screen.findByRole('checkbox', { name: saved.path });
  expect((box as HTMLInputElement).checked).toBe(false);
  fireEvent.click(box);
  fireEvent.change(screen.getByPlaceholderText('Message'), {target:{value:'Recall the shell color'}});
  expect((box as HTMLInputElement).checked).toBe(true);
  expect(submit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', {name:'Send'}));
  await waitFor(() => expect(submit).toHaveBeenCalledWith('Recall the shell color', undefined,
    [{name:saved.path,text:expect.stringContaining('"shellColor":"#009977"')}]));
  expect(request).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole('checkbox')).toBeNull();
  fireEvent.change(screen.getByPlaceholderText('Message'), {target:{value:'New topic'}});
  fireEvent.click(screen.getByRole('button',{name:'Send'}));
  expect(submit).toHaveBeenLastCalledWith('New topic');
});

it('requires a second review after a saved project changes on disk', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(sceneReply('#009977')).mockResolvedValueOnce(sceneReply('#ffffff')));
  const submit = vi.fn();
  render(<InputBar {...props} projectForChat={saved} onSubmit={submit}/>);
  fireEvent.click(await screen.findByRole('checkbox', {name:saved.path}));
  fireEvent.change(screen.getByPlaceholderText('Message'), {target:{value:'Recall the color'}});
  fireEvent.click(screen.getByRole('button', {name:'Send'}));
  await screen.findByText(/changed or became unavailable/);
  expect(submit).not.toHaveBeenCalled();
  expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false);
});

it('keeps the reviewed project and cancels a pending send if the question changes', async () => {
  let finish!: (response: Response) => void;
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(sceneReply('#009977'))
    .mockImplementationOnce(() => new Promise<Response>(resolve => { finish = resolve; })));
  const submit = vi.fn();
  render(<InputBar {...props} projectForChat={saved} onSubmit={submit}/>);
  fireEvent.click(await screen.findByRole('checkbox', {name:saved.path}));
  const field = screen.getByPlaceholderText('Message');
  fireEvent.change(field, {target:{value:'First question'}});
  fireEvent.click(screen.getByRole('button',{name:'Send'}));
  fireEvent.change(field, {target:{value:'Edited question'}});
  await act(async () => finish(sceneReply('#009977')));
  expect(submit).not.toHaveBeenCalled();
  expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(true);
});

it('sends only checked excerpts and clears them before another turn', async () => {
  const submit = vi.fn();
  const search = vi.fn(async () => reply([excerpt, other]));
  vi.stubGlobal('fetch', search);
  render(<InputBar {...props} onSubmit={submit}/>);
  expect(search.mock.calls.length).toBe(0);
  await review();
  expect(screen.getByText(excerpt.text).closest('details')?.open).toBe(true);
  expect(submit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  await waitFor(() => expect(submit).toHaveBeenCalledWith('Workshop plans', undefined, [excerpt]));
  expect(search).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole('checkbox')).toBeNull();
  fireEvent.change(screen.getByPlaceholderText('Message'), { target: { value: 'Hello' } });
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  expect(submit).toHaveBeenLastCalledWith('Hello');
});

it('includes a checked note path in the saved message only after explicit consent', async () => {
  const submit = vi.fn();
  vi.stubGlobal('fetch', vi.fn(async () => sourced()));
  render(<InputBar {...props} onSubmit={submit}/>);
  await review();
  const path = screen.getByRole('checkbox', {name:/Include note path in message.*Projects\/Workshop\.md/}) as HTMLInputElement;
  expect(path.checked).toBe(false);
  expect(screen.getByText('Projects/Workshop.md', {selector:'code'})).toBeTruthy();
  fireEvent.click(path);
  fireEvent.click(screen.getByRole('button', {name:'Send'}));
  await waitFor(() => expect(submit).toHaveBeenCalledWith(
    'Workshop plans\n\nObsidian note path: Projects/Workshop.md', undefined, [excerpt]));
  fireEvent.change(screen.getByPlaceholderText('Message'), {target:{value:'Next message'}});
  fireEvent.click(screen.getByRole('button', {name:'Send'}));
  expect(submit).toHaveBeenLastCalledWith('Next message');
});

it('keeps path consent independent for two checked notes', async () => {
  const otherSource = {...source, file:'Archive/Workshop.md'};
  const submit = vi.fn();
  vi.stubGlobal('fetch', vi.fn(async () => sourced([excerpt, other], {
    [excerpt.name]: source, [other.name]: otherSource,
  })));
  render(<InputBar {...props} onSubmit={submit}/>);
  await review();
  fireEvent.click(screen.getByRole('checkbox', {name:other.name}));
  const paths = screen.getAllByRole('checkbox', {name:/Include note path in message/}) as HTMLInputElement[];
  fireEvent.click(paths[0]);
  fireEvent.click(paths[1]);
  expect(paths.map(path => path.checked)).toEqual([true, true]);
  fireEvent.click(screen.getByRole('button', {name:'Send'}));
  await waitFor(() => expect(submit).toHaveBeenCalledWith(
    'Workshop plans\n\nObsidian note path: Projects/Workshop.md\nObsidian note path: Archive/Workshop.md',
    undefined, [excerpt, other]));
});

it('keeps the full draft when adding the note path exceeds the chat message limit', async () => {
  const submit = vi.fn();
  vi.stubGlobal('fetch', vi.fn(async () => sourced()));
  render(<InputBar {...props} onSubmit={submit}/>);
  fireEvent.change(screen.getByPlaceholderText('Message'), {target:{value:'x'.repeat(4070)}});
  findVaultNotes();
  fireEvent.click(await screen.findByRole('checkbox', {name:excerpt.name}));
  fireEvent.click(screen.getByRole('checkbox', {name:/Include note path in message/}));
  fireEvent.click(screen.getByRole('button', {name:'Send'}));
  await screen.findByText(/too long/i);
  expect(submit).not.toHaveBeenCalled();
  expect((screen.getByPlaceholderText('Message') as HTMLInputElement).value).toHaveLength(4070);
  expect((screen.getByRole('checkbox', {name:/Include note path in message/}) as HTMLInputElement).checked).toBe(true);
});

it('clears path consent when the note is deselected or its source changes', async () => {
  const submit = vi.fn();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(sourced())
    .mockResolvedValueOnce(sourced([excerpt], {[excerpt.name]: {...source, file:'Other.md'}})));
  render(<InputBar {...props} onSubmit={submit}/>);
  await review();
  fireEvent.click(screen.getByRole('checkbox', {name:/Include note path in message/}));
  fireEvent.click(screen.getByRole('checkbox', {name:excerpt.name}));
  expect(screen.queryByRole('checkbox', {name:/Include note path in message/})).toBeNull();
  fireEvent.click(screen.getByRole('checkbox', {name:excerpt.name}));
  expect((screen.getByRole('checkbox', {name:/Include note path in message/}) as HTMLInputElement).checked).toBe(false);
  fireEvent.click(screen.getByRole('checkbox', {name:/Include note path in message/}));
  fireEvent.click(screen.getByRole('button', {name:'Send'}));
  await screen.findByText(/changed or became unavailable/i);
  expect(submit).not.toHaveBeenCalled();
  expect(screen.queryByRole('checkbox', {name:/Include note path in message/})).toBeNull();
});

it('does not carry an opted-in note path into another session while send is pending', async () => {
  let respond!: (response: Response) => void;
  const submit = vi.fn();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(sourced())
    .mockImplementationOnce(() => new Promise<Response>(resolve => {respond = resolve;})));
  const view = render(<InputBar {...props} onSubmit={submit} sessionId="first"/>);
  await review();
  fireEvent.click(screen.getByRole('checkbox', {name:/Include note path in message/}));
  fireEvent.click(screen.getByRole('button', {name:'Send'}));
  view.rerender(<InputBar {...props} onSubmit={submit} sessionId="next"/>);
  await act(async () => respond(sourced()));
  expect(submit).not.toHaveBeenCalled();
  expect(screen.queryByRole('checkbox', {name:/Include note path in message/})).toBeNull();
});

it('requires a fresh selection when a checked note changed or became private', async () => {
  const submit = vi.fn();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(reply([excerpt])).mockResolvedValueOnce(reply([])));
  render(<InputBar {...props} onSubmit={submit}/>);
  await review();
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  await screen.findByText(/changed or became unavailable/i);
  expect(submit).not.toHaveBeenCalled();
  expect(screen.queryByText(excerpt.text)).toBeNull();
});

it('drops a pending send when its agent or session changes', async () => {
  let respond!: (r: Response) => void;
  const submit = vi.fn();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(reply([excerpt]))
    .mockImplementationOnce(() => new Promise<Response>(r => {respond = r;})));
  const view = render(<InputBar {...props} onSubmit={submit} sessionId="first"/>);
  await review();
  fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  view.rerender(<InputBar {...props} onSubmit={submit} sessionId="next" agent="howard"/>);
  await act(async () => respond(reply([excerpt])));
  expect(submit).not.toHaveBeenCalled();
  expect(screen.queryByText(excerpt.text)).toBeNull();
});

it('links only validated sources and does not read notes during lookup', async () => {
  const privateNote = {name:'Private note', text:'Visible excerpt.'};
  const request = vi.fn(async () => sourced([excerpt, other, privateNote], {
    [excerpt.name]: source,
    [other.name]: { vault: 'My Vault', file: '../private.md', readable: true },
    [privateNote.name]: {vault:'My Vault', file:'Private.md', readable:false},
  }));
  vi.stubGlobal('fetch', request);
  render(<InputBar {...props} onSubmit={vi.fn()}/>);
  fireEvent.change(screen.getByPlaceholderText('Message'), {target:{value:'Workshop plans'}});
  findVaultNotes();
  expect((await screen.findAllByRole('link', {name:'Open in Obsidian'}))[0].getAttribute('href'))
    .toBe('obsidian://open?vault=My%20Vault&file=Projects%2FWorkshop.md');
  expect(screen.getAllByRole('link', {name:'Open in Obsidian'})).toHaveLength(2);
  expect(screen.getAllByRole('button', {name:'Choose passage'})).toHaveLength(1);
  fireEvent.click(screen.getByRole('checkbox', {name:'Private note'}));
  expect(screen.queryByRole('checkbox', {name:/Include note path in message/})).toBeNull();
  expect(request).toHaveBeenCalledTimes(1);
});

it('shows the selected passage and sends only its canonical source name and text', async () => {
  const body = ('First paragraph.\n' + 'x'.repeat(2100) + '\nSecond paragraph to send.\n' + 'y'.repeat(3900)).slice(0, 6000);
  const summary = {name:'Workshop index summary', text:excerpt.text};
  const request = vi.fn(async (url: string) => url.includes('/brain/note?') ? note(body)
    : sourced([summary], {[summary.name]:source}));
  const submit = vi.fn();
  vi.stubGlobal('fetch', request);
  render(<InputBar {...props} onSubmit={submit}/>);
  fireEvent.change(screen.getByPlaceholderText('Message'), {target:{value:'Workshop plans'}});
  findVaultNotes();
  fireEvent.click(await screen.findByRole('button', {name:'Choose passage'}));
  const field = await screen.findByRole('textbox', {name:'Select text from this note (first 6,000 characters)'}) as HTMLTextAreaElement;
  const chosen = 'Second paragraph to send.';
  field.setSelectionRange(body.indexOf(chosen), body.indexOf(chosen) + chosen.length);
  fireEvent.click(screen.getByRole('button', {name:'Use selected passage'}));
  expect(screen.getByText(chosen)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', {name:'Send'}));
  await waitFor(() => expect(submit).toHaveBeenCalledWith('Workshop plans', undefined,
    [{name:source.file, text:chosen}]));
  expect(request.mock.calls.filter(([url]) => url.includes('/brain/note?'))).toHaveLength(2);
  expect(request.mock.calls.filter(([url]) => url.includes('/brain/note?'))[0][0])
    .toContain('/api/os/brain/note?relPath=Projects%2FWorkshop.md');
});

it('uses displayed textarea offsets for a later passage after CRLF and lone CR lines', async () => {
  const chosen = 'The verification code is IRIS-9C0C-C28D.\nSecond line.';
  const body = 'Intro\r\n'.repeat(220) + 'Standalone\r' + 'Middle\r\n'.repeat(100) + chosen.replace('\n', '\r\n');
  const request = vi.fn(async (url: string) => url.includes('/brain/note?') ? note(body) : sourced());
  const submit = vi.fn();
  vi.stubGlobal('fetch', request);
  render(<InputBar {...props} onSubmit={submit}/>);
  fireEvent.change(screen.getByPlaceholderText('Message'), {target:{value:'Workshop plans'}});
  findVaultNotes();
  fireEvent.click(await screen.findByRole('button', {name:'Choose passage'}));
  const field = await screen.findByRole('textbox', {name:'Select text from this note'}) as HTMLTextAreaElement;
  expect(field.value).not.toContain('\r');
  const start = field.value.indexOf(chosen);
  expect(start).toBeGreaterThan(2000);
  field.setSelectionRange(start, start + chosen.length);
  fireEvent.click(screen.getByRole('button', {name:'Use selected passage'}));
  expect(screen.getByText((_, element) => element?.tagName === 'P' && element.textContent === chosen)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', {name:'Send'}));
  await waitFor(() => expect(submit).toHaveBeenCalledWith('Workshop plans', undefined,
    [{name:source.file, text:chosen}]));
});

it('opens the search match in a long note and checks that location before sending', async () => {
  const query = 'spectroscope calibration';
  const body = 'Spectroscope calibration uses the indigo reference.';
  const sources = { [excerpt.name]: source };
  let start = 8200;
  const request = vi.fn(async (url: string) => url.includes('/brain/note?')
    ? new Response(JSON.stringify({ok: true, body, start}))
    : sourced([{name: excerpt.name, text: body}], sources));
  const submit = vi.fn();
  vi.stubGlobal('fetch', request);
  render(<InputBar {...props} onSubmit={submit}/>);
  fireEvent.change(screen.getByPlaceholderText('Message'), {target:{value:query}});
  findVaultNotes();
  fireEvent.click(await screen.findByRole('button', {name:'Choose passage'}));
  const field = await screen.findByRole('textbox', {name:/Select text from this note .*8,201/}) as HTMLTextAreaElement;
  field.setSelectionRange(body.indexOf('indigo'), body.indexOf('indigo') + 6);
  fireEvent.click(screen.getByRole('button', {name:'Use selected passage'}));
  start += 80;
  fireEvent.click(screen.getByRole('button', {name:'Send'}));
  expect(await screen.findByText(/A selected note changed/)).toBeTruthy();
  expect(submit).not.toHaveBeenCalled();
  const reads = request.mock.calls.map(([url]) => url).filter(url => url.includes('/brain/note?'));
  expect(reads).toHaveLength(2);
  for (const url of reads) expect(new URL(url, 'http://hub').searchParams.get('q')).toBe(query);
});

it('deselects a passage when its source is missing on recheck', async () => {
  const request = vi.fn().mockResolvedValueOnce(sourced()).mockResolvedValueOnce(note('Picked text.'))
    .mockResolvedValueOnce(sourced([excerpt], {}));
  const submit = vi.fn();
  vi.stubGlobal('fetch', request);
  render(<InputBar {...props} onSubmit={submit}/>);
  fireEvent.change(screen.getByPlaceholderText('Message'), {target:{value:'Workshop plans'}});
  findVaultNotes();
  fireEvent.click(await screen.findByRole('button', {name:'Choose passage'}));
  const field = await screen.findByRole('textbox', {name:'Select text from this note'}) as HTMLTextAreaElement;
  field.setSelectionRange(0, 6);
  fireEvent.click(screen.getByRole('button', {name:'Use selected passage'}));
  fireEvent.click(screen.getByRole('button', {name:'Send'}));
  await screen.findByText(/changed or became unavailable/i);
  expect(submit).not.toHaveBeenCalled();
  expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false);
  expect(request).toHaveBeenCalledTimes(3);
});

it('deselects a checked excerpt when its source identity changes', async () => {
  const request = vi.fn().mockResolvedValueOnce(sourced())
    .mockResolvedValueOnce(sourced([excerpt], {[excerpt.name]: {...source, vault:'Different Vault'}}));
  const submit = vi.fn();
  vi.stubGlobal('fetch', request);
  render(<InputBar {...props} onSubmit={submit}/>);
  await review();
  fireEvent.click(screen.getByRole('button', {name:'Send'}));
  await screen.findByText(/changed or became unavailable/i);
  expect(submit).not.toHaveBeenCalled();
  expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false);
});

it('deselects a passage when its source changes on recheck', async () => {
  const request = vi.fn().mockResolvedValueOnce(sourced()).mockResolvedValueOnce(note('Picked text.'))
    .mockResolvedValueOnce(sourced([excerpt], {[excerpt.name]: {...source, file:'Other.md'}}));
  const submit = vi.fn();
  vi.stubGlobal('fetch', request);
  render(<InputBar {...props} onSubmit={submit}/>);
  fireEvent.change(screen.getByPlaceholderText('Message'), {target:{value:'Workshop plans'}});
  findVaultNotes();
  fireEvent.click(await screen.findByRole('button', {name:'Choose passage'}));
  const field = await screen.findByRole('textbox', {name:'Select text from this note'}) as HTMLTextAreaElement;
  field.setSelectionRange(0, 6);
  fireEvent.click(screen.getByRole('button', {name:'Use selected passage'}));
  fireEvent.click(screen.getByRole('button', {name:'Send'}));
  await screen.findByText(/changed or became unavailable/i);
  expect(submit).not.toHaveBeenCalled();
  expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false);
});

it('deselects a passage when the note changes or a fresh read is denied', async () => {
  for (const response of [note('Changed text.'), new Response('', {status:404})]) {
    const request = vi.fn().mockResolvedValueOnce(sourced()).mockResolvedValueOnce(note('Picked text.'))
      .mockResolvedValueOnce(sourced()).mockResolvedValueOnce(response);
    const submit = vi.fn();
    vi.stubGlobal('fetch', request);
    const view = render(<InputBar {...props} onSubmit={submit}/>);
    fireEvent.change(screen.getByPlaceholderText('Message'), {target:{value:'Workshop plans'}});
    findVaultNotes();
    fireEvent.click(await screen.findByRole('button', {name:'Choose passage'}));
    const field = await screen.findByRole('textbox', {name:'Select text from this note'}) as HTMLTextAreaElement;
    field.setSelectionRange(0, 6);
    fireEvent.click(screen.getByRole('button', {name:'Use selected passage'}));
    fireEvent.click(screen.getByRole('button', {name:'Send'}));
    await screen.findByText(/changed or became unavailable/i);
    expect(submit).not.toHaveBeenCalled();
    expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false);
    view.unmount();
  }
});

it('does not send a selected passage after the session changes during recheck', async () => {
  let finish!: (response: Response) => void;
  const request = vi.fn().mockResolvedValueOnce(sourced()).mockResolvedValueOnce(note('Picked text.'))
    .mockImplementationOnce(() => new Promise<Response>(resolve => { finish = resolve; }));
  const submit = vi.fn();
  vi.stubGlobal('fetch', request);
  const view = render(<InputBar {...props} onSubmit={submit} sessionId="first"/>);
  fireEvent.change(screen.getByPlaceholderText('Message'), {target:{value:'Workshop plans'}});
  findVaultNotes();
  fireEvent.click(await screen.findByRole('button', {name:'Choose passage'}));
  const field = await screen.findByRole('textbox', {name:'Select text from this note'}) as HTMLTextAreaElement;
  field.setSelectionRange(0, 6);
  fireEvent.click(screen.getByRole('button', {name:'Use selected passage'}));
  fireEvent.click(screen.getByRole('button', {name:'Send'}));
  view.rerender(<InputBar {...props} onSubmit={submit} sessionId="next"/>);
  await act(async () => finish(sourced()));
  expect(submit).not.toHaveBeenCalled();
  expect(screen.queryByText('Picked')).toBeNull();
});
