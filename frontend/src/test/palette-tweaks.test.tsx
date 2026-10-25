// @ts-nocheck
/* O26-P3.2 — the dropped TweaksPanel is covered by the command palette: look,
   density, motion, scanline, and dotgrid must all be user-changeable controls. */
import { describe, it, expect, vi } from 'vitest';
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { Palette } from '../shell';
import { LANGUAGES, V2 } from '../data';

const t = V2.I18N.en;

function renderPalette(ui, extra = {}) {
  const onClose = vi.fn();
  render(
    <Palette
      open={true}
      onClose={onClose}
      onMode={() => {}}
      setAccent={() => {}}
      setLang={() => {}}
      {...extra}
      onAmbient={() => {}}
      ui={ui}
      t={t}
    />,
  );
  return onClose;
}

describe('Palette display tweaks', () => {
  it('offers look, density, motion, scanline, and dotgrid controls', () => {
    const ui = {
      look: 'obsidian', setLook: vi.fn(),
      density: 'normal', setDensity: vi.fn(),
      motion: 'lively', setMotion: vi.fn(),
      scanline: 'on', setScanline: vi.fn(),
      dotgrid: 'off', setDotgrid: vi.fn(),
    };
    renderPalette(ui);

    fireEvent.click(screen.getByText('Look · Graphite'));
    expect(ui.setLook).toHaveBeenCalledWith('graphite');

    fireEvent.click(screen.getByText('Density · Comfy'));
    expect(ui.setDensity).toHaveBeenCalledWith('comfy');

    fireEvent.click(screen.getByText('Motion · Calm'));
    expect(ui.setMotion).toHaveBeenCalledWith('calm');

    fireEvent.click(screen.getByText('Scanline · Off'));
    expect(ui.setScanline).toHaveBeenCalledWith('off');

    fireEvent.click(screen.getByText('Dot grid · On'));
    expect(ui.setDotgrid).toHaveBeenCalledWith('on');
  });

  // H221 — the Language row is an appearance row like the others: one entry per translated
  // language (its own name), the active one ticked, chosen by code rather than toggled.
  it('offers a Language row per translated language, the active one ticked', () => {
    const setLang = vi.fn();
    renderPalette({ look: 'obsidian', density: 'normal', motion: 'lively', scanline: 'on', dotgrid: 'off' }, { lang: 'ro', setLang });
    for (const l of LANGUAGES) expect(screen.getByText('Language · ' + l.label + (l.code === 'ro' ? ' ✓' : ''))).toBeTruthy();
    expect(screen.queryByText(/Toggle language/)).toBeNull();
    fireEvent.click(screen.getByText('Language · English'));
    expect(setLang).toHaveBeenCalledWith('en');
  });
});
