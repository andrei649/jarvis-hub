import {afterEach,expect,it,vi} from 'vitest';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';
import {fetchAppearance} from '../../mobile/src/api/appearance';
import {DEFAULT_APPEARANCE,type Look} from '../../mobile/src/appearance';
import {createTheme} from '../../mobile/src/theme';
import {DEFAULT_THEME,THEMES} from '../src/theme/registry';

/* The native Nerva palettes are the browser themes' dark blocks (theme contract v1), as hex. Native's
   roles are the HUD v2 roles, so they map the way the browser's legacy bridge maps them (CONTRACT.md §6):
   accent is the emphasis ink (--accent), accentDim the control edge (--accent-dim), userBubble the
   emphasis wash (--accent-faint, the browser's own user bubble). */
const NATIVE_ROLES={bg:'bg',surface:'sheet',surfaceAlt:'sheet-2',border:'rule-2',text:'text',textDim:'text-2',
  accent:'emph',accentDim:'rule-field',userBubble:'emph-wash',ok:'ok',warn:'warn',danger:'bad'} as const;
type NativeRole=keyof typeof NATIVE_ROLES;
const BROWSER_LOOKS=THEMES.map(theme=>theme.id);
const NERVA_LOOKS=THEMES.filter(theme=>theme.family==='nerva').map(theme=>theme.id as Look);
const read=(...path:string[])=>readFileSync(join(process.cwd(),'src','theme',...path),'utf8').replace(/\/\*[\s\S]*?\*\//g,'');
/** The declarations of the block whose selector matches exactly (whitespace normalised). */
function block(css:string,selector:string):Record<string,string>|null{
  for(const m of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)){
    if(m[1].replace(/\s+/g,' ').trim()!==selector)continue;
    return Object.fromEntries([...m[2].matchAll(/--n-([a-z0-9-]+)\s*:\s*([^;]+);/g)].map(d=>[d[1],d[2].trim()]));
  }
  return null;
}
/* A derived role (emph, emph-wash, ...) that a theme leaves unset keeps its tokens.css default, a var() of
   another role (contract §3). Only those defaults are taken: every other role must be in the theme's block. */
const DERIVED=Object.fromEntries(Object.entries(block(read('tokens.css'),':is(:root, .n-theme-scope)')??{})
  .filter(([,value])=>/^var\(\s*--n-[a-z0-9-]+\s*\)$/.test(value)));
