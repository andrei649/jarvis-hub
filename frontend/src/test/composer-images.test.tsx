import React from 'react';
import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {InputBar} from '../cockpit';
import {describeImages} from '../vision-turn';
const t={channel:'NERVA',placeholder:'Ask Nerva',transmit:'Send'};
const status={configured:true,destination:'http://127.0.0.1:1234/v1',binding:'a'.repeat(64),review_token:'r'.repeat(43),model:'vision-test',backend:'custom',local:true,selected_turn:true,session_id:'image_session'};
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
  expect(Object.keys(submit.mock.calls[0][1]).sort()).toEqual(['agent','expected_binding','expected_destination','images','names','remote_ack','review_token','selected_turn','session_id']);
  expect(submit.mock.calls[0][1]).toMatchObject({selected_turn:true,session_id:'image_session'});
  expect(JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body))).toMatchObject({selected_turn:true});
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
it('invalidates an image review when the message changes before send',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async()=>new Response(JSON.stringify({
    ...status,local:false,destination:'https://vision.example/v1',review_token:'r'.repeat(43),
  }))));
  const submit=vi.fn();render(<InputBar onSubmit={submit} t={t} agent="jarvis"/>);
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[file()]}});
  const ack=await screen.findByRole('checkbox');
  fireEvent.click(ack);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(false));
  fireEvent.change(screen.getByPlaceholderText('Ask Nerva'),{target:{value:'What changed?'}});
  await waitFor(()=>expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false));
  expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(true);
  expect(submit).not.toHaveBeenCalled();
});
it('coalesces rapid prompt edits into one destination review',async()=>{
  render(<InputBar onSubmit={()=>{}} t={t}/>);
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[file()]}});
  await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(1));
  const input=screen.getByPlaceholderText('Ask Nerva');
  fireEvent.change(input,{target:{value:'Wh'}});
  fireEvent.change(input,{target:{value:'What'}});
  fireEvent.change(input,{target:{value:'What is this?'}});
  await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(2));
  expect(JSON.parse(String(vi.mocked(fetch).mock.calls[1][1]?.body))).toMatchObject({
    prompt:'What is this?',agent:'jarvis',
  });
});
it('shows the automatically selected image provider before remote consent',async()=>{
  const chosen={...status,backend:'openrouter',model:'vendor/vision',local:false,
    destination:'https://openrouter.ai/api/v1',selection_source:'auto:openrouter'};
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async()=>new Response(JSON.stringify(chosen))));
  render(<InputBar onSubmit={()=>{}} t={t}/>);
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[file()]}});
  expect(await screen.findByText(/Automatically selected OpenRouter/)).toBeTruthy();
  expect(screen.getByText(/vendor\/vision/)).toBeTruthy();
  expect(screen.getByText(/Send these images and the assembled conversation prompt to https:\/\/openrouter.ai\/api\/v1/)).toBeTruthy();
  expect(screen.getByText(/earlier messages, agent context and a checkpoint/)).toBeTruthy();
});
it('refuses malformed automatic selection metadata before image submission',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async()=>new Response(JSON.stringify({
    ...status,selection_source:'auto:untrusted'}))));
  const submit=vi.fn();render(<InputBar onSubmit={submit} t={t}/>);
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[file()]}});
  await screen.findByText(/Vision model unavailable/);
  expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(true);
  expect(submit).not.toHaveBeenCalled();
});

it('refuses a review that is not bound to the selected conversation session',async()=>{
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async()=>new Response(JSON.stringify({
    ...status,selected_turn:false,session_id:undefined,
  }))));
  const submit=vi.fn();render(<InputBar onSubmit={submit} t={t}/>);
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[file()]}});
  await waitFor(()=>expect(screen.getByText(/Vision model unavailable/)).toBeTruthy());
  expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(true);
  expect(submit).not.toHaveBeenCalled();
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

it('requires independent remote, training, and cost confirmations for one image turn',async()=>{
  const guarded={...status,local:false,destination:'https://vision.example/v1',selection_requirements:[
    {needs:'acknowledge_training',message:'Images may be used to train the provider model.'},
    {needs:'confirm_expensive',message:'This image model exceeds the configured cost threshold.'},
  ]};
  const requests:{url:string;init:RequestInit}[]=[];
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async(url:string,init:RequestInit)=>{
    requests.push({url,init});
    return new Response(JSON.stringify(String(url).includes('/composer/describe-prepared')
      ?{ok:true,response:'A test image.',model:guarded.model,backend:guarded.backend,destination:guarded.destination,local:false}
      :guarded));
  }));
  const submit=vi.fn();render(<InputBar onSubmit={submit} t={t}/>);
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[file()]}});
  const remote=await screen.findByRole('checkbox',{name:/leave this host/});
  const training=screen.getByRole('checkbox',{name:/Images may be used to train the provider model/});
  const cost=screen.getByRole('checkbox',{name:/exceeds the configured cost threshold/});
  expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(true);
  fireEvent.click(remote);
  fireEvent.click(training);
  expect((cost as HTMLInputElement).checked).toBe(false);
  expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(true);
  fireEvent.click(cost);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('button',{name:'Send'}));
  expect(submit.mock.calls[0][1]).toMatchObject({remote_ack:true,acknowledge_training:true,confirm_expensive:true});
  expect(Object.keys(submit.mock.calls[0][1]).sort()).toEqual(['acknowledge_training','agent','confirm_expensive','expected_binding','expected_destination','images','names','remote_ack','review_token','selected_turn','session_id']);
  const answer=await describeImages('Describe it.',submit.mock.calls[0][1],new AbortController().signal);
  expect(answer.text).toBe('A test image.');
  const request=requests.find(item=>item.url.includes('/composer/describe-prepared'));
  expect(request?.url).toContain('/api/vlm/composer/describe-prepared');
  const body=JSON.parse(String(request?.init.body));
  expect(body).toMatchObject({prompt:'Describe it.',remote_ack:true,acknowledge_training:true,confirm_expensive:true,expected_binding:guarded.binding});
  expect(Object.keys(body).sort()).toEqual(['acknowledge_training','agent','confirm_expensive','expected_binding','expected_destination','images','prompt','remote_ack','review_token','selected_turn','session_id']);
});

