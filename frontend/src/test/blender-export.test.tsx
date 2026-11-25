import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { BlenderModel, blenderMeshRequest, hasInconsistentWinding, hasInwardClosedShell, parseBlenderObj } from '../blender-export';
import { apiExportBlender } from '../api/client';
import { Conversation, InputBar } from '../cockpit';
import { V2 } from '../data';
import { composerField, openComposerMenu } from '../home/talk/test-support';

const pyramid = 'o Beacon\nv -2 -2 0\nv 2 -2 0\nv 2 2 0\nv -2 2 0\nv 0 0 3\nf 1 2 3 4\nf -5 -4 -1\nf -4 -3 -1\nf -3 -2 -1\nf -2 -5 -1\n';
const points = 'o Beacon\nv -2 -2 0\nv 2 -2 0\nv 2 2 0\nv -2 2 0\nv 0 0 3\n';
const outward = points + 'f 4 3 2 1\nf 1 2 5\nf 2 3 5\nf 3 4 5\nf 4 1 5\n';
const inward = points + 'f 1 2 3 4\nf 5 2 1\nf 5 3 2\nf 5 4 3\nf 5 1 4\n';

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('parses the real pyramid, global negative indices and named objects without a network request', () => {
  const mesh = parseBlenderObj(pyramid + 'g Beacon cap\nf 1 2 5 # shared global vertices\n');
  expect(mesh.vertices).toHaveLength(5);
  expect(mesh.faces).toHaveLength(6);
  expect(mesh.sections.map(item => [item.name, item.faces])).toEqual([['Beacon', 5], ['Beacon cap', 1]]);
  expect(mesh.faces[1].indices).toEqual([0, 1, 4]);
  expect(() => parseBlenderObj('o Empty\nv 0 0 0\n')).toThrow();
  expect(() => parseBlenderObj('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1/1 2/2 3/3')).toThrow();
  expect(() => parseBlenderObj('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 4')).toThrow();
  expect(() => parseBlenderObj('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 2')).toThrow();
  expect(() => parseBlenderObj('v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\nf 1 2 3')).toThrow();
  expect(parseBlenderObj('v 0 0 0\nv 1 0 0\nv 0 1 0\nf +01 002 -1').sections[0].name).toBe('Mesh');
  expect(() => parseBlenderObj('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\no Mesh\nf 1 2 3')).toThrow();
  expect(hasInconsistentWinding(parseBlenderObj(pyramid))).toBe(true);
  expect(hasInconsistentWinding(parseBlenderObj('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3'))).toBe(false);
});

it('warns for a consistently reversed closed shell but not outward, open or degenerate geometry', () => {
  expect(hasInconsistentWinding(parseBlenderObj(outward))).toBe(false);
  expect(hasInconsistentWinding(parseBlenderObj(inward))).toBe(false);
  expect(hasInwardClosedShell(parseBlenderObj(outward))).toBe(false);
  expect(hasInwardClosedShell(parseBlenderObj(inward))).toBe(true);
  expect(hasInwardClosedShell(parseBlenderObj(inward.replace('f 5 1 4\n', '')))).toBe(false);
  expect(hasInwardClosedShell(parseBlenderObj('v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\nf 3 2 1\n'))).toBe(false);
  const view = render(<BlenderModel source={inward}/>);
  expect(screen.getByText(/closed shell appears to face inward based on signed volume/)).toBeTruthy();
  expect(screen.queryByText(/inconsistent winding/)).toBeNull();
  view.rerender(<BlenderModel source={outward}/>);
  expect(screen.queryByText(/face inward/)).toBeNull();
});

