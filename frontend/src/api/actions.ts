// @ts-nocheck
/* HUD v2 · interactive-control bindings — the write side of the capability modes.
   Each helper hits a REAL endpoint verified against agents/web.py; the mode files
   call these so a button is either live (posts to the backend) or rendered DISABLED
   when no endpoint exists (never a no-op that looks live). Mirrors the gap.tsx
   Console pattern (apiGet/apiPost/apiPut), but reused from the always-visible modes. */
import { apiGet, apiPost, apiPut } from './client';

/* ── Trust · kill-switch (modes.tsx) ─────────────────────────────
   GET  /api/security/kill-switch        → { halted | engaged, ... }
   POST /api/security/kill-switch {engage,scope,reason}  (admin) */
export async function getKillSwitch() {
  return apiGet('/api/security/kill-switch');
}
export async function setKillSwitch(engage: boolean) {
  return apiPost('/api/security/kill-switch', { engage, scope: 'global', reason: 'hud' }, { admin: true });
}

/* ── Build · marketplace skill install (modes2.tsx) ──────────────
   GET  /api/skills/marketplace          → { skills:[{name,signed,review_status}] } (admin)
   POST /api/skills/marketplace/install {name}  (admin, H12.12) */
export async function listMarketplace() {
  return apiGet('/api/skills/marketplace', { admin: true });
}
export async function installSkill(name: string) {
  return apiPost('/api/skills/marketplace/install', { name }, { admin: true });
}

/* ── Admin · plugin enable/disable (modes3.tsx) ──────────────────
   GET /plugins                          → { plugins:[{id,name,enabled,...}] }
   PUT /plugins/{id}/toggle              → flips enabled (no body) */
export async function listPlugins() {
  return apiGet('/plugins');
}
export async function togglePlugin(id: string) {
  return apiPut('/plugins/' + encodeURIComponent(id) + '/toggle');
}

/* ── Dossier · agent soul + history (modes.tsx) ──────────────────
   GET /api/agents/{id}/soul             → { agent_id, soul }
   GET /api/agents/{id}/history          → { agent_id, runs:[...] } */
export async function getAgentSoul(id: string) {
  return apiGet('/api/agents/' + encodeURIComponent(id) + '/soul');
}
export async function getAgentHistory(id: string) {
  return apiGet('/api/agents/' + encodeURIComponent(id) + '/history');
}

/* ── Memory · live recalls + topics + KG (modes.tsx) ─────────────
   GET /api/memory/search?q=             → { results:[{score,payload,sources}] }
   GET /api/kg/entities                  → { entities:[...] } */
export async function memorySearch(q: string) {
  return apiGet('/api/memory/search?q=' + encodeURIComponent(q) + '&top_k=8');
}
export async function kgEntities(limit = 60) {
  return apiGet('/api/kg/entities?limit=' + limit);
}

/* ── Autonomy · global mode AUTO/ASK/OFF (modes2.tsx) ────────────
   GET  /autonomy/mode         → { mode: "auto"|"ask"|"off" } (admin)
   POST /autonomy/mode {mode}  → persists + applies live (admin) */
export async function getAutonomyMode() {
  return apiGet('/autonomy/mode', { admin: true });
}
export async function setAutonomyMode(mode: string) {
  return apiPost('/autonomy/mode', { mode }, { admin: true });
}

/* ── Voice · per-message TTS replay (cockpit.tsx) ────────────────
   POST /tts {text,lang} → audio blob; play it. Returns a stop() handle. */
export async function playTts(text: string, lang = 'en') {
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
