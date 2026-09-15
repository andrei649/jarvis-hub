import { useCallback, useEffect, useRef, useState } from 'react';
import { apiGet, apiPut } from './api/client';
import { basePath } from './base-path';

const OPTIONS = {
  font: ['theme', 'system-sans', 'system-serif', 'system-mono', 'jetbrains-mono'],
  accent: ['cyan', 'amber', 'green', 'violet'], look: ['obsidian', 'graphite'],
  density: ['normal', 'compact', 'comfy'], motion: ['system', 'calm', 'lively'],
  scanline: ['on', 'off'], dotgrid: ['off', 'on'],
} as const;
export type AppearanceKey = keyof typeof OPTIONS;
export type Appearance = Record<AppearanceKey, string>;
const DEFAULTS: Appearance = {font:'theme', accent:'cyan', look:'obsidian', density:'normal', motion:'system', scanline:'on', dotgrid:'off'};
const KEYS = Object.keys(DEFAULTS) as AppearanceKey[];
const ENDPOINT = '/api/preferences/appearance';
type Patch = Partial<Appearance>;
type Reply = {revision:string; configured: boolean; preferences: Appearance};
type State = {preferences: Appearance; pending: Patch; status: 'loading' | 'local' | 'synced' | 'saving' | 'unsynced'; error: string};

function normalize(value: unknown): Patch {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const out: Patch = {};
  for (const key of KEYS) if (Object.prototype.hasOwnProperty.call(value, key)) {
    const candidate = (value as Appearance)[key];
    out[key] = (OPTIONS[key] as readonly string[]).includes(candidate) ? candidate : DEFAULTS[key];
  }
  return out;
}
function reply(value: unknown): Reply {
  const result = value as Reply;
  if (!result || typeof result.configured !== 'boolean' || !result.preferences || typeof result.preferences !== 'object') {
    throw new Error('Invalid appearance response');
  }
  return {revision:typeof result.revision === 'string' ? result.revision : '0', configured:result.configured, preferences:{...DEFAULTS, ...normalize(result.preferences)}};
}
let lastEditTime = 0;
type Edit = {id:string; patch:Patch; time:number};
function journal(key:string): Edit[] {
  const edits:Edit[]=[];
  try {
    for(let i=0;i<localStorage.length;i++) {
      const id=localStorage.key(i)!;
      if(!id.startsWith(key+':edit:'))continue;
      try {const value=JSON.parse(localStorage.getItem(id)!);
        if(typeof value.time==='number')edits.push({id,time:value.time,patch:normalize(value.patch)});
      } catch { /* malformed entries cannot become writes */ }
    }
  } catch { /* browser storage can be unavailable */ }
  return edits.sort((a,b)=>a.time-b.time || a.id.localeCompare(b.id));
}
function patches(edits:Edit[]):Patch {return Object.assign({},...edits.map(edit=>edit.patch));}
function readCache(key: string): State {
  let preferences = {...DEFAULTS}, pending: Patch = {};
  try {
    const cached = JSON.parse(localStorage.getItem(key) || 'null');
    if (cached && cached.version === 1) {
      preferences = {...preferences, ...normalize(cached.preferences)};
      pending = patches(journal(key));
    } else {
      // Legacy browser choices are a display fallback, never a boot-time upload.
      const legacy = Object.fromEntries(KEYS.filter(k => k !== 'motion' && localStorage.getItem('hud.'+k) !== null).map(k => [k, localStorage.getItem('hud.'+k)]));
      preferences = {...preferences, ...normalize(legacy)};
    }
  } catch { /* unavailable/corrupt browser storage keeps safe defaults */ }
  pending = {...pending,...patches(journal(key))};
  return {preferences:{...preferences,...pending}, pending, status:'loading', error:''};
}

