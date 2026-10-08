import React, {useEffect,useRef,useState} from 'react';
import {apiFetchOnce} from './api/client';

const TYPES=['image/png','image/jpeg','image/gif','image/webp'];
const MAX_BYTES=4*1024*1024, MAX_IMAGES=8;
export type VisionDraft={images:string[];names:string[];expected_destination:string;expected_binding:string;remote_ack:boolean;review_token?:string;agent?:string;session_id?:string;active_image_handles?:string[]};
type Draft={id:number;name:string;identity:string;url:string;reader:FileReader;data?:string;error?:string};
type Destination={configured:boolean;destination?:string;binding?:string;review_token?:string;model?:string;backend?:string;local?:boolean;warning?:string;empty_retries?:number;retry_notice?:string};
type ActiveImage={handle:string;count:number;question:string};

function validRetryMetadata(data:Destination){
  const hasBudget=Object.prototype.hasOwnProperty.call(data,'empty_retries');
  const hasNotice=Object.prototype.hasOwnProperty.call(data,'retry_notice');
  if(!hasBudget&&!hasNotice)return true;
  const notice=data.retry_notice;
  return data.empty_retries===1&&typeof notice==='string'&&!!notice.trim()&&
    notice.length<=500&&!/[\x00-\x1f\x7f]/.test(notice);
}

