import React from 'react';
import {act, cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import App from '../app';

vi.mock('../voice',()=>({useVoice:()=>({active:false,toggle:()=>{}})}));
vi.mock('../mesh',()=>({NeuralMesh:({onSelect}:any)=><><button onClick={()=>onSelect('frigga')}>Select Frigga</button><button onClick={()=>onSelect('jarvis')}>Select Jarvis</button></>,isExecutingAgent:()=>false}));
vi.mock('../api/loaders',()=>({loadJarvisData:async()=>({}),createLatestRefreshRunner:()=>({refresh:()=>{},stop:()=>{}})}));
vi.mock('../api/live',()=>({PREVIEW_MODE_LIVE_KEYS:{},useLiveModes:()=>({live:{}})}));
vi.mock('../analytics',()=>({initAnalytics:()=>{},trackPageview:()=>{}}));
vi.mock('../gap',()=>({FirstRunGate:()=>null}));

const token='review-token-'.repeat(4);
const selectedStatus=(session_id:string)=>({configured:true,review_token:token,session_id,
  destination:'http://127.0.0.1:11434',model:'vision-model',backend:'ollama',local:true});
const selectedAnswer=()=>new Response(JSON.stringify({ok:true,committed:true,response:'Selected image answer',
  model:'vision-model',backend:'ollama',destination:'http://127.0.0.1:11434',local:true}));
type Request={path:string;body?:string;signal?:AbortSignal};
let requests:Request[]=[];

beforeEach(()=>{
  localStorage.clear();sessionStorage.clear();requests=[];
  URL.createObjectURL=vi.fn(()=>'blob:image');URL.revokeObjectURL=vi.fn();
  vi.stubGlobal('crypto',{subtle:{digest:async()=>new Uint8Array(32).buffer}});
});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});

async function attach(){
  fireEvent.change(await screen.findByLabelText('Attach images'),{target:{files:[new File(['image'],'shot.png',{type:'image/png'})]}});
}

