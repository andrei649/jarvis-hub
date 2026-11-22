import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ChatMode } from '../modes3';
import { loadJarvisData } from '../api/loaders';
import { selectableChatAgents } from '../chat-routing-policy';

const t = { directLine: 'DIRECT LINE', focusHintChat: 'focus', placeholder: 'Message', channel: 'CHAT', transmit: 'Send' };
const agents = [
  { id: 'jarvis', name: 'Jarvis', chat_routing: 'orchestrated', rosterSource: 'api', enabled: true },
  { id: 'frigga', name: 'Frigga', chat_routing: 'local', rosterSource: 'api', enabled: true },
  { id: 'athena', name: 'Athena', chat_routing: 'cloud_only', rosterSource: 'api', enabled: false },
  { id: 'seed', name: 'Seed Fiction', chat_routing: 'local', enabled: true },
];

const props = { messages: [], thinking: null, onStop: vi.fn(), onSubmit: vi.fn(), onProv: vi.fn(), mic: false, setMic: vi.fn(), lang: 'en', t, agent: 'jarvis', sessionId: '', selectedTurn: true, outcome: null, power: null, agents, demo: false, onSelectAgent: vi.fn() };
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals(); });

it('shows the selected live agent and its policy, then changes the native picker', () => {
  const onSelectAgent = vi.fn();
  const { rerender } = render(<ChatMode {...props} onSelectAgent={onSelectAgent} />);
  expect(screen.getByRole('combobox', { name: 'Selected agent' }).querySelector('option:checked')?.textContent).toBe('Jarvis');
  expect(screen.getByText('Routing policy · Orchestrated')).toBeTruthy();
  const picker = screen.getByRole('combobox', { name: 'Selected agent' }) as HTMLSelectElement;
  expect([...picker.options].map(option => option.value)).toEqual(['jarvis', 'frigga']);
  fireEvent.change(picker, { target: { value: 'frigga' } });
  expect(onSelectAgent).toHaveBeenCalledWith('frigga');
  rerender(<ChatMode {...props} agent="frigga" onSelectAgent={onSelectAgent} />);
  expect(screen.getByRole('combobox', { name: 'Selected agent' }).querySelector('option:checked')?.textContent).toBe('Frigga');
  expect(screen.getByText('Routing policy · Local')).toBeTruthy();
  expect(document.querySelector('.chat-glyph path')?.getAttribute('d')).not.toBeNull();
});

it('labels demo, missing and unknown routing evidence without claiming local execution', () => {
  const view = render(<ChatMode {...props} demo agent="athena" />);
  expect(screen.getByText('Routing policy · Demo sample')).toBeTruthy();
  expect(screen.queryByRole('combobox', { name: 'Selected agent' })).toBeNull();
  view.rerender(<ChatMode {...props} agents={[]} agent="jarvis" />);
  expect(screen.getByText('Routing policy · Unavailable')).toBeTruthy();
  expect(screen.queryByRole('combobox', { name: 'Selected agent' })).toBeNull();
  view.rerender(<ChatMode {...props} agents={[{ id: 'jarvis', name: 'Jarvis', rosterSource: 'api', chat_routing: 'surprise' }]} />);
  expect(screen.getByText('Routing policy · Unknown')).toBeTruthy();
  view.rerender(<ChatMode {...props} agents={[...agents.slice(0, 2), { id: 'athena', name: 'Athena', rosterSource: 'api', chat_routing: 'cloud_only', enabled: false }]} agent="athena" />);
  expect(screen.getByText('Routing policy · Unavailable')).toBeTruthy();
  expect((screen.getByRole('combobox', { name: 'Selected agent' }) as HTMLSelectElement).selectedOptions[0].textContent).toBe('Athena');
  expect((screen.getByRole('combobox', { name: 'Selected agent' }) as HTMLSelectElement).selectedOptions[0].disabled).toBe(true);
});

it('uses Romanian routing labels', () => {
  render(<ChatMode {...props} lang="ro" agents={[{ id: 'jarvis', name: 'Jarvis', rosterSource: 'api', chat_routing: 'cloud_preferred' }]} />);
  expect(screen.getByText('Politica de rutare · Preferă cloud')).toBeTruthy();
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
