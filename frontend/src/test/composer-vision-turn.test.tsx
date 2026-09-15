import React from 'react';
import {render,screen,fireEvent,waitFor,act,cleanup} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import App from '../app';
let submit:any;
vi.mock('../voice',()=>({useVoice:()=>({active:false,toggle:()=>{}})}));
vi.mock('../mesh',()=>({NeuralMesh:()=>null,isExecutingAgent:()=>false}));
vi.mock('../api/loaders',()=>({loadJarvisData:async()=>({}),createLatestRefreshRunner:()=>({refresh:()=>{},stop:()=>{}})}));
vi.mock('../api/live',()=>({PREVIEW_MODE_LIVE_KEYS:{},useLiveModes:()=>({live:{}})}));
vi.mock('../analytics',()=>({initAnalytics:()=>{},trackPageview:()=>{}}));
vi.mock('../gap',()=>({FirstRunGate:()=>null}));
vi.mock('../modes3',async()=>{const {Conversation,InputBar}=await import('../cockpit');return {ChatMode:(props:any)=>{submit=props.onSubmit;return <><Conversation {...props}/><InputBar onSubmit={props.onSubmit} t={props.t}/></>;}};});
const status={configured:true,destination:'http://127.0.0.1:1234/v1',binding:'a'.repeat(64),model:'vision-test',backend:'custom',local:true};
const draft={images:['data:image/png;base64,iVBORw0KGgo='],names:['shot.png'],expected_destination:status.destination,expected_binding:status.binding,remote_ack:false};
const answer=()=>new Response(JSON.stringify({ok:true,response:'A blue square.',model:'vision-test',backend:'custom',destination:status.destination,local:true}));
let resolveVision:(r:Response)=>void;let requests:any[]=[];
beforeEach(()=>{
  localStorage.clear();history.replaceState(null,'','/v2/chat?demo=1');requests=[];
  URL.createObjectURL=vi.fn(()=> 'blob:image');URL.revokeObjectURL=vi.fn();
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async(path,init)=>{
    requests.push({path,...init});
    if(path.endsWith('/composer/status'))return new Response(JSON.stringify(status));
    if(path.endsWith('/composer/describe'))return new Promise<Response>(resolve=>resolveVision=resolve);
    if(path==='/chat/stream')return new Response('data: {"type":"start","agent":"jarvis"}\n\ndata: {"type":"end","text":"Text answer","agent":"jarvis"}\n\n');
    return new Response(JSON.stringify({configured:false,revision:'0',preferences:{}}));
  }));
});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const mount=async()=>{submit=undefined;render(<App/>);await screen.findByLabelText('Attach images');};
it('sends a vision turn from the actual shared input and labels actual provenance',async()=>{
  await mount();
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[new File(['image'],'shot.png',{type:'image/png'})]}});
  const send=screen.getByRole('button',{name:/TRANSMIT/});
  await waitFor(()=>expect(send.hasAttribute('disabled')).toBe(false));fireEvent.click(send);
  await waitFor(()=>expect(requests.some(r=>r.path.endsWith('/composer/describe'))).toBe(true));
  const request=requests.find(r=>r.path.endsWith('/composer/describe'));
  expect(JSON.parse(request.body)).toMatchObject({prompt:'Describe these images.',expected_binding:status.binding});
  expect(JSON.parse(request.body)).not.toHaveProperty('names');
  await act(async()=>resolveVision(answer()));
  await screen.findByText('A blue square.');await screen.findByText(/VISION ANALYSIS/);
  expect(screen.getByText(/vision-test/)).toBeTruthy();
  expect(requests.some(r=>r.path==='/chat/stream')).toBe(false);
});
it('owns one turn synchronously across image and text submissions',async()=>{
  await mount();
  act(()=>{submit('image question',draft);submit('second text');submit('second image',draft);});
  await waitFor(()=>expect(requests.filter(r=>r.path.endsWith('/composer/describe'))).toHaveLength(1));
  expect(requests.some(r=>r.path==='/chat/stream')).toBe(false);
  await act(async()=>resolveVision(answer()));
  act(()=>submit('normal text'));
  await screen.findByText('Text answer');
  expect(JSON.parse(requests.find(r=>r.path==='/chat/stream').body)).toEqual({message:'normal text',agent:'jarvis'});
});
it('stops a vision turn and ignores a late response even if transport ignores abort',async()=>{
  await mount();act(()=>submit('question',draft));
  await waitFor(()=>expect(resolveVision).toBeTruthy());
  fireEvent.click(screen.getByRole('button',{name:'Stop generating'}));
  expect(requests.find(r=>r.path.endsWith('/composer/describe')).signal.aborted).toBe(true);
  await act(async()=>resolveVision(answer()));
  expect(screen.queryByText('A blue square.')).toBeNull();
});
it('renders a structured vision failure without invented agent provenance',async()=>{
  await mount();act(()=>submit('question',draft));
  await act(async()=>resolveVision(new Response(JSON.stringify({error:'Vision destination changed; review it again',reason:'vlm_destination_changed'}),{status:409})));
  await screen.findByText(/Vision destination changed/);
  expect(screen.queryByText('A blue square.')).toBeNull();
});

it('aborts an owned image turn on unmount',async()=>{
  const view=render(<App/>);await screen.findByLabelText('Attach images');
  act(()=>submit('question',draft));
  const request=requests.find(r=>r.path.endsWith('/composer/describe'));
  view.unmount();expect(request.signal.aborted).toBe(true);
  await act(async()=>resolveVision(answer()));
});
