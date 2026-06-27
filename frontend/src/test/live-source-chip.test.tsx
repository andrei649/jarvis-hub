// @ts-nocheck
/* CDX-9 — LIVE vs SEED is now visible. Pure logic + presentational render. */
import { describe, it, expect } from 'vitest';
import React from 'react';
import { render, screen } from '@testing-library/react';
import { LiveSourceChip, liveSourceState } from '../LiveSourceChip';

const KEYS = { observe: ['OBSERVE'], trust: ['AUDIT_CHAIN', 'PAYMENTS'], build: undefined };

describe('liveSourceState (CDX-9)', () => {
  it('is "live" when any of the mode keys reported live', () => {
    expect(liveSourceState('observe', false, { OBSERVE: true }, KEYS)).toBe('live');
    expect(liveSourceState('trust', false, { PAYMENTS: true }, KEYS)).toBe('live');  // any key
  });
  it('is "seed" when demo is on but no source is live', () => {
    expect(liveSourceState('observe', true, {}, KEYS)).toBe('seed');
  });
  it('is null when neither live nor demo (ModeEmpty is showing)', () => {
    expect(liveSourceState('observe', false, {}, KEYS)).toBeNull();
  });
  it('is null when the mode has no backend-source mapping', () => {
    expect(liveSourceState('build', true, { OBSERVE: true }, KEYS)).toBeNull();
  });
});

describe('LiveSourceChip', () => {
  it('renders a LIVE chip', () => {
    render(<LiveSourceChip state="live" />);
    expect(screen.getByText('LIVE')).toBeTruthy();
  });
  it('renders a SEED chip', () => {
    render(<LiveSourceChip state="seed" />);
    expect(screen.getByText('SEED')).toBeTruthy();
  });
  it('renders nothing when state is null', () => {
    const { container } = render(<LiveSourceChip state={null} />);
    expect(container.textContent).toBe('');
  });
});