it('submits only the required training flag and resets it when the image set changes',async()=>{
  const guarded={...status,selection_requirements:[{needs:'acknowledge_training',message:'Provider training is possible.'}]};
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async()=>new Response(JSON.stringify(guarded))));
  const submit=vi.fn();render(<InputBar onSubmit={submit} t={t}/>);
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[file()]}});
  const training=await screen.findByRole('checkbox',{name:/Provider training is possible/});
  fireEvent.click(training);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(false));
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[file('second.png')]}});
  expect((training as HTMLInputElement).checked).toBe(false);
  expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(true);
  fireEvent.click(training);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('button',{name:'Remove second.png'}));
  expect((training as HTMLInputElement).checked).toBe(false);
  expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(true);
  fireEvent.click(training);
  fireEvent.click(screen.getByRole('button',{name:'Send'}));
  expect(submit.mock.calls[0][1]).toMatchObject({acknowledge_training:true,remote_ack:false,names:['shot.png']});
  expect(submit.mock.calls[0][1]).not.toHaveProperty('confirm_expensive');
});

it('clears training consent after send and on destination refresh with a changed binding',async()=>{
  let binding='a'.repeat(64);
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async()=>new Response(JSON.stringify({...status,binding,selection_requirements:[{needs:'acknowledge_training',message:'Training needs confirmation.'}]}))));
  const submit=vi.fn();render(<InputBar onSubmit={submit} t={t}/>);
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[file()]}});
  let training=await screen.findByRole('checkbox',{name:/Training needs confirmation/});
  fireEvent.click(training);
  fireEvent.click(screen.getByRole('button',{name:'Refresh vision destination'}));
  await waitFor(()=>expect((screen.getByRole('checkbox',{name:/Training needs confirmation/}) as HTMLInputElement).checked).toBe(false));
  training=screen.getByRole('checkbox',{name:/Training needs confirmation/});
  fireEvent.click(training);
  binding='b'.repeat(64);
  fireEvent.click(screen.getByRole('button',{name:'Refresh vision destination'}));
  await waitFor(()=>expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(true));
  training=await screen.findByRole('checkbox',{name:/Training needs confirmation/});
  expect((training as HTMLInputElement).checked).toBe(false);
  fireEvent.click(training);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(false));
  fireEvent.click(screen.getByRole('button',{name:'Send'}));
  expect(submit.mock.calls[0][1].expected_binding).toBe('b'.repeat(64));
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[file('next.png')]}});
  training=await screen.findByRole('checkbox',{name:/Training needs confirmation/});
  expect((training as HTMLInputElement).checked).toBe(false);
  expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(true);
});

it.each([
  ['unknown need',[{needs:'allow_anything',message:'Unknown.'}]],
  ['duplicate need',[{needs:'acknowledge_training',message:'First.'},{needs:'acknowledge_training',message:'Second.'}]],
  ['missing message',[{needs:'confirm_expensive'}]],
  ['blank message',[{needs:'confirm_expensive',message:'  '}]],
  ['control character',[{needs:'confirm_expensive',message:'Cost\nnotice.'}]],
  ['oversized message',[{needs:'confirm_expensive',message:'x'.repeat(501)}]],
  ['nonarray requirements',{needs:'confirm_expensive',message:'Cost.'}],
  ['null requirements',null],
])('refuses image submission with %s selection requirements',async(_label,selection_requirements)=>{
  const submit=vi.fn();
  vi.stubGlobal('fetch',vi.fn().mockImplementation(async()=>new Response(JSON.stringify({...status,selection_requirements}))));
  render(<InputBar onSubmit={submit} t={t}/>);
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[file()]}});
  await screen.findByText(/Vision model unavailable/);
  expect(screen.getByRole('button',{name:'Send'}).hasAttribute('disabled')).toBe(true);
  fireEvent.click(screen.getByRole('button',{name:'Send'}));
  expect(submit).not.toHaveBeenCalled();
});

it('forces catalog refresh only when the user refreshes the vision destination',async()=>{
  render(<InputBar onSubmit={()=>{}} t={t}/>);
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[file()]}});
  await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(1));
  expect(String(vi.mocked(fetch).mock.calls[0][0])).not.toContain('refresh_catalog');
  fireEvent.click(screen.getByRole('button',{name:'Refresh vision destination'}));
  await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(2));
  expect(String(vi.mocked(fetch).mock.calls[1][0])).toContain('refresh_catalog=true');
  fireEvent.click(screen.getByRole('button',{name:'Remove shot.png'}));
  fireEvent.change(screen.getByLabelText('Attach images'),{target:{files:[file('next.png')]}});
  await waitFor(()=>expect(fetch).toHaveBeenCalledTimes(3));
  expect(String(vi.mocked(fetch).mock.calls[2][0])).not.toContain('refresh_catalog');
});