export function useComposerImages(prompt='',agent='jarvis',sessionId='',selectedTurn=false){
  const records=useRef<Draft[]>([]), serial=useRef(0);
  const context=useRef('');
  context.current=`${sessionId}\u0000${agent}\u0000${selectedTurn}`;
  const [images,setImages]=useState<Draft[]>([]),[note,setNote]=useState('');
  const [destination,setDestination]=useState<Destination|null>(null),[ack,setAck]=useState('');
  const [refreshId,setRefreshId]=useState(0);
  const [activeImages,setActiveImages]=useState<ActiveImage[]>([]);
  const [selectedHandles,setSelectedHandles]=useState<string[]>([]);
  const [reviewed,setReviewed]=useState('');
  const activeCount=selectedHandles.reduce((sum,handle)=>sum+(activeImages.find(row=>row.handle===handle)?.count||0),0);
  const publish=()=>setImages([...records.current]);
  const dispose=(entry:Draft)=>{entry.reader.onload=null;entry.reader.onerror=null;entry.reader.onabort=null;if(entry.reader.readyState===1)entry.reader.abort();if(entry.url)URL.revokeObjectURL(entry.url);};
  const clear=()=>{records.current.forEach(dispose);records.current=[];publish();setSelectedHandles([]);setDestination(null);setReviewed('');setNote('');setAck('');};
  const remove=(id:number)=>{const entry=records.current.find(item=>item.id===id);records.current=records.current.filter(item=>item.id!==id);if(entry)dispose(entry);setReviewed('');publish();};
  const addFiles=(files:Iterable<File>)=>{
    const errors:string[]=[];
    for(const file of files){
      const identity=[file.name,file.size,file.lastModified,file.type].join(':');
      if(records.current.some(item=>item.identity===identity))continue;
      if(!TYPES.includes(file.type)){errors.push(`${file.name}: use PNG, JPEG, GIF or WebP`);continue;}
      if(!file.size || file.size>MAX_BYTES){errors.push(`${file.name}: image must be between 1 byte and 4 MiB`);continue;}
      if(records.current.length+activeCount>=MAX_IMAGES){errors.push('At most eight images, including images still reading');continue;}
      const reader=new FileReader();
      const entry:Draft={id:++serial.current,name:file.name||'image',identity,url:URL.createObjectURL(file),reader};
      // Reserve synchronously; later paste/drop events count unfinished reads.
      records.current.push(entry);
      reader.onload=()=>{if(!records.current.includes(entry))return;entry.data=typeof reader.result==='string'?reader.result:undefined;if(!entry.data)entry.error='Image could not be read';publish();};
      reader.onerror=()=>{if(records.current.includes(entry)){entry.error='Image could not be read';publish();}};
      try {reader.readAsDataURL(file);} catch {entry.error='Image could not be read';}
    }
    setNote(errors.join(' · '));setReviewed('');publish();
  };
  const transfer=(data:DataTransfer)=>{
    const files=Array.from(data.files||[]);
    for(const item of Array.from(data.items||[]))if(item.kind==='file'){const file=item.getAsFile();if(file)files.push(file);}
    return files;
  };
  const onPaste=(event:React.ClipboardEvent)=>{const files=transfer(event.clipboardData).filter(file=>file.type.startsWith('image/'));if(files.length){event.preventDefault();addFiles(files);}};
  const onDrop=(event:React.DragEvent)=>{const files=transfer(event.dataTransfer);if(files.length){event.preventDefault();addFiles(files);}};
  useEffect(()=>()=>{context.current='';records.current.forEach(dispose);records.current=[];},[]);
  useEffect(()=>{clear();setActiveImages([]);},[sessionId,agent,selectedTurn]); // eslint-disable-line react-hooks/exhaustive-deps
  const loadActive=async()=>{
    if(!sessionId)return;
    const requestedContext=context.current;
    try{
      const response=await apiFetchOnce(`/api/vlm/composer/active-images?session_id=${encodeURIComponent(sessionId)}&agent=${encodeURIComponent(agent)}`);
      const text=await response.text();if(!response.ok||text.length>8192)throw new Error();
      const data=JSON.parse(text);
      if(data.session_id!==sessionId||!Array.isArray(data.images)||data.images.length>32||
        data.images.some((row:ActiveImage)=>!row||typeof row.handle!=='string'||!/^[-_A-Za-z0-9]{20,128}$/.test(row.handle)||
          !Number.isInteger(row.count)||row.count<1||row.count>8||typeof row.question!=='string'||row.question.length>120))throw new Error();
      if(context.current===requestedContext)setActiveImages(data.images);
    }catch{if(context.current===requestedContext){setActiveImages([]);setSelectedHandles([]);setNote('Previous images are unavailable');}}
  };
  const toggleActive=(handle:string)=>{
    const row=activeImages.find(item=>item.handle===handle);if(!row)return;
    const next=selectedHandles.includes(handle)?selectedHandles.filter(item=>item!==handle):[...selectedHandles,handle];
    if(next.reduce((sum,item)=>sum+(activeImages.find(entry=>entry.handle===item)?.count||0),0)+images.length>MAX_IMAGES){setNote('At most eight images');return;}
    setSelectedHandles(next);setReviewed('');setNote('');
  };
  const enabled=images.length>0||selectedHandles.length>0;
  const selection=images.map(image=>image.id).join(',')+'|'+selectedHandles.join(',');
  const readReady=images.every(image=>!!image.data&&!image.error);
  useEffect(()=>{
    setAck('');setDestination(null);setReviewed('');
    if(!enabled||selectedTurn&&!sessionId)return;
    const controller=new AbortController();let active=true;
    const prepare=async()=>{
      if(selectedTurn){
        if(!readReady||activeCount+images.length>MAX_IMAGES)return;
        const image_digests=await Promise.all(images.map(async image=>{
          const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(image.data!));
          return Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');
        }));
        return apiFetchOnce('/api/vlm/composer/selected-prepare',{method:'POST',body:{prompt:prompt.trim()||'Describe these images.',agent,session_id:sessionId,image_digests,active_image_handles:selectedHandles},signal:controller.signal});
      }
      return apiFetchOnce('/api/vlm/composer/status',{signal:controller.signal});
    };
    const timer=setTimeout(()=>{prepare().then(async response=>{
      if(!response)return;
      if(!response.ok)throw new Error('Vision status unavailable');
      const text=await response.text();if(text.length>8192)throw new Error('Invalid vision status');
      const data=JSON.parse(text) as Destination;
      if(typeof data.configured!=='boolean' || data.configured && (typeof data.destination!=='string'||typeof data.model!=='string'||typeof data.backend!=='string'||typeof data.local!=='boolean'||!(selectedTurn?/^[-_A-Za-z0-9]{20,128}$/.test(data.review_token||''):/^\w{64}$/.test(data.binding||''))))throw new Error('Invalid vision status');
      if(data.warning!==undefined&&(typeof data.warning!=='string'||data.warning.length>500))throw new Error('Invalid vision status');
      if(!validRetryMetadata(data))throw new Error('Invalid vision status');
      if(active){setDestination(data);setReviewed(selection+'|'+prompt+'|'+agent+'|'+sessionId);}
    }).catch(()=>{if(active)setDestination({configured:false});});},selectedTurn?200:0);
    return()=>{active=false;clearTimeout(timer);controller.abort();};
  },[enabled,refreshId,selectedTurn?selection:'',selectedTurn?readReady:true,selectedTurn?prompt:'',selectedTurn?agent:'',sessionId,selectedTurn]);
  const ready=enabled&&images.every(image=>!!image.data&&!image.error)&&destination?.configured&&
    (!selectedTurn||!!sessionId&&reviewed===selection+'|'+prompt+'|'+agent+'|'+sessionId)&&(destination.local===true||ack===destination.binding);
  const submission=():VisionDraft|null=>ready?{images:images.map(image=>image.data!),names:[...images.map(image=>image.name),...selectedHandles.map(()=>'previous image')],expected_destination:destination!.destination!,expected_binding:destination!.binding||destination!.review_token!,remote_ack:destination!.local!==true&&ack===destination!.binding,
    ...(selectedTurn?{review_token:destination!.review_token!,agent,session_id:sessionId,active_image_handles:selectedHandles}:{} )}:null;
  return {images,note,destination,ack,ready,addFiles,onPaste,onDrop,clear,remove,submission,activeImages,selectedHandles,loadActive,toggleActive,sessionId,selectedTurn,
    acknowledge:(checked:boolean)=>setAck(checked?destination?.binding||'':''),refresh:()=>setRefreshId(id=>id+1)};
}

