// @ts-nocheck
/* Guide-gap wave — the "BRIEF ME" moment: the Autonomy panel's MORNING BRIEF
   header gains a 🔊 SPEAK button that reads the brief aloud via POST /tts
   (server cloned-voice chain) and falls back to the fully-local
   speechSynthesis when the server can't synthesize. fetch is mocked. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { AutonomyMode } from '../modes2';

const T = { autonomy: 'Autonomy' };

beforeEach(() => {
  try { localStorage.clear(); } catch { /* ignore */ }
  // getAutonomyMode fires on mount; give every fetch a benign default.
  global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ mode: 'ask' }) });
});

describe('AutonomyMode — speak the morning brief', () => {
  it('renders the SPEAK button next to the MORNING BRIEF header', async () => {
    render(<AutonomyMode t={T} />);
    const btn = screen.getByLabelText('speak brief');
    expect(btn).toBeTruthy();
    expect(btn.disabled).toBe(false);   // seeded brief rows exist
  });

  it('POSTs the brief text to /tts on click', async () => {
    const fn = global.fetch;
    render(<AutonomyMode t={T} />);
    // /tts fails → local speechSynthesis fallback path (stubbed) keeps it honest.
    fn.mockResolvedValue({ ok: false, status: 503, json: async () => ({}) });
    const spoken = [];
    global.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; } };
    Object.defineProperty(window, 'speechSynthesis', {
      configurable: true,
      value: { speak: (u) => { spoken.push(u.text); u.onend && u.onend(); } },
    });

    fireEvent.click(screen.getByLabelText('speak brief'));

    await waitFor(() => {
      const call = fn.mock.calls.find((c) => String(c[0]) === '/tts');
      expect(call).toBeTruthy();
      expect(call[1].method).toBe('POST');
      const body = JSON.parse(call[1].body);
      expect(body.text).toContain('Raiffeisen review is today at 14:00');
    });
    // Server refused → the local fallback actually spoke the same text.
    await waitFor(() => expect(spoken.length).toBe(1));
    expect(spoken[0]).toContain('Raiffeisen review is today at 14:00');
    // Button re-enables after playback (no stuck "SPEAKING…" state).
    await waitFor(() => expect(screen.getByLabelText('speak brief').disabled).toBe(false));
  });
});
