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
export interface KillSwitchState { halted?: boolean; engaged?: boolean; scope?: string; reason?: string }
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
export interface AgentSoul { agent_id: string; soul: string }
export interface AgentHistory { agent_id: string; runs: unknown[] }
export interface MemorySearchResult { results: Array<{ score: number; payload: unknown; sources?: unknown }> }
export interface KgEntities { entities: unknown[] }
export type AutonomyModeValue = 'auto' | 'ask' | 'off';
export interface AutonomyModeState { mode: AutonomyModeValue }

/* ── Trust · kill-switch (modes.tsx) ─────────────────────────────
   GET  /api/security/kill-switch        → { halted | engaged, ... }
   POST /api/security/kill-switch {engage,scope,reason}  (admin) */
export async function getKillSwitch(): Promise<KillSwitchState> {
  return apiGet<KillSwitchState>('/api/security/kill-switch');
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
export async function setAutonomyMode(mode: string): Promise<unknown> {
  return apiPost('/autonomy/mode', { mode }, { admin: true });
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

/* ── Voice · per-message TTS replay (cockpit.tsx) ────────────────
   POST /tts {text,lang} → audio blob; play it. */
export async function playTts(text: string, lang = 'en'): Promise<void> {
  const res = await fetch('/tts', {
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
