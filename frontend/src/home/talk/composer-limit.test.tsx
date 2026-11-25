/* The composer's length limit follows the route the words go to (PHASE_B_PLAN.md §5.3): a chat
   message takes 4,096 characters (agents/web.py ChatRequest.message), an image question 4,000
   (agents/core/routers/composer_vision.py), both counted as code points. With images staged (the
   image draft is stubbed here) the count, the hold on Send and its reason say 4,000. */
import React from 'react';
import { cleanup, fireEvent, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const submission = vi.hoisted(() => ({ images: ['data:image/png;base64,AAAA'] }));
vi.mock('../../composer-images', () => ({
  ComposerImages: () => null,
  useComposerImages: () => ({
    enabled: true, ready: true, note: '', activeState: 'idle', xaiUnsupported: false,
    onPaste: undefined, onDrop: undefined, addFiles: () => {}, clear: () => {}, loadActiveImages: async () => {},
    submission: () => submission,
  }),
}));

import { InputBar } from '../../cockpit';
import { V2 } from '../../data';
import { composerField, composerSend } from './test-support';

beforeEach(() => { vi.stubGlobal('fetch', vi.fn(async () => Response.json({}))); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('with images staged', () => {
  it('holds an image question over 4,000 characters and says so', () => {
    const submit = vi.fn(() => true);
    render(<InputBar t={V2.I18N.en} agent="jarvis" sessionId="s" selectedTurn onSubmit={submit} />);
    const field = composerField();
    fireEvent.change(field, { target: { value: 'x'.repeat(4001) } });
    const frame = document.querySelector('[data-composer-frame]') as HTMLElement;
    expect(frame.querySelector('.n-composer__count')?.textContent).toBe('4,001 of 4,000 characters');
    expect(composerSend().disabled).toBe(true);
    expect(frame.querySelector('.n-composer__why')?.textContent).toBe('The message is 1 character over the limit of 4,000.');
    fireEvent.keyDown(field, { key: 'Enter' });
    expect(submit).not.toHaveBeenCalled();
    fireEvent.change(field, { target: { value: 'x'.repeat(4000) } });
    expect(composerSend().disabled).toBe(false);
    fireEvent.keyDown(field, { key: 'Enter' });
    expect(submit).toHaveBeenCalledExactlyOnceWith('x'.repeat(4000), submission);
  });
});
