import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { InputBar } from '../cockpit';
import { signOut } from '../api/owner-session';

const t = { transmit: 'Transmit', placeholder: 'Message', channel: 'Chat' };
const officeFile = (name = 'Quarterly.xlsx') => new File(['sheet data'], name, { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
const blendFile = (name = 'Scene.blend') => new File(['BLENDER-v300'], name, { type: 'application/octet-stream' });
const godotFile = (text: string, name = 'player.gd') => {
  const file = new File([text], name, { type: 'text/plain' });
  Object.defineProperty(file, 'arrayBuffer', { configurable: true, value: async () => new TextEncoder().encode(text).buffer });
  return file;
};
const thumbnail = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lK0AAAAASUVORK5CYII=';
const preview = (kind = 'xlsx', segments: unknown[] = [{ label: 'Revenue', text: 'North: 12\nSouth: 8', truncated: false }], total_segments = segments.length) =>
  Response.json({ kind, segments, total_segments });
const choose = (container: HTMLElement, file = officeFile()) =>
  fireEvent.change(container.querySelector('.office-file-input')!, { target: { files: [file] } });

it('stages passages from two Office files in order and removes only the chosen passage', async () => {
  vi.stubGlobal('fetch', vi.fn(async (_url: string, options: RequestInit) =>
    preview('xlsx', [{ label: 'Revenue', text: options.body instanceof File && options.body.name === 'Second.xlsx' ? 'Second: 2' : 'First: 1', truncated: false }])));
  const submit = vi.fn();
  const { container } = render(<InputBar onSubmit={submit} t={t}/>);
  fireEvent.change(screen.getByPlaceholderText('Message'), { target: { value: 'Compare these' } });
  choose(container, officeFile('First.xlsx'));
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Select a passage' })).toBeTruthy());
  fireEvent.click(screen.getByRole('button', { name: 'Attach shown text' }));
  fireEvent.click(screen.getByRole('button', { name: 'Done reviewing' }));
  fireEvent.click(screen.getByRole('button', { name: 'Add another document' }));
  choose(container, officeFile('Second.xlsx'));
  await waitFor(() => expect((screen.getByRole('textbox', { name: 'Select a passage' }) as HTMLTextAreaElement).value).toBe('Second: 2'));
  fireEvent.click(screen.getByRole('button', { name: 'Attach shown text' }));
  fireEvent.click(screen.getByRole('button', { name: 'Done reviewing' }));
  expect(screen.getByText('First: 1')).toBeTruthy();
  expect(screen.getByText('Second: 2')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Remove passage: First.xlsx · Revenue' }));
  expect(screen.queryByText('First: 1')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  expect(submit).toHaveBeenCalledExactlyOnceWith('Compare these', undefined, [{ name: 'Second.xlsx · Revenue', text: 'Second: 2' }], false, { awaitAdmission: true });
});

it('keeps earlier passages through a failed second preview and rejects duplicate source labels', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(preview('xlsx', [{ label: 'Revenue', text: 'First', truncated: false }]))
    .mockResolvedValueOnce(new Response(null, { status: 422 }))
    .mockResolvedValueOnce(preview('xlsx', [
      { label: 'Revenue', text: 'Duplicate', truncated: false },
      { label: 'Costs', text: 'Distinct', truncated: false },
    ]));
  vi.stubGlobal('fetch', fetcher);
  const { container } = render(<InputBar onSubmit={vi.fn()} t={t}/>);
  choose(container, officeFile());
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Select a passage' })).toBeTruthy());
  fireEvent.click(screen.getByRole('button', { name: 'Attach shown text' }));
  fireEvent.click(screen.getByRole('button', { name: 'Done reviewing' }));
  choose(container, officeFile('Broken.xlsx'));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('cannot read'));
  fireEvent.click(screen.getByRole('button', { name: 'Keep selected passages' }));
  expect(screen.getByText('First')).toBeTruthy();
  choose(container, officeFile());
  await waitFor(() => expect((screen.getByRole('textbox', { name: 'Select a passage' }) as HTMLTextAreaElement).value).toBe('Duplicate'));
  fireEvent.click(screen.getByRole('button', { name: 'Attach shown text' }));
  expect(screen.getByRole('status').textContent).toContain('distinct source');
  fireEvent.change(screen.getByRole('combobox', { name: 'Choose a sheet or document' }), { target: { value: '1' } });
  fireEvent.click(screen.getByRole('button', { name: 'Attach shown text' }));
  fireEvent.click(screen.getByRole('button', { name: 'Done reviewing' }));
  expect(screen.getByText('First')).toBeTruthy();
  expect(screen.getByText('Distinct')).toBeTruthy();
});

it('clears every Office passage when credentials rotate before send', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => preview()));
  localStorage.setItem('hud.admin_token', 'first');
  const submit = vi.fn();
  const { container } = render(<InputBar onSubmit={submit} t={t}/>);
  choose(container);
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Select a passage' })).toBeTruthy());
  fireEvent.click(screen.getByRole('button', { name: 'Attach shown text' }));
  fireEvent.click(screen.getByRole('button', { name: 'Done reviewing' }));
  localStorage.setItem('hud.admin_token', 'second');
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  expect(submit).not.toHaveBeenCalled();
  expect(screen.queryByText(/Selected passage to send:/)).toBeNull();
});

