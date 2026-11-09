import React from 'react';
import { expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StatusStrip, turnOutcome } from '../turn-outcome';

it('shows selected context, complete token counts and estimated cost in one outcome strip', () => {
  const outcome = turnOutcome({ context_detail: { prompt_tokens: 600, window_tokens: 1200 },
    context_pct: 50, usage_detail: { input_tokens: 1000, output_tokens: 200,
      estimated_cost_usd: 0.0042, usage_basis: 'provider_complete', cost_basis: 'price_table' } });
  render(<StatusStrip outcome={outcome} />);
  expect(screen.getByLabelText('Prompt context percent').textContent).toContain('50.0%');
  expect(screen.getByRole('progressbar', { name: 'Context usage meter' }).getAttribute('value')).toBe('50');
  expect(screen.getByLabelText('Turn usage').textContent).toContain('1,000 input / 200 output');
  expect(screen.getByLabelText('Turn usage').textContent).toContain('$0.004200 estimated');
});

it('shows unknown counters and price without a false zero', () => {
  const outcome = turnOutcome({ context_pct: 40,
    usage_detail: { input_tokens: null, output_tokens: null,
      estimated_cost_usd: null, usage_basis: 'unknown', cost_basis: 'unknown' } });
  render(<StatusStrip outcome={outcome} />);
  expect(screen.getByLabelText('Turn usage').textContent).toContain('tokens unknown');
  expect(screen.getByLabelText('Turn usage').textContent).toContain('cost unknown');
  expect(screen.getByLabelText('Turn usage').textContent).not.toContain('$0');
});
