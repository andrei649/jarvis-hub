// @ts-nocheck
/* H168 — one confirmation primitive, graded by the approval queue's risk tiers:
   0 one click, 1 two steps, 2 and 3 a typed phrase. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { flushSync } from 'react-dom';
import { createRoot } from 'react-dom/client';
import { ConfirmAction, RISK_TIER, confirmStyle } from '../confirm';

beforeEach(() => cleanup());

describe('confirmStyle — H168', () => {
  it('grades like RiskTier, and the unknown takes the most', () => {
    expect(RISK_TIER).toEqual({ READ_ONLY: 0, REVERSIBLE: 1, EXTERNAL: 2, IRREVERSIBLE_OR_MONEY: 3 });
    expect([0, 1, 2, 3].map(confirmStyle)).toEqual(['click', 'two-step', 'typed', 'typed']);
    expect([4, -1, 0.5, NaN].map(confirmStyle)).toEqual(['typed', 'typed', 'typed', 'typed']);
  });
});

describe('ConfirmAction — H168', () => {
  it('tier 0 fires on one click', () => {
    const go = vi.fn();
    render(<ConfirmAction tier={RISK_TIER.READ_ONLY} label="HALT ALL" onConfirm={go} />);
    fireEvent.click(screen.getByText('HALT ALL'));
    expect(go).toHaveBeenCalledTimes(1);
  });

  it('tier 1 needs a second click, and cancel or Escape backs out', () => {
    const go = vi.fn();
    render(<ConfirmAction tier={RISK_TIER.REVERSIBLE} label="remove" armedLabel="remove for good" cancelLabel="keep it" onConfirm={go} />);
    fireEvent.click(screen.getByText('remove'));
    expect(go).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByText('remove for good'));      // focus follows
    fireEvent.click(screen.getByText('keep it'));
    expect(go).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByText('remove'));
    fireEvent.click(screen.getByText('remove'));
    fireEvent.keyDown(screen.getByText('remove for good'), { key: 'Escape' });
    expect(screen.queryByText('remove for good')).toBeNull();
    fireEvent.click(screen.getByText('remove'));
    fireEvent.click(screen.getByText('remove for good'));
    expect(go).toHaveBeenCalledTimes(1);
    expect(screen.getByText('remove')).toBeTruthy();                                // back to rest
  });

  it('tier 3 does not fire until the phrase matches exactly', () => {
    const go = vi.fn();
    render(<ConfirmAction tier={RISK_TIER.IRREVERSIBLE_OR_MONEY} label="erase" phrase="FORGET" armedLabel="confirm erase" onConfirm={go} />);
    fireEvent.click(screen.getByText('erase'));
    const box = screen.getByLabelText('type FORGET to confirm erase');
    expect(document.activeElement).toBe(box);
    expect(screen.getByText('type FORGET to confirm')).toBeTruthy();
    const confirm = screen.getByText('confirm erase');
    expect(confirm.disabled).toBe(true);
    fireEvent.change(box, { target: { value: 'forget' } });                          // case matters
    expect(confirm.disabled).toBe(true);
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(go).not.toHaveBeenCalled();
    fireEvent.change(box, { target: { value: 'FORGET' } });
    expect(confirm.disabled).toBe(false);
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(go).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText('erase'));                                      // the box starts empty again
    expect(screen.getByLabelText('type FORGET to confirm erase').value).toBe('');
  });

  it('a cancelled phrase is not remembered: re-opening starts empty and disarmed', () => {
    const go = vi.fn();
    render(<ConfirmAction tier={3} label="erase" phrase="FORGET" armedLabel="confirm erase" onConfirm={go} />);
    fireEvent.click(screen.getByText('erase'));
    fireEvent.change(screen.getByLabelText('type FORGET to confirm erase'), { target: { value: 'FORGET' } });
    fireEvent.keyDown(screen.getByLabelText('type FORGET to confirm erase'), { key: 'Escape' });
    fireEvent.click(screen.getByText('erase'));
    expect(screen.getByLabelText('type FORGET to confirm erase').value).toBe('');
    expect(screen.getByText('confirm erase').disabled).toBe(true);
    fireEvent.keyDown(screen.getByLabelText('type FORGET to confirm erase'), { key: 'Enter' });
    expect(go).not.toHaveBeenCalled();
  });

  it('tier 2 is typed too, and a busy or disabled action cannot fire', () => {
    const go = vi.fn();
    const { rerender } = render(<ConfirmAction tier={RISK_TIER.EXTERNAL} label="disengage" phrase="DISENGAGE" onConfirm={go} busy />);
    expect(screen.getByText('disengage').disabled).toBe(true);
    rerender(<ConfirmAction tier={RISK_TIER.EXTERNAL} label="disengage" phrase="DISENGAGE" onConfirm={go} />);
    fireEvent.click(screen.getByText('disengage'));
    fireEvent.change(screen.getByLabelText('type DISENGAGE to confirm disengage'), { target: { value: 'DISENGAGE' } });
    rerender(<ConfirmAction tier={RISK_TIER.EXTERNAL} label="disengage" phrase="DISENGAGE" onConfirm={go} disabled />);
    fireEvent.keyDown(screen.getByLabelText('type DISENGAGE to confirm disengage'), { key: 'Enter' });
    expect(go).not.toHaveBeenCalled();
    expect(screen.getByText('confirm disengage').closest('button').disabled).toBe(true);
    fireEvent.keyDown(screen.getByLabelText('type DISENGAGE to confirm disengage'), { key: 'Escape' });
    expect(screen.queryByLabelText('type DISENGAGE to confirm disengage')).toBeNull();
  });

  it('an action that returns a promise keeps the confirmation open until it lands, and a refusal keeps it armed', async () => {
    let settle;
    const go = vi.fn(() => new Promise((resolve) => { settle = resolve; }));
    const armedWith = vi.fn();
    render(<ConfirmAction tier={1} label="uninstall…" armedLabel="confirm remove" onArm={armedWith} onConfirm={go}
      extra={<input aria-label="folder" defaultValue="weather" />} />);
    fireEvent.click(screen.getByText('uninstall…'));
    expect(armedWith).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText('folder')).toBeTruthy();                        // the extra fields show
    fireEvent.click(screen.getByText('confirm remove'));
    expect(screen.getByText('confirm remove').disabled).toBe(true);             // in flight
    expect(screen.getByText('cancel').disabled).toBe(true);
    settle(false);                                                               // refused
    await waitFor(() => expect(screen.getByText('confirm remove').disabled).toBe(false));
    expect(screen.getByLabelText('folder')).toBeTruthy();                        // still armed
    fireEvent.click(screen.getByText('confirm remove'));
    settle(true);                                                                // landed
    await waitFor(() => expect(screen.getByText('uninstall…')).toBeTruthy());
    expect(go).toHaveBeenCalledTimes(2);
  });

  it('a synchronous false keeps it armed; a rejected promise re-enables it', async () => {
    const refuse = vi.fn(() => false);
    render(<ConfirmAction tier={1} label="go" onConfirm={refuse} />);
    fireEvent.click(screen.getByText('go'));
    fireEvent.click(screen.getByText('confirm go'));
    expect(screen.getByText('confirm go')).toBeTruthy();
    cleanup();
    const boom = vi.fn(() => Promise.reject(new Error('x')));
    render(<ConfirmAction tier={1} label="go" onConfirm={boom} />);
    fireEvent.click(screen.getByText('go'));
    fireEvent.click(screen.getByText('confirm go'));
    await waitFor(() => expect(screen.getByText('confirm go').disabled).toBe(false));
  });

  it('a controlled confirmation is opened and closed by the page', () => {
    const cancel = vi.fn();
    const go = vi.fn(() => true);
    const { rerender } = render(<ConfirmAction tier={1} label="x" armedLabel="confirm remove" armed={false} onCancel={cancel} onConfirm={go} />);
    expect(screen.queryByText('confirm remove')).toBeNull();                  // nothing while closed
    expect(screen.queryByText('x')).toBeNull();                               // the page owns the trigger
    rerender(<ConfirmAction tier={1} label="x" armedLabel="confirm remove" armed onCancel={cancel} onConfirm={go} />);
    expect(document.activeElement).toBe(screen.getByText('confirm remove'));
    fireEvent.click(screen.getByText('cancel'));
    expect(cancel).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText('confirm remove'));
    expect(go).toHaveBeenCalledTimes(1);
    expect(screen.getByText('confirm remove')).toBeTruthy();                  // the page closes it, not the click
  });

  it('an open typed confirmation shows the phrase box at once, with no trigger and no cancel', () => {
    const go = vi.fn();
    render(<ConfirmAction tier={3} open label="rotate" phrase="admin" armedLabel="ROTATE" onConfirm={go} />);
    const box = screen.getByLabelText('type admin to confirm rotate');
    expect(screen.queryByText('rotate')).toBeNull();
    expect(screen.queryByText('cancel')).toBeNull();
    expect(screen.getAllByRole('button')).toHaveLength(1);
    fireEvent.keyDown(box, { key: 'Escape' });
    expect(screen.getByLabelText('type admin to confirm rotate')).toBeTruthy();   // nothing to close
    fireEvent.change(screen.getByLabelText('type admin to confirm rotate'), { target: { value: 'admin' } });
    fireEvent.click(screen.getByText('ROTATE'));
    expect(go).toHaveBeenCalledTimes(1);
  });

  it('never renders raw HTML from a label or phrase', () => {
    render(<ConfirmAction tier={3} label="<b>x</b>" phrase="<i>y</i>" onConfirm={() => {}} />);
    fireEvent.click(screen.getByText('<b>x</b>'));
    expect(screen.getByText('type <i>y</i> to confirm')).toBeTruthy();
    expect(document.querySelector('b, i')).toBeNull();
  });
});

/* Phase B (PHASE_B_PLAN.md §5.4): the docket's signature line and the Decision Inbox sign through
   ConfirmAction with additive props; left out, nothing above changes. */
