import React from 'react';

export type ChatAgent = { id: string; name?: string; enabled?: boolean; status?: string; chat_routing?: string | null; rosterSource?: string };

const LABELS: Record<string, [string, string]> = {
  orchestrated: ['Orchestrated', 'Orchestrat'],
  local: ['Local', 'Local'],
  cloud_only: ['Cloud only', 'Doar cloud'],
  cloud_preferred: ['Cloud preferred', 'Preferă cloud'],
  claude_preferred: ['Claude preferred', 'Preferă Claude'],
  auto: ['Auto', 'Automat'],
};

export function RoutingPolicyLabel({ selected, demo, lang }: { selected?: ChatAgent; demo: boolean; lang: string }) {
  const ro = lang === 'ro';
  const label = demo ? (ro ? 'Exemplu demo' : 'Demo sample')
    : !selected || selected.enabled === false ? (ro ? 'Indisponibilă' : 'Unavailable')
    : LABELS[selected.chat_routing || '']?.[ro ? 1 : 0] || (ro ? 'Necunoscută' : 'Unknown');
  return <span className="chat-routing-policy" title={ro ? 'Politica declarată înainte de trimitere; modelul folosit se vede după răspuns.' : 'Declared policy before sending; actual model use appears after the reply.'}>
    {ro ? 'Politica de rutare' : 'Routing policy'} · {label}
  </span>;
}

export function selectableChatAgents(agents: ChatAgent[], demo: boolean): ChatAgent[] {
  return demo ? [] : agents.filter(a => a.rosterSource === 'api' && a.enabled !== false && a.status !== 'retired' && a.status !== 'disabled' && typeof a.id === 'string' && !!a.id);
}
