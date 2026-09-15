import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import App from '../app';

vi.mock('../voice', () => ({useVoice: () => ({active:false, toggle:()=>{}})}));
vi.mock('../mesh', () => ({NeuralMesh:()=>null,isExecutingAgent:()=>false}));
vi.mock('../api/loaders', () => ({loadJarvisData:async()=>({}),createLatestRefreshRunner:()=>({refresh:()=>{},stop:()=>{}})}));
vi.mock('../api/live', () => ({PREVIEW_MODE_LIVE_KEYS:{},useLiveModes:()=>({live:{}})}));
vi.mock('../analytics', () => ({initAnalytics:()=>{},trackPageview:()=>{}}));
vi.mock('../modes3', () => ({ChatMode:()=> <div>Chat</div>}));
vi.mock('../gap', () => ({FirstRunGate:()=>null}));

beforeEach(() => {localStorage.clear(); history.replaceState(null,'','/v2/chat?demo=1');});
it('hydrates appearance from the server without writing at boot', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({configured:true, preferences:{accent:'amber',look:'graphite',density:'compact',motion:'system',scanline:'off',dotgrid:'on'}})));
  vi.stubGlobal('fetch',fetch);
  const {container} = render(<App/>);
  await waitFor(() => expect(container.querySelector('.hud-root')?.getAttribute('data-accent')).toBe('amber'));
  expect(fetch.mock.calls.some(call => call[1]?.method==='PUT')).toBe(false);
});
it('saves an explicit palette choice to the narrow preference endpoint', async () => {
  const fetch = vi.fn().mockImplementation(async (_path, init) => new Response(JSON.stringify({configured:!!init?.body,preferences:{accent:init?.body?'violet':'cyan',look:'obsidian',density:'normal',motion:'system',scanline:'on',dotgrid:'off'}})));
  vi.stubGlobal('fetch', fetch);
  render(<App/>);
  fireEvent.keyDown(window,{key:'k',ctrlKey:true});
  fireEvent.click(await screen.findByText('Accent · Violet'));
  await waitFor(() => expect(fetch.mock.calls.some(call => call[0]==='/api/preferences/appearance' && call[1]?.method==='PUT' && JSON.parse(call[1].body).accent==='violet')).toBe(true));
});

it('shows failed explicit saves without reopening the palette', async () => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(async (_url, init) => {
    if (init?.method==='PUT') throw new TypeError('offline');
    return new Response(JSON.stringify({configured:false,preferences:{}}));
  }));
  render(<App/>);
  fireEvent.keyDown(window,{key:'k',ctrlKey:true});
  fireEvent.click(await screen.findByText('Accent · Violet'));
  await screen.findByText('Appearance saved on this browser only. Sync failed.');
  expect(screen.getByRole('button',{name:'Retry sync'})).toBeTruthy();
});
