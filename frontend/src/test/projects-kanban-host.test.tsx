import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { ProjectsMode } from '../gap';

const backend = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock('../panels/kanban/KanbanView', () => ({
  KanbanView: () => <section aria-label="Kanban host">Scoped Kanban module</section>,
}));
vi.mock('../api/client', async importOriginal => ({
  ...await importOriginal<typeof import('../api/client')>(),
  apiGet: backend.get,
}));
afterEach(() => { cleanup(); backend.get.mockReset(); });
beforeEach(() => backend.get.mockResolvedValue({ rooms: [], missions: [], sessions: [], items: [] }));

it('mounts the full Kanban module in Projects while preserving the existing project surfaces', async () => {
  render(<ProjectsMode />);
  expect(screen.getByRole('region', { name: 'Kanban host' })).toBeTruthy();
  expect(screen.getByText(/PROJECTS · rooms/)).toBeTruthy();
  expect(await screen.findByText('ROOMS')).toBeTruthy();
});

it('keeps the demo Projects sample separate from live project reads after toggling', async () => {
  backend.get.mockResolvedValue({ rooms: [{ name: 'LIVE SENTINEL ROOM' }], missions: [{ id: 'live', title: 'LIVE SENTINEL MISSION', status: 'active' }] });
  const { rerender } = render(<ProjectsMode demo={false} lang="en" />);
  expect(await screen.findByText('LIVE SENTINEL ROOM')).toBeTruthy();
  expect(screen.getByRole('button', { name: '+ room' })).toBeTruthy();
  const readsBeforeDemo = backend.get.mock.calls.length;

  rerender(<ProjectsMode demo lang="en" />);
  expect(await screen.findByText(/Demo sample.*read.only/i)).toBeTruthy();
  expect(screen.getByText('Exhibition planning')).toBeTruthy();
  for (const section of ['Rooms', 'Missions', 'Sessions', 'Activity']) {
    expect(screen.getByText(section)).toBeTruthy();
  }
  expect(screen.queryByText('LIVE SENTINEL ROOM')).toBeNull();
  expect(screen.queryByText('LIVE SENTINEL MISSION')).toBeNull();
  expect(screen.queryAllByRole('button')).toHaveLength(0);
  expect(screen.queryAllByRole('textbox')).toHaveLength(0);
  expect(backend.get).toHaveBeenCalledTimes(readsBeforeDemo);
});

it('renders a Romanian-labelled demo without mounting live project panels', () => {
  render(<ProjectsMode demo lang="ro" />);
  expect(screen.getByText(/Exemplu demo.*doar pentru citire/i)).toBeTruthy();
  expect(screen.getByText('Pregătirea expoziției')).toBeTruthy();
  for (const section of ['Camere', 'Misiuni', 'Sesiuni', 'Activitate']) {
    expect(screen.getByText(section)).toBeTruthy();
  }
  expect(screen.queryByRole('region', { name: 'Kanban host' })).toBeNull();
  expect(backend.get).not.toHaveBeenCalled();
});
