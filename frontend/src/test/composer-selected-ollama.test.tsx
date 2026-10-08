import React from 'react';
import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {InputBar} from '../cockpit';
import {describeImages} from '../vision-turn';

const t={channel:'NERVA',placeholder:'Ask Nerva',transmit:'Send'};
const token='review-token-'.repeat(4);
const active='active-handle-'.repeat(3);
let requests:{path:string;body?:string}[]=[];

beforeEach(()=>{
  requests=[];
  vi.stubGlobal('crypto',{subtle:{digest:async()=>new Uint8Array(32).buffer}});
  vi.stubGlobal('fetch',vi.fn(async(path:string,init?:{body?:string})=>{
    requests.push({path,body:init?.body});
    if(path.includes('/active-images'))return new Response(JSON.stringify({session_id:'selected_s',images:[{handle:active,count:1,question:'Earlier question'}]}));
    if(path.endsWith('/selected-prepare'))return new Response(JSON.stringify({configured:true,review_token:token,session_id:'selected_s',destination:'http://127.0.0.1:11434',model:'vision-model',backend:'ollama',local:true}));
    return new Response('{}',{status:404});
  }));
  URL.createObjectURL=vi.fn(()=> 'blob:image');URL.revokeObjectURL=vi.fn();
});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});

it('reviews the selected agent, session, question and exact image digest before submission',async()=>{
  const submit=vi.fn();render(<InputBar onSubmit={submit} t={t} agent="jarvis" sessionId="selected_s" selectedTurn/>);
  fireEvent.change(screen.getByPlaceholderText('Ask Nerva'),{target:{value:'What is shown?'}});
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[new File(['image'],'shot.png',{type:'image/png'})]}});
  await waitFor(()=>expect(requests.some(row=>row.path.endsWith('/selected-prepare'))).toBe(true));
  const review=requests.find(row=>row.path.endsWith('/selected-prepare'))!;
  expect(JSON.parse(review.body!)).toMatchObject({prompt:'What is shown?',agent:'jarvis',session_id:'selected_s',image_digests:['00'.repeat(32)]});
  await waitFor(()=>expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('button',{name:'Send'}));
  expect(submit.mock.calls[0][1]).toMatchObject({agent:'jarvis',session_id:'selected_s',review_token:token,expected_binding:token,remote_ack:false});
});

it('requires a fresh selected review for a previous image',async()=>{
  const submit=vi.fn();render(<InputBar onSubmit={submit} t={t} agent="jarvis" sessionId="selected_s" selectedTurn/>);
  fireEvent.click(screen.getByRole('button',{name:'Use previous image'}));
  fireEvent.click(await screen.findByLabelText(/Earlier question/));
  await waitFor(()=>expect(requests.some(row=>row.path.endsWith('/selected-prepare'))).toBe(true));
  const review=requests.find(row=>row.path.endsWith('/selected-prepare'))!;
  expect(JSON.parse(review.body!)).toMatchObject({session_id:'selected_s',active_image_handles:[active],image_digests:[]});
  await waitFor(()=>expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('button',{name:'Send'}));
  expect(submit.mock.calls[0][1].active_image_handles).toEqual([active]);
});

it('waits for the selected conversation instead of falling back to legacy vision',async()=>{
  render(<InputBar onSubmit={vi.fn()} t={t} agent="jarvis" selectedTurn/>);
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[new File(['image'],'shot.png',{type:'image/png'})]}});
  expect(await screen.findByText('Selecting conversation…')).toBeTruthy();
  expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(true);
  expect(requests).toEqual([]);
});

it('sends a reviewed selected draft to the committed chat route',async()=>{
  vi.stubGlobal('fetch',vi.fn(async(path:string,init?:{body?:string})=>{
    requests.push({path,body:init?.body});
    return new Response(JSON.stringify({ok:true,committed:true,response:'A blue square.',
      model:'vision-model',backend:'ollama',destination:'http://127.0.0.1:11434',local:true}));
  }));
  const result=await describeImages('What is shown?',{
    images:['data:image/png;base64,AAAA'],names:['shot.png'],expected_destination:'http://127.0.0.1:11434',
    expected_binding:token,remote_ack:false,review_token:token,agent:'jarvis',session_id:'selected_s',
    active_image_handles:[],
  },new AbortController().signal);
  expect(result.text).toBe('A blue square.');
  expect(requests[0].path).toContain('/selected-chat');
  expect(JSON.parse(requests[0].body!)).not.toHaveProperty('names');
});