it('keeps a saved passage when an edit is canceled and restores plain messages after last removal', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => preview('xlsx', [
    { label: 'Revenue', text: 'Saved', truncated: false },
    { label: 'Costs', text: 'Other', truncated: false },
  ])));
  const submit = vi.fn();
  const { container } = render(<InputBar onSubmit={submit} t={t}/>);
  choose(container);
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Select a passage' })).toBeTruthy());
  fireEvent.click(screen.getByRole('button', { name: 'Attach shown text' }));
  fireEvent.click(screen.getByRole('button', { name: 'Done reviewing' }));
  fireEvent.click(screen.getByRole('button', { name: 'Review attached passage' }));
  fireEvent.change(screen.getByRole('combobox', { name: 'Choose a sheet or document' }), { target: { value: '1' } });
  fireEvent.click(screen.getByRole('button', { name: 'Close document preview' }));
  expect(screen.getByText('Saved')).toBeTruthy();
  choose(container, blendFile());
  expect(screen.getByRole('alert').textContent).toContain('DOCX or XLSX');
  fireEvent.click(screen.getByRole('button', { name: 'Keep selected passages' }));
  expect(screen.getByText('Saved')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Remove passage' }));
  fireEvent.change(screen.getByPlaceholderText('Message'), { target: { value: 'Plain message' } });
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  expect(submit).toHaveBeenCalledExactlyOnceWith('Plain message');
});

it('replaces one reviewed sheet in place without duplicating the source', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => preview('xlsx', [
    { label: 'Revenue', text: 'Old text', truncated: false },
    { label: 'Costs', text: 'New text', truncated: false },
  ])));
  const submit = vi.fn();
  const { container } = render(<InputBar onSubmit={submit} t={t}/>);
  choose(container);
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Select a passage' })).toBeTruthy());
  fireEvent.click(screen.getByRole('button', { name: 'Attach shown text' }));
  fireEvent.click(screen.getByRole('button', { name: 'Done reviewing' }));
  fireEvent.click(screen.getByRole('button', { name: 'Review attached passage' }));
  fireEvent.change(screen.getByRole('combobox', { name: 'Choose a sheet or document' }), { target: { value: '1' } });
  fireEvent.click(screen.getByRole('button', { name: 'Attach shown text' }));
  fireEvent.click(screen.getByRole('button', { name: 'Done reviewing' }));
  expect(screen.queryByText('Old text')).toBeNull();
  expect(screen.getByText('New text')).toBeTruthy();
  expect(screen.getByText(/1\/8 · 8 \/ 128,000/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  expect(submit.mock.calls[0][2]).toEqual([{ name: 'Quarterly.xlsx · Costs', text: 'New text' }]);
});

