import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiPost, clearActionFailures } from '../api/client';
import { pageForRoute } from '../nav/routes';
import { POWER_UNKNOWN } from '../power-chip';
import { readSafeMode } from '../safe-mode-banner';
import type { HubSnapshot } from '../signals/types';
import { Notices, powerPieces, pressureSentence, safeModeText, type NoticesProps } from './Notices';
import { initialHubSnapshot } from './types';
import { stubHub } from './test-support';

/* Every item the hub can leave out in safe mode (safe-mode-banner.tsx LABELS). */
const SAFE_MODE_KEYS = ['owner_skills', 'mcp_servers', 'acquired_packages', 'plugin_grants', 'persona_overlays', 'heartbeat_overlays',
  'owner_jobs', 'plugins', 'outbound_webhooks', 'memory_injection', 'settings_overrides', 'project_context', 'voice_piper_binary',
  'voice_commands', 'company_mode', 'personality_overlays', 'owner_hooks'];

const page = pageForRoute({ mode: 'cockpit', panel: null });
const hubWith = (over: Partial<HubSnapshot> = {}): HubSnapshot => ({ ...initialHubSnapshot(), ...over } as HubSnapshot);
const show = (over: Partial<NoticesProps> = {}) => render(<Notices lang="en" hub={hubWith()} page={page} demo={false} showFailures={false} {...over} />);
const notice = (kind: string) => document.querySelector(`[data-notice="${kind}"]`) as HTMLElement | null;

afterEach(() => { clearActionFailures(); vi.unstubAllGlobals(); });

