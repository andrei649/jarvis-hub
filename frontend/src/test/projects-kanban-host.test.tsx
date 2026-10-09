import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { ProjectsMode } from '../gap';

vi.mock('../panels/kanban/KanbanView', () => ({
  KanbanView: () => <section aria-label="Kanban host">Scoped Kanban module</section>,
}));
vi.mock('../api/client', async importOriginal => ({
  ...await importOriginal<typeof import('../api/client')>(),
  apiGet: vi.fn().mockResolvedValue({ rooms: [], missions: [], sessions: [], items: [] }),
}));
afterEach(cleanup);

it('mounts the full Kanban module in Projects while preserving the existing project surfaces', async () => {
  render(<ProjectsMode />);
  expect(screen.getByRole('region', { name: 'Kanban host' })).toBeTruthy();
  expect(screen.getByText(/PROJECTS · rooms/)).toBeTruthy();
  expect(await screen.findByText('ROOMS')).toBeTruthy();
});
