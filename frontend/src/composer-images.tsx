import React, {useEffect,useRef,useState} from 'react';
import {apiFetchOnce} from './api/client';

const TYPES=['image/png','image/jpeg','image/gif','image/webp'];
const MAX_BYTES=4*1024*1024, MAX_IMAGES=8;
export type VisionDraft={images:string[];names:string[];expected_destination:string;expected_binding:string;remote_ack:boolean};
type Draft={id:number;name:string;identity:string;url:string;reader:FileReader;data?:string;error?:string};
type Destination={configured:boolean;destination?:string;binding?:string;model?:string;backend?:string;local?:boolean};

export function useComposerImages(){
  const records=useRef<Draft[]>([]), serial=useRef(0);
  const [images,setImages]=useState<Draft[]>([]),[note,setNote]=useState('');
  const [destination,setDestination]=useState<Destination|null>(null),[ack,setAck]=useState('');
  const [refreshId,setRefreshId]=useState(0);
  const publish=()=>setImages([...records.current]);
  const dispose=(entry:Draft)=>{entry.reader.onload=null;entry.reader.onerror=null;entry.reader.onabort=null;if(entry.reader.readyState===1)entry.reader.abort();if(entry.url)URL.revokeObjectURL(entry.url);};
  const clear=()=>{records.current.forEach(dispose);records.current=[];publish();setNote('');setAck('');};
  const remove=(id:number)=>{const entry=records.current.find(item=>item.id===id);records.current=records.current.filter(item=>item.id!==id);if(entry)dispose(entry);publish();};
  const addFiles=(files:Iterable<File>)=>{
    const errors:string[]=[];
    for(const file of files){
      const identity=[file.name,file.size,file.lastModified,file.type].join(':');
      if(records.current.some(item=>item.identity===identity))continue;
      if(!TYPES.includes(file.type)){errors.push(`${file.name}: use PNG, JPEG, GIF or WebP`);continue;}
      if(!file.size || file.size>MAX_BYTES){errors.push(`${file.name}: image must be between 1 byte and 4 MiB`);continue;}
      if(records.current.length>=MAX_IMAGES){errors.push('At most eight images, including images still reading');continue;}
      const reader=new FileReader();
      const entry:Draft={id:++serial.current,name:file.name||'image',identity,url:URL.createObjectURL(file),reader};
      // Reserve synchronously; later paste/drop events count unfinished reads.
      records.current.push(entry);
      reader.onload=()=>{if(!records.current.includes(entry))return;entry.data=typeof reader.result==='string'?reader.result:undefined;if(!entry.data)entry.error='Image could not be read';publish();};
      reader.onerror=()=>{if(records.current.includes(entry)){entry.error='Image could not be read';publish();}};
      try {reader.readAsDataURL(file);} catch {entry.error='Image could not be read';}
    }
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
  useEffect(()=>{
    setAck('');setDestination(null);
    if(!enabled)return;
    const controller=new AbortController();let active=true;
    apiFetchOnce('/api/vlm/composer/status',{signal:controller.signal}).then(async response=>{
      if(!response.ok)throw new Error('Vision status unavailable');
      const text=await response.text();if(text.length>8192)throw new Error('Invalid vision status');
      const data=JSON.parse(text) as Destination;
      if(typeof data.configured!=='boolean' || data.configured && (typeof data.destination!=='string'||typeof data.model!=='string'||typeof data.backend!=='string'||typeof data.local!=='boolean'||!/^\w{64}$/.test(data.binding||'')))throw new Error('Invalid vision status');
      if(active)setDestination(data);
    }).catch(()=>{if(active)setDestination({configured:false});});
    return()=>{active=false;controller.abort();};
  },[enabled,refreshId]);
  const ready=enabled&&images.every(image=>!!image.data&&!image.error)&&destination?.configured&&(destination.local===true||ack===destination.binding);
  const submission=():VisionDraft|null=>ready?{images:images.map(image=>image.data!),names:images.map(image=>image.name),expected_destination:destination!.destination!,expected_binding:destination!.binding!,remote_ack:destination!.local!==true&&ack===destination!.binding}:null;
  return {images,note,destination,ack,ready,addFiles,onPaste,onDrop,clear,remove,submission,
    acknowledge:(checked:boolean)=>setAck(checked?destination?.binding||'':''),refresh:()=>setRefreshId(id=>id+1)};
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
    <div role="status">{draft.note || (draft.images.length ? !d?'Checking vision configuration…':!d.configured?'Vision model unavailable. Remove images to send text.':`${d.model} · ${d.destination} · ${d.local?'loopback':'remote'} · reachability not probed` : '')}</div>
    {!!draft.images.length&&<button className="tool-btn" onClick={draft.refresh}>Refresh vision destination</button>}
    {d?.configured&&d.local!==true&&<label style={{display:'block'}}>
      <input type="checkbox" checked={draft.ack===d.binding} onChange={event=>draft.acknowledge(event.target.checked)}/>
      {`Send these images to ${d.destination}. I acknowledge they leave this host.`}
    </label>}
    {!!draft.images.length&&<div>Up to eight static images · 4 MiB each · images are transient and are not added to agent memory.</div>}
  </div>;
}
