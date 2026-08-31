// @ts-nocheck
/* DRA-06 — the 0.65 screen reflex had no product surface at all: the
   capture-to-answer core (agents/core/screen_reflex.py) had zero non-test
   importers and no route. `ScreenReflexPanel` drives the new
   POST /api/screen/reflex with screenshot BYTES the console can really produce
   (file pick, paste, or getDisplayMedia). The OS-level grab + the 0.64 global
   hotkey stay host-gated, and the panel says so rather than faking them. */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { ScreenReflexPanel } from '../gap';

const vlmStatus = { configured: true, backend: 'custom', base_url: 'http://localhost:1234/v1', default_model: 'qwen2.5-vl', local: true, reachable: null };

let reflex = { ok: true, generated: true, mode: 'answer', model: 'qwen2.5-vl', answer: 'A settings window is open.', question: 'what is open?' };
let reflexStatus = 200;

function response(payload, ok = true, status = 200) {
  return Promise.resolve({ ok, status, json: async () => payload });
}

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
  reflexStatus = 200;
  reflex = { ok: true, generated: true, mode: 'answer', model: 'qwen2.5-vl', answer: 'A settings window is open.', question: 'what is open?' };
  global.fetch = vi.fn((url) => (String(url).includes('/api/screen/reflex')
    ? response(reflex, reflexStatus === 200, reflexStatus)
    : response(vlmStatus)));
});

afterEach(() => {
  if (Object.getOwnPropertyDescriptor(navigator, 'mediaDevices')) {
    // @ts-ignore — remove the per-test stub
    delete navigator.mediaDevices;
  }
});

async function pickAFile() {
  const input = screen.getByLabelText('screenshot image file');
  fireEvent.change(input, { target: { files: [new File(['\x89PNG\r\n'], 'shot.png', { type: 'image/png' })] } });
  await waitFor(() => expect(screen.getByRole('button', { name: /observe screen/i }).disabled).toBe(false));
}

describe('ScreenReflexPanel (DRA-06)', () => {
  it('renders without getDisplayMedia and offers the file/paste input instead', async () => {
    render(<ScreenReflexPanel />);
    await waitFor(() => expect(screen.getByLabelText('screenshot image file')).toBeTruthy());
    expect(screen.queryByRole('button', { name: /capture screen/i })).toBeNull();
    // the honest posture is stated, not implied
    expect(screen.getByText(/held in memory and sent only to the loopback VLM/i)).toBeTruthy();
    expect(screen.getByText(/global hotkey/i)).toBeTruthy();
  });

  it('POSTs the screenshot bytes and renders the answer', async () => {
    render(<ScreenReflexPanel />);
    await waitFor(() => expect(screen.getByLabelText('screenshot image file')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('reflex question'), { target: { value: 'what is open?' } });
    await pickAFile();
    fireEvent.click(screen.getByRole('button', { name: /observe screen/i }));

    await waitFor(() => expect(screen.getByText(/A settings window is open\./)).toBeTruthy());
    const call = vi.mocked(global.fetch).mock.calls.find(([u]) => String(u) === '/api/screen/reflex');
    expect(call[1].method).toBe('POST');
    const body = JSON.parse(call[1].body);
    expect(body.question).toBe('what is open?');
    expect(body.mode).toBe('answer');
    expect(typeof body.image_base64).toBe('string');
    expect(body.image_base64.length).toBeGreaterThan(0);
    expect(body.image_base64).not.toContain('data:');   // bytes only, no data URI prefix
  });

  it('renders a 200 ok:false reason verbatim and no answer', async () => {
    reflex = { ok: false, generated: false, mode: 'answer', reason: 'no local VLM configured (set JARVIS_VLM_URL)' };
    render(<ScreenReflexPanel />);
    await waitFor(() => expect(screen.getByLabelText('screenshot image file')).toBeTruthy());
    await pickAFile();
    fireEvent.click(screen.getByRole('button', { name: /observe screen/i }));

    await waitFor(() => expect(screen.getByText('no local VLM configured (set JARVIS_VLM_URL)')).toBeTruthy());
    expect(screen.queryByText(/A settings window is open/)).toBeNull();
  });

  it('renders a 503 refusal instead of reading as success', async () => {
    reflexStatus = 503;
    reflex = { ok: false, generated: false, reason: 'screen reflex refuses a non-loopback VLM' };
    render(<ScreenReflexPanel />);
    await waitFor(() => expect(screen.getByLabelText('screenshot image file')).toBeTruthy());
    await pickAFile();
    fireEvent.click(screen.getByRole('button', { name: /observe screen/i }));

    await waitFor(() => expect(screen.getByText(/refused ·.*503/)).toBeTruthy());
    expect(screen.queryByText(/A settings window is open/)).toBeNull();
  });

  it('lists grounded elements in ground mode', async () => {
    reflex = { ok: true, generated: true, mode: 'ground', model: 'qwen2.5-vl', answer: 'Save at (12, 34)\nCancel at (90, 34)',
      elements: [{ label: 'Save', x: 12, y: 34, source: 'vlm' }, { label: 'Cancel', x: 90, y: 34, source: 'vlm' }] };
    render(<ScreenReflexPanel />);
    await waitFor(() => expect(screen.getByLabelText('screenshot image file')).toBeTruthy());
    fireEvent.change(screen.getByLabelText('reflex mode'), { target: { value: 'ground' } });
    await pickAFile();
    fireEvent.click(screen.getByRole('button', { name: /observe screen/i }));

    await waitFor(() => expect(screen.getByText(/Save · \(12, 34\)/)).toBeTruthy());
    expect(screen.getByText(/Cancel · \(90, 34\)/)).toBeTruthy();
    expect(JSON.parse(vi.mocked(global.fetch).mock.calls.find(([u]) => String(u) === '/api/screen/reflex')[1].body).mode).toBe('ground');
  });

  it('warns when the configured VLM is not loopback — the route will refuse', async () => {
    global.fetch = vi.fn((url) => (String(url).includes('/api/screen/reflex')
      ? response(reflex)
      : response({ ...vlmStatus, local: false, base_url: 'http://gpu-box.lan:8000/v1' })));
    render(<ScreenReflexPanel />);
    await waitFor(() => expect(screen.getByText(/not loopback/i)).toBeTruthy());
  });

  it('offers capture screen when getDisplayMedia exists and surfaces a denial', async () => {
    const getDisplayMedia = vi.fn().mockRejectedValue(new Error('Permission denied'));
    Object.defineProperty(navigator, 'mediaDevices', { value: { getDisplayMedia }, configurable: true });
    render(<ScreenReflexPanel />);
    await waitFor(() => expect(screen.getByRole('button', { name: /capture screen/i })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /capture screen/i }));
    await waitFor(() => expect(getDisplayMedia).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText(/refused · screen capture/i)).toBeTruthy());
  });
});
