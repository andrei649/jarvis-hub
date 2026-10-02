import React, {useEffect,useRef,useState} from 'react';
import {apiFetchOnce} from './api/client';

const TYPES=['image/png','image/jpeg','image/gif','image/webp'];
const MAX_BYTES=4*1024*1024, MAX_IMAGES=8;
type SelectionNeed='acknowledge_training'|'confirm_expensive';
type SelectionRequirement={needs:SelectionNeed;message:string};
export type VisionDraft={images:string[];names:string[];expected_destination:string;expected_binding:string;review_token:string;agent:string;session_id:string;selected_turn:true;remote_ack:boolean;acknowledge_training?:true;confirm_expensive?:true};
type Draft={id:number;name:string;identity:string;url:string;reader:FileReader;data?:string;error?:string};
type Destination={configured:boolean;destination?:string;binding?:string;review_token?:string;model?:string;backend?:string;local?:boolean;warning?:string;empty_retries?:number;retry_notice?:string;selection_source?:string;selection_requirements?:SelectionRequirement[];session_id?:string;selected_turn?:boolean};

const AUTO_SOURCES=new Set(['auto:main','auto:override','auto:openrouter','auto:nous','auto:deepinfra']);
const PROVIDER_NAMES:Record<string,string>={openrouter:'OpenRouter',nous:'Nous',deepinfra:'DeepInfra',anthropic:'Anthropic Claude',gemini:'Google Gemini',lmstudio:'LM Studio',ollama:'Ollama',custom:'Custom'};

function validRetryMetadata(data:Destination){
  const hasBudget=Object.prototype.hasOwnProperty.call(data,'empty_retries');
  const hasNotice=Object.prototype.hasOwnProperty.call(data,'retry_notice');
  if(!hasBudget&&!hasNotice)return true;
  const notice=data.retry_notice;
  return data.empty_retries===1&&typeof notice==='string'&&!!notice.trim()&&
    notice.length<=500&&!/[\x00-\x1f\x7f]/.test(notice);
}

function validSelectionRequirements(data:Destination){
  if(!Object.prototype.hasOwnProperty.call(data,'selection_requirements'))return true;
  const requirements:unknown=data.selection_requirements;
  if(!Array.isArray(requirements)||requirements.length>8)return false;
  const seen=new Set<SelectionNeed>();
  for(const item of requirements){
    if(!item||typeof item!=='object'||Array.isArray(item))return false;
    const {needs,message}=item as Record<string,unknown>;
    if(needs!=='acknowledge_training'&&needs!=='confirm_expensive')return false;
    if(seen.has(needs)||typeof message!=='string'||!message.trim()||message.length>500||/[\x00-\x1f\x7f]/.test(message))return false;
    seen.add(needs);
  }
  return true;
}

