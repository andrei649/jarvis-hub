import { act, renderHook, waitFor, cleanup } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useAppearance } from '../appearance';

const defaults = {accent:'cyan',look:'obsidian',density:'normal',motion:'system',scanline:'on',dotgrid:'off'};
const result = (patch={}, configured=true) => new Response(JSON.stringify({configured,preferences:{...defaults,...patch}}));
const deferred = () => {let resolve!: (value:Response)=>void; let reject!: (error:Error)=>void; const promise=new Promise<Response>((yes,no)=>{resolve=yes;reject=no;}); return {promise,resolve,reject};};
beforeEach(() => {localStorage.clear(); delete window.__NERVA_BASE_PATH__;});
afterEach(() => {cleanup(); vi.unstubAllGlobals(); delete window.__NERVA_BASE_PATH__;});

it('keeps first-use legacy choices local and never uploads at boot', async () => {
  localStorage.setItem('hud.accent','green');
  const fetch=vi.fn().mockImplementation(async()=>result({},false)); vi.stubGlobal('fetch',fetch);
  const {result:hook}=renderHook(()=>useAppearance());
  await waitFor(()=>expect(hook.current.status).toBe('local'));
  expect(hook.current.preferences.accent).toBe('green');
  expect(fetch.mock.calls).toHaveLength(1);
  expect(fetch.mock.calls[0][1].method).toBe('GET');
});
it('uses reduced motion on the initial render when there is no owner override', () => {
  vi.stubGlobal('matchMedia',()=>({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()}));
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async()=>result({},false)));
  const renders:string[]=[];
  renderHook(()=>{const value=useAppearance(); renders.push(value.motion); return value;});
  expect(renders[0]).toBe('calm');
});
it('ignores an older hydration response after an explicit edit', async () => {
  const read=deferred(), write=deferred();
  vi.stubGlobal('fetch',vi.fn().mockImplementation((_p,init)=>init.method==='PUT'?write.promise:read.promise));
  const {result:hook}=renderHook(()=>useAppearance());
  act(()=>hook.current.setPreference('accent','violet'));
  await act(async()=>read.resolve(result({accent:'amber'})));
  expect(hook.current.preferences.accent).toBe('violet');
  await act(async()=>write.resolve(result({accent:'violet'})));
  expect(hook.current.status).toBe('synced');
});
it('serializes saves and keeps a later edit visible while an older save completes', async () => {
  const first=deferred(), second=deferred(); let puts=0;
  const fetch=vi.fn().mockImplementation((_p,init)=>init.method==='PUT'?(puts++===0?first.promise:second.promise):Promise.resolve(result()));
  vi.stubGlobal('fetch',fetch);
  const {result:hook}=renderHook(()=>useAppearance());
  await waitFor(()=>expect(hook.current.status).toBe('synced'));
  act(()=>hook.current.setPreference('accent','amber'));
  act(()=>hook.current.setPreference('accent','violet'));
  expect(puts).toBe(1);
  await act(async()=>first.resolve(result({accent:'amber'})));
  expect(hook.current.preferences.accent).toBe('violet');
  expect(puts).toBe(2);
  await act(async()=>second.resolve(result({accent:'violet'})));
  expect(hook.current.pending).toEqual({});
});
it('retains failed explicit changes across reload and retries them on reconnect', async () => {
  let offline=true, server={...defaults};
  const fetch=vi.fn().mockImplementation(async(_p,init)=>{
    if(offline)throw new TypeError('offline');
    if(init.method==='PUT')server={...server,...JSON.parse(init.body)};
    return result(server);
  }); vi.stubGlobal('fetch',fetch);
  let hook=renderHook(()=>useAppearance());
  act(()=>hook.result.current.setPreference('look','graphite'));
  await waitFor(()=>expect(hook.result.current.status).toBe('unsynced'));
  hook.unmount(); hook=renderHook(()=>useAppearance());
  await waitFor(()=>expect(hook.result.current.status).toBe('unsynced'));
  expect(hook.result.current.preferences.look).toBe('graphite');
  offline=false; act(()=>window.dispatchEvent(new Event('online')));
  await waitFor(()=>expect(hook.result.current.status).toBe('synced'));
  expect(server.look).toBe('graphite'); expect(hook.result.current.pending).toEqual({});
});
it('refreshes another browser’s choice on focus without writing', async () => {
  let server={...defaults}; const fetch=vi.fn().mockImplementation(async()=>result(server));vi.stubGlobal('fetch',fetch);
  const {result:hook}=renderHook(()=>useAppearance()); await waitFor(()=>expect(hook.current.status).toBe('synced'));
  server.accent='amber'; act(()=>window.dispatchEvent(new Event('focus')));
  await waitFor(()=>expect(hook.current.preferences.accent).toBe('amber'));
  expect(fetch.mock.calls.every(call=>call[1].method==='GET')).toBe(true);
});
it('uses prefixed requests and does not replay another deployment’s pending cache', async () => {
  localStorage.setItem('hud.appearance.v1:/one',JSON.stringify({version:1,preferences:{...defaults,accent:'violet'},pending:{accent:'violet'}}));
  window.__NERVA_BASE_PATH__='/two';
  const fetch=vi.fn().mockImplementation(async()=>result({},false));vi.stubGlobal('fetch',fetch);
  const {result:hook}=renderHook(()=>useAppearance());await waitFor(()=>expect(hook.current.status).toBe('local'));
  expect(hook.current.preferences.accent).toBe('cyan');expect(fetch.mock.calls[0][0]).toBe('/two/api/preferences/appearance');
  expect(fetch.mock.calls).toHaveLength(1);
});
it('does not publish a pending read after unmount', async () => {
  const read=deferred();vi.stubGlobal('fetch',vi.fn().mockReturnValue(read.promise));
  const hook=renderHook(()=>useAppearance()); hook.unmount();
  await act(async()=>read.resolve(result({accent:'amber'})));
  expect(localStorage.getItem('hud.appearance.v1:/')).toBeNull();
});