it('keeps selected Office passages below the visible byte and count limits', async () => {
  const emoji = '🌍'.repeat(11_000);
  vi.stubGlobal('fetch', vi.fn(async (_url: string, options: RequestInit) =>
    preview('xlsx', [{ label: 'Sheet', text: options.body instanceof File && options.body.name.startsWith('Big') ? emoji : 'small', truncated: false }])));
  const { container } = render(<InputBar onSubmit={vi.fn()} t={t}/>);
  for (let i = 0; i < 3; i++) {
    choose(container, officeFile(`Big${i}.xlsx`));
    await waitFor(() => expect((screen.getByRole('textbox', { name: 'Select a passage' }) as HTMLTextAreaElement).value).toBe(emoji));
    fireEvent.click(screen.getByRole('button', { name: 'Attach shown text' }));
    if (i < 2) fireEvent.click(screen.getByRole('button', { name: 'Done reviewing' }));
  }
  expect(screen.getByRole('status').textContent).toContain('128,000 bytes');
  fireEvent.click(screen.getByRole('button', { name: 'Close document preview' }));
  for (let i = 2; i < 8; i++) {
    choose(container, officeFile(`Small${i}.xlsx`));
    await waitFor(() => expect((screen.getByRole('textbox', { name: 'Select a passage' }) as HTMLTextAreaElement).value).toBe('small'));
    fireEvent.click(screen.getByRole('button', { name: 'Attach shown text' }));
    fireEvent.click(screen.getByRole('button', { name: 'Done reviewing' }));
  }
  expect(screen.getByRole('button', { name: 'Add another document' }).hasAttribute('disabled')).toBe(true);
  expect(screen.getByText(/8\/8 · 88,030 \/ 128,000/)).toBeTruthy();
});

it('clears earlier Office passages on expired preview authorization and drops a stale response', async () => {
  let resolve!: (response: Response) => void;
  const fetcher = vi.fn().mockResolvedValueOnce(preview())
    .mockResolvedValueOnce(new Response(null, { status: 401 }))
    .mockImplementationOnce(() => new Promise<Response>(done => { resolve = done; }));
  vi.stubGlobal('fetch', fetcher);
  localStorage.setItem('hud.admin_token', 'first');
  const { container } = render(<InputBar onSubmit={vi.fn()} t={t}/>);
  choose(container);
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Select a passage' })).toBeTruthy());
  fireEvent.click(screen.getByRole('button', { name: 'Attach shown text' }));
  fireEvent.click(screen.getByRole('button', { name: 'Done reviewing' }));
  choose(container, officeFile('Expired.xlsx'));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Sign in'));
  expect(screen.queryByText(/Selected passage to send:/)).toBeNull();
  choose(container, officeFile('Late.xlsx'));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));
  localStorage.setItem('hud.admin_token', 'second');
  resolve(preview());
  await waitFor(() => expect(screen.queryByRole('textbox', { name: 'Select a passage' })).toBeNull());
  expect(screen.queryByText(/Selected passage to send:/)).toBeNull();
});

it('reviews a later Godot source passage locally and transmits only the chosen text with the question', async () => {
  const fetcher = vi.fn();
  vi.stubGlobal('fetch', fetcher);
  const submit = vi.fn();
  const { container } = render(<InputBar onSubmit={submit} t={t} selectedTurn sessionId="s1"/>);
  expect(screen.getByRole('button', { name: 'Attach document' }).textContent).toBe('Files');
  expect(screen.getByRole('button', { name: 'Attach document' }).getAttribute('title')).toContain('Godot');
  expect(container.querySelector('.office-file-input')?.getAttribute('accept')).toContain('.tscn');
  fireEvent.change(screen.getByPlaceholderText('Message'), { target: { value: 'Why does this node fail?' } });
  choose(container, godotFile('a'.repeat(12000) + '\nfunc café():\n\tprint("Salut 🌍")\n', 'res://player.gd'));
  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Choose source page' })).toBeTruthy());
  fireEvent.change(screen.getByRole('combobox', { name: 'Choose source page' }), { target: { value: '1' } });
  const area = screen.getByRole('textbox', { name: 'Select a passage' }) as HTMLTextAreaElement;
  expect(area.value).toContain('func café():\n\tprint("Salut 🌍")');
  area.setSelectionRange(area.value.indexOf('func café'), area.value.length);
  fireEvent.click(screen.getByRole('button', { name: 'Attach selected text' }));
  fireEvent.click(screen.getByRole('button', { name: 'Done reviewing' }));
  expect(fetcher).not.toHaveBeenCalled();
  expect(submit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  expect(submit).toHaveBeenCalledExactlyOnceWith('Why does this node fail?', undefined, [{ name: 'player.gd · Page 2', text: 'func café():\n\tprint("Salut 🌍")\n' }]);
  expect(fetcher).not.toHaveBeenCalled();
});

it('rejects malformed or oversized Godot text and clears reviewed source on target change', async () => {
  const fetcher = vi.fn();
  vi.stubGlobal('fetch', fetcher);
  const submit = vi.fn();
  const view = render(<InputBar onSubmit={submit} t={t} agent="frigga" sessionId="s1"/>);
  const invalid = godotFile('placeholder', 'project.godot');
  Object.defineProperty(invalid, 'arrayBuffer', { value: async () => Uint8Array.of(0xff).buffer });
  choose(view.container, invalid);
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('UTF-8'));
  const huge = godotFile('x', 'scene.tscn');
  Object.defineProperty(huge, 'size', { value: 1024 * 1024 + 1 });
  choose(view.container, huge);
  expect(screen.getByRole('alert').textContent).toContain('1 MiB');
  choose(view.container, godotFile('[gd_scene]\n[node name="Raíz" type="Node"]\n', 'scene.tscn'));
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Select a passage' })).toBeTruthy());
  fireEvent.click(screen.getByRole('button', { name: 'Attach shown text' }));
  fireEvent.click(screen.getByRole('button', { name: 'Done reviewing' }));
  view.rerender(<InputBar onSubmit={submit} t={t} agent="ultron" sessionId="s1"/>);
  expect(screen.queryByText(/Selected passage to send:/)).toBeNull();
  expect(fetcher).not.toHaveBeenCalled();
  expect(submit).not.toHaveBeenCalled();
});

