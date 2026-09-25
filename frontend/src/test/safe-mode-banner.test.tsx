// @ts-nocheck
/* H275 — the HUD says when the hub runs in safe mode, and names what was left out. */
import { describe, it, expect, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, cleanup } from '@testing-library/react';
import { SAFE_MODE_OFF, SafeModeBanner, readSafeMode, safeModeLabel } from '../safe-mode-banner';

beforeEach(() => cleanup());

describe('safe mode — H275', () => {
  it('reads the hub field and treats anything malformed as off', () => {
    expect(readSafeMode({ enabled: true, skipped: ['owner_skills', 'mcp_servers'] }))
      .toEqual({ enabled: true, skipped: ['owner_skills', 'mcp_servers'] });
    expect(readSafeMode({ enabled: true, skipped: ['owner_jobs', 'the_kernel', 3] }))
      .toEqual({ enabled: true, skipped: ['owner_jobs'] });
    expect(readSafeMode({ enabled: true })).toEqual({ enabled: true, skipped: [] });
    for (const raw of [undefined, null, true, 'on', { enabled: 'true' }, { enabled: false, skipped: ['owner_jobs'] }]) {
      expect(readSafeMode(raw)).toEqual(SAFE_MODE_OFF);
    }
  });

  it('names the layers left out, or what still loads', () => {
    expect(safeModeLabel({ enabled: true, skipped: ['owner_skills', 'owner_jobs'] }))
      .toBe('left out: your skills, scheduled jobs');
    expect(safeModeLabel({ enabled: true, skipped: [] })).toBe('only shipped skills, personas and schedules load');
  });

  it('names the reduced-posture layers (H490)', () => {
    const state = readSafeMode({ enabled: true,
      skipped: ['plugins', 'outbound_webhooks', 'memory_injection', 'settings_overrides'] });
    expect(state.skipped).toHaveLength(4);
    expect(safeModeLabel(state))
      .toBe('left out: plugins, outbound webhooks, memory in prompts, loosened settings');
  });

  it('shows a banner only in safe mode, with no way to dismiss it', () => {
    const { rerender, container } = render(<SafeModeBanner state={SAFE_MODE_OFF} />);
    expect(container.innerHTML).toBe('');
    rerender(<SafeModeBanner state={{ enabled: true, skipped: ['mcp_servers'] }} />);
    const banner = screen.getByTestId('safe-mode-banner');
    expect(banner.textContent).toContain('SAFE MODE');
    expect(banner.textContent).toContain('left out: saved MCP servers');
    expect(banner.querySelector('button')).toBeNull();
  });
});
