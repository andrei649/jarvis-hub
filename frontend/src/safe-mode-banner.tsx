/* H275 — the hub was started in safe mode (JARVIS_SAFE_MODE / serve.py --safe-mode):
   only shipped skills, personas and schedules loaded, and (H490) no plugins, outbound
   webhooks, memory in prompts or loosened settings. The banner says so on every
   page while it lasts and names what was left out; it cannot be dismissed, since the
   hub behaving differently from what the owner configured is the thing to notice. */
import React from 'react';
import { LABEL } from './theme/type';

export interface SafeModeState {
  enabled: boolean;
  skipped: string[];
}

export const SAFE_MODE_OFF: SafeModeState = { enabled: false, skipped: [] };

const LABELS: Record<string, string> = {
  owner_skills: 'your skills',
  mcp_servers: 'saved MCP servers',
  acquired_packages: 'acquired packages',
  plugin_grants: 'plugin grants',
  persona_overlays: 'persona overlays',
  heartbeat_overlays: 'heartbeat overlays',
  owner_jobs: 'scheduled jobs',
  plugins: 'plugins',
  outbound_webhooks: 'outbound webhooks',
  memory_injection: 'memory in prompts',
  settings_overrides: 'loosened settings',
  project_context: 'project convention files',
  voice_piper_binary: 'the Piper voice program',
  voice_commands: 'voice command providers',
  company_mode: 'the company-mode night shift',
  personality_overlays: 'personality presets',
  owner_hooks: 'your event hooks',
};

/** The hub's `safe_mode` field as the HUD holds it; anything malformed is "off". */
export function readSafeMode(raw: unknown): SafeModeState {
  if (!raw || typeof raw !== 'object' || (raw as any).enabled !== true) return SAFE_MODE_OFF;
  const skipped = Array.isArray((raw as any).skipped)
    ? (raw as any).skipped.filter((s: unknown) => typeof s === 'string' && s in LABELS)
    : [];
  return { enabled: true, skipped };
}

export function safeModeLabel(state: SafeModeState): string {
  const left = state.skipped.map((s) => LABELS[s]);
  return left.length
    ? `left out: ${left.join(', ')}`
    : 'only shipped skills, personas and schedules load';
}

export function SafeModeBanner({ state }: { state: SafeModeState }) {
  if (!state.enabled) return null;
  return (
    <div role="status" data-testid="safe-mode-banner"
      style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12, flexWrap: 'wrap', padding: '4px 12px',
        background: 'repeating-linear-gradient(45deg, var(--n-bad-wash) 0 12px, transparent 12px 24px)',
        borderBottom: '1px solid var(--red)', fontSize: 'var(--n-fs-meta)',
        color: 'var(--red)' }}>
      <span style={LABEL}>⚠ SAFE MODE</span>
      <span>
        {safeModeLabel(state)} · restart without --safe-mode or JARVIS_SAFE_MODE to load them again
      </span>
    </div>
  );
}
