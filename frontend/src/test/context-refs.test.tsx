// @ts-nocheck
/* H579 — while the last word typed is an @file: reference, the composer asks the hub for the
   in-scope paths that complete it; Tab or a click takes one. fetch is mocked. */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import React, { useState } from 'react';
import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react';
import { CONTEXT_REFS_PATH, ContextRefHints, acceptRef, typedRef, useContextRefs } from '../context-refs';

let calls;

beforeEach(() => {
  cleanup();
  calls = [];
  global.fetch = vi.fn(async (url) => {
    calls.push(String(url));
    return { ok: true, status: 200, json: async () => ({ ok: true, types: ['file'], items: [
      { ref: '@file:src/', kind: 'dir' }, { ref: '@file:setup.py', kind: 'file' }] }), text: async () => '' };
  });
});

function Composer() {
  const [val, setVal] = useState('');
  const refs = useContextRefs(val);
  return (
    <div>
      <ContextRefHints items={refs} onPick={(ref) => setVal(acceptRef(val, ref))} />
      <input aria-label="composer" value={val} onChange={(e) => setVal(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Tab' && refs.length) { e.preventDefault(); setVal(acceptRef(val, refs[0].ref)); } }} />
    </div>
  );
}

describe('context refs — H579', () => {
  it('finds the reference being typed and replaces it', () => {
    expect(typedRef('look at @file:sr')).toBe('sr');
    expect(typedRef('@file:')).toBe('');
    expect(typedRef('look at @file:a.py#L1-2')).toBeNull();
    expect(typedRef('email me@file:x')).toBeNull();
    expect(typedRef('@file:a.py done')).toBeNull();
    expect(acceptRef('see @file:s', '@file:setup.py')).toBe('see @file:setup.py ');
    expect(acceptRef('see @file:s', '@file:src/')).toBe('see @file:src/');
    expect(acceptRef('no ref here', '@file:x')).toBe('no ref here');
  });

  it('asks the hub only while a reference is typed, and Tab or a click takes one', async () => {
    render(<Composer />);
    const box = screen.getByLabelText('composer');
    fireEvent.change(box, { target: { value: 'hello there' } });
    await new Promise((r) => setTimeout(r, 200));
    expect(calls).toEqual([]);
    fireEvent.change(box, { target: { value: 'read @file:s' } });
    await waitFor(() => expect(screen.getByText('@file:setup.py')).toBeTruthy());
    expect(calls[0].endsWith(`${CONTEXT_REFS_PATH}?prefix=s`)).toBe(true);
    fireEvent.keyDown(box, { key: 'Tab' });
    expect(box.value).toBe('read @file:src/');
    await waitFor(() => expect(calls.some((u) => u.endsWith('?prefix=src%2F'))).toBe(true));
    fireEvent.mouseDown(screen.getByText('@file:setup.py'));
    expect(box.value).toBe('read @file:setup.py ');
    await waitFor(() => expect(screen.queryByRole('listbox')).toBeNull());
  });

  it('shows nothing when the hub refuses', async () => {
    global.fetch = vi.fn(async () => ({ ok: false, status: 503, json: async () => ({ ok: false }), text: async () => '' }));
    render(<Composer />);
    fireEvent.change(screen.getByLabelText('composer'), { target: { value: '@file:x' } });
    await new Promise((r) => setTimeout(r, 250));
    expect(screen.queryByRole('listbox')).toBeNull();
  });
});
