import React, {useEffect,useRef,useState} from 'react';
import {apiFetchOnce} from './api/client';

const TYPES=['image/png','image/jpeg','image/gif','image/webp'];
const MAX_BYTES=4*1024*1024, MAX_IMAGES=8;
type SelectionNeed='acknowledge_training'|'confirm_expensive';
type SelectionRequirement={needs:SelectionNeed;message:string};
type ActiveImage={handle:string;count:number;question:string};
export type VisionDraft={images:string[];names:string[];active_image_handles?:string[];expected_destination:string;expected_binding:string;review_token:string;agent:string;session_id:string;selected_turn:true;selected_main?:true;remote_ack:boolean;acknowledge_training?:true;confirm_expensive?:true};
type Draft={id:number;name:string;identity:string;url:string;reader:FileReader;data?:string;error?:string};
type Destination={configured:boolean;destination?:string;binding?:string;review_token?:string;model?:string;backend?:string;local?:boolean;warning?:string;data_policy_note?:string;empty_retries?:number;retry_notice?:string;selection_source?:string;selection_requirements?:SelectionRequirement[];session_id?:string;selected_turn?:boolean;active_image_count?:number};

const AUTO_SOURCES=new Set(['auto:main','auto:override','auto:openrouter','auto:nous','auto:deepinfra']);
const PROVIDER_NAMES:Record<string,string>={openrouter:'OpenRouter',nous:'Nous',deepinfra:'DeepInfra',anthropic:'Anthropic Claude',gemini:'Google Gemini','openai-responses':'OpenAI Responses',xai:'xAI Grok',lmstudio:'LM Studio',ollama:'Ollama',custom:'Custom'};

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