it('drops a late local source read after replacement and accepts uppercase GDScript extensions', async () => {
  let resolve!: (buffer: ArrayBuffer) => void;
  const old = godotFile('old', 'old.gd');
  Object.defineProperty(old, 'arrayBuffer', { value: () => new Promise<ArrayBuffer>(done => { resolve = done; }) });
  const fetcher = vi.fn();
  vi.stubGlobal('fetch', fetcher);
  const { container } = render(<InputBar onSubmit={vi.fn()} t={t}/>);
  choose(container, old);
  choose(container, godotFile('func new():\n\tpass\n', 'NEW.GD'));
  await waitFor(() => expect((screen.getByRole('textbox', { name: 'Select a passage' }) as HTMLTextAreaElement).value).toContain('func new()'));
  await act(async () => resolve(new TextEncoder().encode('old').buffer));
  expect((screen.getByRole('textbox', { name: 'Select a passage' }) as HTMLTextAreaElement).value).toContain('func new()');
  expect(fetcher).not.toHaveBeenCalled();
});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.removeItem('hud.admin_token'); });

it('previews raw bytes, selects a literal sheet passage, and sends only after Transmit', async () => {
  const fetcher = vi.fn(async () => preview());
  vi.stubGlobal('fetch', fetcher);
  const submit = vi.fn();
  const { container } = render(<InputBar onSubmit={submit} t={t} selectedTurn sessionId="s1"/>);
  fireEvent.change(screen.getByPlaceholderText('Message'), { target: { value: 'Compare regions' } });
  choose(container);
  await waitFor(() => expect((screen.getByRole('textbox', { name: 'Select a passage' }) as HTMLTextAreaElement).value).toBe('North: 12\nSouth: 8'));
  expect(submit).not.toHaveBeenCalled();
  const [url, options] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe('/api/canvas/office-preview?kind=xlsx');
  expect(options.body).toBeInstanceOf(File);
  expect(options.body).toHaveProperty('name', 'Quarterly.xlsx');
  expect(options.headers).toMatchObject({ 'Content-Type': 'application/octet-stream' });
  expect(options).toMatchObject({ method: 'POST', redirect: 'error', credentials: 'same-origin', cache: 'no-store' });
  const area = screen.getByRole('textbox', { name: 'Select a passage' }) as HTMLTextAreaElement;
  area.setSelectionRange(0, 9);
  fireEvent.click(screen.getByRole('button', { name: 'Attach selected text' }));
  expect(screen.getByText('North: 12', { exact: true })).toBeTruthy();
  expect(submit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Done reviewing' }));
  expect(screen.getByText(/Selected passage to send:/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  expect(submit).toHaveBeenCalledExactlyOnceWith('Compare regions', undefined, [{ name: 'Quarterly.xlsx · Revenue', text: 'North: 12' }], false, { awaitAdmission: true });
  expect(screen.queryByRole('dialog', { name: 'Attach document' })).toBeNull();
});

it('rejects wrong shapes and size before any model attachment, then allows retry', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(preview('docx')).mockResolvedValueOnce(preview());
  vi.stubGlobal('fetch', fetcher);
  const submit = vi.fn();
  const { container } = render(<InputBar onSubmit={submit} t={t}/>);
  choose(container, new File(['x'], 'bad.pdf'));
  expect(screen.getByRole('alert').textContent).toContain('8 MiB');
  expect(fetcher).not.toHaveBeenCalled();
  choose(container);
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('invalid'));
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  expect(submit).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Retry preview' }));
  await waitFor(() => expect((screen.getByRole('textbox', { name: 'Select a passage' }) as HTMLTextAreaElement).value).toBe('North: 12\nSouth: 8'));
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it('rejects unbounded preview text and unsafe sheet labels', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(preview('xlsx', [{ label: 'Sheet', text: 'x'.repeat(12001), truncated: false }]))
    .mockResolvedValueOnce(preview('xlsx', [{ label: 'bad\nlabel', text: 'safe text', truncated: false }]));
  vi.stubGlobal('fetch', fetcher);
  const submit = vi.fn();
  const { container } = render(<InputBar onSubmit={submit} t={t}/>);
  choose(container);
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('invalid'));
  choose(container);
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('invalid'));
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole('textbox', { name: 'Select a passage' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  expect(submit).not.toHaveBeenCalled();
});

it('keeps the question and passage when send is refused, and removes attachment on sheet change', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => preview('xlsx', [
    { label: 'Revenue', text: 'North: 12', truncated: false },
    { label: 'Costs', text: 'Costs: 5', truncated: true },
  ], 3)));
  const submit = vi.fn(() => false);
  const { container } = render(<InputBar onSubmit={submit} t={t}/>);
  fireEvent.change(screen.getByPlaceholderText('Message'), { target: { value: 'Explain this' } });
  choose(container);
  await waitFor(() => expect((screen.getByRole('textbox', { name: 'Select a passage' }) as HTMLTextAreaElement).value).toBe('North: 12'));
  fireEvent.click(screen.getByRole('button', { name: 'Attach shown text' }));
  fireEvent.click(screen.getByRole('button', { name: 'Done reviewing' }));
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  expect((screen.getByPlaceholderText('Message') as HTMLInputElement).value).toBe('Explain this');
  expect(screen.getByText(/Selected passage to send:/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Review attached passage' }));
  fireEvent.change(screen.getByRole('combobox', { name: 'Choose a sheet or document' }), { target: { value: '1' } });
  expect(screen.queryByText(/Selected passage to send:/)).toBeNull();
  expect(screen.getByText(/This preview is truncated\./)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  expect(submit).toHaveBeenCalledTimes(1);
});

it('aborts a pending preview on close and session change, and never auto sends', async () => {
  let resolve!: (value: Response) => void;
  const fetcher = vi.fn(() => new Promise<Response>(done => { resolve = done; }));
  vi.stubGlobal('fetch', fetcher);
  const submit = vi.fn();
  const props = { onSubmit: submit, t, sessionId: 'first', selectedTurn: true };
  const view = render(<InputBar {...props}/>);
  choose(view.container);
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  const signal = (fetcher.mock.calls[0] as unknown as [string, RequestInit])[1].signal!;
  fireEvent.click(screen.getByRole('button', { name: 'Close document preview' }));
  expect(signal.aborted).toBe(true);
  resolve(preview());
  await waitFor(() => expect(screen.queryByRole('textbox', { name: 'Select a passage' })).toBeNull());
  choose(view.container);
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  view.rerender(<InputBar {...props} sessionId="next"/>);
  expect(((fetcher.mock.calls[1] as unknown as [string, RequestInit])[1].signal as AbortSignal).aborted).toBe(true);
  expect(submit).not.toHaveBeenCalled();
});

it('keeps document and vault review mutually exclusive, and clears on command or demo', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => preview()));
  const submit = vi.fn();
  const props = { onSubmit: submit, t, selectedTurn: true, sessionId: 's1' };
  const view = render(<InputBar {...props}/>);
  choose(view.container);
  await waitFor(() => expect((screen.getByRole('textbox', { name: 'Select a passage' }) as HTMLTextAreaElement).value).toBe('North: 12\nSouth: 8'));
  expect(screen.getByRole('button', { name: 'Find vault notes' }).hasAttribute('disabled')).toBe(true);
  fireEvent.change(screen.getByPlaceholderText('Message'), { target: { value: '/help' } });
  expect(screen.queryByRole('dialog', { name: 'Attach document' })).toBeNull();
  view.rerender(<InputBar {...props} demo/>);
  expect(screen.getByRole('button', { name: 'Attach document' }).hasAttribute('disabled')).toBe(true);
  expect(submit).not.toHaveBeenCalled();
});

