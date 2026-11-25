/* Which agents may use which models (PHASE_B_PLAN.md §2.2, §5.3 "Local-only list").

   The hub's own policy sets (agents/core/llm/hybrid_router.py LOCAL_ONLY_AGENTS and
   CLOUD_ONLY_AGENTS), written once for the HUD so the composer, the chat-history search and the
   agents-by-exception derivation read one list instead of three hard-coded ones. `hestia` was
   missing from the two hard-coded copies in cockpit.tsx and chat-history-search.tsx.

   A local-only agent never leaves the machine (physically refused otherwise); a cloud-only agent
   has no local fallback, so with no cloud model configured it cannot answer at all. */

/** Strictly local: no cloud fallback, whatever the settings say. */
export const LOCAL_ONLY_AGENTS: readonly string[] = Object.freeze(['frigga', 'ultron', 'howard', 'hestia']);

/** Cloud only: unavailable when no cloud model is configured. */
export const CLOUD_ONLY_AGENTS: readonly string[] = Object.freeze(['athena']);

const norm = (id: unknown): string => (typeof id === 'string' ? id.trim().toLowerCase() : '');

export function isLocalOnlyAgent(id: unknown): boolean {
  return LOCAL_ONLY_AGENTS.includes(norm(id));
}

export function isCloudOnlyAgent(id: unknown): boolean {
  return CLOUD_ONLY_AGENTS.includes(norm(id));
}