export function useComposerImages(prompt='',agent='jarvis'){
  const records=useRef<Draft[]>([]), serial=useRef(0);
  const activeRequest=useRef<AbortController|null>(null);
  const [images,setImages]=useState<Draft[]>([]),[note,setNote]=useState('');
  const [activeImages,setActiveImages]=useState<ActiveImage[]>([]);
  const [selectedHandles,setSelectedHandles]=useState<string[]>([]);
  const [activeSession,setActiveSession]=useState('');
  const [activeState,setActiveState]=useState<'idle'|'loading'|'ready'|'unavailable'>('idle');
  const [destination,setDestination]=useState<Destination|null>(null),[ack,setAck]=useState('');
  const [reviewedSelection,setReviewedSelection]=useState<string|null>(null);
  const [consents,setConsents]=useState<Partial<Record<SelectionNeed,string>>>({});
  const [refreshId,setRefreshId]=useState(0);
  const refreshCatalog=useRef(false);
  const activeCount=selectedHandles.reduce((total,handle)=>total+(activeImages.find(image=>image.handle===handle)?.count||0),0);
  const reviewPrompt=prompt.trim()||'Describe these images.';
  const invalidateReview=()=>{setDestination(null);setReviewedSelection(null);setAck('');setConsents({});};
  const publish=()=>setImages([...records.current]);
  const dispose=(entry:Draft)=>{entry.reader.onload=null;entry.reader.onerror=null;entry.reader.onabort=null;if(entry.reader.readyState===1)entry.reader.abort();if(entry.url)URL.revokeObjectURL(entry.url);};
  const clear=()=>{activeRequest.current?.abort();records.current.forEach(dispose);records.current=[];publish();setActiveImages([]);setSelectedHandles([]);setActiveSession('');setActiveState('idle');invalidateReview();setNote('');};
  const remove=(id:number)=>{const entry=records.current.find(item=>item.id===id);records.current=records.current.filter(item=>item.id!==id);if(entry){dispose(entry);invalidateReview();}publish();};
  const loadActiveImages=async()=>{
    activeRequest.current?.abort();
    const controller=new AbortController();activeRequest.current=controller;
    setActiveState('loading');setActiveImages([]);setSelectedHandles([]);setActiveSession('');invalidateReview();
    try {
      const response=await apiFetchOnce(`/api/vlm/composer/active-images?agent=${encodeURIComponent(agent)}`,{signal:controller.signal});
      if(!response.ok)throw new Error('active images unavailable');
      const text=await response.text();if(text.length>8192)throw new Error('invalid active images');
      const data=JSON.parse(text) as {session_id?:unknown;images?:unknown};
      if(typeof data.session_id!=='string'||data.session_id.length>128||!/^[-_A-Za-z0-9]+$/.test(data.session_id)||
        !Array.isArray(data.images)||data.images.length>32)throw new Error('invalid active images');
      const rows=data.images as ActiveImage[];
      if(rows.some(row=>!row||typeof row.handle!=='string'||!/^[-_A-Za-z0-9]{20,128}$/.test(row.handle)||
        !Number.isInteger(row.count)||row.count<1||row.count>8||typeof row.question!=='string'||
        row.question.length>120||/[\x00-\x1f\x7f]/.test(row.question))||
        new Set(rows.map(row=>row.handle)).size!==rows.length)throw new Error('invalid active images');
      if(!controller.signal.aborted){setActiveImages(rows);setActiveSession(data.session_id);setActiveState(rows.length?'ready':'unavailable');}
    } catch {if(!controller.signal.aborted){setActiveImages([]);setActiveSession('');setActiveState('unavailable');}}
    finally {if(activeRequest.current===controller)activeRequest.current=null;}
  };
  const toggleActive=(handle:string)=>{
    const row=activeImages.find(image=>image.handle===handle);if(!row)return;
    const next=selectedHandles.includes(handle)?selectedHandles.filter(item=>item!==handle):[...selectedHandles,handle];
    const count=next.reduce((total,item)=>total+(activeImages.find(image=>image.handle===item)?.count||0),0);
    if(count+records.current.length>MAX_IMAGES){setNote('At most eight images across previous and new selections');return;}
    setSelectedHandles(next);setNote('');invalidateReview();
  };
  const addFiles=(files:Iterable<File>)=>{
    const errors:string[]=[];let changed=false;
    for(const file of files){
      const identity=[file.name,file.size,file.lastModified,file.type].join(':');
      if(records.current.some(item=>item.identity===identity))continue;
      if(!TYPES.includes(file.type)){errors.push(`${file.name}: use PNG, JPEG, GIF or WebP`);continue;}
      if(!file.size || file.size>MAX_BYTES){errors.push(`${file.name}: image must be between 1 byte and 4 MiB`);continue;}
      if(records.current.length+activeCount>=MAX_IMAGES){errors.push('At most eight images, including previous selections and images still reading');continue;}
      const reader=new FileReader();
      const entry:Draft={id:++serial.current,name:file.name||'image',identity,url:URL.createObjectURL(file),reader};
      // Reserve synchronously; later paste/drop events count unfinished reads.
      records.current.push(entry);changed=true;
      reader.onload=()=>{if(!records.current.includes(entry))return;entry.data=typeof reader.result==='string'?reader.result:undefined;if(!entry.data)entry.error='Image could not be read';publish();};
      reader.onerror=()=>{if(records.current.includes(entry)){entry.error='Image could not be read';publish();}};
      try {reader.readAsDataURL(file);} catch {entry.error='Image could not be read';}
    }
    if(changed)invalidateReview();
    setNote(errors.join(' · '));publish();
  };
  const transfer=(data:DataTransfer)=>{
    const files=Array.from(data.files||[]);
    for(const item of Array.from(data.items||[]))if(item.kind==='file'){const file=item.getAsFile();if(file)files.push(file);}
    return files;
  };
  const onPaste=(event:React.ClipboardEvent)=>{const files=transfer(event.clipboardData).filter(file=>file.type.startsWith('image/'));if(files.length){event.preventDefault();addFiles(files);}};
  const onDrop=(event:React.DragEvent)=>{const files=transfer(event.dataTransfer);if(files.length){event.preventDefault();addFiles(files);}};
  useEffect(()=>()=>{activeRequest.current?.abort();records.current.forEach(dispose);records.current=[];},[]);
  const enabled=images.length>0||selectedHandles.length>0;
  const selectionKey=`${images.map(image=>image.id).join(',')}|${selectedHandles.join(',')}`;
  useEffect(()=>{
    setAck('');setConsents({});setDestination(null);setReviewedSelection(null);
    if(!enabled||selectedHandles.length>0&&!prompt.trim()||
      activeCount+images.length>MAX_IMAGES||!images.every(image=>!!image.data&&!image.error))return;
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
        const response=await apiFetchOnce(statusPath,{method:'POST',body:{prompt:reviewPrompt,agent,selected_turn:true,
          ...(images.length?{image_digests}:{}),...(selectedHandles.length?{active_image_handles:selectedHandles}:{})},signal:controller.signal});
        const text=await response.text();if(text.length>8192)throw new Error('Invalid vision status');
        const data=JSON.parse(text) as Destination&{reason?:string};
        if(!response.ok){
          if(active&&selectedHandles.length&&response.status===409&&data.reason==='vlm_active_image_unavailable'){
            setActiveImages([]);setSelectedHandles([]);setActiveSession('');setActiveState('unavailable');
          }
          throw new Error('Vision status unavailable');
        }
        if(typeof data.configured!=='boolean' || data.configured && (typeof data.destination!=='string'||typeof data.model!=='string'||typeof data.backend!=='string'||typeof data.local!=='boolean'||!/^\w{64}$/.test(data.binding||'')||!/^[-\w]{20,128}$/.test(data.review_token||'')))throw new Error('Invalid vision status');
        if(data.warning!==undefined&&(typeof data.warning!=='string'||data.warning.length>500))throw new Error('Invalid vision status');
        if(data.data_policy_note!==undefined&&(typeof data.data_policy_note!=='string'||data.data_policy_note.length>500))throw new Error('Invalid vision status');
        if(data.configured&&(data.selected_turn!==true||typeof data.session_id!=='string'||data.session_id.length>128||!/^[-_A-Za-z0-9]+$/.test(data.session_id)))throw new Error('Invalid vision status');
        if(data.selection_source!==undefined&&(!AUTO_SOURCES.has(data.selection_source)||
          data.selection_source==='auto:override'&&data.backend!=='custom'||
          !['auto:main','auto:override'].includes(data.selection_source)&&data.selection_source!==`auto:${data.backend}`))throw new Error('Invalid vision status');
        if(selectedHandles.length&&(data.selection_source!=='auto:main'||data.session_id!==activeSession||
          data.active_image_count!==activeCount))throw new Error('Invalid active image selection');
        if(!validRetryMetadata(data)||!validSelectionRequirements(data))throw new Error('Invalid vision status');
        if(active){setDestination(data);setReviewedSelection(selectionKey);}
      } catch {if(active)setDestination({configured:false});}
    },200);
    return()=>{active=false;clearTimeout(timer);controller.abort();};
  },[images,selectedHandles,refreshId,prompt,agent,activeSession]);
  const requirements=destination?.selection_requirements||[];
  const xaiUnsupported=destination?.backend==='xai'&&images.some(image=>
    !!image.data&&!/^data:image\/(png|jpeg);base64,/.test(image.data));
  const ready=enabled&&(!selectedHandles.length||!!prompt.trim())&&reviewedSelection===selectionKey&&
    activeCount+images.length<=MAX_IMAGES&&images.every(image=>!!image.data&&!image.error)&&destination?.configured&&
    !xaiUnsupported&&(destination.local===true||ack===destination.binding)&&requirements.every(item=>consents[item.needs]===destination.binding);
  const submission=():VisionDraft|null=>ready?{
    images:images.map(image=>image.data!),names:[...images.map(image=>image.name),
      ...selectedHandles.map(handle=>`Previous: ${activeImages.find(image=>image.handle===handle)?.question||'image'}`)],
    ...(selectedHandles.length?{active_image_handles:selectedHandles}:{}),
    expected_destination:destination!.destination!,expected_binding:destination!.binding!,review_token:destination!.review_token!,agent,
    selected_turn:true,session_id:destination!.session_id!,
    ...(destination!.selection_source==='auto:main'?{selected_main:true as const}:{}),
    remote_ack:destination!.local!==true&&ack===destination!.binding,
    ...(requirements.some(item=>item.needs==='acknowledge_training')?{acknowledge_training:true as const}:{}),
    ...(requirements.some(item=>item.needs==='confirm_expensive')?{confirm_expensive:true as const}:{}),
  }:null;
  return {images,note,destination,ack,consents,ready,xaiUnsupported,addFiles,onPaste,onDrop,clear,remove,submission,
    activeImages,selectedHandles,activeState,activeCount,enabled,loadActiveImages,toggleActive,
    acknowledge:(checked:boolean)=>setAck(checked?destination?.binding||'':''),
    confirm:(need:SelectionNeed,checked:boolean)=>setConsents(current=>({...current,[need]:checked?destination?.binding||'':''})),
    refresh:()=>{refreshCatalog.current=true;setConsents({});setRefreshId(id=>id+1);}};
}

