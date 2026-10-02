import {afterEach,expect,it,vi} from 'vitest';
import {describeImages,restoreVisionTurn} from '../vision-turn';
import type {VisionDraft} from '../composer-images';

const draft:VisionDraft={images:['data:image/png;base64,aGVsbG8='],names:['a.png'],
  expected_destination:'https://api.x.ai/v1',expected_binding:'a'.repeat(64),
  review_token:'r'.repeat(43),agent:'jarvis',session_id:'image_session',
  selected_turn:true,selected_main:true,remote_ack:true};

afterEach(()=>vi.unstubAllGlobals());

it('sends a selected main image to the committed conversation route',async()=>{
  const requests:any[]=[];
  vi.stubGlobal('fetch',vi.fn(async(url,options)=>{
    requests.push({url,options});
    return new Response(JSON.stringify({ok:true,committed:true,response:'A blue square.',
      model:'grok-4.6',backend:'xai',destination:'https://api.x.ai/v1',local:false}));
  }));
  const result=await describeImages('What is here?',draft,new AbortController().signal);
  expect(result.text).toBe('A blue square.');
  expect(requests).toHaveLength(1);
  expect(String(requests[0].url)).toContain('/api/vlm/composer/chat-prepared');
  expect(JSON.parse(requests[0].options.body)).not.toHaveProperty('selected_main');
});

it('sends an explicit history-only follow-up through the committed route',async()=>{
  const requests:any[]=[];
  vi.stubGlobal('fetch',vi.fn(async(url,options)=>{
    requests.push({url,options});
    return new Response(JSON.stringify({ok:true,committed:true,response:'Brass.',
      model:'grok-4.6',backend:'xai',destination:'https://api.x.ai/v1',local:false}));
  }));
  const selected:VisionDraft={...draft,images:[],names:['Previous: door'],active_image_handles:['h'.repeat(32)]};
  const result=await describeImages('What is its handle made of?',selected,new AbortController().signal);
  expect(result.text).toBe('Brass.');
  expect(JSON.parse(requests[0].options.body)).toMatchObject({images:[],
    active_image_handles:['h'.repeat(32)]});
  expect(JSON.parse(requests[0].options.body)).not.toHaveProperty('names');
});

it('refuses a history draft without a selected main route before transport',async()=>{
  const sent=vi.fn();vi.stubGlobal('fetch',sent);
  const unselected:VisionDraft={...draft,selected_main:undefined,images:[],
    active_image_handles:['h'.repeat(32)]};
  await expect(describeImages('Follow up',unselected,new AbortController().signal))
    .rejects.toThrow('selected main');
  expect(sent).not.toHaveBeenCalled();
});

it('refuses to render a selected main answer without a server commit',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({ok:true,response:'Uncommitted.',
    model:'grok-4.6',backend:'xai',destination:'https://api.x.ai/v1',local:false}))));
  await expect(describeImages('What is here?',draft,new AbortController().signal))
    .rejects.toThrow('Invalid vision response');
});

it('rehydrates only validated assistant image provenance',()=>{
  const media={kind:'image',count:1,model:'grok-4.6',backend:'xai',local:false};
  expect(restoreVisionTurn({role:'assistant',content:'A blue square.',media},'12:00')).toEqual({
    role:'vision',text:'A blue square.',model:'grok-4.6',backend:'xai',
    destination:'',local:false,ts:'12:00',
  });
  expect(restoreVisionTurn({role:'user',content:'Question',media},'12:00')).toBeNull();
  expect(restoreVisionTurn({role:'assistant',content:'No proof',media:{...media,local:'false'}},'12:00')).toBeNull();
});
