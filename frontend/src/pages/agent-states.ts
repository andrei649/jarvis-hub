/* Roster helpers for the pages. The state of each agent (waiting on you, working, finished today,
   unavailable, halted, scheduled, no activity reported) is derived once, in signals/agents-exception.ts
   (agentsByException): the running foot, the fourth register and the Timeline's Now column all read
   that one derivation, so they cannot disagree. This file only holds what the pages add around it. */
export { LOCAL_ONLY_AGENTS, CLOUD_ONLY_AGENTS } from '../signals/agents-policy';

export interface RosterAgent { readonly id: string; readonly name: string; readonly role: string | null }

/** Roster rows as {id, name, role}; anything without an id is left out. */
export function rosterAgents(roster: readonly unknown[]): RosterAgent[] {
  const out: RosterAgent[] = [];
  const seen = new Set<string>();
  for (const row of roster) {
    if (!row || typeof row !== 'object') continue;
    const r = row as Record<string, unknown>;
    const id = typeof r.id === 'string' ? r.id.trim().toLowerCase() : '';
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push({ id, name: typeof r.name === 'string' && r.name.trim() ? r.name.trim() : id, role: typeof r.role === 'string' && r.role.trim() ? r.role.trim() : null });
  }
  return out;
}
