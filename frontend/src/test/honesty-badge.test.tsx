/* Tranche 3b — HUD honesty badges over the /plugins `honesty` verdict.

   The plugin registry must stop letting mock read as live: a plugin whose backend
   verdict is `live` gets a green LIVE badge, one still on a mock/degraded fallback
   gets an amber NEEDS SETUP badge whose tooltip names the exact config it needs,
   and seeded demo rows (no verdict) stay unbadged. */
import React from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

import { V2 } from '../data';
import { AdminMode } from '../modes3';

const T = { admin: 'ADMIN' };

function seedPlugins(plugins: any[]) {
  V2.ADMIN = { ...V2.ADMIN, plugins };
}

afterEach(cleanup);

describe('HonestyBadge in the plugin registry', () => {
  it('badges a live plugin LIVE and a mock one NEEDS SETUP with its needs in the tooltip', () => {
    seedPlugins([
      { id: 'weather', name: 'Weather', scope: 'wttr.in', net: 'restricted', on: true,
        honesty: { status: 'live', reason: 'no setup required', needs: [] } },
      { id: 'iot-control', name: 'Tuya SmartHome IoT', scope: 'openapi.tuya.com', net: 'restricted', on: true,
        honesty: { status: 'needs_config', reason: 'running in mock/degraded mode until configured',
          needs: ['plugins.tuya_client_id', 'plugins.tuya_secret'] } },
    ]);
    render(<AdminMode t={T} />);

    const live = screen.getByText('LIVE');
    expect(live).toBeTruthy();

    const needsSetup = screen.getByText('NEEDS SETUP');
    expect(needsSetup).toBeTruthy();
    const tooltip = needsSetup.closest('span[title]')?.getAttribute('title')
      || needsSetup.parentElement?.getAttribute('title') || '';
    expect(tooltip).toContain('plugins.tuya_secret');
  });

  it('leaves demo rows (no verdict) unbadged and counts live in the section header', () => {
    seedPlugins([
      { id: 'weather', name: 'Weather', scope: 'wttr.in', net: 'restricted', on: true,
        honesty: { status: 'live', reason: 'no setup required', needs: [] } },
      { name: 'Demo Plugin', scope: 'demo', net: 'restricted', on: true }, // seeded, no id/honesty
    ]);
    render(<AdminMode t={T} />);

    expect(screen.getAllByText('LIVE')).toHaveLength(1);
    expect(screen.queryByText('NEEDS SETUP')).toBeNull();
    expect(screen.getByText(/PLUGIN REGISTRY · 2\/2 enabled · 1 live/)).toBeTruthy();
  });

  it('shows no live count when no row carries a verdict (pure demo seed)', () => {
    seedPlugins([
      { name: 'Demo Plugin', scope: 'demo', net: 'restricted', on: true },
    ]);
    render(<AdminMode t={T} />);
    expect(screen.getByText(/PLUGIN REGISTRY · 1\/1 enabled$/)).toBeTruthy();
    expect(screen.queryByText('LIVE')).toBeNull();
  });
});
