import React from 'react';
import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {InputBar} from '../cockpit';
const t={channel:'NERVA',placeholder:'Ask Nerva',transmit:'Send'};
const status={configured:true,destination:'http://127.0.0.1:1234/v1',binding:'a'.repeat(64),model:'vision-test',backend:'custom',local:true};
const retryNotice='May retry once with the same images and model after an empty response (at most two model calls).';
beforeEach(()=>{
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async()=>new Response(JSON.stringify(status))));
  URL.createObjectURL=vi.fn(()=> 'blob:preview');URL.revokeObjectURL=vi.fn();
});
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const file=(name='shot.png',type='image/png',size=16)=>new File([new Uint8Array(size)],name,{type,lastModified:1});
it('chooses an image with a removable preview and submits an explicit vision draft',async()=>{
  const submit=vi.fn();render(<InputBar onSubmit={submit} t={t}/>);
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[file()]}});
  await screen.findByAltText('shot.png');
  fireEvent.change(screen.getByPlaceholderText('Ask Nerva'),{target:{value:'What is shown?'}});
  await waitFor(()=>expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('button',{name:'Send'}));
  expect(submit.mock.calls[0][0]).toBe('What is shown?');
  expect(submit.mock.calls[0][1]).toMatchObject({names:['shot.png'],expected_destination:status.destination,expected_binding:status.binding});
  expect(submit.mock.calls[0][1].images[0]).toMatch(/^data:image\/png;base64,/);
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview');
});
it('preserves ordinary text submission and nonimage paste without a vision request',()=>{
  const submit=vi.fn();render(<InputBar onSubmit={submit} t={t}/>);
  const input=screen.getByPlaceholderText('Ask Nerva');
  const event=new Event('paste',{bubbles:true,cancelable:true});Object.defineProperty(event,'clipboardData',{value:{items:[],files:[]}});
  fireEvent(input,event);expect(event.defaultPrevented).toBe(false);
  fireEvent.change(input,{target:{value:' hello '}});fireEvent.click(screen.getByRole('button',{name:'Send'}));
  expect(submit).toHaveBeenCalledExactlyOnceWith('hello');expect(fetch).not.toHaveBeenCalled();
});
it('deduplicates image paste items/files and rejects nonimages and oversize files',async()=>{
  render(<InputBar onSubmit={()=>{}} t={t}/>);const image=file();
  fireEvent.paste(screen.getByPlaceholderText('Ask Nerva'),{clipboardData:{items:[{kind:'file',getAsFile:()=>image}],files:[image]}});
  expect(await screen.findAllByAltText('shot.png')).toHaveLength(1);
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[file('large.png','image/png',4*1024*1024+1),file('text.txt','text/plain')]}});
  expect(screen.getByRole('status').textContent).toContain('4 MiB');
  expect(screen.queryByAltText('text.txt')).toBeNull();
});