/** One owner instance, with a prefix-scoped offline queue of explicit cosmetic edits. */
export function useAppearance() {
  const [cacheKey] = useState(() => 'hud.appearance.v1:' + (basePath() || '/'));
  const [state, setState] = useState(() => readCache(cacheKey));
  const current = useRef(state);
  const mounted = useRef(false);
  const busy = useRef(false);
  const memoryEdits = useRef<Edit[]>([]);
  const edits = useCallback(() => [...journal(cacheKey),...memoryEdits.current].sort((a,b)=>a.time-b.time || a.id.localeCompare(b.id)), [cacheKey]);
  const generation = useRef(0);
  const revision = useRef('0');
  const fetchId = useRef(0);
  const [reducedMotion, setReducedMotion] = useState(() => {
    try { return !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches; } catch { return false; }
  });
  const publish = useCallback((next: State) => {
    current.current = next;
    if (mounted.current) setState(next);
    try { localStorage.setItem(cacheKey, JSON.stringify({version:1, preferences:next.preferences, })); } catch { /* memory state still works */ }
  }, [cacheKey]);

  const flush = useCallback(async () => {
    if (busy.current || !mounted.current || !edits().length) return;
    busy.current = true;
    const run = async () => {
      let conflicts=0;
      while (mounted.current) {
        const batch = edits();
        if(!batch.length) {
          if(!Object.keys(current.current.pending).length)break;
          const latest=reply(await apiGet(ENDPOINT));
          if(!mounted.current)return;
          revision.current=latest.revision;
          const pending=patches(edits());
          publish({...current.current,preferences:{...latest.preferences,...pending},pending,status:Object.keys(pending).length?'saving':'synced',error:''});
          if(!Object.keys(pending).length)break;
          continue;
        }
        const sent = patches(batch);
        generation.current++;
        publish({...current.current, status:'saving', error:''});
        let saved:Reply;
        try {saved = reply(await apiPut(ENDPOINT, {...sent,_revision:revision.current}, {conflictIsExpected:true}));}
        catch(error) {
          if((error as {status?:number}).status !== 409 || ++conflicts>8)throw error;
          const latest=reply(await apiGet(ENDPOINT));
          if(!mounted.current)return;
          revision.current=latest.revision;
          const pending=patches(edits());
          publish({...current.current,preferences:{...latest.preferences,...pending},pending,status:Object.keys(pending).length?'saving':'synced',error:''});
          continue;
        }
        revision.current=saved.revision;
        generation.current++;
        // Acknowledgements remove only immutable entries included in this write.
        for(const edit of batch) {try {localStorage.removeItem(edit.id);} catch { /* memory queue below */ }}
        memoryEdits.current=memoryEdits.current.filter(edit=>!batch.some(sent=>sent.id===edit.id));
        if (!mounted.current) return;
        const pending = patches(edits());
        publish({preferences:{...saved.preferences,...pending}, pending,
          status:Object.keys(pending).length ? 'saving' : 'synced', error:''});
      }
    };
    try {
      // Same-origin tabs share one writer; each writer reads the journal inside the lock.
      if(navigator.locks) await navigator.locks.request(cacheKey, run);
      else await run();
    } catch (error) {
      if (mounted.current) publish({...current.current, status:'unsynced', error:'Appearance saved on this browser only. Sync failed.'});
    } finally { busy.current = false; }
  }, [publish, edits, cacheKey]);

  const refresh = useCallback(async () => {
    const id = ++fetchId.current, version = generation.current;
    try {
      const saved = reply(await apiGet(ENDPOINT));
      if (!mounted.current || id !== fetchId.current || version !== generation.current || busy.current) return;
      revision.current=saved.revision;
      const pending = patches(edits());
      publish({...current.current, pending,
        preferences: saved.configured ? {...saved.preferences,...pending} : current.current.preferences,
        status:Object.keys(pending).length ? 'unsynced' : saved.configured ? 'synced' : 'local',
        error:Object.keys(pending).length ? current.current.error : ''});
    } catch {
      if (mounted.current && id === fetchId.current && version === generation.current) {
        publish({...current.current, status:'unsynced', error:'Appearance is using this browser’s saved choices. Server unavailable.'});
      }
    }
  }, [publish, edits]);

  useEffect(() => {
    mounted.current = true;
    void refresh(); void flush();
    const reconnect = () => {void refresh(); void flush();};
    window.addEventListener('online', reconnect);
    window.addEventListener('focus', reconnect);
    return () => {mounted.current = false; fetchId.current++; window.removeEventListener('online', reconnect); window.removeEventListener('focus', reconnect);};
  }, [refresh, flush]);
  useEffect(() => {
    if (!window.matchMedia) return;
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const changed = () => setReducedMotion(media.matches);
    changed(); media.addEventListener?.('change', changed);
    return () => media.removeEventListener?.('change', changed);
  }, []);

  const setPreference = useCallback((key: AppearanceKey, value: string) => {
    const next = normalize({[key]:value})[key]!;
    const edit={id:cacheKey+':edit:'+(crypto.randomUUID?.() || Math.random().toString(36).slice(2)), time:(lastEditTime=Math.max(Date.now(),lastEditTime+0.001)), patch:{[key]:next}};
    try {localStorage.setItem(edit.id,JSON.stringify(edit));} catch {memoryEdits.current.push(edit);}
    generation.current++;
    publish({...current.current, preferences:{...current.current.preferences,[key]:next},
      pending:patches(edits()), status:'saving', error:''});
    void flush();
  }, [publish, flush, cacheKey, edits]);
  const retry = useCallback(() => {void refresh(); void flush();}, [refresh,flush]);
  return {...state, setPreference, retry,
    motion:state.preferences.motion === 'system' ? reducedMotion ? 'calm' : 'lively' : state.preferences.motion};
}
