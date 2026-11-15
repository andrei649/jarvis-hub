// @ts-nocheck
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { PetCompanionOverlay, PetsPanel } from './pets';

const sampleCells = Array.from({ length: 8 }, () => Array.from({ length: 8 }, () => '#00b4d8'));

const petInfo = {
  ok: true,
  enabled: true,
  active_id: 'spark-owl',
  active_pet: {
    id: 'spark-owl',
    name: 'Spark Owl',
    species: 'Strigiformes Arc',
    rarity: 'common',
    vibe: 'watchful',
    builtin: true,
    palette: { primary: '#00b4d8' },
    states: ['idle', 'thinking', 'tool', 'finishing', 'failing'],
  },
  scale: 1.0,
  roam: false,
  overlay_enabled: true,
  image_backend: 'procedural-pixel',
  installed_count: 6,
  custom_count: 0,
  example_prompts: ['cybernetic barn owl with glowing amber runes'],
  image_backends: ['procedural-pixel', 'svg-synth', 'local-vlm'],
  agent_states: ['idle', 'thinking', 'tool', 'finishing', 'failing'],
  agent_state: 'thinking',
  detail: 'reasoning',
  vibe_reaction: 'pondering hypotheses…',
  current_cells: sampleCells,
};

const galleryPayload = {
  ok: true,
  active_id: 'spark-owl',
  enabled: true,
  pets: [
    petInfo.active_pet,
    {
      id: 'hatch-custom1',
      name: 'Neon Axolotl',
      species: 'Hatched',
      rarity: 'epic',
      vibe: 'radiant',
      builtin: false,
      palette: { primary: '#ff70a6' },
      states: ['idle', 'thinking', 'tool', 'finishing', 'failing'],
      active: false,
    },
  ],
};

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('PetsPanel & PetCompanionOverlay (H214 + H238 + H590)', () => {
  it('renders Hatch-a-Pet candidates, enforces confirmed remix, adopts, and manages Petdex', async () => {
    const calls = [];
    global.fetch = vi.fn(async (url, init = {}) => {
      const path = String(url);
      calls.push([path, init]);
      if (path.endsWith('/api/pets/gallery')) {
        return { ok: true, status: 200, json: async () => galleryPayload };
      }
      if (path.endsWith('/api/pets/doctor')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            active_id: 'spark-owl',
            terminal_protocol: 'halfblock',
            checks: [{ name: 'store_writable', ok: true, detail: 'ok' }],
          }),
        };
      }
      if (path.endsWith('/api/pets/hatch/generate')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            job_id: 'pgen_test1',
            prompt: 'cybernetic owl',
            image_backend: 'procedural-pixel',
            has_reference_image: false,
            status: 'completed',
            drafts: [
              {
                draft_id: 'draft_1_abc',
                index: 0,
                vibe: 'arcane',
                rarity: 'rare',
                palette: { primary: '#00b4d8' },
                preview_cells: sampleCells,
              },
            ],
          }),
        };
      }
      if (path.includes('/api/pets/hatch/jobs/pgen_test1/remix')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            ok: true,
            job_id: 'pgen_test1',
            prompt: 'cybernetic owl',
            image_backend: 'procedural-pixel',
            has_reference_image: false,
            status: 'completed',
            drafts: [
              {
                draft_id: 'draft_1_remixed',
                index: 0,
                vibe: 'radiant',
                rarity: 'epic',
                palette: { primary: '#ff70a6' },
                preview_cells: sampleCells,
              },
            ],
          }),
        };
      }
      if (path.includes('/api/pets/hatch/jobs/pgen_test1/adopt')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ ok: true, hatch_stage: 'hatched', pet: { id: 'hatch-new', name: 'Nova Owl' } }),
        };
      }
      if (path.includes('/api/pets/hatch/jobs/pgen_test1')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ ok: true, job_id: 'pgen_test1', status: 'hatched', drafts: [] }),
        };
      }
      return { ok: true, status: 200, json: async () => petInfo };
    });

    render(<PetsPanel />);
    await screen.findByText(/Neon Axolotl/);

    // Generate 4 looks -> refuses remix until Confirm remix is checked -> remixes -> adopts
    fireEvent.click(screen.getByText('generate 4 looks'));
    await screen.findByText('arcane');

    fireEvent.click(screen.getByText('remix'));
    await screen.findByText(/check Confirm remix before remixing/);
    expect(calls.some(([u]) => u.includes('/remix'))).toBe(false);

    fireEvent.click(screen.getByLabelText(/Confirm remix/));
    fireEvent.click(screen.getByText('remix'));
    await screen.findByText('radiant');
    expect(calls.some(([u]) => u.includes('/remix'))).toBe(true);

    fireEvent.click(screen.getByText('hatch & adopt'));
    await waitFor(() => expect(calls.some(([u]) => u.includes('/adopt'))).toBe(true));

    // Doctor check
    fireEvent.click(screen.getByText('run doctor'));
    await screen.findByText(/store_writable/);
  });

  it('mounts reactive PetCompanionOverlay driven by live agentState', async () => {
    global.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => petInfo,
    }));

    render(<PetCompanionOverlay enabled agentState="thinking" />);
    const overlay = await screen.findByTestId('pet-companion-overlay');
    expect(overlay.textContent).toContain('Spark Owl');
    expect(overlay.textContent).toContain('[thinking]');
    expect(overlay.textContent).toContain('pondering hypotheses');
  });
});