it('keeps the owner draft, recipient and normal Send when Blender mode is toggled', () => {
  const onSubmit = vi.fn(() => false);
  render(<InputBar selectedTurn agent="frigga" sessionId="here" recipientStatus="ready" onSubmit={onSubmit} t={V2.I18N.en}/>);
  const input = screen.getByPlaceholderText('Message Frigga…') as HTMLTextAreaElement;
  expect(input).toBe(composerField());
  fireEvent.change(input, { target: { value: 'A Beacon square pyramid with a 4×4 base at z=0 and centered tip at z=3.' } });
  openComposerMenu('options');   // the Blender toggle is in the composer's Options menu since the re-lay
  fireEvent.click(screen.getByRole('button', { name: 'Make editable Blender model' }));
  fireEvent.click(screen.getByText('Review instruction to send'));
  expect(screen.getByText(/Create an editable Blender model from this brief:/).textContent).toBe(blenderMeshRequest(input.value));
  expect(blenderMeshRequest(input.value)).toContain("Use Blender XYZ coordinates with Z up and XY as the ground plane. Follow the brief's named axes exactly.");
  fireEvent.click(screen.getByRole('button', { name: V2.I18N.en.transmit }));
  expect(onSubmit).toHaveBeenCalledWith(blenderMeshRequest(input.value));
  expect(input.value).toContain('Beacon square pyramid');
  fireEvent.click(screen.getByRole('button', { name: 'Make editable Blender model' }));
  fireEvent.click(screen.getByRole('button', { name: V2.I18N.en.transmit }));
  expect(onSubmit).toHaveBeenLastCalledWith(input.value);
  fireEvent.click(screen.getByRole('button', { name: 'Make editable Blender model' }));
  fireEvent.change(input, { target: { value: 'x'.repeat(4096) } });
  expect(screen.getByRole('alert').textContent).toContain('4,096');
  expect(screen.getByRole('button', { name: V2.I18N.en.transmit }).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Make editable Blender model' }));
  expect(screen.getByRole('button', { name: V2.I18N.en.transmit }).hasAttribute('disabled')).toBe(false);
});

it('shows a projected review only for completed OBJ replies, and downloads only on click', async () => {
  const fetch = vi.fn(async (_path, opts) => {
    expect(opts.body).toBe(pyramid);
    expect(opts.headers['Content-Type']).toBe('text/plain; charset=utf-8');
    return new Response('BLENDER-v300', { status: 200,
      headers: { 'Content-Type': 'application/x-blender', 'Content-Disposition': 'attachment; filename="Nerva model.blend"' } });
  });
  vi.stubGlobal('fetch', fetch);
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:blend');
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  const reply = { role: 'agent', who: 'frigga', text: `\`\`\`wavefront\n${pyramid}\`\`\``, _turnId: 1, _complete: true };
  const view = render(<Conversation messages={[reply]} thinking={null} exportAllowed lang="en" />);
  // the reply's own preview sits in its words (data-turn-body, the Ledger transcript)
  const body = document.querySelector('[data-turn="reply"] [data-turn-body]') as HTMLElement;
  expect(within(body).getByRole('img', { name: /Projected geometry preview: 5 vertices, 5 faces, 1 objects/ })).toBeTruthy();
  expect(within(body).getByText('Beacon (5)')).toBeTruthy();
  expect(within(body).getByText(/Some neighboring faces have inconsistent winding/)).toBeTruthy();
  expect(fetch).not.toHaveBeenCalled();
  // "Review Blender model" is in the reply's More menu since the re-lay (PHASE_B_PLAN.md §5.3, §8.3)
  const more = openComposerMenu('more', document.querySelector('[data-turn="reply"]') as HTMLElement);
  const opener = more.firstElementChild as HTMLButtonElement;
  fireEvent.click(within(more).getByRole('button', { name: 'Review Blender model' }));
  expect(screen.getByRole('dialog', { name: 'Review Blender model' })).toBeTruthy();
  expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Close model review' }));
  fireEvent.click(screen.getByRole('button', { name: 'Close model review' }));
  // focus returns to the control that opened it: More, since the item hides with its menu
  expect(document.activeElement).toBe(opener);
  fireEvent.click(screen.getByRole('button', { name: 'Download Blender project' }));
  await waitFor(() => expect(fetch).toHaveBeenCalledOnce());
  expect(fetch.mock.calls[0][0]).toBe('/api/canvas/blender-export');
  await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledOnce());
  view.rerender(<Conversation messages={[{ ...reply, _complete: false }]} thinking={{ label: 'thinking' }} exportAllowed />);
  expect(screen.queryByRole('button', { name: 'Download Blender project' })).toBeNull();
});

it('accepts native modern and Zstandard Blender project headers with admin credentials', async () => {
  localStorage.setItem('hud.admin_token', 'owner-token');
  const fetch = vi.fn()
    .mockResolvedValueOnce(new Response('BLENDER17-01v0503', { headers: {
      'Content-Type': 'application/x-blender', 'Content-Disposition': 'attachment; filename="Nerva model.blend"' } }))
    .mockResolvedValueOnce(new Response(new Uint8Array([0x28, 0xb5, 0x2f, 0xfd, 1, 2, 3, 4]), { headers: {
      'Content-Type': 'application/x-blender', 'Content-Disposition': 'attachment; filename="Nerva model.blend"' } }));
  vi.stubGlobal('fetch', fetch);
  expect((await apiExportBlender(pyramid)).size).toBeGreaterThan(0);
  expect((await apiExportBlender(pyramid)).size).toBeGreaterThan(0);
  expect(fetch.mock.calls[0][1].headers['X-Admin-Token']).toBe('owner-token');
  localStorage.clear();
});

it('refuses spoofed JSON and keeps the reply visible for retry', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ error: 'pretend export' })));
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:bad');
  render(<BlenderModel source={pyramid} lang="ro"/>);
  fireEvent.click(screen.getByRole('button', { name: 'Descarcă proiectul Blender' }));
  await screen.findByRole('alert');
  expect(URL.createObjectURL).not.toHaveBeenCalled();
  expect(screen.getByText('Beacon (5)')).toBeTruthy();
});

it('fits a subunit model in the same preview and rejects a fake Blender body with native headers', async () => {
  const tiny = 'v 0 0 0\nv .001 0 0\nv 0 .001 0\nf 1 2 3\n';
  const view = render(<BlenderModel source={tiny}/>);
  const points = view.container.querySelector('polygon')!.getAttribute('points')!;
  const xValues = points.split(' ').map(pair => Number(pair.split(',')[0]));
  expect(Math.max(...xValues) - Math.min(...xValues)).toBeGreaterThan(100);
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{"error":"spoofed"}', { status: 200,
    headers: { 'Content-Type': 'application/x-blender', 'Content-Disposition': 'attachment; filename="Nerva model.blend"' } })));
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:bad');
  fireEvent.click(screen.getByRole('button', { name: 'Download Blender project' }));
  await screen.findByRole('alert');
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});
