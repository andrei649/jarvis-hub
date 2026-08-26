// @ts-nocheck
/* Registry-only agents (howard, argus, hestia, …) have no hand-drawn glyph in the
   seed corpus. Every renderer that turns a glyph into an SVG <path> must still emit
   a visible neutral mark instead of an empty one, so live agents never appear as
   invisible roster entries.

   The Glyph primitive got that fallback first; NetworkBrain kept a raw
   `V2.GLYPHS[a.id] || ''` lookup and rendered blank nodes for exactly those agents.
   Both now route through the single `V2.glyphFor` helper, and these tests cover
   both call sites so the next renderer cannot regress only one of them. */
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { Glyph } from '../primitives';
import { V2 } from '../data';
import { NetworkBrain } from '../network';

const REGISTRY_ONLY = ['howard', 'argus', 'hestia', 'totally-new-agent'];

describe('Glyph fallback for registry agents without a seed glyph', () => {
  it('renders a non-empty path for a known seed agent', () => {
    const { container } = render(<Glyph id="jarvis" />);
    const d = container.querySelector('path').getAttribute('d');
    expect(d.length).toBeGreaterThan(0);
  });

  it('renders a non-empty NEUTRAL path for registry-only agents', () => {
    for (const id of REGISTRY_ONLY) {
      const { container } = render(<Glyph id={id} />);
      const d = container.querySelector('path').getAttribute('d');
      expect(d && d.length).toBeGreaterThan(0);
    }
  });
});

describe('glyphFor is the single source of the fallback', () => {
  it('returns the hand-drawn glyph when one exists', () => {
    expect(V2.glyphFor('jarvis')).toBe(V2.GLYPHS.jarvis);
  });

  it('returns the neutral mark for unknown, empty and missing ids', () => {
    for (const id of [...REGISTRY_ONLY, '', undefined, null]) {
      expect(V2.glyphFor(id)).toBe(V2.FALLBACK_GLYPH);
    }
  });

  it('never returns an empty string', () => {
    for (const id of [...REGISTRY_ONLY, 'jarvis', '']) {
      expect(V2.glyphFor(id).length).toBeGreaterThan(0);
    }
  });
});

describe('NetworkBrain draws every agent, seeded or not', () => {
  const agents = [
    { id: 'jarvis', name: 'Jarvis', tier: 'CNS', status: 'active' },
    { id: 'hestia', name: 'Hestia', tier: 'FND', status: 'idle' },
    { id: 'howard', name: 'Howard', tier: 'CNS', status: 'idle' },
    { id: 'argus', name: 'Argus', tier: 'BIZ', status: 'idle' },
  ];
  const t = { network: 'NETWORK', agents: 'AGENTS' };

  it('emits no empty glyph path for registry-only agents', () => {
    const { container } = render(
      <NetworkBrain agents={agents} tasks={[]} activeId={null} onSelect={() => {}}
        focusId={null} setFocusId={() => {}} motion="calm" t={t} />,
    );
    const glyphs = [...container.querySelectorAll('path.net-glyph')];
    expect(glyphs.length).toBeGreaterThanOrEqual(agents.length);
    for (const g of glyphs) {
      expect((g.getAttribute('d') || '').length).toBeGreaterThan(0);
    }
  });

  it('gives the un-seeded agents the neutral mark specifically', () => {
    const { container } = render(
      <NetworkBrain agents={agents} tasks={[]} activeId={null} onSelect={() => {}}
        focusId={null} setFocusId={() => {}} motion="calm" t={t} />,
    );
    const drawn = [...container.querySelectorAll('path.net-glyph')].map((g) => g.getAttribute('d'));
    expect(drawn).toContain(V2.FALLBACK_GLYPH);
    expect(drawn).toContain(V2.GLYPHS.jarvis);
  });
});
