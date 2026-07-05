// @ts-nocheck
/* HONESTY tests: controls whose backend genuinely doesn't exist must render DISABLED
   (never a no-op button that looks live). Seeded Comms preview rows have no real
   thread id, so Reply/Hand/Archive stay disabled. Live channel inbox rows are
   tested separately. (The autonomy AUTO/ASK/OFF mode IS wired now — see wired-controls.) */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { CommsMode } from '../modes3';
import { V2 } from '../data';

const t = V2.I18N.en;

beforeEach(() => {
  // No control should call the network in these tests; fail loudly if one does.
  global.fetch = vi.fn(() => Promise.reject(new Error('no network in disabled-control tests'))) as any;
});

describe('CommsMode — seeded channel inbox rows stay disabled', () => {
  it('renders Reply / Hand / Archive disabled', async () => {
    render(<CommsMode t={t} />);
    expect((screen.getByText(/^Reply via/) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByText('Hand to agent') as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByText('Archive') as HTMLButtonElement).disabled).toBe(true);
    // Let the embedded RoomsPanel's mount fetch settle (rejected) inside act().
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  });
});
