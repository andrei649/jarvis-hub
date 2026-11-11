import { appUrl } from '../base-path';
/* HUD v2 · interactive-control bindings — the write side of the capability modes.
   Each helper hits a REAL endpoint verified against agents/web.py; the mode files
   call these so a button is either live (posts to the backend) or rendered DISABLED
   when no endpoint exists (never a no-op that looks live). Mirrors the gap.tsx
   Console pattern (apiGet/apiPost/apiPut), but reused from the always-visible modes.

   CDX-9: typed against the documented response shapes (removing the old @ts-nocheck)
   so a backend shape change is caught at the call boundary. Interfaces capture the
   fields the HUD reads; unconsumed POST responses stay `unknown`. */
import { apiGet, apiPost, apiPut } from './client';

// ── response shapes (the fields the HUD consumes) ─────────────────────────────
// The public read is an aggregate. Never retain persisted scope or reason text here.
export interface KillSwitchState { global: boolean; any_halted: boolean; halted_count: number }
export function isKillSwitchState(raw: unknown): raw is KillSwitchState {
  if (!raw || typeof raw !== 'object') return false;
  const state = raw as Record<string, unknown>;
  return typeof state.global === 'boolean' && typeof state.any_halted === 'boolean' &&
    typeof state.halted_count === 'number' && Number.isSafeInteger(state.halted_count) &&
    state.halted_count >= 0 && state.any_halted === (state.halted_count > 0) &&
    (!state.global || state.any_halted);
}
export interface AuditVerifyResult { valid: boolean; first_invalid_id: number | null; entries: number }

export interface NorthStarMetrics {
  days: number;
  north_star: { accepted_per_active_user: number | null; total_accepted: number | null; active_users: number | null };
  counter_metrics: {
    interrupt_rate_per_day: number | null; reject_rate: number | null;
    local_pct: number | null; p95_latency_ms: number | null;
  };
  night_shift?: { done: number; pct: number | null; window: [number, number] };
  proposal_funnel?: { proposed: number; surfaced: number; accepted: number; rejected: number;
                      pending: number; surface_rate: number | null; accept_rate: number | null } | null;
  interrupt_budget?: { per_day: number; remaining: number } | null;
  raw?: Record<string, number>;
}

export interface MarketplaceSkill { name: string; signed?: boolean; review_status?: string }
export interface MarketplaceList { skills: MarketplaceSkill[] }
export interface PluginInfo { id: string; name: string; enabled: boolean; [k: string]: unknown }
export interface PluginList { plugins: PluginInfo[] }
export interface AgentSoul { agent_id: string; soul: string; description?: string }
export interface AgentHistory { agent_id: string; runs: unknown[] }
export interface MemorySearchResult { results: Array<{ score: number; payload: unknown; sources?: unknown }> }
export interface KgEntities { entities: unknown[] }
export type AutonomyModeValue = 'auto' | 'ask' | 'off';
export interface AutonomyModeState { mode: AutonomyModeValue }

/* ── Trust · kill-switch (modes.tsx) ─────────────────────────────
   GET  /api/security/kill-switch        → { global, any_halted, halted_count }
   POST /api/security/kill-switch {engage,scope,reason}  (admin) */
export async function getKillSwitch(): Promise<KillSwitchState> {
  const raw = await apiGet<unknown>('/api/security/kill-switch');
  if (!isKillSwitchState(raw)) throw new Error('Invalid kill-switch status');
  return { global: raw.global, any_halted: raw.any_halted, halted_count: raw.halted_count };
}
export async function setKillSwitch(engage: boolean): Promise<unknown> {
  return apiPost('/api/security/kill-switch', { engage, scope: 'global', reason: 'hud' }, { admin: true });
}

/* ── Trust · live audit-chain verification (modes.tsx) ───────────
   GET /api/security/audit/verify → { valid, first_invalid_id, entries }
   Makes the "Merkle-verified" badge honest: it reflects a real chain check,
   not a static claim. */
export async function getAuditVerify(): Promise<AuditVerifyResult> {
  return apiGet<AuditVerifyResult>('/api/security/audit/verify');
}

/* ── Analytics · MOONSHOT §6 north-star meter (modes2.tsx · ObserveMode) ──
   GET /api/metrics/north-star?days=N → north_star + counter_metrics + night_shift
   + proposal_funnel + interrupt_budget + raw. The 1.0-gating metric. Every value
   is null (not a fabricated 0) when its source has no data — the meter renders "—". */
