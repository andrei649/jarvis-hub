/* Who the owner may write to. The declared routing policy is worded by the conversation register
   (home/talk/strings.ts policyWord: its head and the composer's "To" options); the label ChatMode
   drew beside its picker went with ChatMode at the Phase B stage 5 cleanup. */
export type ChatAgent = { id: string; name?: string; enabled?: boolean; status?: string; chat_routing?: string | null; rosterSource?: string };

export function selectableChatAgents(agents: ChatAgent[], demo: boolean): ChatAgent[] {
  return demo ? [] : agents.filter(a => a.rosterSource === 'api' && a.enabled !== false && a.status !== 'retired' && a.status !== 'disabled' && typeof a.id === 'string' && !!a.id);
}
