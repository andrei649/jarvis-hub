import React from 'react';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ServerProvider, useServer } from '../../mobile/src/context/ServerContext';
import { AppearanceProvider, useAppearance } from '../../mobile/src/context/AppearanceContext';
import { records, storage } from './support/storage';
import { foreground } from './support/native';
const KEY='jarvis.server.config.v1';
const connection={baseUrl:'https://one.test/prefix',token:'fixture-one',adminToken:''};
const defaults={accent:'cyan',look:'obsidian',font:'theme'};
const reply=(preferences:any)=>({ok:true,status:200,json:async()=>({configured:true,preferences})});
let server:any;
function Probe(){server=useServer();const appearance=useAppearance();return <span data-testid="appearance">{JSON.stringify(appearance)}</span>}
const mount=()=>render(<ServerProvider><AppearanceProvider><Probe/></AppearanceProvider></ServerProvider>);
const current=()=>JSON.parse(screen.getByTestId('appearance').textContent!);
beforeEach(()=>{records.clear();records.set(KEY,JSON.stringify(connection));vi.restoreAllMocks();global.fetch=vi.fn().mockResolvedValue(reply({accent:'violet',look:'graphite',font:'system-serif'}));});
afterEach(()=>cleanup());

it('loads legacy connection, GETs prefix with user credentials only and renders preferences',async()=>{
  mount();await waitFor(()=>expect(current().preferences.accent).toBe('violet'));
  expect(fetch).toHaveBeenCalledWith('https://one.test/prefix/api/preferences/appearance',expect.objectContaining({method:'GET',headers:expect.objectContaining({'X-User-Token':'fixture-one'})}));
  expect((fetch as any).mock.calls[0][1].headers['X-Admin-Token']).toBeUndefined();
  await waitFor(()=>expect(JSON.parse(records.get(KEY)!).appearance.accent).toBe('violet'));
});

it('defaults on the first connection-switch render and ignores late old responses',async()=>{
  let resolveOld:any;global.fetch=vi.fn().mockImplementation(()=>new Promise(resolve=>{resolveOld=resolve;}));
  mount();await waitFor(()=>expect(resolveOld).toBeTruthy());
  global.fetch=vi.fn().mockRejectedValue(new Error('offline'));
  await act(async()=>server.updateConfig({...connection,baseUrl:'https://two.test/other',token:'fixture-two'}));
  expect(current().preferences).toEqual(defaults);
  await act(async()=>resolveOld(reply({accent:'amber',look:'graphite',font:'system-mono'})));
  expect(current().preferences).toEqual(defaults);
});

it('keeps only same-connection offline cache and clears it after unauthorized refresh',async()=>{
  mount();await waitFor(()=>expect(current().preferences.accent).toBe('violet'));
  global.fetch=vi.fn().mockRejectedValue(new Error('offline'));
  await act(async()=>{foreground('background');foreground('active');});
  await waitFor(()=>expect(current().status).toBe('offline'));
  expect(current().preferences.accent).toBe('violet');
  global.fetch=vi.fn().mockResolvedValue({ok:false,status:401});
  await act(async()=>{foreground('background');foreground('active');});
  await waitFor(()=>expect(current().status).toBe('unauthorized'));
  expect(current().preferences).toEqual(defaults);
  await waitFor(()=>expect(JSON.parse(records.get(KEY)!).appearance).toBeNull());
});

it('serializes a delayed cache write before newer credentials without restoring the old config',async()=>{
  const original=storage.setItem;let release:any;let first=true;
  vi.spyOn(storage,'setItem').mockImplementation(async(key,value)=>{if(first){first=false;await new Promise(resolve=>{release=resolve;});}await original(key,value);});
  mount();await waitFor(()=>expect(release).toBeTruthy());
  global.fetch=vi.fn().mockRejectedValue(new Error('offline'));
  let saving:Promise<void>;await act(async()=>{saving=server.updateConfig({...connection,token:'new-token'});});
  expect(current().preferences).toEqual(defaults);
  await act(async()=>{release();await saving!;});
  await waitFor(()=>expect(JSON.parse(records.get(KEY)!).config.token).toBe('new-token'));
  expect(JSON.parse(records.get(KEY)!).appearance).toBeNull();
});