export async function getNorthStar(days = 7): Promise<NorthStarMetrics> {
  return apiGet<NorthStarMetrics>(`/api/metrics/north-star?days=${days}`);
}

/* ── Build · marketplace skill install (modes2.tsx) ──────────────
   GET  /api/skills/marketplace          → { skills:[{name,signed,review_status}] } (admin)
   POST /api/skills/marketplace/install {name}  (admin, H12.12) */
export async function listMarketplace(): Promise<MarketplaceList> {
  return apiGet<MarketplaceList>('/api/skills/marketplace', { admin: true });
}
export async function installSkill(name: string): Promise<unknown> {
  return apiPost('/api/skills/marketplace/install', { name }, { admin: true });
}

/* ── Admin · plugin enable/disable (modes3.tsx) ──────────────────
   GET /plugins                          → { plugins:[{id,name,enabled,...}] }
   PUT /plugins/{id}/toggle              → flips enabled (no body) */
export async function listPlugins(): Promise<PluginList> {
  return apiGet<PluginList>('/plugins');
}
export async function togglePlugin(id: string): Promise<unknown> {
  return apiPut('/plugins/' + encodeURIComponent(id) + '/toggle');
}

/* ── Comms · live channel inbox governed reply (modes3.tsx) ──────
   POST /api/channels/inbox/{thread_id}/reply {text,agent,source}
   Queues a reply draft into the existing approval funnel; it does not send
   until approved. */
export async function queueChannelReply(threadId: string, text: string, agent = 'veronica'): Promise<unknown> {
  return apiPost('/api/channels/inbox/' + encodeURIComponent(threadId) + '/reply', {
    text,
    agent,
    source: 'hud.comms',
  });
}

/* ── Dossier · agent soul + history (modes.tsx) ──────────────────
   GET /api/agents/{id}/soul             → { agent_id, soul }
   GET /api/agents/{id}/history          → { agent_id, runs:[...] } */
export async function getAgentSoul(id: string): Promise<AgentSoul> {
  return apiGet<AgentSoul>('/api/agents/' + encodeURIComponent(id) + '/soul');
}
export async function getAgentHistory(id: string): Promise<AgentHistory> {
  return apiGet<AgentHistory>('/api/agents/' + encodeURIComponent(id) + '/history');
}

/* ── Memory · live recalls + topics + KG (modes.tsx) ─────────────
   GET /api/memory/search?q=             → { results:[{score,payload,sources}] }
   GET /api/kg/entities                  → { entities:[...] } */
export async function memorySearch(q: string): Promise<MemorySearchResult> {
  return apiGet<MemorySearchResult>('/api/memory/search?q=' + encodeURIComponent(q) + '&top_k=8');
}
export async function kgEntities(limit = 60): Promise<KgEntities> {
  return apiGet<KgEntities>('/api/kg/entities?limit=' + limit);
}

/* ── Autonomy · global mode AUTO/ASK/OFF (modes2.tsx) ────────────
   GET  /autonomy/mode         → { mode: "auto"|"ask"|"off" } (admin)
   POST /autonomy/mode {mode}  → persists + applies live (admin) */
export async function getAutonomyMode(): Promise<AutonomyModeState> {
  return apiGet<AutonomyModeState>('/autonomy/mode', { admin: true });
}
/* H484 — a mode or override write the hub refused is an ANSWER, not a thrown failure:
   503 `mode_not_saved` (nothing stored), 503 `mode_not_effective` (stored, but the live
   policy runs `live`), 422 `invalid_agent`. The caller shows the mode in force and why. */
const modeRefusal = (status: number, body: unknown) =>
  (status === 503 || status === 422) && !!body && typeof body === 'object' && typeof (body as any).error === 'string';
export async function setAutonomyMode(mode: string): Promise<unknown> {
  return apiPost('/autonomy/mode', { mode }, { admin: true, accept: modeRefusal });
}
export async function setAgentAutonomyMode(agent: string, mode: string): Promise<unknown> {
  return apiPost('/autonomy/policy', { agent, mode }, { admin: true, accept: modeRefusal });
}
const KNOWN_MODES = ['auto', 'ask', 'off'];
/* What to tell the owner about a refused global-mode write, and the mode to display:
   the one the hub says is in force, never the one that was clicked. */
