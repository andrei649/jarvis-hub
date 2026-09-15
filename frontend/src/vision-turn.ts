import {apiFetchOnce} from './api/client';
import type {VisionDraft} from './composer-images';
export type VisionMessage={role:'vision';text:string;model:string;backend:string;destination:string;local:boolean;ts:string};
export async function describeImages(prompt:string,draft:VisionDraft,signal:AbortSignal):Promise<Omit<VisionMessage,'role'|'ts'>>{
  const {names,...request}=draft;
  const response=await apiFetchOnce('/api/vlm/composer/describe',{method:'POST',body:{prompt,...request},signal});
  const text=await response.text();
  if(text.length>128*1024)throw new Error('Vision response exceeded its display limit');
  let data:any;try{data=JSON.parse(text);}catch{throw new Error('Invalid vision response');}
  if(!response.ok)throw new Error(typeof data.error==='string'?data.error.slice(0,240):`Vision analysis failed (HTTP ${response.status})`);
  if(data.ok!==true||typeof data.response!=='string'||!data.response.trim()||typeof data.model!=='string'||typeof data.backend!=='string'||typeof data.destination!=='string'||typeof data.local!=='boolean')throw new Error('Invalid vision response');
  return {text:data.response,model:data.model,backend:data.backend,destination:data.destination,local:data.local};
}