function darkRoles(look:string):Record<string,string>{
  const roles=block(read('themes',`${look}.css`),`:is(:root, .n-theme-scope)[data-look="${look}"]`);
  if(!roles)throw new Error(`${look}.css has no dark block`);
  return roles;
}
/** A role's value in a dark block, following var(--n-…) to the role it names (as theme-contrast.test.ts does). */
function resolve(roles:Record<string,string>,role:string,depth=0):string{
  const raw=roles[role]??DERIVED[role]??'';
  const ref=/^var\(\s*--n-([a-z0-9-]+)\s*\)$/.exec(raw);
  return ref&&depth<6?resolve(roles,ref[1],depth+1):raw;
}
/** oklch()/#rrggbb -> #rrggbb, the CSS Color 4 conversion clipped to sRGB (as theme-contrast.test.ts). */
function hex(raw:string):string{
  const literal=/^#[0-9a-f]{6}$/i.exec(raw.trim());
  if(literal)return literal[0].toLowerCase();
  const ok=/^oklch\(\s*([\d.]+)(%?)\s+([\d.]+)\s+([\d.]+)(?:deg)?\s*\)$/i.exec(raw.trim());
  if(!ok)throw new Error(`not an opaque literal: ${raw}`);
  const l=Number(ok[1])/(ok[2]?100:1), c=Number(ok[3]), h=Number(ok[4])*Math.PI/180;
  const a=c*Math.cos(h), b=c*Math.sin(h);
  const [L,M,S]=[l+0.3963377774*a+0.2158037573*b, l-0.1055613458*a-0.0638541728*b, l-0.0894841775*a-1.291485548*b].map(v=>v**3);
  return '#'+[4.0767416621*L-3.3077115913*M+0.2309699292*S, -1.2684380046*L+2.6097574011*M-0.3413193965*S, -0.0041960863*L-0.7034186147*M+1.707614701*S]
    .map(v=>{const x=Math.min(1,Math.max(0,v));return Math.round((x<=0.0031308?12.92*x:1.055*x**(1/2.4)-0.055)*255).toString(16).padStart(2,'0');}).join('');
}
/** #rrggbb -> OKLab, to tell two painted colours apart (the distance theme-contrast.test.ts measures). */
function oklab(value:string):number[]{
  const [r,g,b]=[1,3,5].map(i=>{const v=parseInt(value.slice(i,i+2),16)/255;return v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4;});
  const [l,m,s]=[0.4122214708*r+0.5363325363*g+0.0514459929*b, 0.2119034982*r+0.6806995451*g+0.1073969566*b, 0.0883024619*r+0.2817188376*g+0.6299787005*b].map(Math.cbrt);
  return [0.2104542553*l+0.793617785*m-0.0040720468*s, 1.9779984951*l-2.428592205*m+0.4505937099*s, 0.0259040371*l+0.7827717662*m-0.808675766*s];
}
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
  global.fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>({configured:true,preferences:{accent:'no',look:'no',font:'no',motion:'lively',scanlines:true,density:'compact',scheme:'light'}})});
  await expect(fetchAppearance(config,new AbortController().signal)).resolves.toEqual({accent:'cyan',look:'ledger',font:'theme'});
});
it('keeps every browser theme id as the look, and defaults to the browser default',async()=>{
  expect(DEFAULT_APPEARANCE.look).toBe(DEFAULT_THEME);
  expect(BROWSER_LOOKS).toHaveLength(9);
  for(const look of BROWSER_LOOKS){
    global.fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>({configured:true,preferences:{accent:'amber',look,font:'theme'}})});
    await expect(fetchAppearance(config,new AbortController().signal)).resolves.toEqual({accent:'amber',look,font:'theme'});
  }
});
it('gives each Nerva theme its own dark palette, drawn in its own ink, and keeps Classic as it was',()=>{
  const hexValue=/^#[0-9a-f]{6}$/;
  const grounds=new Set<string>();
  expect(NERVA_LOOKS).toHaveLength(7);
  for(const look of NERVA_LOOKS){
    const theme=createTheme({accent:'cyan',look,font:'theme'},'ios');
    for(const role of Object.keys(NATIVE_ROLES) as NativeRole[])expect(theme[role],`${look} ${role}`).toMatch(hexValue);
    // the Classic accent axis does not recolour a Nerva theme
    expect(createTheme({accent:'violet',look,font:'theme'},'ios')).toEqual(theme);
    grounds.add(theme.bg);
  }
  expect(grounds.size).toBe(NERVA_LOOKS.length);
  // Ledger's vermilion is the owner's hand (signatures, the stop), so native chrome, links and Send are its ink
  const ledger=createTheme({accent:'cyan',look:'ledger',font:'theme'},'ios');
  expect(ledger).toMatchObject({bg:'#0e1210',text:'#dde4db',accent:'#dde4db',userBubble:'#1b211e'});
  expect(Object.values(ledger)).not.toContain('#fd6c48');
  expect(createTheme({accent:'cyan',look:'obsidian',font:'theme'},'ios')).toMatchObject({bg:'#030810',accent:'#00aeef'});
  expect(createTheme({accent:'violet',look:'graphite',font:'theme'},'ios')).toMatchObject({bg:'#0b0d11',accent:'#a78bfa'});
});
it('takes every Nerva palette from the dark block of its browser theme file',()=>{
  // the fallback for a derived role a theme leaves unset must really have been read from tokens.css
  expect(Object.keys(DERIVED)).toEqual(expect.arrayContaining(['emph','emph-wash']));
  const drift:string[]=[];
  for(const look of NERVA_LOOKS){
    const roles=darkRoles(look);const theme=createTheme({accent:'cyan',look,font:'theme'},'ios');
    for(const [native,role] of Object.entries(NATIVE_ROLES) as [NativeRole,string][]){
      const raw=resolve(roles,role);
      let expected:string;
      try{expected=hex(raw);}catch{drift.push(`${look}.${native}: --n-${role} is not an opaque literal (${raw||'not declared'})`);continue;}
      if(theme[native]!==expected)drift.push(`${look}.${native} is ${theme[native]}, --n-${role} is ${expected}`);
    }
  }
  expect(drift).toEqual([]);
});
it('keeps native status colours apart from each other, from the text ink and from the accent',()=>{
  // Tasks, Approvals, Memory and the briefing wall tell states apart by accent / ok / warn / danger;
  // contract §3's floor (OKLab distance 0.05) must hold for the colours native paints.
  const failures:string[]=[];
  const marks=['ok','warn','danger'] as const;
  for(const look of NERVA_LOOKS){
    const theme=createTheme({accent:'cyan',look,font:'theme'},'ios');
    marks.forEach((mark,i)=>{
      for(const other of [...marks.slice(i+1),'text','accent'] as const){
        const [a,b]=[oklab(theme[mark]),oklab(theme[other])];
        const distance=Math.hypot(a[0]-b[0],a[1]-b[1],a[2]-b[2]);
        if(distance<0.05)failures.push(`${look}: ${mark} ${theme[mark]} ~ ${other} ${theme[other]} (${distance.toFixed(3)})`);
      }
    });
  }
  expect(failures).toEqual([]);
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