export function modeRefusalNote(asked: string, r: any): { live: string | null; text: string } | null {
  if (!r || typeof r !== 'object' || typeof r.error !== 'string') return null;
  const live = KNOWN_MODES.includes(r.live) ? r.live : KNOWN_MODES.includes(r.mode) ? r.mode : null;
  const now = live ? ` ${live.toUpperCase()} is in force.` : '';
  if (r.error === 'mode_not_saved') return { live, text: `${asked.toUpperCase()} was not saved.${now}` };
  if (r.error === 'mode_not_effective') {
    return { live, text: `${asked.toUpperCase()} did not take effect: the settings store holds another mode.${now}` };
  }
  return { live, text: `${asked.toUpperCase()} was refused (${r.error}).${now}` };
}
/* The same for a per-agent override. */
export function agentModeRefusalNote(agent: string, asked: string, r: any): string | null {
  if (!r || typeof r !== 'object' || typeof r.error !== 'string') return null;
  if (r.error === 'invalid_agent') return typeof r.detail === 'string' ? r.detail : 'that agent id was refused';
  if (r.error === 'mode_not_saved') return `${agent}: ${asked} was not saved`;
  if (r.error === 'mode_not_effective') {
    const runs = KNOWN_MODES.includes(r.live) ? ` — ${agent} runs ${r.live}` : '';
    return `${agent}: ${asked} did not take effect${runs} (safe mode serves no looser override, or the store could not be read back)`;
  }
  return `${agent}: ${asked} was refused (${r.error})`;
}

/* ── Trust · governed payments lifecycle (modes.tsx, H16.3) ──────
   POST /api/payments/{id}/approve|reject|settle  (admin) */
export async function decidePayment(id: string, action: 'approve' | 'reject' | 'settle'): Promise<unknown> {
  return apiPost('/api/payments/' + encodeURIComponent(id) + '/' + action, {}, { admin: true });
}

/* ── Build · marketplace moderation (gap.tsx, H12.12) ────────────
   POST /api/skills/marketplace/review {name,status}  (admin) */
export async function reviewSkill(name: string, status: 'approved' | 'rejected' | 'pending'): Promise<unknown> {
  return apiPost('/api/skills/marketplace/review', { name, status }, { admin: true });
}

/* ── Agents · bench promotion (gap.tsx) ──────────────────────────
   POST /learning/promote {bench_agent}  (admin) */
export async function promoteBench(benchAgent: string): Promise<unknown> {
  return apiPost('/learning/promote', { bench_agent: benchAgent }, { admin: true });
}

export interface EstopState { engaged: boolean; state: { reason: string | null; engaged_at: string | null } | null }
export interface EstopResumeResult { engaged: boolean; lifted: boolean }

/* ── Admin · global emergency stop (modes3.tsx, hermes v2026.8.27 port) ──
   GET  /api/ops/estop                → { engaged, state:{reason,engaged_at}|null }
   POST /api/ops/estop/engage {reason?}  (admin) — pauses NEW autonomous work only
   POST /api/ops/estop/resume            (admin) — lifts the pause
   Distinct from the Trust kill-switch (/api/security/kill-switch): estop pauses
   heartbeat/autonomy dispatch; it does not halt agents or owner chat. */
export async function getEstopStatus(): Promise<EstopState> {
  return apiGet<EstopState>('/api/ops/estop');
}
export async function engageEstop(reason?: string): Promise<EstopState> {
  return apiPost<EstopState>('/api/ops/estop/engage', reason ? { reason } : {}, { admin: true });
}
export async function resumeEstop(): Promise<EstopResumeResult> {
  return apiPost<EstopResumeResult>('/api/ops/estop/resume', undefined, { admin: true });
}

/* ── Voice · per-message TTS replay (cockpit.tsx) ────────────────
   POST /tts {text,lang} → audio blob; play it. */
export async function playTts(text: string, lang = 'en'): Promise<void> {
  const res = await fetch(appUrl('/tts'), {
    method: 'POST',
    headers: ttsHeaders(),
    body: JSON.stringify({ text, lang }),
  });
  if (!res.ok) throw Object.assign(new Error('tts ' + res.status), { status: res.status });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  await new Promise<void>((resolve) => {
    audio.onended = () => resolve();
    audio.onerror = () => resolve();
    audio.play().catch(() => resolve());
  });
  try { URL.revokeObjectURL(url); } catch { /* ignore */ }
}

function ttsHeaders(): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' };
  try {
    const tok = localStorage.getItem('hud.user_token') || '';
    if (tok) h['X-User-Token'] = tok;
  } catch { /* ignore */ }
  return h;
}
