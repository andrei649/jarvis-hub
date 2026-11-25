/* RecipientPicker, the composer's To (PHASE_B_PLAN.md §5.3, §12 item 11): a change of recipient
   asked for while a reply is being written waits for the owner's answer, since it would stop that
   reply. Nothing switches by itself: when the reply ends with the question still open the question
   stays, without its "stops the reply" clause, until the owner answers. App keeps the question
   (`pending`) so it outlives the composer; drawn without App the picker keeps its own. */
import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RecipientPicker, agentDisplayName, recipientChoosable, recipientRefusalText, rosterServed, switchStanding } from './RecipientPicker';

const roster = [
  { id: 'jarvis', name: 'Jarvis', rosterSource: 'api', chat_routing: 'orchestrated', enabled: true },
  { id: 'frigga', name: 'Frigga', rosterSource: 'api', chat_routing: 'local', enabled: true },
];
const base = { agent: 'jarvis', agents: roster, demo: false, recipientStatus: 'ready' as const, lang: 'en' };
const question = () => screen.queryByRole('alert');
const to = () => screen.getByRole('combobox', { name: 'To' }) as HTMLSelectElement;

afterEach(cleanup);

describe('RecipientPicker · a pick while a reply is being written', () => {
  it('takes a pick at once when no reply is being written', () => {
    const select = vi.fn();
    render(<RecipientPicker {...base} inFlight={false} onSelectAgent={select} />);
    fireEvent.change(to(), { target: { value: 'frigga' } });
    expect(select).toHaveBeenCalledExactlyOnceWith('frigga');
    expect(question()).toBeNull();
  });

  it('stops nothing while a reply is being written: it asks first', () => {
    const select = vi.fn();
    render(<RecipientPicker {...base} inFlight onSelectAgent={select} />);
    fireEvent.change(to(), { target: { value: 'frigga' } });
    expect(select).not.toHaveBeenCalled();
    expect(question()?.textContent).toContain('Writing to Frigga stops the reply in progress.');
    expect(question()?.getAttribute('data-recipient-switch-state')).toBe('writing');
    expect(to().getAttribute('aria-describedby')).toBe(question()?.id);
    fireEvent.click(screen.getByRole('button', { name: 'Stop it and write to Frigga' }));
    expect(select).toHaveBeenCalledExactlyOnceWith('frigga');
    expect(question()).toBeNull();
  });

  it('keeps the recipient, and the reply, when the question is declined', () => {
    const select = vi.fn();
    render(<RecipientPicker {...base} inFlight onSelectAgent={select} />);
    fireEvent.change(to(), { target: { value: 'frigga' } });
    fireEvent.click(screen.getByRole('button', { name: 'Keep writing to Jarvis' }));
    expect(select).not.toHaveBeenCalled();
    expect(question()).toBeNull();
  });
});