it('counts pending reads across drops and aborts removed and unmounted drafts',()=>{
  const readers:any[]=[];
  class Reader {
    readyState=0;result=null;onload:any;onerror:any;onabort:any;
    abort=vi.fn(()=>{this.readyState=2;});
    readAsDataURL(){this.readyState=1;}
    constructor(){readers.push(this);}
  }
  vi.stubGlobal('FileReader',Reader);
  const view=render(<InputBar onSubmit={()=>{}} t={t}/>);
  const input=screen.getByPlaceholderText('Ask Nerva');
  fireEvent.drop(input,{dataTransfer:{files:Array.from({length:6},(_,i)=>file(`${i}.png`)),items:[]}});
  fireEvent.drop(input,{dataTransfer:{files:[file('6.png'),file('7.png'),file('8.png')],items:[]}});
  expect(screen.getAllByRole('img')).toHaveLength(8);expect(readers).toHaveLength(8);
  expect(screen.getByRole('status').textContent).toContain('eight');
  const late=readers[0].onload;
  fireEvent.click(screen.getByRole('button',{name:'Remove 0.png'}));
  expect(readers[0].abort).toHaveBeenCalledOnce();
  readers[0].result='data:image/png;base64,AAAA';late();
  expect(screen.queryByAltText('0.png')).toBeNull();
  view.unmount();expect(URL.revokeObjectURL).toHaveBeenCalledTimes(8);
  expect(readers.every(reader=>reader.abort.mock.calls.length===1)).toBe(true);
});
it('requires acknowledgement of the current remote destination and resets it on refresh',async()=>{
  let destination:typeof status&{empty_retries?:number;retry_notice?:string}={...status,local:false,destination:'https://vision.example/v1'};
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async()=>new Response(JSON.stringify(destination))));
  const submit=vi.fn();render(<InputBar onSubmit={submit} t={t}/>);
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[file()]}});
  const ack=await screen.findByRole('checkbox');
  expect(screen.queryByText(retryNotice)).toBeNull();
  expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(true);
  fireEvent.click(ack);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(false));
  destination={...destination,binding:'b'.repeat(64),empty_retries:1,retry_notice:retryNotice};
  fireEvent.click(screen.getByRole('button',{name:'Refresh vision destination'}));
  const disclosure=await screen.findByText(retryNotice);
  expect(disclosure.compareDocumentPosition(screen.getByRole('checkbox'))&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false);
  expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('checkbox'));
  await waitFor(()=>expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('button',{name:'Send'}));
  expect(submit.mock.calls[0][1]).toMatchObject({expected_destination:destination.destination,expected_binding:destination.binding,remote_ack:true});
});
it('accepts a bounded retry notice with a local image submission',async()=>{
  const notice='A local model may retry once after an empty response.';
  const submit=vi.fn();
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async()=>new Response(JSON.stringify({...status,empty_retries:1,retry_notice:notice}))));
  render(<InputBar onSubmit={submit} t={t}/>);
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[file()]}});
  expect(await screen.findByText(notice)).toBeTruthy();
  expect(screen.queryByRole('checkbox')).toBeNull();
  await waitFor(()=>expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('button',{name:'Send'}));
  expect(submit.mock.calls[0][1]).toMatchObject({expected_binding:status.binding,remote_ack:false});
});
it.each([
  ['missing notice',{empty_retries:1}],
  ['notice without budget',{retry_notice:retryNotice}],
  ['explicit zero budget',{empty_retries:0}],
  ['out-of-range budget',{empty_retries:2,retry_notice:retryNotice}],
  ['wrong budget type',{empty_retries:'1',retry_notice:retryNotice}],
  ['blank notice',{empty_retries:1,retry_notice:'   '}],
  ['control character',{empty_retries:1,retry_notice:'Retry once.\u0007'}],
  ['oversized notice',{empty_retries:1,retry_notice:'x'.repeat(501)}],
])('refuses image submission with %s metadata',async(_label,metadata)=>{
  const submit=vi.fn();
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async()=>new Response(JSON.stringify({...status,...metadata}))));
  render(<InputBar onSubmit={submit} t={t}/>);
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[file()]}});
  fireEvent.change(screen.getByPlaceholderText('Ask Nerva'),{target:{value:'What is shown?'}});
  await screen.findByText(/Vision model unavailable/);
  expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button',{name:'Send'}));
  expect(submit).not.toHaveBeenCalled();
});
it('shows a remote policy warning without replacing the current destination checkbox',async()=>{
  const warning='Images and prompts may be used for training.';
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async()=>new Response(JSON.stringify({...status,local:false,warning,data_policy:'unknown'}))));
  render(<InputBar onSubmit={()=>{}} t={t}/>);
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[file()]}});
  expect(await screen.findByText(warning)).toBeTruthy();
  expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('checkbox'));
  await waitFor(()=>expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(false));
  expect(screen.getByText(warning)).toBeTruthy();
});
