// @ts-nocheck
/* O26-P3.1 — the six design-preview modes must have honest live gates.
   Finance in particular must not flip LIVE from the balance plugin's realistic
   mock payload (`mock:true`); that stays SEED until real owner data is wired. */
import { describe, expect, it } from 'vitest';
import { MODE_LIVE_KEYS } from '../app';
import { balancePayloadIsLive, pluginIsConfigured } from '../api/live';
import { FinanceMode } from '../modes4';
import { CommsMode } from '../modes3';
import { V2 } from '../data';
import { liveSourceState } from '../LiveSourceChip';
import React from 'react';
import { render, screen } from '@testing-library/react';

describe('preview mode live-key coverage', () => {
  it('covers all six P3.1 preview modes', () => {
    for (const mode of ['build', 'comms', 'finance', 'health', 'knowledge', 'family']) {
      expect(MODE_LIVE_KEYS[mode]).toEqual([mode.toUpperCase()]);
      expect(liveSourceState(mode, false, { [mode.toUpperCase()]: true }, MODE_LIVE_KEYS)).toBe('live');
    }
  });
});

describe('preview mode plugin honesty helpers', () => {
  it('does not treat enabled-but-unconfigured plugins as configured', () => {
    expect(pluginIsConfigured({ id: 'balance', enabled: true, configured: false })).toBe(false);
    expect(pluginIsConfigured({ id: 'balance', enabled: false, configured: true })).toBe(false);
    expect(pluginIsConfigured({ id: 'balance', enabled: true, configured: true })).toBe(true);
  });

  it('keeps balance mock payloads out of LIVE finance', () => {
    expect(balancePayloadIsLive({ mock: true, ing: [{ balance: 100 }] })).toBe(false);
    expect(balancePayloadIsLive({ mock: false, csv: [{ balance: 100 }] })).toBe(true);
  });
});

describe('Finance preview honesty', () => {
  it('does not render the seeded sweep banner when live finance has no pending items', () => {
    const original = V2.FINANCE;
    try {
      V2.FINANCE = { ...original, net_worth: '—', mom: 'owner data', accounts: [], budgets: [], watches: [], pending: [] };
      render(React.createElement(FinanceMode, { t: V2.I18N.en }));
      expect(screen.queryByText(/sweep awaiting approval/i)).toBeNull();
    } finally {
      V2.FINANCE = original;
    }
  });
});

describe('Comms preview honesty', () => {
  it('can render configured channels without seeded inbox threads', () => {
    const original = V2.COMMS;
    try {
      V2.COMMS = { ...original, threads: [], channels: [{ id: 'discord', label: 'Discord', count: 0 }] };
      render(React.createElement(CommsMode, { t: V2.I18N.en }));
      expect(screen.getByText(/no live comms threads/i)).toBeTruthy();
    } finally {
      V2.COMMS = original;
    }
  });
});