describe('ConfirmAction — Phase B props', () => {
  it('enterConfirms={false}: Enter in the phrase box never confirms, even when the phrase matches, and is held there', () => {
    const go = vi.fn();
    render(<ConfirmAction tier={3} open enterConfirms={false} label="sign" phrase="restart" armedLabel="Sign" onConfirm={go} />);
    const box = screen.getByLabelText('type restart to confirm sign');
    fireEvent.change(box, { target: { value: 'restart' } });
    const enter = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
    box.dispatchEvent(enter);
    expect(enter.defaultPrevented).toBe(true);
    expect(go).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('Sign'));                                     // only the button signs
    expect(go).toHaveBeenCalledTimes(1);
  });

  it('enterConfirms is true by default: a matching phrase and Enter confirm, as before', () => {
    const go = vi.fn();
    render(<ConfirmAction tier={2} open label="send" phrase="send" onConfirm={go} />);
    const box = screen.getByLabelText('type send to confirm send');
    fireEvent.change(box, { target: { value: 'send' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(go).toHaveBeenCalledTimes(1);
  });

  it('plain: no inline colour or layout anywhere in a typed confirmation, only the caller\'s classes', () => {
    const { container } = render(<ConfirmAction tier={3} open plain label="sign" phrase="delete" armedLabel="Sign"
      groupClassName="sig-group" inputClassName="sig-input" confirmClassName="sig-button" groupLabel="Signature line: Delete logs"
      prompt="Sign here — type delete" onConfirm={() => {}} />);
    const group = screen.getByRole('group', { name: 'Signature line: Delete logs' });
    expect(group.className).toBe('sig-group');
    expect(screen.getByLabelText('type delete to confirm sign').className).toBe('sig-input');
    expect(screen.getByText('Sign').className).toBe('sig-button');
    expect(container.querySelectorAll('[style]')).toHaveLength(0);
    fireEvent.change(screen.getByLabelText('type delete to confirm sign'), { target: { value: 'delete' } });
    expect(container.querySelectorAll('[style]')).toHaveLength(0);                 // and none once it matches
  });

  it('plain: none in a two-step confirmation either', () => {
    const { container } = render(<ConfirmAction tier={1} plain label="Sign" armedLabel="Confirm signature" cancelLabel="Cancel"
      groupClassName="two-step" prompt="Sign: Draft a reply" onConfirm={() => {}} />);
    fireEvent.click(screen.getByText('Sign'));
    expect(screen.getByRole('group').className).toBe('two-step');
    expect(container.querySelectorAll('[style]')).toHaveLength(0);
  });

  it('repeatConfirms={false}, two steps: the press that armed it cannot also confirm — no key repeat, no double-click', () => {
    const go = vi.fn();
    render(<ConfirmAction tier={1} repeatConfirms={false} label="Sign" armedLabel="Confirm signature" onConfirm={go} />);
    fireEvent.click(screen.getByText('Sign'));
    const confirm = screen.getByText('Confirm signature');
    expect(document.activeElement).toBe(confirm);                       // focus moved onto it
    const held = new KeyboardEvent('keydown', { key: 'Enter', repeat: true, bubbles: true, cancelable: true });
    confirm.dispatchEvent(held);
    expect(held.defaultPrevented).toBe(true);                           // a held Enter does not press it
    const fresh = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
    confirm.dispatchEvent(fresh);
    expect(fresh.defaultPrevented).toBe(false);                         // a new press still can
    fireEvent.click(confirm, { detail: 2 });                            // the second click of a double-click
    expect(go).not.toHaveBeenCalled();
    fireEvent.click(confirm, { detail: 1 });
    expect(go).toHaveBeenCalledTimes(1);
  });

  it('repeatConfirms={false}, typed and one click: the same for the signing button and a one-click action', () => {
    const typed = vi.fn();
    const once = vi.fn();
    render(<>
      <ConfirmAction tier={3} open repeatConfirms={false} label="sign" phrase="delete" armedLabel="Sign" onConfirm={typed} />
      <ConfirmAction tier={0} repeatConfirms={false} label="Read" onConfirm={once} />
    </>);
    fireEvent.change(screen.getByLabelText('type delete to confirm sign'), { target: { value: 'delete' } });
    fireEvent.click(screen.getByText('Sign'), { detail: 2 });
    fireEvent.click(screen.getByText('Read'), { detail: 2 });
    const held = new KeyboardEvent('keydown', { key: 'Enter', repeat: true, bubbles: true, cancelable: true });
    screen.getByText('Read').dispatchEvent(held);
    expect(held.defaultPrevented).toBe(true);
    expect(typed).not.toHaveBeenCalled();
    expect(once).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('Sign'));
    fireEvent.click(screen.getByText('Read'));
    expect(typed).toHaveBeenCalledTimes(1);
    expect(once).toHaveBeenCalledTimes(1);
  });

  it('repeatConfirms is true by default: every click confirms, as before', () => {
    const go = vi.fn();
    render(<ConfirmAction tier={0} label="stop" onConfirm={go} />);
    fireEvent.click(screen.getByText('stop'), { detail: 2 });
    const held = new KeyboardEvent('keydown', { key: 'Enter', repeat: true, bubbles: true, cancelable: true });
    screen.getByText('stop').dispatchEvent(held);
    expect(held.defaultPrevented).toBe(false);
    expect(go).toHaveBeenCalledTimes(1);
  });

  it('without the new props, the group keeps its default name and inline look', () => {
    render(<ConfirmAction tier={3} label="erase" phrase="FORGET" onConfirm={() => {}} />);
    fireEvent.click(screen.getByText('erase'));
    const group = screen.getByRole('group', { name: 'confirming erase' });
    expect(group.getAttribute('style')).toContain('inline-flex');
    expect(group.className).toBe('');
    expect(screen.getByLabelText('type FORGET to confirm erase').getAttribute('style')).toContain('var(--surface)');
  });
});

/* A controlled confirmation takes the focus in the commit that draws it, so no event can land
   between the drawing and the focus. When the focus was taken in a passive effect, a commit later,
   an Escape or a click that landed in between had the page move the focus (RunningHead's approval
   mode below 760px: back to its button), then the confirmation took it back as React flushed its
   effects before the next render, and left the screen with it: the focus fell to the page. */
describe('ConfirmAction — the focus is taken in the commit that draws it', () => {
  // flushSync outside act(): the commit that draws it and its layout effects run before this
  // returns; an effect left to a later commit does not
  const focusWhenDrawn = (element, target) => {
    const was = globalThis.IS_REACT_ACT_ENVIRONMENT;
    globalThis.IS_REACT_ACT_ENVIRONMENT = false;
    const host = document.body.appendChild(document.createElement('div'));
    const root = createRoot(host);
    try {
      flushSync(() => root.render(element));
      return { active: document.activeElement, target: target(host) };
    } finally {
      root.unmount();
      host.remove();
      globalThis.IS_REACT_ACT_ENVIRONMENT = was;
    }
  };

  it('two steps: the confirm button has the focus as soon as it is drawn', () => {
    const { active, target } = focusWhenDrawn(
      <ConfirmAction tier={1} armed block repeatConfirms={false} label="Auto" armedLabel="Switch to Auto" cancelLabel="Cancel"
        onCancel={() => {}} onConfirm={() => {}} />,
      (host) => Array.from(host.querySelectorAll('button')).find((b) => b.textContent === 'Switch to Auto'));
    expect(target).toBeTruthy();
    expect(active).toBe(target);
  });

  it('a typed phrase: the phrase box has the focus as soon as it is drawn', () => {
    const { active, target } = focusWhenDrawn(
      <ConfirmAction tier={3} armed label="erase" phrase="FORGET" onCancel={() => {}} onConfirm={() => {}} />,
      (host) => host.querySelector('input'));
    expect(target).toBeTruthy();
    expect(active).toBe(target);
  });
});
