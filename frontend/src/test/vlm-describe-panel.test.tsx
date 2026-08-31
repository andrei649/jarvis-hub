// @ts-nocheck
/* DRA-29 — the VLM *input* leg. Before this panel the HUD could read
   `GET /api/vlm/status` (LOCAL MODELS renders the config line) but nothing in the
   product ever called `POST /api/vlm/describe`: the multimodal surface was
   output-only. These tests pin the wiring AND the egress disclosure — the route
   has no is_local gate, so a non-loopback VLM must never receive owner-picked
   images without an explicit, per-session acknowledgement. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { VlmDescribePanel } from '../gap';

beforeEach(() => { try { localStorage.clear(); } catch { /* ignore */ } });

/* routes: { path-fragment: () => ({status, payload}) } */
function mockFetch(routes) {
  const fn = vi.fn().mockImplementation(async (url) => {
    const u = String(url);
    const hit = Object.keys(routes).find((k) => u.includes(k));
    if (!hit) return { ok: true, status: 200, json: async () => ({}) };
    const r = routes[hit];
    const status = r.status || 200;
    return { ok: status < 400, status, json: async () => r.payload };
  });
  global.fetch = fn;
  return fn;
}

const pngFile = (name = 'a.png') => new File([new Uint8Array([137, 80, 78, 71])], name, { type: 'image/png' });

async function pick(name = 'a.png') {
  const input = screen.getByLabelText('image files to describe');
  fireEvent.change(input, { target: { files: [pngFile(name)] } });
  await waitFor(() => expect(screen.getByText(new RegExp(name))).toBeTruthy());
}

function typePrompt(text = 'what is in this image?') {
  fireEvent.change(screen.getByLabelText('describe prompt'), { target: { value: text } });
}

const describeCalls = (fn) => fn.mock.calls.filter((c) => String(c[0]).includes('/api/vlm/describe'));

describe('VlmDescribePanel — the VLM input leg is really wired', () => {
  it('POSTs prompt + data-URI images to /api/vlm/describe and renders the answer', async () => {
    const fn = mockFetch({
      '/api/vlm/status': { payload: { configured: true, backend: 'lmstudio', base_url: 'http://localhost:1234/v1', default_model: 'qwen3-vl', local: true, reachable: null } },
      '/api/vlm/describe': { payload: { ok: true, model: 'qwen3-vl', response: 'a cat on a desk' } },
    });
    render(<VlmDescribePanel />);
    await waitFor(() => expect(screen.getByLabelText('image files to describe')).toBeTruthy());
    await pick();
    typePrompt();
    fireEvent.click(screen.getByRole('button', { name: 'describe' }));
    await waitFor(() => expect(screen.getByText('a cat on a desk')).toBeTruthy());
    const call = describeCalls(fn)[0];
    expect(call).toBeTruthy();
    expect(call[1].method).toBe('POST');
    const body = JSON.parse(call[1].body);
    expect(body.prompt).toBe('what is in this image?');
    expect(body.images.length).toBe(1);
    expect(String(body.images[0]).startsWith('data:image/')).toBe(true);
  });

  it('renders the backend reason and stays inert when no VLM is configured', async () => {
    const fn = mockFetch({
      '/api/vlm/status': { payload: { configured: false, backend: 'off', reason: 'JARVIS_VLM_URL unset', default_model: null, reachable: null } },
    });
    render(<VlmDescribePanel />);
    await waitFor(() => expect(screen.getByText(/JARVIS_VLM_URL unset/)).toBeTruthy());
    expect(screen.getByRole('button', { name: 'describe' }).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'describe' }));
    await waitFor(() => expect(describeCalls(fn).length).toBe(0));
  });

  it('surfaces a 503 as an honest failure instead of a fabricated description', async () => {
    mockFetch({
      '/api/vlm/status': { payload: { configured: true, backend: 'lmstudio', base_url: 'http://localhost:1234/v1', default_model: 'qwen3-vl', local: true } },
      '/api/vlm/describe': { status: 503, payload: { error: 'VLM not configured', reason: 'vlm_disabled' } },
    });
    render(<VlmDescribePanel />);
    await waitFor(() => expect(screen.getByLabelText('image files to describe')).toBeTruthy());
    await pick();
    typePrompt();
    fireEvent.click(screen.getByRole('button', { name: 'describe' }));
    await waitFor(() => expect(screen.getByText(/describe failed/)).toBeTruthy());
    expect(screen.getByText(/503/)).toBeTruthy();
    expect(screen.queryByText('a cat on a desk')).toBeNull();
  });

  it('refuses to upload to a non-loopback VLM until the destination is acknowledged', async () => {
    const fn = mockFetch({
      '/api/vlm/status': { payload: { configured: true, backend: 'custom', base_url: 'https://vision.example.com/v1', default_model: 'gpt-vision', local: false } },
      '/api/vlm/describe': { payload: { ok: true, model: 'gpt-vision', response: 'a cat on a desk' } },
    });
    render(<VlmDescribePanel />);
    // the destination host is named verbatim, not hidden behind "remote"
    await waitFor(() => expect(screen.getByText(/https:\/\/vision\.example\.com\/v1/)).toBeTruthy());
    await pick();
    typePrompt();
    fireEvent.click(screen.getByRole('button', { name: 'describe' }));
    await waitFor(() => expect(screen.getByText(/refused/)).toBeTruthy());
    expect(describeCalls(fn).length).toBe(0);   // not one byte left the host

    fireEvent.click(screen.getByLabelText(/acknowledge/i));
    fireEvent.click(screen.getByRole('button', { name: 'describe' }));
    await waitFor(() => expect(screen.getByText('a cat on a desk')).toBeTruthy());
    expect(describeCalls(fn).length).toBe(1);
  });

  it('keeps a loopback VLM free of the acknowledgement gate', async () => {
    mockFetch({
      '/api/vlm/status': { payload: { configured: true, backend: 'lmstudio', base_url: 'http://localhost:1234/v1', default_model: 'qwen3-vl', local: true } },
    });
    render(<VlmDescribePanel />);
    await waitFor(() => expect(screen.getByLabelText('image files to describe')).toBeTruthy());
    expect(screen.queryByLabelText(/acknowledge/i)).toBeNull();
  });
});