describe('RecipientPicker · nothing switches by itself', () => {
  it('keeps the question when the reply ends, without "stops the reply", and switches only on the answer', () => {
    const select = vi.fn();
    const pending = vi.fn();
    const view = render(<RecipientPicker {...base} inFlight onSelectAgent={select} onPendingChange={pending} whyId="why" />);
    fireEvent.change(to(), { target: { value: 'frigga' } });
    expect(pending).toHaveBeenLastCalledWith('frigga');
    // the reply ends (finished, or stopped by the owner): nothing changes by itself
    view.rerender(<RecipientPicker {...base} inFlight={false} onSelectAgent={select} onPendingChange={pending} whyId="why" />);
    expect(select).not.toHaveBeenCalled();
    expect(pending).toHaveBeenLastCalledWith('frigga');
    expect(question()?.getAttribute('data-recipient-switch-state')).toBe('ended');
    // the sentence Send points at, reworded: nothing left to stop
    expect(document.getElementById('why')?.textContent).toBe('The reply from Jarvis has ended. Write to Frigga?');
    expect(question()?.textContent).not.toContain('stops');
    expect(screen.queryByRole('button', { name: /^Stop/ })).toBeNull();
    expect(to().value).toBe('jarvis');
    fireEvent.click(screen.getByRole('button', { name: 'Write to Frigga' }));
    expect(select).toHaveBeenCalledExactlyOnceWith('frigga');
    expect(pending).toHaveBeenLastCalledWith(null);
    expect(question()).toBeNull();
  });

  it('answers "Stay with <Agent>" by changing nothing', () => {
    const select = vi.fn();
    const view = render(<RecipientPicker {...base} inFlight onSelectAgent={select} />);
    fireEvent.change(to(), { target: { value: 'frigga' } });
    view.rerender(<RecipientPicker {...base} inFlight={false} onSelectAgent={select} />);
    fireEvent.click(screen.getByRole('button', { name: 'Stay with Jarvis' }));
    expect(select).not.toHaveBeenCalled();
    expect(question()).toBeNull();
    // a later reply ending has nothing left to carry out
    view.rerender(<RecipientPicker {...base} inFlight onSelectAgent={select} />);
    view.rerender(<RecipientPicker {...base} inFlight={false} onSelectAgent={select} />);
    expect(select).not.toHaveBeenCalled();
  });

  it('asks again in the reply\'s words if another reply starts before the answer', () => {
    const view = render(<RecipientPicker {...base} inFlight onSelectAgent={vi.fn()} />);
    fireEvent.change(to(), { target: { value: 'frigga' } });
    view.rerender(<RecipientPicker {...base} inFlight={false} onSelectAgent={vi.fn()} />);
    expect(question()?.getAttribute('data-recipient-switch-state')).toBe('ended');
    // a voice turn, say: the change would stop this one
    view.rerender(<RecipientPicker {...base} inFlight onSelectAgent={vi.fn()} />);
    expect(question()?.textContent).toContain('Writing to Frigga stops the reply in progress.');
  });

  it('writes both forms in Romanian', () => {
    const view = render(<RecipientPicker {...base} lang="ro" inFlight onSelectAgent={vi.fn()} whyId="why" />);
    fireEvent.change(screen.getByRole('combobox', { name: 'Către' }), { target: { value: 'frigga' } });
    expect(document.getElementById('why')?.textContent).toBe('Dacă îi scrii lui Frigga, răspunsul în curs se oprește.');
    expect(screen.getByRole('button', { name: 'Oprește-l și scrie-i lui Frigga' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Rămâi la Jarvis' })).toBeTruthy();
    view.rerender(<RecipientPicker {...base} lang="ro" inFlight={false} onSelectAgent={vi.fn()} whyId="why" />);
    expect(document.getElementById('why')?.textContent).toBe('Răspunsul lui Jarvis s-a încheiat. Îi scrii lui Frigga?');
    expect(screen.getByRole('button', { name: 'Scrie-i lui Frigga' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Rămâi la Jarvis' })).toBeTruthy();
  });

  it('words the question without a current recipient, never "Keep writing to "', () => {
    const view = render(<RecipientPicker {...base} agent="" recipientStatus="choose" inFlight onSelectAgent={vi.fn()} whyId="why" />);
    fireEvent.change(to(), { target: { value: 'frigga' } });
    expect(screen.getByRole('button', { name: 'Let the reply finish' })).toBeTruthy();
    view.rerender(<RecipientPicker {...base} agent="" recipientStatus="choose" inFlight={false} onSelectAgent={vi.fn()} whyId="why" />);
    expect(document.getElementById('why')?.textContent).toBe('The reply has ended. Write to Frigga?');
    expect(screen.getByRole('button', { name: 'Not now' })).toBeTruthy();
  });

  it('drops its own question when the recipient moves some other way, or the demo sample is turned on or off', () => {
    const select = vi.fn();
    const view = render(<RecipientPicker {...base} inFlight onSelectAgent={select} />);
    fireEvent.change(to(), { target: { value: 'frigga' } });
    expect(question()).toBeTruthy();
    // the demo boundary is a provenance boundary: a live question does not cross it
    view.rerender(<RecipientPicker {...base} demo inFlight onSelectAgent={select} />);
    expect(question()).toBeNull();
    view.rerender(<RecipientPicker {...base} inFlight={false} onSelectAgent={select} />);
    expect(question()).toBeNull();
    // the recipient moved meanwhile (the question was about replacing someone else)
    view.rerender(<RecipientPicker {...base} inFlight onSelectAgent={select} />);
    fireEvent.change(to(), { target: { value: 'frigga' } });
    expect(question()).toBeTruthy();
    view.rerender(<RecipientPicker {...base} agent="frigga" inFlight onSelectAgent={select} />);
    expect(question()).toBeNull();
    view.rerender(<RecipientPicker {...base} agent="frigga" inFlight={false} onSelectAgent={select} />);
    expect(select).not.toHaveBeenCalled();
  });
});

describe('RecipientPicker · a question App keeps', () => {
  it('draws the question App keeps, and hands every answer back to App', () => {
    const select = vi.fn();
    const pending = vi.fn();
    const view = render(<RecipientPicker {...base} pending="frigga" inFlight onSelectAgent={select} onPendingChange={pending} />);
    expect(question()?.textContent).toContain('Writing to Frigga stops the reply in progress.');
    // drawn, not asked: mounting with App's question tells App nothing
    expect(pending).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Stop it and write to Frigga' }));
    expect(pending).toHaveBeenLastCalledWith(null);
    expect(select).toHaveBeenCalledExactlyOnceWith('frigga');
    view.rerender(<RecipientPicker {...base} agent="frigga" pending={null} inFlight={false} onSelectAgent={select} onPendingChange={pending} />);
    expect(question()).toBeNull();
  });

  it('shows the same question again when drawn anew, as leaving Home and coming back does', () => {
    const select = vi.fn();
    const pending = vi.fn();
    const view = render(<RecipientPicker {...base} pending="frigga" inFlight onSelectAgent={select} onPendingChange={pending} />);
    view.unmount();
    // back on Home after the reply ended: the question is still open, in its ended form
    render(<RecipientPicker {...base} pending="frigga" inFlight={false} onSelectAgent={select} onPendingChange={pending} whyId="why" />);
    expect(document.getElementById('why')?.textContent).toBe('The reply from Jarvis has ended. Write to Frigga?');
    expect(select).not.toHaveBeenCalled();
    expect(pending).not.toHaveBeenCalled();
  });

  it('asks App to keep a pick made while a reply is being written, and keeps nothing itself', () => {
    const select = vi.fn();
    const pending = vi.fn();
    const view = render(<RecipientPicker {...base} pending={null} inFlight onSelectAgent={select} onPendingChange={pending} />);
    fireEvent.change(to(), { target: { value: 'frigga' } });
    expect(pending).toHaveBeenLastCalledWith('frigga');
    expect(select).not.toHaveBeenCalled();
    expect(question()).toBeNull();   // until App keeps it
    view.rerender(<RecipientPicker {...base} pending="frigga" inFlight onSelectAgent={select} onPendingChange={pending} />);
    expect(question()).toBeTruthy();
    // a recipient that moved some other way: App drops it, and the picker never answers it itself
    view.rerender(<RecipientPicker {...base} agent="frigga" pending={null} inFlight onSelectAgent={select} onPendingChange={pending} />);
    expect(question()).toBeNull();
    expect(pending).toHaveBeenCalledTimes(1);
  });
});

describe('RecipientPicker · when the hub did not serve the roster', () => {
  const seed = [{ id: 'jarvis', name: 'Jarvis' }, { id: 'frigga', name: 'Frigga' }];

  it('shows a ready recipient in words, with no policy it does not know', () => {
    render(<RecipientPicker {...base} agents={seed} inFlight={false} onSelectAgent={vi.fn()} />);
    expect(screen.queryByRole('combobox')).toBeNull();
    expect(document.querySelector('[data-recipient="jarvis"]')?.textContent).toBe('ToJarvis');
    expect(rosterServed(seed)).toBe(false);
    expect(rosterServed(roster)).toBe(true);
  });

  it('names a selected agent App keeps but cannot confirm, and still offers Jarvis', () => {
    const select = vi.fn();
    const chosen = vi.fn();
    const view = render(<RecipientPicker {...base} agent="" agents={seed} recipientStatus="checking" unconfirmed={{ agent: 'frigga', name: 'Frigga Allmother' }}
      inFlight={false} onSelectAgent={select} onChosen={chosen} />);
    expect(Array.from(to().options).map((o) => o.textContent)).toEqual(['Frigga Allmother · not confirmed', 'Jarvis · Routing policy unknown']);
    expect(to().value).toBe('');
    expect(to().getAttribute('data-recipient-unconfirmed')).toBe('frigga');
    expect(to().getAttribute('data-recipient-choices')).toBe('not-served');
    expect(document.querySelector('[data-recipient]')?.getAttribute('data-recipient')).toBe('frigga');
    // nothing is chosen by itself; Jarvis is the owner's to choose
    expect(select).not.toHaveBeenCalled();
    fireEvent.change(to(), { target: { value: 'jarvis' } });
    expect(select).toHaveBeenCalledExactlyOnceWith('jarvis');
    expect(chosen).toHaveBeenCalledOnce();
    // still being checked (no hold): no choice is offered while a check is under way
    view.rerender(<RecipientPicker {...base} agent="" agents={seed} recipientStatus="checking" inFlight={false} onSelectAgent={select} onChosen={chosen} />);
    expect(screen.queryByRole('combobox')).toBeNull();
    // in Romanian
    view.rerender(<RecipientPicker {...base} lang="ro" agent="frigga" agents={seed} recipientStatus="checking" unconfirmed={{ agent: 'frigga' }}
      inFlight={false} onSelectAgent={select} onChosen={chosen} />);
    expect(Array.from((screen.getByRole('combobox', { name: 'Către' }) as HTMLSelectElement).options).map((o) => o.textContent))
      .toEqual(['Frigga · neconfirmat', 'Jarvis · Politica de rutare necunoscută']);
  });

  it('offers Jarvis, App\'s default, when there is no recipient: choosing one is possible', () => {
    const select = vi.fn();
    const chosen = vi.fn();
    render(<RecipientPicker {...base} agent="" agents={seed} recipientStatus="choose" inFlight={false} onSelectAgent={select} onChosen={chosen} />);
    expect(Array.from(to().options).map((o) => o.textContent)).toEqual(['Choose an agent', 'Jarvis · Routing policy unknown']);
    expect(to().getAttribute('data-recipient-choices')).toBe('not-served');
    expect(to().getAttribute('title')).toBe('The hub did not serve the agent roster, so the declared routing policy is not known.');
    fireEvent.change(to(), { target: { value: 'jarvis' } });
    expect(select).toHaveBeenCalledExactlyOnceWith('jarvis');
    // the To turns back into words: the composer takes the focus rather than the page
    expect(chosen).toHaveBeenCalledOnce();
  });
});

/* A poll the hub did not serve says nothing about the agent asked for: the question stays until the
   owner answers it, and only its switch waits, saying why, until a served roster offers the agent.
   A roster the hub served that no longer offers the agent drops the question (App drops the one it
   keeps; drawn alone, the picker drops its own). */
describe('RecipientPicker · a question while the roster is not served', () => {
  const seed = [{ id: 'jarvis', name: 'Jarvis' }, { id: 'frigga', name: 'Frigga' }];
  const HELD = 'The hub did not serve the agent roster, so Frigga cannot be chosen until it does.';

  it('keeps the question and holds its switch, saying why, until a served roster offers the agent', () => {
    const select = vi.fn();
    const pending = vi.fn();
    const view = render(<RecipientPicker {...base} agents={seed} pending="frigga" inFlight onSelectAgent={select} onPendingChange={pending} whyId="why" />);
    const take = screen.getByRole('button', { name: 'Stop it and write to Frigga' }) as HTMLButtonElement;
    expect(take.disabled).toBe(true);
    expect(document.getElementById(take.getAttribute('aria-describedby') || '')?.textContent).toBe(HELD);
    expect(question()?.hasAttribute('data-recipient-switch-held')).toBe(true);
    // Send points at the question's own sentence, unchanged
    expect(document.getElementById('why')?.textContent).toBe('Writing to Frigga stops the reply in progress.');
    fireEvent.click(take);
    expect(select).not.toHaveBeenCalled();
    expect(pending).not.toHaveBeenCalled();
    // with no rows at all, the same
    view.rerender(<RecipientPicker {...base} agents={[]} pending="frigga" inFlight={false} onSelectAgent={select} onPendingChange={pending} whyId="why" />);
    expect((screen.getByRole('button', { name: 'Write to Frigga' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(HELD)).toBeTruthy();
    // served again, Frigga in it: the answer is taken
    view.rerender(<RecipientPicker {...base} pending="frigga" inFlight onSelectAgent={select} onPendingChange={pending} whyId="why" />);
    expect(screen.queryByText(HELD)).toBeNull();
    expect(question()?.hasAttribute('data-recipient-switch-held')).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Stop it and write to Frigga' }));
    expect(pending).toHaveBeenLastCalledWith(null);
    expect(select).toHaveBeenCalledExactlyOnceWith('frigga');
  });

  it('still takes "Stay": the owner can always answer', () => {
    const select = vi.fn();
    const pending = vi.fn();
    render(<RecipientPicker {...base} agents={seed} pending="frigga" inFlight={false} onSelectAgent={select} onPendingChange={pending} />);
    fireEvent.click(screen.getByRole('button', { name: 'Stay with Jarvis' }));
    expect(pending).toHaveBeenLastCalledWith(null);
    expect(select).not.toHaveBeenCalled();
  });

  it('holds nothing for Jarvis, App\'s own default, which needs no roster', () => {
    const select = vi.fn();
    render(<RecipientPicker {...base} agent="frigga" agents={seed} recipientStatus="checking" pending="jarvis" inFlight onSelectAgent={select} onPendingChange={vi.fn()} />);
    const take = screen.getByRole('button', { name: 'Stop it and write to Jarvis' }) as HTMLButtonElement;
    expect(take.disabled).toBe(false);
    expect(take.hasAttribute('aria-describedby')).toBe(false);
    fireEvent.click(take);
    expect(select).toHaveBeenCalledExactlyOnceWith('jarvis');
  });

  it('says why in Romanian', () => {
    render(<RecipientPicker {...base} lang="ro" agents={seed} pending="frigga" inFlight={false} onSelectAgent={vi.fn()} onPendingChange={vi.fn()} />);
    expect(screen.getByText('Hubul nu a trimis lista agenților, așa că agentul Frigga nu poate fi ales până nu o trimite.')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Scrie-i lui Frigga' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('drops its own question when a served roster no longer offers the agent, not for a poll the hub did not serve', () => {
    const select = vi.fn();
    const pending = vi.fn();
    const view = render(<RecipientPicker {...base} inFlight onSelectAgent={select} onPendingChange={pending} />);
    fireEvent.change(to(), { target: { value: 'frigga' } });
    view.rerender(<RecipientPicker {...base} agents={seed} inFlight onSelectAgent={select} onPendingChange={pending} />);
    expect(question()?.getAttribute('data-recipient-switch')).toBe('frigga');
    expect(pending).toHaveBeenLastCalledWith('frigga');
    view.rerender(<RecipientPicker {...base} agents={[roster[0]]} inFlight onSelectAgent={select} onPendingChange={pending} />);
    expect(question()).toBeNull();
    expect(pending).toHaveBeenLastCalledWith(null);
    // a roster that offers her again does not bring it back
    view.rerender(<RecipientPicker {...base} inFlight={false} onSelectAgent={select} onPendingChange={pending} />);
    expect(question()).toBeNull();
    expect(select).not.toHaveBeenCalled();
  });

  it('names the agent asked about as the hub\'s roster last named it, not by a /status or seed row', () => {
    const view = render(<RecipientPicker {...base} agents={seed} pending="frigga" pendingName="Frigga Allmother" inFlight
      onSelectAgent={vi.fn()} onPendingChange={vi.fn()} whyId="why" />);
    expect(document.getElementById('why')?.textContent).toBe('Writing to Frigga Allmother stops the reply in progress.');
    expect(screen.getByText('The hub did not serve the agent roster, so Frigga Allmother cannot be chosen until it does.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Stop it and write to Frigga Allmother' })).toBeTruthy();
    view.rerender(<RecipientPicker {...base} agents={[]} pending="frigga" pendingName="Frigga Allmother" inFlight={false}
      onSelectAgent={vi.fn()} onPendingChange={vi.fn()} whyId="why" />);
    expect(document.getElementById('why')?.textContent).toBe('The reply from Jarvis has ended. Write to Frigga Allmother?');
    // a roster the hub serves names her itself
    view.rerender(<RecipientPicker {...base} pending="frigga" pendingName="Frigga Allmother" inFlight={false}
      onSelectAgent={vi.fn()} onPendingChange={vi.fn()} whyId="why" />);
    expect(document.getElementById('why')?.textContent).toBe('The reply from Jarvis has ended. Write to Frigga?');
  });

  it('tells the composer when it drops its own question for a served roster that no longer offers the agent', () => {
    const dropped = vi.fn();
    const view = render(<RecipientPicker {...base} inFlight onSelectAgent={vi.fn()} onDropped={dropped} />);
    fireEvent.change(to(), { target: { value: 'frigga' } });
    // not for a poll the hub did not serve
    view.rerender(<RecipientPicker {...base} agents={seed} inFlight onSelectAgent={vi.fn()} onDropped={dropped} />);
    expect(dropped).not.toHaveBeenCalled();
    view.rerender(<RecipientPicker {...base} agents={[roster[0]]} inFlight onSelectAgent={vi.fn()} onDropped={dropped} />);
    expect(dropped).toHaveBeenCalledExactlyOnceWith('frigga');
    expect(question()).toBeNull();
    // a question App keeps is App's to drop: the picker tells nothing
    const kept = vi.fn();
    cleanup();
    render(<RecipientPicker {...base} agents={[roster[0]]} pending="frigga" inFlight onSelectAgent={vi.fn()} onPendingChange={vi.fn()} onDropped={kept} />);
    expect(kept).not.toHaveBeenCalled();
  });

  it('agrees with App on whom the owner may choose', () => {
    expect(recipientChoosable('frigga', roster, false)).toBe(true);
    expect(recipientChoosable('frigga', seed, false)).toBe(false);
    expect(recipientChoosable('jarvis', seed, false)).toBe(true);
    expect(recipientChoosable('jarvis', [], false)).toBe(true);
    expect(recipientChoosable('jarvis', [{ ...roster[0], enabled: false }, roster[1]], false)).toBe(false);
    expect(recipientChoosable('anyone', [], true)).toBe(true);
    expect(switchStanding('frigga', roster, false)).toBe('open');
    expect(switchStanding('frigga', seed, false)).toBe('held');
    expect(switchStanding('frigga', [], false)).toBe('held');
    expect(switchStanding('frigga', [roster[0]], false)).toBe('gone');
  });
});

describe('recipientRefusalText', () => {
  it('names an agent that is not available, and says nothing goes to another one', () => {
    expect(recipientRefusalText({ reason: 'unavailable', agent: 'frigga' }, roster, 'en'))
      .toBe('Frigga is not available now. Nothing is sent until you choose who to write to.');
    expect(recipientRefusalText({ reason: 'unavailable', agent: 'frigga' }, roster, 'ro'))
      .toBe('Agentul Frigga nu este disponibil acum. Nu se trimite nimic până nu alegi cui îi scrii.');
  });

  it('names an agent that left the roster by the last name the hub gave it, else by its id', () => {
    expect(recipientRefusalText({ reason: 'unavailable', agent: 'hermes', name: 'Hermes the Herald' }, roster, 'en'))
      .toBe('Hermes the Herald is not available now. Nothing is sent until you choose who to write to.');
    expect(recipientRefusalText({ reason: 'unavailable', agent: 'hermes' }, roster, 'en'))
      .toBe('Hermes is not available now. Nothing is sent until you choose who to write to.');
    // the roster's own name wins over an older one
    expect(agentDisplayName('frigga', roster, 'Frigga (old)')).toBe('Frigga');
    expect(agentDisplayName('hermes', roster, '  ')).toBe('Hermes');
    // …but a /status or seed row is not the hub's roster: the last name the roster gave wins over it
    const seed = [{ id: 'frigga', name: 'Frigga' }];
    expect(agentDisplayName('frigga', seed, 'Frigga Allmother')).toBe('Frigga Allmother');
    expect(agentDisplayName('frigga', seed)).toBe('Frigga');
    expect(recipientRefusalText({ reason: 'unavailable', agent: 'frigga', name: 'Frigga Allmother' }, seed, 'en'))
      .toBe('Frigga Allmother is not available now. Nothing is sent until you choose who to write to.');
  });

  it('does not name what another sign-in chose, and words the other reasons', () => {
    expect(recipientRefusalText({ reason: 'signin' }, roster, 'en'))
      .toBe('The sign-in changed, so the agent chosen before is not used. Nothing is sent until you choose who to write to.');
    expect(recipientRefusalText({ reason: 'conversation' }, roster, 'en'))
      .toBe('No agent is chosen for this conversation. Nothing is sent until you choose who to write to.');
    expect(recipientRefusalText({ reason: 'unverified' }, roster, 'ro'))
      .toBe('Agentul ales înainte nu a putut fi verificat, așa că nu este folosit. Nu se trimite nimic până nu alegi cui îi scrii.');
  });

  it('has nothing specific to say without a reason, or an unavailable agent without a name', () => {
    expect(recipientRefusalText(null, roster, 'en')).toBeNull();
    expect(recipientRefusalText({ reason: 'unavailable' }, roster, 'en')).toBeNull();
  });
});
