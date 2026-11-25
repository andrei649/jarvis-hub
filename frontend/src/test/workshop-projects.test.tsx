import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { WorkshopProjects, fetchWorkshopContext, projectLink } from '../workshop-projects';

const project = { path: 'Journal/Inbox/Model (2).md', title: 'Model (2)', view: 'robot' };
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); delete window.__NERVA_BASE_PATH__; });

it('lists saved projects on demand and opens the exact version under the hub base path', async () => {
  window.__NERVA_BASE_PATH__ = '/nerva';
  const fetcher = vi.fn().mockResolvedValue(response({ ok: true, projects: [project] }));
  vi.stubGlobal('fetch', fetcher);
  const choose = vi.fn();
  render(<WorkshopProjects actionLabel="Discuss" onChoose={choose}/>);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('Saved 3D projects'));
  const link = await screen.findByRole('link', { name: 'Model (2)' });
  expect(link.getAttribute('href')).toBe('/nerva/os/?project=Journal%2FInbox%2FModel%20%282%29.md');
  expect(fetcher.mock.calls[0][0]).toBe('/nerva/api/os/workshop/projects');
  fireEvent.click(screen.getByRole('button', { name: 'Discuss' }));
  await waitFor(() => expect(choose).toHaveBeenCalledWith(project, expect.any(AbortSignal)));
});

it('rejects a missing or mismatched project instead of attaching a different note', async () => {
  vi.stubGlobal('fetch', vi.fn()
    .mockResolvedValueOnce(response({ok:false}, 404))
    .mockResolvedValueOnce(response({ok:true,path:'another.md',title:'Another',summary:'Summary', project:{version:1,view:'robot',state:{}}})));
  await expect(fetchWorkshopContext(project.path)).rejects.toThrow();
  await expect(fetchWorkshopContext(project.path)).rejects.toThrow();
  expect(projectLink('a (2).md')).toBe('/os/?project=a%20%282%29.md');
});