describe('Notices', () => {
  it('says nothing when there is nothing to say', () => {
    show();
    expect(document.querySelector('[data-frame="notices"]')?.children).toHaveLength(0);
  });

  it('names what safe mode left out, in both languages, and cannot be dismissed', () => {
    const state = readSafeMode({ enabled: true, skipped: SAFE_MODE_KEYS });
    expect(state.skipped).toEqual(SAFE_MODE_KEYS);
    for (const lang of ['en', 'ro'] as const) expect(safeModeText(state, lang)).not.toMatch(/sm_|undefined/);
    show({ hub: hubWith({ safeMode: readSafeMode({ enabled: true, skipped: ['plugins', 'owner_jobs'] }) }) });
    const line = notice('safe-mode') as HTMLElement;
    expect(line.getAttribute('role')).toBe('status');
    expect(line.textContent).toBe('Safe mode — left out: plugins, scheduled jobs. Restart without --safe-mode or JARVIS_SAFE_MODE to load them again.');
    expect(within(line).queryByRole('button')).toBeNull();
    expect(safeModeText(readSafeMode({ enabled: true, skipped: [] }), 'ro'))
      .toBe('Mod sigur — se încarcă doar abilitățile, personajele și programările livrate. Repornește fără --safe-mode sau JARVIS_SAFE_MODE ca să le încarci din nou.');
  });

  it('says the power state piece by piece', () => {
    expect(powerPieces(POWER_UNKNOWN, 'en')).toEqual([]);
    const battery = { ...POWER_UNKNOWN, onBattery: true, percent: 41, deferred: true, keepAwake: { enabled: true, active: false, refused: 'policy', error: null } };
    expect(powerPieces(battery, 'en')).toEqual(['On battery 41%', 'background jobs deferred', 'Keep-awake off: policy']);
    expect(powerPieces(battery, 'ro')).toEqual(['Pe baterie 41%', 'sarcinile de fundal sunt amânate', 'Menținerea trează e oprită: policy']);
    show({ power: battery });
    expect(notice('power')?.querySelector('[data-mark="attn"]')).not.toBeNull();
  });

  it('raises the worst memory or disk condition, with Dismiss for this boot', () => {
    expect(pressureSentence({ condition: 'disk_critical', percent: 97, paths: [{ path: 'C:\\', percent: 97 }] }, 'en'))
      .toBe('Disk almost full: C:\\ at 97%. Free some space, or the hub may stop saving your data.');
    expect(pressureSentence({ condition: 'memory_elevated', percent: null, paths: [] }, 'en')).toBe('Memory running high.');
    const onDismissPressure = vi.fn();
    show({ pressure: { bootId: 'boot-1', worst: { condition: 'memory_critical', percent: 93, paths: [] } }, onDismissPressure });
    const line = notice('pressure') as HTMLElement;
    expect(line.getAttribute('role')).toBe('alert');
    expect(line.textContent).toContain('Memory almost exhausted: 93% in use.');
    fireEvent.click(within(line).getByRole('button', { name: 'Dismiss' }));
    expect(onDismissPressure).toHaveBeenCalledWith('memory_critical', 'boot-1');
  });

  it('labels demo and lets the owner leave it', () => {
    const onExitDemo = vi.fn();
    show({ demo: true, onExitDemo });
    const line = notice('demo') as HTMLElement;
    expect(line.textContent).toContain('Demo sample on screen — seeded data, not your live hub.');
    // the canonical, shareable address of the sample (the 2026-07-14 honesty spec; DemoBanner's pin)
    expect(line.querySelector('code')?.textContent).toBe('/v2/?demo=1');
    expect(line.textContent).toContain('Its address: /v2/?demo=1');
    fireEvent.click(within(line).getByRole('button', { name: 'Exit demo' }));
    expect(onExitDemo).toHaveBeenCalled();
  });

  it('shows the first-run notice only when the hub answered with no model loaded', () => {
    const firstRun = { dismissed: false, onDismiss: vi.fn(), onDemo: vi.fn() };
    const noModel = hubWith({ serverUp: true, state: 'live', llm: { state: 'no_model', model: null, residents: [] } });
    const { unmount } = show({ hub: noModel, firstRun });
    const line = notice('first-run') as HTMLElement;
    expect(line.textContent).toContain('No language model is loaded yet');
    fireEvent.click(within(line).getByRole('button', { name: 'Show a demo sample' }));
    expect(firstRun.onDemo).toHaveBeenCalled();
    unmount();
    for (const hub of [hubWith({ serverUp: true, llm: { state: 'unknown', model: null, residents: [] } }),
      hubWith({ serverUp: false, llm: { state: 'no_model', model: null, residents: [] } }),
      hubWith({ serverUp: true, llm: { state: 'ready', model: 'gemma', residents: [] } })]) {
      const view = show({ hub, firstRun });
      expect(notice('first-run')).toBeNull();
      view.unmount();
    }
    show({ hub: noModel, firstRun: { ...firstRun, dismissed: true } });
    expect(notice('first-run')).toBeNull();
  });

  it('says a page was not found and where it returned', () => {
    const onDismissRouteNotice = vi.fn();
    show({ routeNotice: 'Page not found. Returned to cockpit.', onDismissRouteNotice });
    const line = notice('route') as HTMLElement;
    expect(line.textContent).toContain('Page not found. Returned to Today.');
    fireEvent.click(within(line).getByRole('button', { name: 'Dismiss' }));
    expect(onDismissRouteNotice).toHaveBeenCalled();
  });

  it('names the page the router fell back to, not the page on screen, as that page\'s heading names it', () => {
    // the owner moved on to Trust while the notice stood: it still names where the router returned
    const { unmount } = show({ page: pageForRoute({ mode: 'trust', panel: null }), routeNotice: 'x', routeNoticePage: page });
    expect(notice('route')?.textContent).toContain('Page not found. Returned to Today.');
    unmount();
    // a landing page is named by its area, as its heading is ("Trust"), never "Overview"
    show({ routeNotice: 'x', routeNoticePage: pageForRoute({ mode: 'trust', panel: null }) });
    expect(notice('route')?.textContent).toContain('Page not found. Returned to Trust.');
    expect(notice('route')?.textContent).not.toContain('Overview');
  });

  it('lists failed actions on every page, from the API client\'s record', async () => {
    stubHub(() => ({ status: 403, body: { error: 'kernel denied' } }), vi.stubGlobal);
    render(<Notices lang="en" hub={hubWith()} page={page} demo={false} />);
    expect(notice('failures')).toBeNull();
    await act(async () => { await apiPost('/api/security/kill-switch', { engage: true }, { admin: true }).catch(() => {}); });
    const line = notice('failures') as HTMLElement;
    expect(line.getAttribute('role')).toBe('alert');
    expect(line.textContent).toContain('1 action failed — the change did not happen.');
    expect(line.textContent).toContain('POST /api/security/kill-switch → 403');
    expect(line.textContent).toContain('refused (kernel denial or missing admin token)');
    fireEvent.click(within(line).getByRole('button', { name: 'Dismiss' }));
    expect(notice('failures')).toBeNull();
  });

  it('draws App\'s appearance sync notice as it is', () => {
    show({ appearanceNotice: <div role="status">Sync failed <button>Retry sync</button></div> });
    expect(within(notice('appearance') as HTMLElement).getByRole('button', { name: 'Retry sync' })).toBeTruthy();
  });

  it('speaks Romanian', () => {
    render(<Notices lang="ro" hub={hubWith()} page={page} demo onExitDemo={() => {}} routeNotice="x" showFailures={false} />);
    expect(screen.getByRole('button', { name: 'Ieși din demo' })).toBeTruthy();
    expect(notice('route')?.textContent).toContain('Pagina nu a fost găsită. Revenire la Azi.');
  });
});
