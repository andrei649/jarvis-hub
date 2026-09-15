import {afterEach,expect,it,vi} from 'vitest';
import {fetchAppearance} from '../../mobile/src/api/appearance';
import {createTheme} from '../../mobile/src/theme';
const config={baseUrl:'https://fixture.test/prefix/',token:'user',adminToken:'admin'};
afterEach(()=>{vi.useRealTimers();vi.restoreAllMocks();});
it('aborts after fifteen seconds without retries or writes',async()=>{
  vi.useFakeTimers();global.fetch=vi.fn((_url,options)=>new Promise((_resolve,reject)=>options!.signal!.addEventListener('abort',()=>reject(new Error('aborted')))));
  const result=fetchAppearance(config,new AbortController().signal).catch(error=>error);
  await vi.advanceTimersByTimeAsync(15000);expect((await result).message).toBe('aborted');expect(fetch).toHaveBeenCalledTimes(1);
});
it('rejects malformed response envelopes',async()=>{
  global.fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>({preferences:[]})});
  await expect(fetchAppearance(config,new AbortController().signal)).rejects.toThrow('Invalid appearance');
});
it('coerces unknown choices and discards browser-only fields',async()=>{
  global.fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>({configured:true,preferences:{accent:'no',look:'no',font:'no',motion:'lively',scanlines:true,density:'compact'}})});
  await expect(fetchAppearance(config,new AbortController().signal)).resolves.toEqual({accent:'cyan',look:'obsidian',font:'theme'});
});
it.each(['ios','android'])('maps platform fonts without changing independent code mono on %s',platform=>{
  const expected=platform==='ios'?'Menlo':'monospace';
  for(const font of ['theme','system-sans','system-serif','system-mono','jetbrains-mono'] as const){
    const theme=createTheme({accent:'cyan',look:'obsidian',font},platform);
    expect(theme.codeFont).toBe(expected);
    if(font==='jetbrains-mono'){expect(theme.fontFamily).toBe(expected);expect(theme.fontFallback).toBeTruthy();}
    if(font==='system-serif')expect(theme.fontFamily).toBe(platform==='ios'?'Georgia':'serif');
    if(font==='theme'||font==='system-sans')expect(theme.fontFamily).toBeUndefined();
  }
});
