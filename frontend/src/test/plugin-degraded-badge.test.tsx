// @ts-nocheck
/* HONESTY: a plugin whose calls return MOCK data (degraded: true from /plugins)
   must be visibly badged in the Admin plugin registry — scaffold never reads as
   live. The tooltip carries the reason + the config the owner must supply. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { AdminMode } from '../modes3';
import { V2 } from '../data';

const t = V2.I18N.en;

beforeEach(() => {
  global.fetch = vi.fn(() => Promise.reject(new Error('offline'))) as any;
});

describe('AdminMode — degraded plugins are badged MOCK', () => {
  it('renders the MOCK badge with reason + needs in the tooltip', async () => {
    const original = V2.ADMIN.plugins;
    V2.ADMIN.plugins = [
      { id: 'sms-alerts', name: 'sms-alerts', scope: 'api.twilio.com', net: 'external', on: true,
        degraded: true, degradedReason: 'twilio_not_configured',
        degradedNeeds: ['plugins.twilio_account_sid'] },
      { id: 'weather', name: 'weather', scope: 'wttr.in', net: 'external', on: true, degraded: false },
    ];
    try {
      render(<AdminMode t={t} />);
      await waitFor(() => expect(screen.getByText('MOCK')).toBeTruthy());
      const badge = screen.getByText('MOCK');
      expect(badge.getAttribute('title')).toContain('twilio_not_configured');
      expect(badge.getAttribute('title')).toContain('plugins.twilio_account_sid');
      // Only the degraded plugin is badged.
      expect(screen.getAllByText('MOCK')).toHaveLength(1);
    } finally {
      V2.ADMIN.plugins = original;
    }
  });
});