it('follows OS changes only for System motion, preserving an explicit override', async () => {
  let changed=()=>{}; const media={matches:true,addEventListener:(_name:string,fn:()=>void)=>changed=fn,removeEventListener:vi.fn()};
  vi.stubGlobal('matchMedia',()=>media);
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async(_p,init)=>result(init.method==='PUT'?JSON.parse(init.body):{})));
  const {result:hook}=renderHook(()=>useAppearance());await waitFor(()=>expect(hook.current.status).toBe('synced'));
  expect(hook.current.motion).toBe('calm');
  act(()=>{media.matches=false;changed();});expect(hook.current.motion).toBe('lively');
  act(()=>hook.current.setPreference('motion','calm'));
  await waitFor(()=>expect(hook.current.status).toBe('synced'));
  act(()=>{media.matches=true;changed();media.matches=false;changed();});
  expect(hook.current.motion).toBe('calm');
});
it('does not let a focus read started during a save undo its acknowledgement', async () => {
  const write=deferred(), stale=deferred();let reads=0;
  vi.stubGlobal('fetch',vi.fn().mockImplementation((_p,init)=>init.method==='PUT'?write.promise:reads++===0?Promise.resolve(result()):stale.promise));
  const {result:hook}=renderHook(()=>useAppearance());await waitFor(()=>expect(hook.current.status).toBe('synced'));
  act(()=>hook.current.setPreference('accent','violet'));
  act(()=>window.dispatchEvent(new Event('focus')));
  await act(async()=>write.resolve(result({accent:'violet'})));
  await act(async()=>stale.resolve(result({accent:'cyan'})));
  expect(hook.current.preferences.accent).toBe('violet');expect(hook.current.status).toBe('synced');
});

it('preserves both offline tabs edits through failed reads and reload', async () => {
  let offline=true, server={...defaults};
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async(_p,init)=>{
    if(offline)throw new TypeError('offline');
    if(init.method==='PUT')server={...server,...JSON.parse(init.body)};
    return result(server);
  }));
  const a=renderHook(()=>useAppearance()), b=renderHook(()=>useAppearance());
  act(()=>a.result.current.setPreference('accent','violet'));
  await waitFor(()=>expect(a.result.current.status).toBe('unsynced'));
  act(()=>b.result.current.setPreference('look','graphite'));
  await waitFor(()=>expect(b.result.current.status).toBe('unsynced'));
  act(()=>a.result.current.retry());
  await act(async()=>{});
  a.unmount();b.unmount();
  const restored=renderHook(()=>useAppearance());
  expect(restored.result.current.preferences).toMatchObject({accent:'violet',look:'graphite'});
  await waitFor(()=>expect(restored.result.current.status).toBe('unsynced'));
  offline=false;act(()=>restored.result.current.retry());
  await waitFor(()=>expect(restored.result.current.status).toBe('synced'));
  expect(server).toMatchObject({accent:'violet',look:'graphite'});
});
it('does not migrate ambiguous legacy motion as an explicit override', () => {
  localStorage.setItem('hud.motion','lively');
  vi.stubGlobal('matchMedia',()=>({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()}));
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async()=>result({},false)));
  const hook=renderHook(()=>useAppearance());
  expect(hook.result.current.motion).toBe('calm');
  expect(hook.result.current.preferences.motion).toBe('system');
});

