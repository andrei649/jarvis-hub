/* The re-laid composer (PHASE_B_PLAN.md §5.3, §9.4 E5): exactly To, Mode, the field, Attach,
   Voice, Options and Send are visible; Enter sends, Shift+Enter adds a line, an IME composition
   never sends; a disabled Send says why; the local-only list includes howard; the recipient
   picker warns before it stops a reply. Its body renders the same in both frames, so these run
   against InputBar itself (the classic cockpit passes no picker, mode or variant, and draws no
   head: its layout shows the recipient above the composer). */
import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { InputBar } from '../../cockpit';
import { V2 } from '../../data';
import { composerField, composerSend, openComposerMenu } from './test-support';

const roster = [
  { id: 'jarvis', name: 'Jarvis', rosterSource: 'api', chat_routing: 'orchestrated', enabled: true },
  { id: 'frigga', name: 'Frigga', rosterSource: 'api', chat_routing: 'local', enabled: true },
  { id: 'howard', name: 'Howard', rosterSource: 'api', chat_routing: 'local', enabled: true },
];
const live = { state: 'live' as const, value: { mode: 'ask' as const }, checkedAt: 1, lastGoodAt: 1 };
const frame = () => document.querySelector('[data-composer-frame]') as HTMLElement;
const names = (nodes: HTMLElement[]) => nodes.map((node) => (node.textContent || '').trim());

