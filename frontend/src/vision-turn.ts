import {apiFetchOnce} from './api/client';
import type {VisionDraft} from './composer-images';
export type VisionMessage={role:'vision';text:string;model:string;backend:string;destination:string;local:boolean;ts:string;warning?:string};
export async function describeImages(prompt:string,draft:VisionDraft,signal:AbortSignal):Promise<Omit<VisionMessage,'role'|'ts'>>{
  const {names,selected_main,...request}=draft;
  if(draft.active_image_handles?.length&&!selected_main)throw new Error('Active image history requires a selected main route');
  const path=selected_main?'/api/vlm/composer/chat-prepared':'/api/vlm/composer/describe-prepared';
  const response=await apiFetchOnce(path,{method:'POST',body:{prompt,...request},signal});
  const text=await response.text();
  if(text.length>128*1024)throw new Error('Vision response exceeded its display limit');
  let data:any;try{data=JSON.parse(text);}catch{throw new Error('Invalid vision response');}
  if(!response.ok)throw new Error(typeof data.error==='string'?data.error.slice(0,240):`Vision analysis failed (HTTP ${response.status})`);
  if(data.ok!==true||selected_main&&data.committed!==true||typeof data.response!=='string'||!data.response.trim()||typeof data.model!=='string'||typeof data.backend!=='string'||typeof data.destination!=='string'||typeof data.local!=='boolean')throw new Error('Invalid vision response');
  if(data.warning!==undefined&&(typeof data.warning!=='string'||data.warning.length>500))throw new Error('Invalid vision response');
  return {text:data.response,model:data.model,backend:data.backend,destination:data.destination,local:data.local,...(data.warning?{warning:data.warning}:{})};
}

export function restoreVisionTurn(turn:unknown,ts:string):VisionMessage|null{
  if(!turn||typeof turn!=='object'||Array.isArray(turn))return null;
  const row=turn as Record<string,unknown>;
  if(row.role!=='assistant'||typeof row.content!=='string'||!row.content.trim())return null;
  const media=row.media;
  if(!media||typeof media!=='object'||Array.isArray(media))return null;
  const value=media as Record<string,unknown>;
  if(value.kind!=='image'||!Number.isInteger(value.count)||Number(value.count)<1||Number(value.count)>8||
    typeof value.model!=='string'||!value.model||value.model.length>512||/[\x00-\x20\x7f]/.test(value.model)||
    typeof value.backend!=='string'||!/^[a-z][a-z0-9_-]{0,63}$/.test(value.backend)||typeof value.local!=='boolean')return null;
  return {role:'vision',text:row.content,model:value.model,backend:value.backend,destination:'',local:value.local,ts};
}
