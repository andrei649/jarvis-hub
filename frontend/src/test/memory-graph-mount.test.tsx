import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryNeighborhood } from '../panels/memory-neighborhood';
import * as graph from '../api/memory-graph';
import * as listApi from '../api/memory-map';

vi.mock('../api/memory-map', () => ({ memoryNodes: vi.fn(), memoryNeighborhood: vi.fn() }));
vi.mock('../api/memory-graph', async importOriginal => ({
  ...(await importOriginal<typeof import('../api/memory-graph')>()),
  loadMemoryMap: vi.fn(), loadFacts: vi.fn(), loadSkills: vi.fn(),
}));

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(listApi.memoryNodes).mockResolvedValue([{ name: 'Alpha', type: 'project' }]);
  vi.mocked(graph.loadMemoryMap).mockResolvedValue({ entities: [{ name: 'Alpha', type: 'project', firstSeen: 1 }], relations: [], clipped: false, relationsClipped: false });
  vi.mocked(graph.loadSkills).mockResolvedValue([]);
  vi.mocked(graph.loadFacts).mockResolvedValue({ axis: 'known', facts: [], clipped: false, bounds: { count: 0, firstIngested: null, lastIngested: null, firstValid: null, lastChange: null } });
});

describe('live Memory mode mounts the explorer above the text list', () => {
  it('renders the star-map canvas and keeps the accessible entity list', async () => {
    render(<MemoryNeighborhood />);
    await screen.findByRole('group', { name: /Memory graph canvas/ });
    expect(screen.getByRole('region', { name: 'Memory graph' })).toBeTruthy();
    expect(screen.getByRole('region', { name: 'Memory neighborhood' })).toBeTruthy();
    expect(await screen.findAllByRole('button', { name: /^Alpha/ })).toHaveLength(2);   // list button + canvas node
    expect(graph.loadMemoryMap).toHaveBeenCalledOnce();
    expect(listApi.memoryNodes).toHaveBeenCalledOnce();
  });
});
