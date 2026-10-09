import React from 'react';
import { webcrypto } from 'node:crypto';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import App from '../app';

vi.mock('../voice',()=>({useVoice:()=>({active:false,toggle:()=>{}})}));
vi.mock('../mesh',()=>({NeuralMesh:()=>null,isExecutingAgent:()=>false}));
vi.mock('../api/loaders',()=>({loadJarvisData:async()=>({}),createLatestRefreshRunner:()=>({refresh:()=>{},stop:()=>{}})}));
vi.mock('../api/live',()=>({PREVIEW_MODE_LIVE_KEYS:{},useLiveModes:()=>({live:{}})}));
vi.mock('../analytics',()=>({initAnalytics:()=>{},trackPageview:()=>{}}));
vi.mock('../gap',()=>({FirstRunGate:()=>null}));

const id='a'.repeat(32), question='Choose the synthetic workspace';
let frames:ReadableStreamDefaultController, requests:any[], rejectAnswer:boolean, multi:boolean, batch:boolean;
const emit=(event:any)=>frames.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
beforeEach(()=>{
  vi.stubGlobal('crypto',webcrypto); localStorage.clear(); history.replaceState(null,'','/v2/chat?demo=1');
  requests=[];rejectAnswer=false;multi=false;batch=false;
  vi.stubGlobal('fetch',vi.fn(async(path,init)=>{
    requests.push({path,...init});
    if(path==='/chat/stream')return new Response(new ReadableStream({start(controller){
      frames=controller; emit({type:'start',agent:'jarvis'});
      emit({type:'clarify',id,question,choices:['Local (Recommended)','Remote'],multi_select:multi});
    }}));
    if(path===`/chat/pending/${id}/answer` || path===`/chat/pending/${'b'.repeat(32)}/answer`){
      if(rejectAnswer)return new Response(JSON.stringify({status:'invalid'}),{status:422});
      if(batch && path===`/chat/pending/${id}/answer`){
        emit({type:'clarify',id:'b'.repeat(32),question:'Second question',choices:['Keep','Change'],multi_select:false});
        await new Promise(resolve=>setTimeout(resolve,0));
        return new Response(JSON.stringify({ok:true,status:'resolved'}));
      }
      emit({type:'end',text:'Finished using the answer',agent:'jarvis'});frames.close();
      return new Response(JSON.stringify({ok:true,status:'resolved'}));
    }
    return new Response(JSON.stringify({configured:false,revision:'0',preferences:{}}));
  }));
});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});

async function ask(){
  const view=render(<App/>);
  const input=await waitFor(()=>{const el=view.container.querySelector('[data-composer="1"]');expect(el).toBeTruthy();return el;});
  fireEvent.change(input,{target:{value:'ask'}});fireEvent.keyDown(input,{key:'Enter'});
  return screen.findByRole('dialog',{name:question});
}
it('answers the live App stream through a choice without a second model request',async()=>{
  await ask();fireEvent.click(screen.getByRole('button',{name:'Remote'}));
  await screen.findByText('Finished using the answer');
  expect(requests.filter(r=>r.path==='/chat/stream')).toHaveLength(1);
  expect(JSON.parse(requests.find(r=>r.path.includes('/answer')).body)).toEqual({answer:'2'});
  expect(screen.queryByRole('dialog',{name:question})).toBeNull();
});
it('keeps the question on a rejected Other answer and permits a corrected retry',async()=>{
  rejectAnswer=true;await ask();fireEvent.click(screen.getByRole('button',{name:'Other'}));
  fireEvent.change(screen.getByRole('textbox',{name:'Your answer'}),{target:{value:'Synthetic dataset'}});
  fireEvent.click(screen.getByRole('button',{name:'Send answer'}));
  await screen.findByRole('alert');expect(screen.getByRole('dialog',{name:question})).toBeTruthy();
  rejectAnswer=false;fireEvent.click(screen.getByRole('button',{name:'Send answer'}));
  await screen.findByText('Finished using the answer');
  expect(requests.filter(r=>r.path.includes('/answer')).map(r=>JSON.parse(r.body))).toEqual([
    {answer:'Synthetic dataset',other:true},{answer:'Synthetic dataset',other:true}]);
});
it('sends multiple selected options together and cancels through the answer endpoint',async()=>{
  multi=true;await ask();fireEvent.click(screen.getByRole('button',{name:'Local (Recommended)'}));
  fireEvent.click(screen.getByRole('button',{name:'Remote'}));
  expect(requests.filter(r=>r.path.includes('/answer'))).toHaveLength(0);
  fireEvent.click(screen.getByRole('button',{name:'Send answer'}));
  await screen.findByText('Finished using the answer');
  expect(JSON.parse(requests.find(r=>r.path.includes('/answer')).body)).toEqual({answer:['1','2']});
});
it('cancels only the question and retains stream completion',async()=>{
  await ask();fireEvent.click(screen.getByRole('button',{name:'Cancel question'}));
  await screen.findByText('Finished using the answer');
  expect(JSON.parse(requests.find(r=>r.path.includes('/answer')).body)).toEqual({cancel:true});
});
it('Stop aborts the stream and removes the pending question without posting an answer',async()=>{
  await ask();fireEvent.click(screen.getByRole('button',{name:'Stop generating'}));
  await waitFor(()=>expect(screen.queryByRole('dialog',{name:question})).toBeNull());
  expect(requests.find(r=>r.path==='/chat/stream').signal.aborted).toBe(true);
  expect(requests.filter(r=>r.path.includes('/answer'))).toHaveLength(0);
});
it('retains the next batch question when the previous answer response arrives later',async()=>{
  batch=true;await ask();fireEvent.click(screen.getByRole('button',{name:'Remote'}));
  await screen.findByRole('dialog',{name:'Second question'});
  await waitFor(()=>expect(screen.getByRole('button',{name:'Keep'}).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('button',{name:'Keep'}));await screen.findByText('Finished using the answer');
  expect(requests.filter(r=>r.path.includes('/answer')).map(r=>r.path)).toEqual([
    `/chat/pending/${id}/answer`,`/chat/pending/${'b'.repeat(32)}/answer`]);
  expect(requests.filter(r=>r.path==='/chat/stream')).toHaveLength(1);
});
