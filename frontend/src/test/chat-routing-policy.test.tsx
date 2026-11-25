/* The declared routing policy of the agent the owner writes to, before sending. Since the Ledger
   cutover it is the conversation register's (PHASE_B_PLAN.md §5.3): its head says "with <agent> ·
   <policy>", and the composer's "To" picker lists the selectable agents with their policies. The
   classic ChatMode header that carried it was deleted at the stage 5 cleanup. */
import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { TalkRegister } from '../home/talk/TalkRegister';
import { V2 } from '../data';
import { loadJarvisData } from '../api/loaders';
import { selectableChatAgents } from '../chat-routing-policy';
import { resetPolling } from '../signals/poll';

const agents = [
  { id: 'jarvis', name: 'Jarvis', chat_routing: 'orchestrated', rosterSource: 'api', enabled: true },
  { id: 'frigga', name: 'Frigga', chat_routing: 'local', rosterSource: 'api', enabled: true },
  { id: 'athena', name: 'Athena', chat_routing: 'cloud_only', rosterSource: 'api', enabled: false },
  { id: 'seed', name: 'Seed Fiction', chat_routing: 'local', enabled: true },
];

/** The conversation page as App draws it ('chat', the register at full width). */
const page = (over: Record<string, unknown> = {}) => <TalkRegister variant="chat" turns={[]} messages={[]} thinking={null}
  onStop={vi.fn()} onSubmit={vi.fn()} onProv={vi.fn()} lang="en" t={V2.I18N.en} agent="jarvis" sessionId="s" selectedTurn
  agents={agents} demo={false} onSelectAgent={vi.fn()} recipientStatus="ready" messageScope="jarvis:s" {...over} />;
const policy = () => document.querySelector('[data-register="talk"] .n-talk__policy')?.textContent;
const picker = () => screen.queryByRole('combobox', { name: 'To' }) as HTMLSelectElement | null;

beforeEach(() => { resetPolling(); vi.stubGlobal('fetch', vi.fn(async () => Response.json({}))); });
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals(); resetPolling(); });

it('shows the selected live agent and its policy, then changes the native picker', () => {
  const onSelectAgent = vi.fn();
  const { rerender } = render(page({ onSelectAgent }));
  expect(picker()!.selectedOptions[0].textContent).toBe('Jarvis · Orchestrated');
  expect(policy()).toBe('Orchestrated');
  // only the live roster's enabled agents can be chosen: not the disabled one, not a seed row
  expect([...picker()!.options].map(option => option.value)).toEqual(['jarvis', 'frigga']);
  fireEvent.change(picker()!, { target: { value: 'frigga' } });
  expect(onSelectAgent).toHaveBeenCalledWith('frigga');
  rerender(page({ agent: 'frigga', onSelectAgent }));
  expect(picker()!.selectedOptions[0].textContent).toBe('Frigga · Local');
  expect(policy()).toBe('Local');
  expect(document.querySelector('[data-register="talk"] .n-talk__with b')?.textContent).toBe('Frigga');
});

it('labels demo, missing and unknown routing evidence without claiming local execution', () => {
  const view = render(page({ demo: true, agent: 'athena' }));
  expect(policy()).toBe('Demo sample');
  expect(picker()).toBeNull();
  // no roster served (the hub's /api/agents did not answer): the declared policy is not known, and
  // that is never "Unavailable", which only the served roster can say (below: a disabled agent)
  view.rerender(page({ agents: [], agent: 'jarvis' }));
  expect(policy()).toBe('Routing policy unknown');
  expect(policy()).not.toMatch(/local/i);
  expect(picker()).toBeNull();
  view.rerender(page({ agents: [{ id: 'jarvis', name: 'Jarvis', rosterSource: 'api', chat_routing: 'surprise' }] }));
  expect(policy()).toBe('Routing policy unknown');
  expect(policy()).not.toMatch(/local/i);
  view.rerender(page({ agents: [...agents.slice(0, 2), { id: 'athena', name: 'Athena', rosterSource: 'api', chat_routing: 'cloud_only', enabled: false }], agent: 'athena' }));
  expect(policy()).toBe('Unavailable');
  // the current recipient cannot be chosen again: it is shown, disabled, and selected
  expect(picker()!.selectedOptions[0].textContent).toBe('Athena');
  expect(picker()!.selectedOptions[0].disabled).toBe(true);
});

it('uses Romanian routing labels', () => {
  render(page({ lang: 'ro', t: V2.I18N.ro, agents: [{ id: 'jarvis', name: 'Jarvis', rosterSource: 'api', chat_routing: 'cloud_preferred' }] }));
  expect(policy()).toBe('Preferă cloud');
  expect(document.querySelector('[data-register="talk"] .n-talk__policy')?.getAttribute('title'))
    .toBe('Politica declarată înainte de trimitere; modelul folosit se vede după răspuns.');
});

it('marks only authenticated roster rows selectable and drops stale policy on fallback', async () => {
  let rosterAvailable = true;
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (String(url).endsWith('/api/agents') && rosterAvailable) return new Response(JSON.stringify({ agents: [
      { id: 'jarvis', name: 'Jarvis', chat_routing: 'orchestrated' },
      { id: 'frigga', name: 'Frigga', chat_routing: 'local', enabled: false },
    ] }), { status: 200 });
    if (String(url).endsWith('/status')) return new Response(JSON.stringify({ agents: [{ id: 'jarvis', status: 'ready' }] }), { status: 200 });
    return new Response('{}', { status: 503 });
  }));
  const live = await loadJarvisData(false);
  expect(selectableChatAgents(live.agents, false).map(a => a.id)).toEqual(['jarvis']);
  expect(live.agents[0].chat_routing).toBe('orchestrated');
  rosterAvailable = false;
  const degraded = await loadJarvisData(false);
  expect(selectableChatAgents(degraded.agents, false)).toEqual([]);
  expect(degraded.agents.find(a => a.id === 'jarvis')?.chat_routing).toBeUndefined();
});
