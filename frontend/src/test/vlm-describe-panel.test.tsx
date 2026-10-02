// @ts-nocheck
/* This authenticated route is strict loopback; optional policy warnings stay
   visible before upload and after successful inference. */
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
const retryNotice = 'May retry once with the same images and model after an empty response (at most two model calls).';

describe('VlmDescribePanel — the VLM input leg is really wired', () => {
  it('POSTs prompt + data-URI images to /api/vlm/describe and renders the answer', async () => {
    const fn = mockFetch({
      '/api/vlm/status': { payload: { configured: true, backend: 'lmstudio', base_url: 'http://localhost:1234/v1', default_model: 'qwen3-vl', local: true, reachable: null } },
      '/api/vlm/describe': { payload: { ok: true, model: 'qwen3-vl', response: 'a cat on a desk', retry_notice: retryNotice } },
    });
    render(<VlmDescribePanel />);
    await waitFor(() => expect(screen.getByLabelText('image files to describe')).toBeTruthy());
    await pick();
    typePrompt();
    fireEvent.click(screen.getByRole('button', { name: 'describe' }));
    await waitFor(() => expect(screen.getByText('a cat on a desk')).toBeTruthy());
    expect(screen.getByText(retryNotice)).toBeTruthy();
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

  it('refuses a non-loopback destination with no remote checkbox or POST', async () => {
    const fn = mockFetch({
      '/api/vlm/status': { payload: { configured: true, backend: 'custom', base_url: 'https://vision.example.com', default_model: 'gpt-vision', local: false } },
      '/api/vlm/describe': { payload: { ok: true, response: 'must not appear' } },
    });
    render(<VlmDescribePanel />);
    await waitFor(() => expect(screen.getByText(/vision.example.com/)).toBeTruthy());
    await pick(); typePrompt();
    const submit = screen.getByRole('button', { name: 'describe' });
    expect(submit.disabled).toBe(true);
    expect(screen.queryByRole('checkbox')).toBeNull();
    expect(screen.getByText(/refused/i)).toBeTruthy();
    fireEvent.click(submit);
    expect(describeCalls(fn)).toHaveLength(0);
  });

  it('shows status policy warnings before upload and retains response warnings after success', async () => {
    mockFetch({
      '/api/vlm/status': { payload: { configured: true, backend: 'custom', base_url: 'http://localhost:1234', local: true,
        data_policy: 'unknown', data_policy_note: 'Custom model policy is unknown.', warning: 'Review inputs before sending.', retry_notice: retryNotice } },
      '/api/vlm/describe': { payload: { ok: true, response: 'a local answer', warning: 'This request used an unknown-policy model.' } },
    });
    render(<VlmDescribePanel />);
    await waitFor(() => expect(screen.getByText('Review inputs before sending.')).toBeTruthy());
    expect(screen.getByText('Custom model policy is unknown.')).toBeTruthy();
    expect(screen.getByText(retryNotice)).toBeTruthy();
    await pick(); typePrompt();
    fireEvent.click(screen.getByRole('button', { name: 'describe' }));
    await waitFor(() => expect(screen.getByText('a local answer')).toBeTruthy());
    expect(screen.getByText('This request used an unknown-policy model.')).toBeTruthy();
    expect(screen.getByText('Review inputs before sending.')).toBeTruthy();
  });

  it('shows a 200 ok:false refusal and suppresses its fabricated response', async () => {
    mockFetch({
      '/api/vlm/status': { payload: { configured: true, backend: 'lmstudio', local: true } },
      '/api/vlm/describe': { payload: { ok: false, error: 'inference did not complete', response: 'must not appear' } },
    });
    render(<VlmDescribePanel />);
    await pick(); typePrompt();
    fireEvent.click(screen.getByRole('button', { name: 'describe' }));
    await waitFor(() => expect(screen.getByText(/inference did not complete/)).toBeTruthy());
    expect(screen.queryByText('must not appear')).toBeNull();
  });

  it('does not present an empty ok:true response as an answer', async () => {
    mockFetch({
      '/api/vlm/status': { payload: { configured: true, backend: 'lmstudio', local: true } },
      '/api/vlm/describe': { payload: { ok: true, model: 'false-success-model', response: '' } },
    });
    render(<VlmDescribePanel />);
    await pick(); typePrompt();
    fireEvent.click(screen.getByRole('button', { name: 'describe' }));
    await waitFor(() => expect(screen.getByText(/describe failed/)).toBeTruthy());
    expect(screen.queryByText(/model · false-success-model/)).toBeNull();
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
