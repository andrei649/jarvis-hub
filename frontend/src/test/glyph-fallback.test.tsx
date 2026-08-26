// @ts-nocheck
/* Registry-only agents (howard, hestia, …) have no hand-drawn glyph in the seed
   corpus. The Glyph primitive must still render a visible neutral mark instead of
   an empty <path>, so live agents never appear as invisible roster entries. */
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { Glyph } from '../primitives';

describe('Glyph fallback for registry agents without a seed glyph', () => {
  it('renders a non-empty path for a known seed agent', () => {
    const { container } = render(<Glyph id="jarvis" />);
    const d = container.querySelector('path').getAttribute('d');
    expect(d.length).toBeGreaterThan(0);
  });

  it('renders a non-empty NEUTRAL path for registry-only agents', () => {
    for (const id of ['howard', 'hestia', 'totally-new-agent']) {
      const { container } = render(<Glyph id={id} />);
      const d = container.querySelector('path').getAttribute('d');
      expect(d && d.length).toBeGreaterThan(0);
    }
  });
});