it('shows actionable hub errors and Romanian preview labels', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(null, { status: 429 })).mockResolvedValueOnce(preview()));
  const { container } = render(<InputBar onSubmit={vi.fn()} t={t} lang="ro"/>);
  choose(container);
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('ocupat'));
  fireEvent.click(screen.getByRole('button', { name: 'Reîncearcă previzualizarea' }));
  await waitFor(() => expect((screen.getByRole('textbox', { name: 'Selectează un pasaj' }) as HTMLTextAreaElement).value).toBe('North: 12\nSouth: 8'));
  expect(screen.getByText(/foi · 18 \/ 12,000 caractere/)).toBeTruthy();
  expect(screen.getByText(/Hubul conectat citește fișierul/)).toBeTruthy();
});

it('keeps dialog focus reachable and clears a prepared passage on sign-out', async () => {
  vi.stubGlobal('fetch', vi.fn(async (path: string) => path === '/api/auth/logout' ? Response.json({ ok: true }) : preview()));
  const { container } = render(<InputBar onSubmit={vi.fn()} t={t}/>);
  choose(container);
  await waitFor(() => expect(screen.getByRole('dialog', { name: 'Attach document' })).toBeTruthy());
  const close = screen.getByRole('button', { name: 'Close document preview' });
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Select a passage' })).toBeTruthy());
  expect(document.activeElement).toBe(close);
  fireEvent.keyDown(close, { key: 'Tab', shiftKey: true });
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Attach shown text' }));
  fireEvent.click(screen.getByRole('button', { name: 'Attach shown text' }));
  fireEvent.click(screen.getByRole('button', { name: 'Done reviewing' }));
  expect(screen.getByText(/Selected passage to send:/)).toBeTruthy();
  await act(async () => { await signOut(); });
  expect(screen.queryByText(/Selected passage to send:/)).toBeNull();
});

