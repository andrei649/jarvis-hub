// @ts-nocheck
/* review-H153e NIT-5 — a poller slower than its interval is always loading; its failed
   poll must still show, not hide behind "loading…". */
import { describe, it, expect } from 'vitest';
import React from 'react';
import { render, screen } from '@testing-library/react';
import { State } from '../panel-kit';

describe('State', () => {
  it('shows an error even while a newer request is out', () => {
    render(<State e="hub down" loading={true} n={0} />);
    expect(screen.getByText('offline · hub down')).toBeTruthy();
    expect(screen.queryByText('loading…')).toBeNull();
  });

  it('shows loading while nothing failed, and nothing yet when empty', () => {
    const { rerender } = render(<State e={null} loading={true} n={0} />);
    expect(screen.getByText('loading…')).toBeTruthy();
    rerender(<State e={null} loading={false} n={0} />);
    expect(screen.getByText('nothing yet')).toBeTruthy();
  });
});