export function ComposerImages({draft}:{draft:ReturnType<typeof useComposerImages>}){
  if(!draft.images.length&&!draft.selectedHandles.length&&!draft.note&&!draft.selectedTurn)return null;
  const d=draft.destination;
  return <div style={{padding:'6px 8px',fontSize:11}}>
    <div style={{display:'flex',gap:8,overflowX:'auto'}}>{draft.images.map(image=><div key={image.id} style={{flex:'0 0 92px'}}>
      <img src={image.url} alt={image.name} style={{width:88,height:64,objectFit:'contain'}}/>
      <div style={{overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{image.name}</div>
      <button className="tool-btn" onClick={()=>draft.remove(image.id)} aria-label={`Remove ${image.name}`}>Remove</button>
      {!image.data&&!image.error&&<span> Reading…</span>}{image.error&&<span>{image.error}</span>}
    </div>)}</div>
    {!!draft.sessionId&&<button className="tool-btn" onClick={draft.loadActive}>Use previous image</button>}
    {!!draft.activeImages.length&&<div>{draft.activeImages.map(row=><label key={row.handle} style={{display:'block'}}><input type="checkbox" checked={draft.selectedHandles.includes(row.handle)} onChange={()=>draft.toggleActive(row.handle)}/>{row.question} · {row.count} image(s)</label>)}</div>}
    <div role="status">{draft.note || (draft.images.length||draft.selectedHandles.length ? draft.selectedTurn&&!draft.sessionId?'Selecting conversation…':!d?'Checking vision configuration…':!d.configured?'Vision model unavailable. Remove images to send text.':`${d.model} · ${d.destination} · ${d.local?'loopback':'remote'} · reachability not probed` : '')}</div>
    {d?.configured&&d.warning&&<div style={{color:'var(--amber)'}}>{d.warning}</div>}
    {d?.configured&&d.retry_notice&&<div role="status" style={{color:'var(--amber)'}}>{d.retry_notice}</div>}
    {!!(draft.images.length||draft.selectedHandles.length)&&<button className="tool-btn" onClick={draft.refresh}>Refresh vision destination</button>}
    {d?.configured&&d.local!==true&&<label style={{display:'block'}}>
      <input type="checkbox" checked={draft.ack===d.binding} onChange={event=>draft.acknowledge(event.target.checked)}/>
      {`Send these images to ${d.destination}. I acknowledge they leave this host.`}
    </label>}
    {!!(draft.images.length||draft.selectedHandles.length)&&<div>Up to eight static images · 4 MiB each · recent images expire locally after 30 minutes.</div>}
  </div>;
}