it('keeps Escape working while retrying a second rejected document', async () => {
  let rejectAgain!: (response: Response) => void;
  const fetcher = vi.fn().mockResolvedValueOnce(new Response(null, { status: 422 }))
    .mockImplementationOnce(() => new Promise<Response>(resolve => { rejectAgain = resolve; }));
  vi.stubGlobal('fetch', fetcher);
  const { container } = render(<InputBar onSubmit={vi.fn()} t={t}/>);
  choose(container, new File(['invalid'], 'invalid.docx'));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('cannot read'));
  fireEvent.click(screen.getByRole('button', { name: 'Retry preview' }));
  const close = screen.getByRole('button', { name: 'Close document preview' });
  expect(document.activeElement).toBe(close);
  rejectAgain(new Response(null, { status: 422 }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Retry preview' })).toBeTruthy());
  expect(document.activeElement).toBe(close);
  fireEvent.keyDown(close, { key: 'Escape' });
  expect(screen.queryByRole('dialog', { name: 'Attach document' })).toBeNull();
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Attach document' }));
});

it('asks before uploading a Blender file and sends only selected inspection text to the chosen agent', async () => {
  const fetcher = vi.fn(async () => Response.json({ kind: 'blend', segments: [
    { label: 'Overview', text: 'Scenes: 1', truncated: false },
    { label: 'Objects', text: 'Cube\nCamera', truncated: false },
  ], total_segments: 2, thumbnail_png: thumbnail }));
  vi.stubGlobal('fetch', fetcher);
  const submit = vi.fn();
  const { container, rerender } = render(<InputBar onSubmit={submit} t={t} agent="frigga" selectedTurn sessionId="s1"/>);
  expect(screen.getByRole('button', { name: 'Attach document' }).getAttribute('title')).toContain('Blender');
  choose(container, blendFile());
  expect(screen.getByText(/Blender lists datablock names without rendering or editing/)).toBeTruthy();
  expect(screen.getByText(/Destination:/).textContent).toContain('frigga');
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Inspect with Blender' }));
  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Choose a datablock group' })).toBeTruthy());
  expect(screen.getByText(/2 \/ 2 sections/)).toBeTruthy();
  const [url, options] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe('/api/canvas/blender-preview');
  expect(options).toMatchObject({ method: 'POST', redirect: 'error', credentials: 'same-origin', cache: 'no-store' });
  expect(options.body).toBeInstanceOf(File);
  expect(options.headers).toMatchObject({ 'Content-Type': 'application/octet-stream' });
  expect(JSON.stringify(options.headers)).not.toMatch(/Scene\.blend|path|name/i);
  expect(screen.getByRole('img', { name: 'Blender thumbnail' }).getAttribute('src')).toBe(`data:image/png;base64,${thumbnail}`);
  fireEvent.change(screen.getByRole('combobox', { name: 'Choose a datablock group' }), { target: { value: '1' } });
  const area = screen.getByRole('textbox', { name: 'Select a passage' }) as HTMLTextAreaElement;
  area.setSelectionRange(0, 4);
  fireEvent.click(screen.getByRole('button', { name: 'Attach selected text' }));
  fireEvent.click(screen.getByRole('button', { name: 'Done reviewing' }));
  rerender(<InputBar onSubmit={submit} t={t} agent="frigga" selectedTurn sessionId="s1"/>);
  expect(fetcher).toHaveBeenCalledTimes(1);
  fireEvent.change(screen.getByPlaceholderText('Message'), { target: { value: 'What is selected?' } });
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  expect(submit).toHaveBeenCalledExactlyOnceWith('What is selected?', undefined, [{ name: 'Blender · Objects', text: 'Cube' }]);
  expect(JSON.stringify(submit.mock.calls)).not.toContain('Scene.blend');
  expect(JSON.stringify(submit.mock.calls)).not.toContain('BLENDER-v300');
  expect(JSON.stringify(submit.mock.calls)).not.toContain('iVBORw0KGgo');
});

it('cancels Blender inspection without uploading and keeps the Office 8 MiB limit', () => {
  const fetcher = vi.fn();
  vi.stubGlobal('fetch', fetcher);
  const { container } = render(<InputBar onSubmit={vi.fn()} t={t}/>);
  choose(container, blendFile());
  fireEvent.click(screen.getByRole('button', { name: 'Close Blender inspection' }));
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.queryByRole('dialog', { name: 'Blender inspection' })).toBeNull();
  const bigOffice = officeFile();
  Object.defineProperty(bigOffice, 'size', { value: 8 * 1024 * 1024 + 1 });
  choose(container, bigOffice);
  expect(screen.getByRole('alert').textContent).toContain('8 MiB');
  expect(fetcher).not.toHaveBeenCalled();
});