export function useComposerImages(prompt='Describe these images.',agent='jarvis'){
  const records=useRef<Draft[]>([]), serial=useRef(0);
  const [images,setImages]=useState<Draft[]>([]),[note,setNote]=useState('');
  const [destination,setDestination]=useState<Destination|null>(null),[ack,setAck]=useState('');
  const [reviewedSelection,setReviewedSelection]=useState<string|null>(null);
  const [consents,setConsents]=useState<Partial<Record<SelectionNeed,string>>>({});
  const [refreshId,setRefreshId]=useState(0);
  const refreshCatalog=useRef(false);
  const publish=()=>setImages([...records.current]);
  const dispose=(entry:Draft)=>{entry.reader.onload=null;entry.reader.onerror=null;entry.reader.onabort=null;if(entry.reader.readyState===1)entry.reader.abort();if(entry.url)URL.revokeObjectURL(entry.url);};
  const clear=()=>{records.current.forEach(dispose);records.current=[];publish();setDestination(null);setReviewedSelection(null);setNote('');setAck('');setConsents({});};
  const remove=(id:number)=>{const entry=records.current.find(item=>item.id===id);records.current=records.current.filter(item=>item.id!==id);if(entry){dispose(entry);setDestination(null);setReviewedSelection(null);setAck('');setConsents({});}publish();};
  const addFiles=(files:Iterable<File>)=>{
    const errors:string[]=[];let changed=false;
    for(const file of files){
      const identity=[file.name,file.size,file.lastModified,file.type].join(':');
      if(records.current.some(item=>item.identity===identity))continue;
      if(!TYPES.includes(file.type)){errors.push(`${file.name}: use PNG, JPEG, GIF or WebP`);continue;}
      if(!file.size || file.size>MAX_BYTES){errors.push(`${file.name}: image must be between 1 byte and 4 MiB`);continue;}
      if(records.current.length>=MAX_IMAGES){errors.push('At most eight images, including images still reading');continue;}
      const reader=new FileReader();
      const entry:Draft={id:++serial.current,name:file.name||'image',identity,url:URL.createObjectURL(file),reader};
      // Reserve synchronously; later paste/drop events count unfinished reads.
      records.current.push(entry);changed=true;
      reader.onload=()=>{if(!records.current.includes(entry))return;entry.data=typeof reader.result==='string'?reader.result:undefined;if(!entry.data)entry.error='Image could not be read';publish();};
      reader.onerror=()=>{if(records.current.includes(entry)){entry.error='Image could not be read';publish();}};
      try {reader.readAsDataURL(file);} catch {entry.error='Image could not be read';}
    }
    if(changed){setDestination(null);setReviewedSelection(null);setAck('');setConsents({});}
    setNote(errors.join(' · '));publish();
  };
  const transfer=(data:DataTransfer)=>{
    const files=Array.from(data.files||[]);
    for(const item of Array.from(data.items||[]))if(item.kind==='file'){const file=item.getAsFile();if(file)files.push(file);}
    return files;
  };
  const onPaste=(event:React.ClipboardEvent)=>{const files=transfer(event.clipboardData).filter(file=>file.type.startsWith('image/'));if(files.length){event.preventDefault();addFiles(files);}};
  const onDrop=(event:React.DragEvent)=>{const files=transfer(event.dataTransfer);if(files.length){event.preventDefault();addFiles(files);}};
  useEffect(()=>()=>{records.current.forEach(dispose);records.current=[];},[]);
  const enabled=images.length>0;
  const selectionKey=images.map(image=>image.id).join(',');
  useEffect(()=>{
    setAck('');setConsents({});setDestination(null);setReviewedSelection(null);
    if(!enabled||!images.every(image=>!!image.data&&!image.error))return;
    const controller=new AbortController();let active=true;
    const timer=setTimeout(async()=>{
      if(!active)return;
      try {
        if(!globalThis.crypto?.subtle)throw new Error('Image review unavailable in this browser');
        const image_digests=await Promise.all(images.map(async image=>{
          const hash=await globalThis.crypto.subtle.digest('SHA-256',new TextEncoder().encode(image.data!));
          return Array.from(new Uint8Array(hash),byte=>byte.toString(16).padStart(2,'0')).join('');
        }));
        if(!active)return;
        const statusPath='/api/vlm/composer/prepare'+(refreshCatalog.current?'?refresh_catalog=true':'');
        refreshCatalog.current=false;
        const response=await apiFetchOnce(statusPath,{method:'POST',body:{prompt,agent,selected_turn:true,image_digests},signal:controller.signal});
        if(!response.ok)throw new Error('Vision status unavailable');
        const text=await response.text();if(text.length>8192)throw new Error('Invalid vision status');
        const data=JSON.parse(text) as Destination;
        if(typeof data.configured!=='boolean' || data.configured && (typeof data.destination!=='string'||typeof data.model!=='string'||typeof data.backend!=='string'||typeof data.local!=='boolean'||!/^\w{64}$/.test(data.binding||'')||!/^[-\w]{20,128}$/.test(data.review_token||'')))throw new Error('Invalid vision status');
        if(data.warning!==undefined&&(typeof data.warning!=='string'||data.warning.length>500))throw new Error('Invalid vision status');
        if(data.configured&&(data.selected_turn!==true||typeof data.session_id!=='string'||data.session_id.length>128||!/^[-_A-Za-z0-9]+$/.test(data.session_id)))throw new Error('Invalid vision status');
        if(data.selection_source!==undefined&&(!AUTO_SOURCES.has(data.selection_source)||
          data.selection_source==='auto:override'&&data.backend!=='custom'||
          !['auto:main','auto:override'].includes(data.selection_source)&&data.selection_source!==`auto:${data.backend}`))throw new Error('Invalid vision status');
        if(!validRetryMetadata(data)||!validSelectionRequirements(data))throw new Error('Invalid vision status');
        if(active){setDestination(data);setReviewedSelection(selectionKey);}
      } catch {if(active)setDestination({configured:false});}
    },200);
    return()=>{active=false;clearTimeout(timer);controller.abort();};
  },[images,refreshId,prompt,agent]);
  const requirements=destination?.selection_requirements||[];
  const ready=enabled&&reviewedSelection===selectionKey&&images.every(image=>!!image.data&&!image.error)&&destination?.configured&&
    (destination.local===true||ack===destination.binding)&&requirements.every(item=>consents[item.needs]===destination.binding);
  const submission=():VisionDraft|null=>ready?{
    images:images.map(image=>image.data!),names:images.map(image=>image.name),
    expected_destination:destination!.destination!,expected_binding:destination!.binding!,review_token:destination!.review_token!,agent,
    selected_turn:true,session_id:destination!.session_id!,
    remote_ack:destination!.local!==true&&ack===destination!.binding,
    ...(requirements.some(item=>item.needs==='acknowledge_training')?{acknowledge_training:true as const}:{}),
    ...(requirements.some(item=>item.needs==='confirm_expensive')?{confirm_expensive:true as const}:{}),
  }:null;
  return {images,note,destination,ack,consents,ready,addFiles,onPaste,onDrop,clear,remove,submission,
    acknowledge:(checked:boolean)=>setAck(checked?destination?.binding||'':''),
    confirm:(need:SelectionNeed,checked:boolean)=>setConsents(current=>({...current,[need]:checked?destination?.binding||'':''})),
    refresh:()=>{refreshCatalog.current=true;setConsents({});setRefreshId(id=>id+1);}};
}