export function ComposerImages({draft}:{draft:ReturnType<typeof useComposerImages>}){
  const d=draft.destination;
  return <div style={{padding:'6px 8px',fontSize:11}}>
    <button type="button" className="tool-btn" onClick={draft.loadActiveImages}>Reuse earlier images</button>
    {draft.activeState==='loading'&&<span role="status"> Checking earlier images…</span>}
    {draft.activeState==='unavailable'&&<span role="status"> Earlier images are unavailable in this session. Attach them again if needed.</span>}
    {draft.activeState==='ready'&&<div style={{display:'flex',gap:8,overflowX:'auto',marginTop:5}}>
      {draft.activeImages.map(image=><label key={image.handle} style={{flex:'0 0 150px',border:'1px solid var(--panel-line)',borderRadius:6,padding:5}}>
        <input type="checkbox" checked={draft.selectedHandles.includes(image.handle)} onChange={()=>draft.toggleActive(image.handle)}/>
        {`Use previous image: ${image.question} (${image.count})`}
        {draft.selectedHandles.includes(image.handle)&&<span>{` · #${draft.selectedHandles.indexOf(image.handle)+1}`}</span>}
      </label>)}
    </div>}
    <div style={{display:'flex',gap:8,overflowX:'auto'}}>{draft.images.map(image=><div key={image.id} style={{flex:'0 0 92px'}}>
      <img src={image.url} alt={image.name} style={{width:88,height:64,objectFit:'contain'}}/>
      <div style={{overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{image.name}</div>
      <button className="tool-btn" onClick={()=>draft.remove(image.id)} aria-label={`Remove ${image.name}`}>Remove</button>
      {!image.data&&!image.error&&<span> Reading…</span>}{image.error&&<span>{image.error}</span>}
    </div>)}</div>
    {(draft.enabled||draft.note)&&<div role="status">{draft.note || (!d?'Checking vision configuration…':!d.configured?'Vision model unavailable. Remove image selections to send text.':`${d.selection_source?`Automatically selected ${PROVIDER_NAMES[d.backend||'']||d.backend} · `:''}${d.model} · ${d.destination} · ${d.local?'loopback':'remote'} · reachability not probed`)}</div>}
    {draft.xaiUnsupported&&<div role="status" style={{color:'var(--amber)'}}>xAI accepts PNG or JPEG images. Remove GIF/WebP images before sending.</div>}
    {d?.configured&&d.warning&&<div style={{color:'var(--amber)'}}>{d.warning}</div>}
    {d?.configured&&d.backend==='openai-responses'&&d.data_policy_note&&<div>{d.data_policy_note}</div>}
    {d?.configured&&d.retry_notice&&<div role="status" style={{color:'var(--amber)'}}>{d.retry_notice}</div>}
    {draft.enabled&&<button className="tool-btn" onClick={draft.refresh}>Refresh vision destination</button>}
    {d?.configured&&d.local!==true&&<label style={{display:'block'}}>
      <input type="checkbox" checked={draft.ack===d.binding} onChange={event=>draft.acknowledge(event.target.checked)}/>
      {`Send these images and the assembled conversation prompt to ${d.destination}. The prompt may include earlier messages, agent context and a checkpoint. I acknowledge they leave this host.`}
    </label>}
    {d?.configured&&d.selection_requirements?.map(requirement=><label key={requirement.needs} style={{display:'block'}}>
      <input type="checkbox" checked={draft.consents[requirement.needs]===d.binding} onChange={event=>draft.confirm(requirement.needs,event.target.checked)}/>
      {requirement.needs==='acknowledge_training'?'Training use: ':'Cost confirmation: '}{requirement.message}
    </label>)}
    {draft.enabled&&<div>Selected {draft.activeCount} previous + {draft.images.length} new images · up to eight static images total · 4 MiB each · {d?.selection_source==='auto:main'?'image bytes are transient; the question and answer are saved in this conversation.':'images are transient and are not added to agent memory.'}</div>}
  </div>;
}