it('rejects oversized Blender files and invalid inspection responses', async () => {
  const wide = Uint8Array.from(atob(thumbnail), char => char.charCodeAt(0));
  wide[18] = 1; wide[19] = 44;
  const fetcher = vi.fn().mockResolvedValueOnce(Response.json({ kind: 'blend', segments: [
    { label: 'Objects', text: 'Cube', truncated: false },
  ], total_segments: 1, thumbnail_png: 'https://example.com/image.png' }))
    .mockResolvedValueOnce(Response.json({ kind: 'blend', segments: [
      { label: 'Objects', text: 'Cube', truncated: false },
    ], total_segments: 1, thumbnail_png: btoa(String.fromCharCode(...wide)) }));
  vi.stubGlobal('fetch', fetcher);
  const { container } = render(<InputBar onSubmit={vi.fn()} t={t}/>);
  const bigBlend = blendFile();
  Object.defineProperty(bigBlend, 'size', { value: 64 * 1024 * 1024 + 1 });
  choose(container, bigBlend);
  expect(screen.getByRole('alert').textContent).toContain('64 MiB');
  expect(fetcher).not.toHaveBeenCalled();
  choose(container, blendFile());
  fireEvent.click(screen.getByRole('button', { name: 'Inspect with Blender' }));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('invalid'));
  expect(screen.queryByRole('img', { name: 'Blender thumbnail' })).toBeNull();
  choose(container, blendFile());
  fireEvent.click(screen.getByRole('button', { name: 'Inspect with Blender' }));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('invalid'));
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it('accepts empty Blender datablock groups and a null thumbnail without attaching them', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ kind: 'blend', segments: [
    { label: 'Overview', text: 'Scenes: 0', truncated: false },
    { label: 'Scenes', text: '', truncated: false },
  ], total_segments: 2, thumbnail_png: null })));
  const { container } = render(<InputBar onSubmit={vi.fn()} t={t}/>);
  choose(container, blendFile());
  fireEvent.click(screen.getByRole('button', { name: 'Inspect with Blender' }));
  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Choose a datablock group' })).toBeTruthy());
  expect(screen.queryByRole('img', { name: 'Blender thumbnail' })).toBeNull();
  fireEvent.change(screen.getByRole('combobox', { name: 'Choose a datablock group' }), { target: { value: '1' } });
  fireEvent.click(screen.getByRole('button', { name: 'Attach shown text' }));
  expect(screen.getByRole('status').textContent).toContain('Select text');
});