it('without Web Locks never replays a stale write after another tab acknowledges it', async () => {
  let server={...defaults}, revision='0';const old=deferred();let writes=0;
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async(_p,init)=>{
    if(init.method==='PUT') {
      if(writes++===0)return old.promise;
      const {_revision,...patch}=JSON.parse(init.body);
      if(_revision!==revision)return new Response('{}',{status:409});
      server={...server,...patch};revision=String(Number(revision)+1);
    }
    return new Response(JSON.stringify({configured:true,preferences:server,revision}));
  }));
  const a=renderHook(()=>useAppearance()),b=renderHook(()=>useAppearance());
  await waitFor(()=>expect(b.result.current.status).toBe('synced'));
  act(()=>a.result.current.setPreference('accent','amber'));
  act(()=>b.result.current.setPreference('accent','violet'));
  await waitFor(()=>expect(b.result.current.status).toBe('synced'));
  await act(async()=>old.resolve(new Response('{}',{status:409})));
  await waitFor(()=>expect(a.result.current.status).toBe('synced'));
  expect(a.result.current.preferences.accent).toBe('violet');
  expect(server.accent).toBe('violet');expect(writes).toBe(2);
});

it('drains an edit made while a lock waiter refreshes an already consumed batch', async () => {
  let lock=Promise.resolve();
  vi.stubGlobal('navigator',{locks:{request:(_key:string,run:()=>Promise<void>)=>{const next=lock.then(run);lock=next.catch(()=>{});return next;}}});
  let server={...defaults}, reads=0;const tail=deferred(),first=deferred();let writes=0;
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async(_p,init)=>{
    if(init.method==='GET')return reads++===2?tail.promise:result(server);
    if(writes++===0)await first.promise;
    const {_revision,...patch}=JSON.parse(init.body);server={...server,...patch};return result(server);
  }));
  const a=renderHook(()=>useAppearance()),b=renderHook(()=>useAppearance());
  await waitFor(()=>expect(b.result.current.status).toBe('synced'));
  act(()=>a.result.current.setPreference('accent','amber'));
  await waitFor(()=>expect(writes).toBe(1));
  act(()=>b.result.current.setPreference('accent','violet'));
  await act(async()=>first.resolve(result()));
  await waitFor(()=>expect(reads).toBe(3));
  act(()=>b.result.current.setPreference('look','graphite'));
  await act(async()=>tail.resolve(result(server)));
  await waitFor(()=>expect(b.result.current.status).toBe('synced'));
  expect(b.result.current.pending).toEqual({});expect(server).toMatchObject({accent:'violet',look:'graphite'});
});

it('acknowledges a completed save after unmount without replaying it on reload', async () => {
  const write=deferred();let writes=0;
  vi.stubGlobal('fetch',vi.fn().mockImplementation((_p,init)=>{
    if(init.method==='PUT'){writes++;return write.promise;}
    return Promise.resolve(result());
  }));
  const first=renderHook(()=>useAppearance());
  act(()=>first.result.current.setPreference('accent','amber'));
  first.unmount();await act(async()=>write.resolve(result({accent:'amber'})));
  const next=renderHook(()=>useAppearance());
  await waitFor(()=>expect(next.result.current.status).toBe('synced'));
  expect(writes).toBe(1);
});

it('defaults old replies to theme and preserves an explicit offline font through reload', async () => {
  let offline=false, server={...defaults};
  const fetch=vi.fn().mockImplementation(async(_p,init)=>{
    if(offline)throw new TypeError('offline');
    if(init.method==='PUT'){const {_revision,...patch}=JSON.parse(init.body);server={...server,...patch};}
    return result(server);
  });vi.stubGlobal('fetch',fetch);
  let hook=renderHook(()=>useAppearance());
  await waitFor(()=>expect(hook.result.current.status).toBe('synced'));
  expect(hook.result.current.preferences.font).toBe('theme');
  expect(fetch.mock.calls.every(call=>call[1].method==='GET')).toBe(true);
  offline=true;act(()=>hook.result.current.setPreference('font','system-serif'));
  await waitFor(()=>expect(hook.result.current.status).toBe('unsynced'));
  hook.unmount();hook=renderHook(()=>useAppearance());
  await waitFor(()=>expect(hook.result.current.status).toBe('unsynced'));
  expect(hook.result.current.preferences.font).toBe('system-serif');
  offline=false;act(()=>hook.result.current.retry());
  await waitFor(()=>expect(hook.result.current.status).toBe('synced'));
  expect(hook.result.current.preferences.font).toBe('system-serif');
});