export function ComposerImages({draft}:{draft:ReturnType<typeof useComposerImages>}){
  if(!draft.images.length&&!draft.note)return null;
  const d=draft.destination;
  return <div style={{padding:'6px 8px',fontSize:11}}>
    <div style={{display:'flex',gap:8,overflowX:'auto'}}>{draft.images.map(image=><div key={image.id} style={{flex:'0 0 92px'}}>
      <img src={image.url} alt={image.name} style={{width:88,height:64,objectFit:'contain'}}/>
      <div style={{overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{image.name}</div>
      <button className="tool-btn" onClick={()=>draft.remove(image.id)} aria-label={`Remove ${image.name}`}>Remove</button>
      {!image.data&&!image.error&&<span> Reading…</span>}{image.error&&<span>{image.error}</span>}
    </div>)}</div>
    <div role="status">{draft.note || (draft.images.length ? !d?'Checking vision configuration…':!d.configured?'Vision model unavailable. Remove images to send text.':`${d.selection_source?`Automatically selected ${PROVIDER_NAMES[d.backend||'']||d.backend} · `:''}${d.model} · ${d.destination} · ${d.local?'loopback':'remote'} · reachability not probed` : '')}</div>
    {d?.configured&&d.warning&&<div style={{color:'var(--amber)'}}>{d.warning}</div>}
    {d?.configured&&d.retry_notice&&<div role="status" style={{color:'var(--amber)'}}>{d.retry_notice}</div>}
    {!!draft.images.length&&<button className="tool-btn" onClick={draft.refresh}>Refresh vision destination</button>}
    {d?.configured&&d.local!==true&&<label style={{display:'block'}}>
      <input type="checkbox" checked={draft.ack===d.binding} onChange={event=>draft.acknowledge(event.target.checked)}/>
      {`Send these images and the assembled conversation prompt to ${d.destination}. The prompt may include earlier messages, agent context and a checkpoint. I acknowledge they leave this host.`}
    </label>}
    {d?.configured&&d.selection_requirements?.map(requirement=><label key={requirement.needs} style={{display:'block'}}>
      <input type="checkbox" checked={draft.consents[requirement.needs]===d.binding} onChange={event=>draft.confirm(requirement.needs,event.target.checked)}/>
      {requirement.needs==='acknowledge_training'?'Training use: ':'Cost confirmation: '}{requirement.message}
    </label>)}
    {!!draft.images.length&&<div>Up to eight static images · 4 MiB each · images are transient and are not added to agent memory.</div>}
  </div>;
}