it.each(['baseUrl','token','adminToken'])('clears a populated cache in every render after changing %s',async field=>{
  const renders:any[]=[];
  function Observe(){const s=useServer();const a=useAppearance();renders.push({config:s.config,preferences:a.preferences});return null;}
  render(<ServerProvider><AppearanceProvider><Probe/><Observe/></AppearanceProvider></ServerProvider>);
  await waitFor(()=>expect(current().preferences.accent).toBe('violet'));
  global.fetch=vi.fn().mockRejectedValue(new Error('offline'));
  const changed={...connection,[field]:field==='baseUrl'?'https://one.test/other-prefix':'changed-credential'};
  await act(async()=>server.updateConfig(changed));
  const switched=renders.filter(item=>item.config[field]===changed[field]);
  expect(switched.length).toBeGreaterThan(0);expect(switched.every(item=>JSON.stringify(item.preferences)===JSON.stringify(defaults))).toBe(true);
});

it('restores normalized same-connection appearance offline on restart',async()=>{
  records.set(KEY,JSON.stringify({version:2,config:connection,appearance:{accent:'amber',look:'unknown',font:'unknown',private:'discard'}}));
  global.fetch=vi.fn().mockRejectedValue(new Error('offline'));
  mount();await waitFor(()=>expect(current().status).toBe('offline'));
  expect(current().preferences).toEqual({...defaults,accent:'amber'});
});

it('does not restore delayed legacy hydration over a newly saved connection',async()=>{
  let release:any;vi.spyOn(storage,'getItem').mockImplementation(()=>new Promise(resolve=>{release=resolve;}));
  mount();await waitFor(()=>expect(release).toBeTruthy());
  global.fetch=vi.fn().mockRejectedValue(new Error('offline'));
  await act(async()=>server.updateConfig({...connection,token:'new-token'}));
  await act(async()=>release(JSON.stringify({version:2,config:connection,appearance:{accent:'amber'}})));
  expect(server.config.token).toBe('new-token');expect(current().preferences).toEqual(defaults);
});

it('aborts superseded foreground requests and ignores an older response body',async()=>{
  mount();await waitFor(()=>expect(current().status).toBe('synced'));
  let resolveBody:any;let signal:AbortSignal;
  global.fetch=vi.fn().mockImplementationOnce((_url,options)=>{signal=options.signal;return Promise.resolve({ok:true,status:200,json:()=>new Promise(resolve=>{resolveBody=resolve;})});}).mockResolvedValue(reply({accent:'green',font:'system-mono',look:'obsidian'}));
  await act(async()=>{foreground('background');foreground('active');});
  await waitFor(()=>expect(resolveBody).toBeTruthy());
  await act(async()=>{foreground('background');foreground('active');});
  await waitFor(()=>expect(current().preferences.accent).toBe('green'));
  expect(signal!.aborted).toBe(true);
  await act(async()=>resolveBody({configured:true,preferences:{accent:'amber'}}));
  expect(current().preferences.accent).toBe('green');
});

it('aborts on unmount and removes foreground listeners',async()=>{
  let signal:AbortSignal;global.fetch=vi.fn().mockImplementation((_url,options)=>{signal=options.signal;return new Promise(()=>{});});
  const view=mount();await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(1));
  view.unmount();expect(signal!.aborted).toBe(true);
  foreground('background');foreground('active');expect(fetch).toHaveBeenCalledTimes(1);
});

it('reports cache failure honestly while retaining fetched preferences in memory',async()=>{
  vi.spyOn(storage,'setItem').mockRejectedValue(new Error('disk unavailable'));
  mount();await waitFor(()=>expect(current().status).toBe('uncached'));
  expect(current().preferences.accent).toBe('violet');
});

it('keeps an explicit empty connection save when delayed hydration contains an old identity',async()=>{
  let release:any;vi.spyOn(storage,'getItem').mockImplementation(()=>new Promise(resolve=>{release=resolve;}));
  mount();await waitFor(()=>expect(release).toBeTruthy());
  await act(async()=>server.updateConfig({baseUrl:'',token:'',adminToken:''}));
  await act(async()=>release(JSON.stringify({version:2,config:connection,appearance:{accent:'amber'}})));
  expect(server.config).toEqual({baseUrl:'',token:'',adminToken:''});
  expect(current().preferences).toEqual(defaults);
  expect(current().status).toBe('unconfigured');
  expect(fetch).not.toHaveBeenCalled();
});