beforeEach(() => { vi.stubGlobal('fetch', vi.fn(async () => Response.json({}))); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('the fixed visible set', () => {
  it('shows exactly To, Mode, the field, Attach, Voice, Options and Send in the Ledger register', () => {
    render(<InputBar t={V2.I18N.en} lang="en" agent="jarvis" agents={roster} selectedTurn sessionId="s" recipientStatus="ready"
      onSubmit={vi.fn()} onSelectAgent={vi.fn()} approvalMode={live} variant="home" />);
    const box = frame();
    expect(within(box).getAllByRole('combobox')).toEqual([within(box).getByRole('combobox', { name: 'To' })]);
    expect(within(box).getAllByRole('textbox')).toEqual([composerField()]);
    expect(names(within(box).getAllByRole('button'))).toEqual(['Attach', 'Voice', 'Options', 'Send']);
    const mode = box.querySelector('[data-mode]') as HTMLElement;
    expect(mode.getAttribute('data-mode')).toBe('ask');
    expect(mode.textContent).toBe('Mode Ask — anything with a side effect waits for you');
    expect(mode.getAttribute('title')).toContain('waits for your approval');
    expect(within(box).getByText('commands')).toBeTruthy();
    expect(within(box).getByText('files')).toBeTruthy();
    // the old prompt glyph and the hard-coded "VOICE · LOCAL" are gone
    expect(box.textContent).not.toContain('▸');
    expect(box.textContent).not.toContain(V2.I18N.en.channel);
    expect(composerSend().textContent).toBe('Send');
    expect(composerField().getAttribute('placeholder')).toBe('Message Jarvis…');
    expect(composerField().getAttribute('data-anchor')).toBe('composer');
    expect(box.querySelector('[data-composer-bar]')?.contains(composerSend())).toBe(true);
  });

  // The classic layout (no head, the outcome lines under the bar) was deleted with ChatMode at the
  // stage 5 cleanup (PHASE_B_PLAN.md §9.3, §8.3): a composer drawn without a variant is the Home one.
  it('draws the Ledger composer when no variant is given: the head, the fixed set, no outcome strip', () => {
    render(<InputBar t={V2.I18N.en} agent="frigga" agents={roster} selectedTurn sessionId="s" onSubmit={vi.fn()}
      outcome={{ latency_ms: 40, tokens: { total: 12 } } as any} />);
    const box = frame();
    expect(box.querySelector('.n-composer__head')).not.toBeNull();
    // no picker without onSelectAgent: the recipient is shown; the mode says it was not read here
    expect(box.querySelector('[data-recipient="frigga"]')?.textContent).toContain('Frigga');
    expect(box.querySelector('[data-mode]')).not.toBeNull();
    expect(within(box).getAllByRole('textbox')).toEqual([composerField()]);
    expect(names(within(box).getAllByRole('button'))).toEqual(['Attach', 'Voice', 'Options', 'Send']);
    expect(composerField().getAttribute('placeholder')).toBe('Message Frigga…');
    expect(box.getAttribute('aria-label')).toBe('Write to Frigga');
    expect(document.querySelector('[data-composer-variant="home"]')).toBeTruthy();
    expect(document.querySelector('[data-composer-variant="classic"]')).toBeNull();
    // the turn's outcome lines are its reply's Turn details now, never a strip under the composer
    expect(document.querySelector('section[aria-label="Turn outcome"]')).toBeNull();
    expect(document.body.textContent).not.toMatch(/Turn duration/);
  });

  it('says when the mode is the recipient\'s own setting rather than the global one', () => {
    render(<InputBar t={V2.I18N.en} agent="frigga" agents={roster} onSubmit={vi.fn()} onSelectAgent={vi.fn()} variant="home"
      approvalMode={{ state: 'live', value: { mode: 'auto', source: 'agent' }, checkedAt: 1, lastGoodAt: 1 }} />);
    const mode = frame().querySelector('[data-mode]') as HTMLElement;
    expect(mode.getAttribute('data-mode')).toBe('auto');
    expect(mode.getAttribute('data-mode-source')).toBe('agent');
    expect(mode.textContent).toBe('Mode Auto — each action is decided by its risk tier · Frigga’s own setting');
    expect(mode.getAttribute('title')).toMatch(/^Frigga has its own approval mode, which applies instead of the global one\. Each action/);
  });

  it('words a refused, stale or demo mode honestly and never guesses one', () => {
    const view = render(<InputBar t={V2.I18N.en} agent="jarvis" agents={roster} onSubmit={vi.fn()} variant="home"
      approvalMode={{ state: 'refused', value: null, checkedAt: 1, lastGoodAt: null, reason: 'credential', status: 401 }} />);
    expect(frame().querySelector('[data-mode]')?.textContent).toBe('Mode unknown — needs the owner credential');
    view.rerender(<InputBar t={V2.I18N.en} agent="jarvis" agents={roster} onSubmit={vi.fn()} variant="home"
      approvalMode={{ state: 'stale', value: { mode: 'off' }, checkedAt: 1, lastGoodAt: new Date(2026, 10, 23, 10, 44).getTime() }} />);
    const stale = frame().querySelector('[data-mode]') as HTMLElement;
    expect(stale.getAttribute('data-mode')).toBe('off');
    expect(stale.querySelector('[data-source-state="stale"]')?.textContent).toBe('Stale · checked 10:44');
    view.rerender(<InputBar t={V2.I18N.en} agent="jarvis" agents={roster} onSubmit={vi.fn()} variant="home" demo
      approvalMode={{ state: 'demo', value: null, checkedAt: null, lastGoodAt: null }} />);
    const demo = frame().querySelector('[data-mode]') as HTMLElement;
    expect(demo.getAttribute('data-mode')).toBe('demo');
    expect(demo.textContent).toContain('Demo sample');
    view.rerender(<InputBar t={V2.I18N.en} agent="jarvis" agents={roster} onSubmit={vi.fn()} variant="home"
      approvalMode={{ state: 'unknown', value: null, checkedAt: null, lastGoodAt: null, reason: 'checking' }} />);
    expect(frame().querySelector('[data-mode]')?.textContent).toBe('Mode Checking…');
    view.rerender(<InputBar t={V2.I18N.en} agent="jarvis" agents={roster} onSubmit={vi.fn()} variant="home"
      approvalMode={{ state: 'offline', value: { mode: 'ask' }, checkedAt: 2, lastGoodAt: new Date(2026, 10, 23, 10, 44).getTime(), reason: 'network' }} />);
    expect(frame().querySelector('[data-mode]')?.textContent).toBe('Mode Ask — anything with a side effect waits for you Offline · last good reading 10:44');
  });

  it('writes the head and the hints in Romanian', () => {
    render(<InputBar t={V2.I18N.ro} lang="ro" agent="jarvis" agents={roster} selectedTurn sessionId="s" onSubmit={vi.fn()}
      onSelectAgent={vi.fn()} approvalMode={live} variant="home" />);
    const box = frame();
    expect(names(within(box).getAllByRole('button'))).toEqual(['Atașează', 'Voce', 'Opțiuni', 'Trimite']);
    expect(box.querySelector('[data-mode]')?.textContent).toBe('Mod Întreabă — orice acțiune cu efecte te așteaptă pe tine');
    expect(composerField().getAttribute('placeholder')).toBe('Mesaj către Jarvis…');
    expect(within(box).getByText('comenzi')).toBeTruthy();
  });

  it('claims speech-to-text on this machine only when the voice capabilities say so', () => {
    const view = render(<InputBar t={V2.I18N.en} agent="jarvis" onSubmit={vi.fn()} voice={{ caps: { stt: true } }} />);
    const voice = within(frame()).getAllByRole('button')[1];
    expect(voice.textContent).toBe('Voice · speech-to-text on this machine');
    expect(voice.getAttribute('title')).toBe('hands-free voice');
    view.rerender(<InputBar t={V2.I18N.en} agent="jarvis" onSubmit={vi.fn()} voice={{ caps: { stt: false } }} cfg={{ mode: 'ptt' }} onCfg={vi.fn()} />);
    expect(within(frame()).getAllByRole('button')[1].textContent).toBe('Voice');
    expect(within(frame()).getAllByRole('button')[1].getAttribute('title')).toBe('push-to-talk');
  });

  it('says a muted or unsupported microphone in the Voice button\'s words, not by fading it', () => {
    const view = render(<InputBar t={V2.I18N.en} agent="jarvis" onSubmit={vi.fn()} voice={{ caps: { stt: true } }} micMuted />);
    const muted = within(frame()).getByRole('button', { name: 'Voice · mic muted' });
    expect(muted.getAttribute('title')).toBe('mic muted — unmute NERVA');
    expect(muted.getAttribute('style')).toBeNull();
    view.rerender(<InputBar t={V2.I18N.ro} lang="ro" agent="jarvis" onSubmit={vi.fn()} voice={{ supported: false }} />);
    const unsupported = within(frame()).getByRole('button', { name: 'Voce · nu e suportată în acest browser' });
    expect(unsupported.getAttribute('title')).toBe('voice not supported in this browser');
  });

  it('keeps the moved controls, with their names, behind Attach and Options', () => {
    render(<InputBar t={V2.I18N.en} agent="jarvis" agents={roster} selectedTurn sessionId="s" onSubmit={vi.fn()}
      cfg={{ mode: 'hands-free', tts: 'server', lang: 'auto' }} onCfg={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Choose images' })).toBeNull();
    const attach = openComposerMenu('attach');
    expect(names(within(attach).getAllByRole('button')).slice(1)).toEqual(['Images…', 'Files', 'Vault notes · type a message first', 'Board result']);
    expect(within(attach).getByRole('button', { name: 'Choose images' })).toBeTruthy();
    expect(within(attach).getByRole('button', { name: 'Attach document' })).toBeTruthy();
    expect((within(attach).getByRole('button', { name: 'Find vault notes' }) as HTMLButtonElement).disabled).toBe(true);
    expect(within(attach).getByRole('button', { name: 'Attach board result' })).toBeTruthy();
    const options = openComposerMenu('options');
    expect(names(within(options).getAllByRole('button')).slice(1)).toEqual(['Direct reply', 'Search chat history', 'Compare agents',
      'Make editable Blender model', 'Skills', 'Voice settings…', 'Use previous image']);
    fireEvent.click(within(options).getByRole('button', { name: 'Voice settings…' }));
    expect(within(options).getByText('MODE')).toBeTruthy();
    // Escape closes the menu and returns focus to its button
    fireEvent.keyDown(within(options).getByRole('button', { name: 'Direct reply' }), { key: 'Escape' });
    expect(options.querySelector('[role="group"]')?.hasAttribute('hidden')).toBe(true);
    expect(document.activeElement).toBe(options.firstElementChild);
  });
});

describe('keys', () => {
  it('sends on Enter, adds a line on Shift+Enter and never sends while an IME composes', () => {
    const submit = vi.fn(() => true);
    render(<InputBar t={V2.I18N.en} agent="jarvis" onSubmit={submit} />);
    const field = composerField();
    expect(field.tagName).toBe('TEXTAREA');
    fireEvent.change(field, { target: { value: 'line one' } });
    expect(fireEvent.keyDown(field, { key: 'Enter', shiftKey: true })).toBe(true);   // not prevented: the browser adds the line
    expect(submit).not.toHaveBeenCalled();
    expect(fireEvent.keyDown(field, { key: 'Enter', isComposing: true })).toBe(true);
    expect(fireEvent.keyDown(field, { key: 'Enter', keyCode: 229 })).toBe(true);
    expect(submit).not.toHaveBeenCalled();
    fireEvent.change(field, { target: { value: 'line one\nline two' } });
    expect(fireEvent.keyDown(field, { key: 'Enter' })).toBe(false);   // prevented: Enter sends, no new line
    expect(submit).toHaveBeenCalledExactlyOnceWith('line one\nline two');
    expect(field.value).toBe('');
  });

  it('accepts an @file: completion on Tab', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Response.json({ ok: true, items: [{ ref: '@file:notes.md', kind: 'file' }] })));
    const submit = vi.fn();
    render(<InputBar t={V2.I18N.en} agent="jarvis" onSubmit={submit} />);
    const field = composerField();
    fireEvent.change(field, { target: { value: 'read @file:no' } });
    expect(await screen.findByRole('option', { name: /@file:notes\.md/ })).toBeTruthy();
    expect(fireEvent.keyDown(field, { key: 'Tab' })).toBe(false);
    expect(field.value).toBe('read @file:notes.md ');
    expect(submit).not.toHaveBeenCalled();
  });

  it('counts from 3,500 and holds a message over the hub\'s 4,096 characters, counted as the hub counts them', () => {
    const submit = vi.fn(() => true);
    render(<InputBar t={V2.I18N.en} agent="jarvis" onSubmit={submit} />);
    const field = composerField();
    // no maxlength: a long paste is never cut silently
    expect(field.hasAttribute('maxlength')).toBe(false);
    fireEvent.change(field, { target: { value: 'x'.repeat(3500) } });
    expect(frame().querySelector('.n-composer__count')).toBeNull();
    fireEvent.change(field, { target: { value: 'x'.repeat(3612) } });
    expect(frame().querySelector('.n-composer__count')?.textContent).toBe('3,612 of 4,096 characters');
    expect(field.getAttribute('aria-describedby')).toBe(frame().querySelector('.n-composer__count')?.id);
    // 4,097 characters (8,194 UTF-16 units): kept in the field, counted, and not sent
    const over = '😀'.repeat(4097);
    fireEvent.change(field, { target: { value: over } });
    expect(field.value).toBe(over);
    const count = frame().querySelector('.n-composer__count') as HTMLElement;
    expect(count.textContent).toBe('4,097 of 4,096 characters');
    expect(count.hasAttribute('data-over')).toBe(true);
    expect(composerSend().disabled).toBe(true);
    const why = frame().querySelector('.n-composer__why') as HTMLElement;
    expect(why.textContent).toBe('The message is 1 character over the limit of 4,096.');
    expect(composerSend().getAttribute('aria-describedby')).toBe(why.id);
    fireEvent.keyDown(field, { key: 'Enter' });
    expect(submit).not.toHaveBeenCalled();
    // 4,096 of them is within the limit, though it is 8,192 UTF-16 units
    fireEvent.change(field, { target: { value: '😀'.repeat(4096) } });
    expect(composerSend().disabled).toBe(false);
    fireEvent.keyDown(field, { key: 'Enter' });
    expect(submit).toHaveBeenCalledExactlyOnceWith('😀'.repeat(4096));
  });

  it('holds text a control put past the limit (a completion, the voice) the same way', () => {
    render(<InputBar t={V2.I18N.ro} lang="ro" agent="jarvis" onSubmit={vi.fn()} />);
    fireEvent.change(composerField(), { target: { value: 'x'.repeat(4120) } });
    expect(composerSend().disabled).toBe(true);
    expect(frame().querySelector('.n-composer__why')?.textContent).toBe('Mesajul depășește limita de 4.096 cu 24 de caractere.');
  });
});

describe('a disabled Send says why', () => {
  it('points at the recipient hint, which already says it', () => {
    render(<InputBar t={V2.I18N.en} agent="frigga" onSubmit={vi.fn()} recipientStatus="checking" />);
    expect(composerSend().disabled).toBe(true);
    expect(composerSend().getAttribute('aria-describedby')).toBe(screen.getByText('Checking the selected agent…').id);
    expect(frame().querySelector('.n-composer__why')).toBeNull();
  });

  it('writes the reason under the bar when nothing above says it', () => {
    render(<InputBar t={V2.I18N.en} agent="frigga" sessionId="s" selectedTurn onSubmit={vi.fn()} />);
    expect(composerSend().disabled).toBe(false);
    openComposerMenu('options');
    fireEvent.click(screen.getByRole('button', { name: 'Make editable Blender model' }));
    expect(composerSend().disabled).toBe(true);
    const why = frame().querySelector('.n-composer__why') as HTMLElement;
    expect(why.textContent).toBe('Describe the model in the message field.');
    expect(composerSend().getAttribute('aria-describedby')).toBe(why.id);
    expect(why.getAttribute('role')).toBeNull();   // not a live region: Send carries it
    fireEvent.change(composerField(), { target: { value: 'A cube' } });
    expect(composerSend().disabled).toBe(false);
    expect(frame().querySelector('.n-composer__why')).toBeNull();
    expect(composerSend().getAttribute('aria-describedby')).toBeNull();
    fireEvent.change(composerField(), { target: { value: 'x'.repeat(4096) } });
    expect(composerSend().getAttribute('aria-describedby')).toBe(screen.getByRole('alert').id);
    // a / command, not an attachment, is what holds the Blender model here
    fireEvent.change(composerField(), { target: { value: '/new a cube' } });
    expect(composerSend().disabled).toBe(true);
    expect(frame().querySelector('.n-composer__why')?.textContent).toBe('A / command cannot make a Blender model. Remove the / or turn off the Blender model.');
  });

  it('turns the Blender model off when its switch leaves the screen (demo), so Send is never held by it', () => {
    const view = render(<InputBar t={V2.I18N.en} agent="frigga" sessionId="s" selectedTurn onSubmit={vi.fn()} />);
    openComposerMenu('options');
    fireEvent.click(screen.getByRole('button', { name: 'Make editable Blender model' }));
    expect(composerSend().disabled).toBe(true);
    view.rerender(<InputBar t={V2.I18N.en} agent="frigga" sessionId="s" selectedTurn={false} demo onSubmit={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Make editable Blender model' })).toBeNull();
    expect(composerSend().disabled).toBe(false);
    expect(frame().querySelector('.n-composer__why')).toBeNull();
  });
});

describe('the recipient', () => {
  it('chooses from the selectable roster and never opens the Dossier', () => {
    const select = vi.fn();
    render(<InputBar t={V2.I18N.en} agent="jarvis" agents={[...roster, { id: 'retired', rosterSource: 'api', status: 'retired' }]}
      onSubmit={vi.fn()} onSelectAgent={select} variant="home" />);
    const picker = screen.getByRole('combobox', { name: 'To' }) as HTMLSelectElement;
    expect(Array.from(picker.options).map((o) => o.textContent)).toEqual(['Jarvis · Orchestrated', 'Frigga · Local', 'Howard · Local']);
    fireEvent.change(picker, { target: { value: 'frigga' } });
    expect(select).toHaveBeenCalledExactlyOnceWith('frigga');
  });

  it('warns before changing the recipient stops a reply in progress', () => {
    const select = vi.fn();
    render(<InputBar t={V2.I18N.en} agent="jarvis" agents={roster} onSubmit={vi.fn()} onSelectAgent={select} turnActive variant="home" />);
    fireEvent.change(screen.getByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
    expect(select).not.toHaveBeenCalled();
    const warning = screen.getByRole('alert');
    expect(warning.textContent).toContain('Writing to Frigga stops the reply in progress.');
    fireEvent.click(within(warning).getByRole('button', { name: 'Keep writing to Jarvis' }));
    expect(screen.queryByRole('alert')).toBeNull();
    expect(select).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
    fireEvent.click(screen.getByRole('button', { name: 'Stop it and write to Frigga' }));
    expect(select).toHaveBeenCalledExactlyOnceWith('frigga');
  });

  it('asks for a choice when no recipient is ready', () => {
    render(<InputBar t={V2.I18N.en} agent="" agents={roster} onSubmit={vi.fn()} onSelectAgent={vi.fn()} recipientStatus="choose" variant="home" />);
    const picker = screen.getByRole('combobox', { name: 'To' }) as HTMLSelectElement;
    expect(picker.value).toBe('');
    expect(picker.selectedOptions[0].textContent).toBe('Choose an agent');
    expect(composerField().getAttribute('placeholder')).toBe('Choose an agent');
    // without a reason from App, the generic line
    expect(composerSend().disabled).toBe(true);
    expect(document.getElementById(composerSend().getAttribute('aria-describedby') || '')?.textContent).toBe('Choose an available agent before sending.');
  });

  it('says why the recipient was dropped, and that nothing goes to another agent', () => {
    const submit = vi.fn();
    const view = render(<InputBar t={V2.I18N.en} agent="" agents={roster} onSubmit={submit} onSelectAgent={vi.fn()} recipientStatus="choose"
      recipientRefusal={{ reason: 'unavailable', agent: 'frigga' }} variant="home" />);
    const line = () => document.getElementById(composerSend().getAttribute('aria-describedby') || '') as HTMLElement;
    expect(composerSend().disabled).toBe(true);
    expect(line().textContent).toBe('Frigga is not available now. Nothing is sent until you choose who to write to.');
    expect(line().getAttribute('role')).toBe('status');
    expect(line().getAttribute('data-recipient-reason')).toBe('unavailable');
    // said in words, never by a status hue (the line is drawn by talk.css, not an inline amber)
    expect(line().className).toBe('n-composer__recipient');
    expect(line().getAttribute('style')).toBeNull();
    fireEvent.change(composerField(), { target: { value: 'Do not send this anywhere' } });
    fireEvent.keyDown(composerField(), { key: 'Enter' });
    expect(submit).not.toHaveBeenCalled();
    view.rerender(<InputBar t={V2.I18N.ro} lang="ro" agent="" agents={roster} onSubmit={submit} onSelectAgent={vi.fn()} recipientStatus="choose"
      recipientRefusal={{ reason: 'signin' }} variant="home" />);
    expect(line().textContent).toBe('Autentificarea s-a schimbat, așa că agentul ales înainte nu mai este folosit. Nu se trimite nimic până nu alegi cui îi scrii.');
    // while the saved choice is still being checked, it says so, whatever reason came before
    view.rerender(<InputBar t={V2.I18N.en} agent="" agents={roster} onSubmit={submit} onSelectAgent={vi.fn()} recipientStatus="checking"
      recipientRefusal={{ reason: 'signin' }} variant="home" />);
    expect(line().textContent).toBe('Checking the selected agent…');
    expect(line().getAttribute('data-recipient-reason')).toBeNull();
  });

  it('holds Send while the To asks about stopping a reply, and lets it go once answered', () => {
    const submit = vi.fn(() => true);
    render(<InputBar t={V2.I18N.en} agent="jarvis" agents={roster} onSubmit={submit} onSelectAgent={vi.fn()} turnActive variant="home" />);
    fireEvent.change(composerField(), { target: { value: 'Meant for Frigga' } });
    expect(composerSend().disabled).toBe(false);
    fireEvent.change(screen.getByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
    // the change waits for the answer; a message sent now would still go to Jarvis, so Send waits too
    expect(composerSend().disabled).toBe(true);
    expect(document.getElementById(composerSend().getAttribute('aria-describedby') || '')?.textContent)
      .toBe('Writing to Frigga stops the reply in progress.');
    fireEvent.keyDown(composerField(), { key: 'Enter' });
    expect(submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Keep writing to Jarvis' }));
    expect(composerSend().disabled).toBe(false);
    expect(composerSend().getAttribute('aria-describedby')).toBeNull();
    fireEvent.keyDown(composerField(), { key: 'Enter' });
    expect(submit).toHaveBeenCalledExactlyOnceWith('Meant for Frigga');
  });

  // PHASE_B_PLAN.md §12 item 11: nothing switches by itself when the reply ends
  it('keeps Send held, pointing at the question, when the reply ends unanswered', () => {
    const submit = vi.fn(() => true);
    const select = vi.fn();
    const view = render(<InputBar t={V2.I18N.en} agent="jarvis" agents={roster} onSubmit={submit} onSelectAgent={select} turnActive variant="home" />);
    fireEvent.change(composerField(), { target: { value: 'Meant for Frigga' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
    view.rerender(<InputBar t={V2.I18N.en} agent="jarvis" agents={roster} onSubmit={submit} onSelectAgent={select} turnActive={false} variant="home" />);
    expect(select).not.toHaveBeenCalled();
    expect(composerSend().disabled).toBe(true);
    expect(document.getElementById(composerSend().getAttribute('aria-describedby') || '')?.textContent)
      .toBe('The reply from Jarvis has ended. Write to Frigga?');
    fireEvent.keyDown(composerField(), { key: 'Enter' });
    expect(submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Write to Frigga' }));
    expect(select).toHaveBeenCalledExactlyOnceWith('frigga');
  });

  it('holds Send for a question App keeps from the first frame it is drawn, and hands the answer to App', () => {
    const submit = vi.fn(() => true);
    const select = vi.fn();
    const answer = vi.fn();
    const kept = { id: 'frigga', from: 'jarvis', demo: false, at: 1 };
    const view = render(<InputBar t={V2.I18N.en} agent="jarvis" agents={roster} onSubmit={submit} onSelectAgent={select}
      recipientSwitch={kept} onRecipientSwitch={answer} variant="home" />);
    expect(composerSend().disabled).toBe(true);
    expect(document.getElementById(composerSend().getAttribute('aria-describedby') || '')?.textContent)
      .toBe('The reply from Jarvis has ended. Write to Frigga?');
    fireEvent.click(screen.getByRole('button', { name: 'Stay with Jarvis' }));
    expect(answer).toHaveBeenCalledExactlyOnceWith(null);
    expect(select).not.toHaveBeenCalled();
    // App let it go: Send is free again, and a pick while a reply is written goes to App to keep
    view.rerender(<InputBar t={V2.I18N.en} agent="jarvis" agents={roster} onSubmit={submit} onSelectAgent={select}
      recipientSwitch={null} onRecipientSwitch={answer} turnActive variant="home" />);
    fireEvent.change(composerField(), { target: { value: 'Still to Jarvis' } });
    expect(composerSend().disabled).toBe(false);
    fireEvent.change(screen.getByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
    expect(answer).toHaveBeenLastCalledWith('frigga');
    expect(select).not.toHaveBeenCalled();
  });

  it('says it is checking in one sentence, in both languages', () => {
    const view = render(<InputBar t={V2.I18N.en} agent="" agents={roster} onSubmit={vi.fn()} onSelectAgent={vi.fn()} recipientStatus="checking" variant="home" />);
    const line = () => document.getElementById(composerSend().getAttribute('aria-describedby') || '') as HTMLElement;
    expect(line().textContent).toBe('Checking the selected agent…');
    view.rerender(<InputBar t={V2.I18N.ro} lang="ro" agent="" agents={roster} onSubmit={vi.fn()} onSelectAgent={vi.fn()} recipientStatus="checking" variant="home" />);
    expect(line().textContent).toBe('Se verifică agentul selectat…');
    view.rerender(<InputBar t={V2.I18N.ro} lang="ro" agent="" agents={roster} onSubmit={vi.fn()} onSelectAgent={vi.fn()} recipientStatus="choose" variant="home" />);
    expect(line().textContent).toBe('Alege un agent disponibil înainte de a trimite.');
  });

  // a poll has completed without the hub's roster: the selected agent cannot be confirmed (App keeps it)
  it('says a selected agent cannot be confirmed while the roster is not served, names it, and offers Jarvis', () => {
    const seed = [{ id: 'jarvis', name: 'Jarvis' }, { id: 'frigga', name: 'Frigga' }];
    const select = vi.fn();
    const submit = vi.fn(() => true);
    const view = render(<InputBar t={V2.I18N.en} agent="" agents={seed} onSubmit={submit} onSelectAgent={select} recipientStatus="checking"
      recipientHold={{ agent: 'frigga', name: 'Frigga Allmother' }} variant="home" />);
    const line = () => document.getElementById(composerSend().getAttribute('aria-describedby') || '') as HTMLElement;
    expect(composerSend().disabled).toBe(true);
    expect(line().textContent).toBe('The hub did not serve the agent roster, so Frigga Allmother cannot be confirmed until it does. Nothing is sent until then, unless you choose Jarvis.');
    expect(line().getAttribute('data-recipient-state')).toBe('unconfirmed');
    expect(line().getAttribute('role')).toBe('status');
    // the field is for her, as the owner chose; nothing is sent to her meanwhile
    expect(composerField().getAttribute('placeholder')).toBe('Message Frigga Allmother…');
    expect(screen.getByRole('textbox', { name: 'Write to Frigga Allmother' })).toBe(composerField());
    fireEvent.change(composerField(), { target: { value: 'For Frigga' } });
    fireEvent.keyDown(composerField(), { key: 'Enter' });
    expect(submit).not.toHaveBeenCalled();
    // the To names her and offers Jarvis, which needs no roster; choosing him is the owner's choice
    const picker = screen.getByRole('combobox', { name: 'To' }) as HTMLSelectElement;
    expect(Array.from(picker.options).map((o) => o.textContent)).toEqual(['Frigga Allmother · not confirmed', 'Jarvis · Routing policy unknown']);
    expect(picker.value).toBe('');
    fireEvent.change(picker, { target: { value: 'jarvis' } });
    expect(select).toHaveBeenCalledExactlyOnceWith('jarvis');
    expect(document.activeElement).toBe(composerField());
    view.rerender(<InputBar t={V2.I18N.ro} lang="ro" agent="frigga" agents={seed} onSubmit={submit} onSelectAgent={select} recipientStatus="checking"
      recipientHold={{ agent: 'frigga' }} variant="home" />);
    expect(line().textContent).toBe('Hubul nu a trimis lista agenților, așa că agentul Frigga nu poate fi confirmat până nu o trimite. Nu se trimite nimic până atunci, decât dacă îl alegi pe Jarvis.');
    expect(Array.from((screen.getByRole('combobox', { name: 'Către' }) as HTMLSelectElement).options).map((o) => o.textContent))
      .toEqual(['Frigga · neconfirmat', 'Jarvis · Politica de rutare necunoscută']);
    // still being checked (no hold from App): it says so, as before
    view.rerender(<InputBar t={V2.I18N.en} agent="" agents={seed} onSubmit={submit} onSelectAgent={select} recipientStatus="checking" variant="home" />);
    expect(line().textContent).toBe('Checking the selected agent…');
    expect(line().getAttribute('data-recipient-state')).toBe('checking');
  });

  it('says why its own question was dropped (drawn without App), until the next send, a new recipient or Dismiss', () => {
    const submit = vi.fn(() => true);
    const DROPPED = 'Frigga is not available now, so the change to Frigga was dropped. Messages still go to Jarvis.';
    const bar = (agent: string, agents: typeof roster, turnActive: boolean) => (
      <InputBar t={V2.I18N.en} agent={agent} agents={agents} onSubmit={submit} onSelectAgent={vi.fn()} turnActive={turnActive} variant="home" />);
    const line = () => document.querySelector('[data-recipient-dropped]') as HTMLElement | null;
    const view = render(bar('jarvis', roster, true));
    const dropOwn = () => {
      fireEvent.change(screen.getByRole('combobox', { name: 'To' }), { target: { value: 'frigga' } });
      expect(screen.getByRole('alert')).toBeTruthy();
      // a roster the hub served without Frigga: the question goes, and the line says why
      view.rerender(bar('jarvis', roster.filter((a) => a.id !== 'frigga'), true));
      expect(screen.queryByRole('alert')).toBeNull();
    };
    dropOwn();
    expect(line()?.getAttribute('data-recipient-dropped')).toBe('frigga');
    expect(line()?.getAttribute('role')).toBe('status');
    expect(within(line()!).getByText(DROPPED)).toBeTruthy();
    // Send is free: the line holds nothing; the next send ends it
    view.rerender(bar('jarvis', roster.filter((a) => a.id !== 'frigga'), false));
    fireEvent.change(composerField(), { target: { value: 'Still Jarvis' } });
    expect(composerSend().disabled).toBe(false);
    fireEvent.keyDown(composerField(), { key: 'Enter' });
    expect(submit).toHaveBeenCalledExactlyOnceWith('Still Jarvis');
    expect(line()).toBeNull();
    // Dismiss ends it
    view.rerender(bar('jarvis', roster, true));
    dropOwn();
    fireEvent.click(within(line()!).getByRole('button', { name: 'Dismiss' }));
    expect(line()).toBeNull();
    // so does a new recipient
    view.rerender(bar('jarvis', roster, true));
    dropOwn();
    expect(line()).not.toBeNull();
    view.rerender(bar('howard', roster.filter((a) => a.id !== 'frigga'), true));
    expect(line()).toBeNull();
  });

  it('draws the line App keeps about a dropped question, names the agent as the hub last did, and hands Dismiss to App', () => {
    const dismiss = vi.fn();
    const view = render(<InputBar t={V2.I18N.en} agent="jarvis" agents={[roster[0]]} onSubmit={vi.fn()} onSelectAgent={vi.fn()}
      recipientSwitch={null} onRecipientSwitch={vi.fn()} recipientSwitchDropped={{ id: 'frigga', name: 'Frigga Allmother', from: 'jarvis', demo: false }}
      onRecipientSwitchDropped={dismiss} variant="home" />);
    const line = () => document.querySelector('[data-recipient-dropped]') as HTMLElement;
    expect(line().textContent).toContain('Frigga Allmother is not available now, so the change to Frigga Allmother was dropped. Messages still go to Jarvis.');
    expect(composerSend().hasAttribute('aria-describedby')).toBe(false);
    fireEvent.click(within(line()).getByRole('button', { name: 'Dismiss' }));
    expect(dismiss).toHaveBeenCalledOnce();
    view.rerender(<InputBar t={V2.I18N.ro} lang="ro" agent="jarvis" agents={[roster[0]]} onSubmit={vi.fn()} onSelectAgent={vi.fn()}
      recipientSwitch={null} onRecipientSwitch={vi.fn()} recipientSwitchDropped={{ id: 'frigga', from: 'jarvis', demo: false }}
      onRecipientSwitchDropped={dismiss} variant="home" />);
    expect(line().textContent).toContain('Agentul Frigga nu este disponibil acum, așa că schimbarea către Frigga a fost anulată. Mesajele merg în continuare către Jarvis.');
    expect(within(line()).getByRole('button', { name: 'Închide' })).toBeTruthy();
  });

  it('lets a choice be made when the hub did not serve the roster, and gives the field the focus', () => {
    const select = vi.fn();
    render(<InputBar t={V2.I18N.en} agent="" agents={[{ id: 'jarvis', name: 'Jarvis' }]} onSubmit={vi.fn()} onSelectAgent={select}
      recipientStatus="choose" recipientRefusal={{ reason: 'signin' }} variant="home" />);
    const picker = screen.getByRole('combobox', { name: 'To' }) as HTMLSelectElement;
    expect(Array.from(picker.options).map((o) => o.textContent)).toEqual(['Choose an agent', 'Jarvis · Routing policy unknown']);
    fireEvent.change(picker, { target: { value: 'jarvis' } });
    expect(select).toHaveBeenCalledExactlyOnceWith('jarvis');
    expect(document.activeElement).toBe(composerField());
  });
});

describe('the local-only list includes howard', () => {
  it('stages a task result for howard without a cloud consent, as for the other local-only agents', async () => {
    HTMLDialogElement.prototype.showModal ||= function () { this.setAttribute('open', ''); };
    HTMLDialogElement.prototype.close ||= function () { this.removeAttribute('open'); };
    const digest = 'a'.repeat(64);
    const card = { id: 't_one', title: 'One', status: 'done', result: 'First', board_source_sha256: digest };
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url.endsWith('/boards')) return Response.json({ current: 'alpha', boards: [{ slug: 'alpha' }] });
      if (url.includes('/board?')) return Response.json({ columns: [{ tasks: [card] }] });
      return Response.json({ task: card });
    }));
    for (const agent of ['howard', 'athena']) {
      const view = render(<InputBar t={V2.I18N.en} selectedTurn agent={agent} sessionId={`s-${agent}`} onSubmit={vi.fn()} />);
      openComposerMenu('attach');
      fireEvent.click(screen.getByRole('button', { name: 'Attach board result' }));
      fireEvent.change(await screen.findByRole('combobox', { name: 'Completed task' }), { target: { value: 't_one' } });
      fireEvent.click(await screen.findByRole('button', { name: 'Attach full result' }));
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Attach completed task result' })).toBeNull());
      const consent = screen.queryByRole('checkbox', { name: /Allow these reviewed passages/ });
      if (agent === 'howard') {
        expect(consent).toBeNull();
        expect(composerSend().disabled).toBe(false);
      } else {
        expect(consent).toBeTruthy();
        expect(composerSend().disabled).toBe(true);
        expect(frame().querySelector('.n-composer__why')?.textContent).toBe('Allow the reviewed passages to reach the cloud provider, or remove them.');
      }
      view.unmount();
    }
  });
});