it('rehydrates an empty selected session and sends through its reviewed Ollama route',async()=>{
  history.replaceState(null,'','/v2/chat');
  let releaseMemory!:(response:Response)=>void;
  vi.stubGlobal('fetch',vi.fn(async(path:string,init?:{body?:string;signal?:AbortSignal})=>{
    requests.push({path,body:init?.body,signal:init?.signal});
    if(path==='/memory')return new Promise<Response>(resolve=>{releaseMemory=resolve;});
    if(path.endsWith('/selected-prepare'))return new Response(JSON.stringify(selectedStatus('empty_session')));
    if(path.endsWith('/selected-chat'))return selectedAnswer();
    return new Response(JSON.stringify({configured:false,revision:'0',preferences:{}}));
  }));
  render(<App/>);await attach();
  expect(await screen.findByText('Selecting conversation…')).toBeTruthy();
  expect(requests.some(row=>row.path.endsWith('/composer/status')||row.path.endsWith('/composer/describe'))).toBe(false);
  await act(async()=>releaseMemory(new Response(JSON.stringify({session:'empty_session',turns:[]}))));
  expect(sessionStorage.getItem('nerva.chat.session_id')).toBe('empty_session');
  await attach();
  await waitFor(()=>expect(requests.some(row=>row.path.endsWith('/selected-prepare'))).toBe(true));
  const prepare=requests.find(row=>row.path.endsWith('/selected-prepare'))!;
  expect(JSON.parse(prepare.body!)).toMatchObject({agent:'jarvis',session_id:'empty_session',image_digests:['00'.repeat(32)]});
  await waitFor(()=>expect(screen.getByRole('button',{name:/TRANSMIT/}).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('button',{name:/TRANSMIT/}));
  await screen.findByText('Selected image answer');
  expect(JSON.parse(requests.find(row=>row.path.endsWith('/selected-chat'))!.body!)).toMatchObject({agent:'jarvis',session_id:'empty_session',review_token:token});
  expect(requests.some(row=>row.path.endsWith('/composer/describe'))).toBe(false);
});

it('invalidates a pending review when the selected topic changes',async()=>{
  history.replaceState(null,'','/v2/chat');sessionStorage.setItem('nerva.chat.session_id','old_session');
  let releasePrepare!:(response:Response)=>void;
  vi.stubGlobal('fetch',vi.fn(async(path:string,init?:{body?:string;signal?:AbortSignal})=>{
    requests.push({path,body:init?.body,signal:init?.signal});
    if(path.endsWith('/selected-prepare')){
      if(JSON.parse(init!.body!).session_id==='old_session')return new Promise<Response>(resolve=>{releasePrepare=resolve;});
      return new Response(JSON.stringify(selectedStatus('new_session')));
    }
    if(path==='/sessions/resume')return new Response(JSON.stringify({session:'old_session',turns:[]}));
    return new Response(JSON.stringify({configured:false,revision:'0',preferences:{}}));
  }));
  render(<App/>);await attach();
  await waitFor(()=>expect(releasePrepare).toBeTruthy());
  const old=requests.find(row=>row.path.endsWith('/selected-prepare'))!;
  act(()=>window.dispatchEvent(new CustomEvent('nerva:session-selected',{detail:{sessionId:'new_session',turns:[]}})));
  expect(old.signal?.aborted).toBe(true);
  await act(async()=>releasePrepare(new Response(JSON.stringify(selectedStatus('old_session')))));
  expect(screen.queryByText(/vision-model/)).toBeNull();
  await attach();
  await waitFor(()=>expect(requests.filter(row=>row.path.endsWith('/selected-prepare'))).toHaveLength(2));
  expect(JSON.parse(requests.filter(row=>row.path.endsWith('/selected-prepare'))[1].body!)).toMatchObject({session_id:'new_session',agent:'jarvis'});
});

it('uses the selected agent and aborts its image answer when the agent changes',async()=>{
  history.replaceState(null,'','/v2/cockpit');sessionStorage.setItem('nerva.chat.session_id','current_session');
  let releaseChat!:(response:Response)=>void;
  vi.stubGlobal('fetch',vi.fn(async(path:string,init?:{body?:string;signal?:AbortSignal})=>{
    requests.push({path,body:init?.body,signal:init?.signal});
    if(path.endsWith('/selected-prepare'))return new Response(JSON.stringify(selectedStatus('current_session')));
    if(path.endsWith('/selected-chat'))return new Promise<Response>(resolve=>{releaseChat=resolve;});
    if(path==='/sessions/resume')return new Response(JSON.stringify({session:'current_session',turns:[]}));
    return new Response(JSON.stringify({configured:false,revision:'0',preferences:{}}));
  }));
  render(<App/>);
  fireEvent.click(await screen.findByRole('button',{name:'Select Frigga'}));
  await attach();
  await waitFor(()=>expect(requests.some(row=>row.path.endsWith('/selected-prepare'))).toBe(true));
  expect(JSON.parse(requests.find(row=>row.path.endsWith('/selected-prepare'))!.body!)).toMatchObject({agent:'frigga',session_id:'current_session'});
  await waitFor(()=>expect(screen.getByRole('button',{name:/TRANSMIT/}).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('button',{name:/TRANSMIT/}));
  await waitFor(()=>expect(releaseChat).toBeTruthy());
  expect(JSON.parse(requests.find(row=>row.path.endsWith('/selected-chat'))!.body!)).toMatchObject({agent:'frigga',session_id:'current_session'});
  fireEvent.click(screen.getByRole('button',{name:'Select Jarvis'}));
  expect(requests.find(row=>row.path.endsWith('/selected-chat'))?.signal?.aborted).toBe(true);
  await act(async()=>releaseChat(selectedAnswer()));
  expect(screen.queryByText('Selected image answer')).toBeNull();
});