it('explains missing Blender and invalid files in Romanian', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(new Response(null, { status: 503 }))
    .mockResolvedValueOnce(new Response(null, { status: 422 }));
  vi.stubGlobal('fetch', fetcher);
  const { container } = render(<InputBar onSubmit={vi.fn()} t={t} lang="ro"/>);
  choose(container, blendFile());
  expect(screen.getByText(/Blender listează numele blocurilor de date/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Inspectează cu Blender' }));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('nu este disponibil'));
  fireEvent.click(screen.getByRole('button', { name: 'Reîncearcă previzualizarea' }));
  await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('fișier Blender valid'));
});

it('clears a Blender file when the credential changes before inspection', () => {
  const fetcher = vi.fn();
  vi.stubGlobal('fetch', fetcher);
  localStorage.setItem('hud.admin_token', 'first');
  const { container } = render(<InputBar onSubmit={vi.fn()} t={t}/>);
  choose(container, blendFile());
  localStorage.setItem('hud.admin_token', 'second');
  fireEvent.click(screen.getByRole('button', { name: 'Inspect with Blender' }));
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.queryByRole('dialog', { name: 'Blender inspection' })).toBeNull();
});

it('drops native Blender results after credential rotation and blocks duplicate Inspect clicks', async () => {
  let resolve!: (value: Response) => void;
  const fetcher = vi.fn(() => new Promise<Response>(done => { resolve = done; }));
  vi.stubGlobal('fetch', fetcher);
  localStorage.setItem('hud.admin_token', 'first');
  const submit = vi.fn();
  const { container } = render(<InputBar onSubmit={submit} t={t}/>);
  choose(container, blendFile());
  const inspect = screen.getByRole('button', { name: 'Inspect with Blender' });
  fireEvent.click(inspect);
  fireEvent.click(inspect);
  expect(fetcher).toHaveBeenCalledTimes(1);
  localStorage.setItem('hud.admin_token', 'second');
  resolve(Response.json({ kind: 'blend', segments: [{ label: 'Overview', text: 'Scenes: 1', truncated: false }], total_segments: 1 }));
  await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Blender inspection' })).toBeNull());
  expect(submit).not.toHaveBeenCalled();
});

it('drops a prepared Blender passage if credentials rotate before Transmit', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ kind: 'blend', segments: [
    { label: 'Overview', text: 'Scenes: 1', truncated: false },
  ], total_segments: 1, thumbnail_png: null })));
  localStorage.setItem('hud.admin_token', 'first');
  const submit = vi.fn();
  const { container } = render(<InputBar onSubmit={submit} t={t}/>);
  choose(container, blendFile());
  fireEvent.click(screen.getByRole('button', { name: 'Inspect with Blender' }));
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Select a passage' })).toBeTruthy());
  fireEvent.click(screen.getByRole('button', { name: 'Attach shown text' }));
  fireEvent.click(screen.getByRole('button', { name: 'Done reviewing' }));
  localStorage.setItem('hud.admin_token', 'second');
  fireEvent.click(screen.getByRole('button', { name: 'Transmit' }));
  expect(submit).not.toHaveBeenCalled();
  expect(screen.queryByText(/Selected passage to send:/)).toBeNull();
});
