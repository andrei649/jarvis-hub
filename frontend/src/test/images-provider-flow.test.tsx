import React from 'react';
import { beforeEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ImagesPanel } from '../panels/images';
import { imageStatus, proposeCloudImage, proposeKreaResume, proposeKreaEnhance, proposeDeepInfraRefresh, imageTask, imageBlob } from '../api/images';

const id = 'a'.repeat(32);
const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { 'Content-Type': 'application/json' },
});
const capability = (edit: boolean, max: number, kind = 'artifact_id') => ({
  edit, max_reference_images: max, reference_kind: kind,
});
const provider = (model: string, extra = {}) => ({
  configured: true, enabled: true, default_model: model, models: [model],
  reachable: null, reason: 'configured', model_capabilities: { [model]: capability(true, 16) }, ...extra,
});
const providers = {
  openai: provider('gpt-image-1.5', {
    models: ['gpt-image-1.5', 'gpt-image-2-low', 'gpt-image-2-medium', 'gpt-image-2-high'],
    model_capabilities: {
      'gpt-image-1.5': capability(false, 0),
      'gpt-image-2-low': capability(true, 16),
      'gpt-image-2-medium': capability(true, 16),
      'gpt-image-2-high': capability(true, 16),
    },
  }),
  'openai-codex': provider('gpt-image-2-medium'),
  fal: provider('fal-ai/flux-2/klein/9b', {
    models: ['fal-ai/flux-2/klein/9b', 'fal-ai/z-image/turbo'],
    model_capabilities: {
      'fal-ai/flux-2/klein/9b': capability(true, 9, 'fal_media_url'),
      'fal-ai/z-image/turbo': capability(false, 0, 'fal_media_url'),
    },
  }),
};
const extendedProviders = {
  ...providers,
  openrouter: provider('openai/gpt-5.4-image-2', {
    models: ['openai/gpt-5.4-image-2', 'openai/gpt-image-2'],
    model_capabilities: {
      'openai/gpt-5.4-image-2': capability(true, 3),
      'openai/gpt-image-2': capability(true, 16),
    },
  }),
  krea: provider('krea-2-medium', {
    models: ['krea-2-medium', 'krea-2-large', 'krea-2-medium-turbo'],
    model_capabilities: {
      'krea-2-medium': { ...capability(false, 0, 'style_url'), style_guided: true, max_style_references: 10 },
      'krea-2-large': { ...capability(false, 0, 'style_url'), style_guided: true, max_style_references: 10 },
      'krea-2-medium-turbo': { ...capability(false, 0, 'style_url'), style_guided: true, max_style_references: 10 },
    },
  }),
};
const nextProviders = {
  ...extendedProviders,
  xai: provider('grok-imagine-image', {models:['grok-imagine-image','grok-imagine-image-2.0','grok-imagine-image-quality'], model_capabilities:{
    'grok-imagine-image': capability(true,3), 'grok-imagine-image-2.0':capability(true,5),
    'grok-imagine-image-quality':capability(true,3),
  }}),
  deepinfra: provider('black-forest-labs/FLUX-1-schnell', {models:['black-forest-labs/FLUX-1-schnell'],
    model_capabilities:{'black-forest-labs/FLUX-1-schnell':capability(false,0)}, catalog_refresh_available:true}),
};
const status = (rows: Record<string,any> = providers) => ({
  local_image: { configured: false, local: true, approval_required: true, edit: false },
  cloud_image: { local: false, approval_required: true, providers: rows },
});
function transport(rows: Record<string,any> = providers) {
  vi.mocked(fetch).mockImplementation(async (url, options) => {
    if (url === '/api/media') return reply(status(rows));
    if (url === '/api/media/generate' && options?.method === 'POST') {
      return reply({ reason: 'approval_required', task_id: 17 }, 202);
    }
    if (url === '/api/media/generation-tasks/17') {
      return reply({ task_id: 17, state: 'awaiting_approval', artifact: null });
    }
    throw new Error('unexpected request');
  });
}
const posts = () => vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === 'POST');
async function selectCloud(backend: string) {
  render(<ImagesPanel />);
  await screen.findByRole('option', { name: 'Cloud image providers' });
  fireEvent.change(screen.getByLabelText('Image provider'), { target: { value: 'cloud' } });
  fireEvent.change(screen.getByLabelText('Cloud image provider'), { target: { value: backend } });
  fireEvent.change(screen.getByLabelText('Image prompt'), { target: { value: ' exact image prompt ' } });
}
beforeEach(() => {
  localStorage.clear();
  history.replaceState(null, '', '/');
  window.__NERVA_BASE_PATH__ = '';
  vi.stubGlobal('fetch', vi.fn());
  transport();
});

it('reads all offered providers without a legacy cloud status or local generator', async () => {
  const result = await imageStatus();
  expect((result as any).cloudProviders.map((p: any) => p.id)).toEqual(['openai', 'openai-codex', 'fal']);
  expect((result as any).cloudProviders[2].model_capabilities['fal-ai/flux-2/klein/9b'])
    .toEqual(capability(true, 9, 'fal_media_url'));
  expect(result.configured).toBe(false);
  expect(fetch).toHaveBeenCalledOnce();
});

it('reads OpenRouter edit caps and Krea style-guided caps without treating Krea as image editing', async () => {
  transport(extendedProviders);
  const result = await imageStatus();
  const rows = result.cloudProviders!;
  expect(rows.map(p => p.id)).toEqual(['openai', 'openai-codex', 'fal', 'openrouter', 'krea']);
  expect(rows.find(p => p.id === 'openrouter')!.model_capabilities['openai/gpt-image-2'])
    .toEqual(capability(true, 16));
  expect(rows.find(p => p.id === 'krea')!.model_capabilities['krea-2-medium'])
    .toEqual({ ...capability(false, 0, 'style_url'), style_guided: true, max_style_references: 10 });
});

it('keeps DeepInfra visible before catalog refresh and parses a bounded dynamic catalog', async () => {
  const unavailable = { ...nextProviders, deepinfra: {enabled:true, configured:false, reachable:null,
    models:[], default_model:'', reason:'catalog_unavailable', catalog_refresh_available:true, model_capabilities:{}} };
  transport(unavailable);
  const status = await imageStatus();
  expect(status.cloudProviders?.find(row=>row.id==='deepinfra')).toMatchObject({models:[],default_model:'',configured:false,catalog_refresh_available:true});
  const models = Array.from({length:512},(_,i)=>`owner/model-${i}`);
  transport({...nextProviders, deepinfra:provider(models[0],{models, catalog_refresh_available:true,
    model_capabilities:Object.fromEntries(models.map(m=>[m,capability(false,0)]))})});
  const catalog = await imageStatus();
  expect(catalog.cloudProviders?.find(row=>row.id==='deepinfra')?.models).toHaveLength(512);
  const longModel = 'a'.repeat(128) + '/' + 'b'.repeat(127);
  await expect(proposeCloudImage('prompt',{backend:'deepinfra',model:longModel,size:'1024x1024'})).resolves.toBe(17);
  expect(JSON.parse(posts()[0][1].body as string).model).toBe(longModel);
  vi.mocked(fetch).mockClear();
  await expect(proposeCloudImage('prompt',{backend:'deepinfra',model:longModel+'b',size:'1024x1024'})).rejects.toMatchObject({code:'refused'});
  expect(fetch).not.toHaveBeenCalled();
});

it('submits xAI 2.0 quality and resolution only for that model and rejects unsupported knobs', async () => {
  transport(nextProviders);
  await selectCloud('xai');
  expect(screen.queryByLabelText('xAI quality')).toBeNull();
  fireEvent.change(screen.getByLabelText('Cloud image model'),{target:{value:'grok-imagine-image-2.0'}});
  fireEvent.change(screen.getByLabelText('xAI quality'),{target:{value:'medium'}});
  fireEvent.change(screen.getByLabelText('xAI resolution'),{target:{value:'2k'}});
  fireEvent.click(screen.getByRole('button',{name:'Propose image'}));
  await waitFor(()=>expect(posts()).toHaveLength(1));
  expect(JSON.parse(posts()[0][1].body as string)).toMatchObject({backend:'xai',model:'grok-imagine-image-2.0',quality:'medium',resolution:'2k'});
  vi.mocked(fetch).mockClear();
  for (const options of [
    {backend:'xai',model:'grok-imagine-image',size:'1024x1024',quality:'low'},
    {backend:'xai',model:'grok-imagine-image-2.0',size:'1024x1024',resolution:'4k'},
    {backend:'xai',model:'grok-imagine-image',size:'1024x1024',references:Array(4).fill(id)},
    {backend:'deepinfra',model:'owner/model',size:'1024x1024',references:[id]},
  ]) await expect(proposeCloudImage('prompt',options as any)).rejects.toMatchObject({code:'refused'});
  expect(fetch).not.toHaveBeenCalled();
});

it('queues exact Krea continuation and DeepInfra refresh operations once and reads resume capability', async () => {
  await expect(proposeKreaResume(17)).resolves.toBe(17);
  await expect(proposeDeepInfraRefresh()).resolves.toBe(17);
  expect(posts().map(([,options])=>JSON.parse(options!.body as string))).toEqual([
    {kind:'image',cloud:true,backend:'krea',prompt:'',resume_task_id:17},
    {kind:'image',cloud:true,backend:'deepinfra',prompt:'',refresh_catalog:true},
  ]);
  vi.mocked(fetch).mockClear();
  await expect(proposeKreaResume(0)).rejects.toMatchObject({code:'refused'});
  expect(fetch).not.toHaveBeenCalled();
  vi.mocked(fetch).mockImplementation(async url => url==='/api/media/generation-tasks/17'
    ? reply({task_id:17,state:'uncertain',artifact:null,resume_available:true}) : reply({}));
  expect(await imageTask(17)).toMatchObject({resume_available:true});
});

it('proposes Krea Enhance only for a positive source task and reads its advertised availability', async () => {
  await expect(proposeKreaEnhance(17)).resolves.toBe(17);
  expect(JSON.parse(posts()[0][1].body as string)).toEqual({
    kind:'image',cloud:true,backend:'krea',prompt:'',enhance_task_id:17,
  });
  vi.mocked(fetch).mockClear();
  await expect(proposeKreaEnhance(0)).rejects.toMatchObject({code:'refused'});
  expect(fetch).not.toHaveBeenCalled();
  vi.mocked(fetch).mockImplementation(async url => url==='/api/media/generation-tasks/17'
    ? reply({task_id:17,state:'ready',artifact:{id,bytes:8,width:512,height:512},enhance_available:true}) : reply({}));
  expect(await imageTask(17)).toMatchObject({enhance_available:true});
});

it('accepts a measured 4096px ready artifact and bounded PNG bytes from the approved task reader',async()=>{
  const png=new Uint8Array([137,80,78,71,13,10,26,10]);
  vi.mocked(fetch).mockImplementation(async url=>{
    if(url==='/api/media/generation-tasks/17') return reply({task_id:17,state:'ready',artifact:{id,bytes:8,width:4096,height:2048}});
    if(url==='/api/media/generated/'+id) return new Response(png,{status:200,headers:{'Content-Type':'image/png'}});
    throw new Error('unexpected request');
  });
  const task=await imageTask(17);
  expect(task.artifact).toMatchObject({width:4096,height:2048});
  expect(task.enhance_available).toBe(false);
  expect((await imageBlob(task.artifact!)).size).toBe(8);
});

it('keeps the original Krea image visible while watching one separately approved Enhance task',async()=>{
  history.replaceState(null,'','/?image_task=17');
  URL.createObjectURL=vi.fn().mockReturnValue('blob:original-krea');
  URL.revokeObjectURL=vi.fn();
  const png=new Uint8Array([137,80,78,71,13,10,26,10]);
  vi.mocked(fetch).mockImplementation(async (url,options)=>{
    if(url==='/api/media') return reply(status(nextProviders));
    if(url==='/api/media/generation-tasks/17') return reply({task_id:17,state:'ready',artifact:{id,bytes:8,width:512,height:512},enhance_available:true});
    if(url==='/api/media/generated/'+id) return new Response(png,{status:200,headers:{'Content-Type':'image/png'}});
    if(url==='/api/media/generation-tasks/18') return reply({task_id:18,state:'awaiting_approval',artifact:null});
    if(url==='/api/media/generate'&&options?.method==='POST') return reply({reason:'approval_required',task_id:18},202);
    throw new Error('unexpected request');
  });
  render(<ImagesPanel/>);
  const original=await screen.findByRole('img',{name:'Generated image'});
  expect(original.getAttribute('src')).toBe('blob:original-krea');
  fireEvent.click(screen.getByRole('button',{name:'Propose Enhance 2×'}));
  await screen.findByText('Task 18');
  expect(posts()).toHaveLength(1);
  expect(JSON.parse(posts()[0][1].body as string)).toEqual({kind:'image',cloud:true,backend:'krea',prompt:'',enhance_task_id:17});
  expect(screen.getByRole('img',{name:'Original image'}).getAttribute('src')).toBe('blob:original-krea');
  expect(URL.revokeObjectURL).not.toHaveBeenCalledWith('blob:original-krea');
  expect(screen.queryByRole('button',{name:'Propose Enhance 2×'})).toBeNull();
});

it('holds an ambiguous Enhance proposal at one POST without replaying it on status refresh',async()=>{
  history.replaceState(null,'','/?image_task=17');
  URL.createObjectURL=vi.fn().mockReturnValue('blob:ambiguous-source');
  URL.revokeObjectURL=vi.fn();
  const png=new Uint8Array([137,80,78,71,13,10,26,10]);
  vi.mocked(fetch).mockImplementation(async (url,options)=>{
    if(url==='/api/media') return reply(status(nextProviders));
    if(url==='/api/media/generation-tasks/17') return reply({task_id:17,state:'ready',artifact:{id,bytes:8,width:512,height:512},enhance_available:true});
    if(url==='/api/media/generated/'+id) return new Response(png,{status:200,headers:{'Content-Type':'image/png'}});
    if(url==='/api/media/generate'&&options?.method==='POST') throw new TypeError('lost POST response');
    throw new Error('unexpected request');
  });
  render(<ImagesPanel/>);
  fireEvent.click(await screen.findByRole('button',{name:'Propose Enhance 2×'}));
  await screen.findByText(/Enhance response lost or unclear/);
  fireEvent.click(screen.getByRole('button',{name:'Check status'}));
  await screen.findByRole('img',{name:'Generated image'});
  expect(posts()).toHaveLength(1);
  expect(screen.queryByRole('button',{name:'Propose Enhance 2×'})).toBeNull();
  expect(screen.getByRole('img',{name:'Generated image'}).getAttribute('src')).toBe('blob:ambiguous-source');
});

it('keeps the source through Enhance completion and releases both previews on reset',async()=>{
  history.replaceState(null,'','/?image_task=17');
  URL.createObjectURL=vi.fn().mockReturnValueOnce('blob:source').mockReturnValueOnce('blob:enhanced');
  URL.revokeObjectURL=vi.fn();
  const outputId='b'.repeat(32);
  const png=new Uint8Array([137,80,78,71,13,10,26,10]);
  let outputReady=false;
  vi.mocked(fetch).mockImplementation(async (url,options)=>{
    if(url==='/api/media') return reply(status(nextProviders));
    if(url==='/api/media/generation-tasks/17') return reply({task_id:17,state:'ready',artifact:{id,bytes:8,width:512,height:512},enhance_available:true});
    if(url==='/api/media/generation-tasks/18') return reply(outputReady
      ? {task_id:18,state:'ready',artifact:{id:outputId,bytes:8,width:2048,height:2048},enhance_available:false}
      : {task_id:18,state:'awaiting_approval',artifact:null});
    if(url==='/api/media/generated/'+id || url==='/api/media/generated/'+outputId)
      return new Response(png,{status:200,headers:{'Content-Type':'image/png'}});
    if(url==='/api/media/generate'&&options?.method==='POST') return reply({reason:'approval_required',task_id:18},202);
    throw new Error('unexpected request');
  });
  render(<ImagesPanel/>);
  fireEvent.click(await screen.findByRole('button',{name:'Propose Enhance 2×'}));
  await screen.findByText('Task 18');
  outputReady=true;
  fireEvent.click(screen.getByRole('button',{name:'Check status'}));
  await waitFor(()=>expect(screen.getByRole('img',{name:'Generated image'}).getAttribute('src')).toBe('blob:enhanced'));
  expect(screen.getByRole('img',{name:'Original image'}).getAttribute('src')).toBe('blob:source');
  expect(URL.revokeObjectURL).not.toHaveBeenCalledWith('blob:source');
  fireEvent.click(screen.getByRole('button',{name:'New proposal'}));
  expect(screen.queryByRole('img',{name:'Original image'})).toBeNull();
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:source');
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:enhanced');
});

it('releases the held original preview when unmounting during Enhance watch',async()=>{
  history.replaceState(null,'','/?image_task=17');
  URL.createObjectURL=vi.fn().mockReturnValue('blob:held-source');
  URL.revokeObjectURL=vi.fn();
  const png=new Uint8Array([137,80,78,71,13,10,26,10]);
  vi.mocked(fetch).mockImplementation(async (url,options)=>{
    if(url==='/api/media') return reply(status(nextProviders));
    if(url==='/api/media/generation-tasks/17') return reply({task_id:17,state:'ready',artifact:{id,bytes:8,width:512,height:512},enhance_available:true});
    if(url==='/api/media/generated/'+id) return new Response(png,{status:200,headers:{'Content-Type':'image/png'}});
    if(url==='/api/media/generation-tasks/18') return reply({task_id:18,state:'awaiting_approval',artifact:null});
    if(url==='/api/media/generate'&&options?.method==='POST') return reply({reason:'approval_required',task_id:18},202);
    throw new Error('unexpected request');
  });
  const view=render(<ImagesPanel/>);
  fireEvent.click(await screen.findByRole('button',{name:'Propose Enhance 2×'}));
  await screen.findByRole('img',{name:'Original image'});
  view.unmount();
  expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:held-source');
});

it('keeps the source through a separate saved-job continuation proposal for Enhance',async()=>{
  history.replaceState(null,'','/?image_task=17');
  URL.createObjectURL=vi.fn().mockReturnValue('blob:resume-source');
  URL.revokeObjectURL=vi.fn();
  const png=new Uint8Array([137,80,78,71,13,10,26,10]);
  vi.mocked(fetch).mockImplementation(async (url,options)=>{
    if(url==='/api/media') return reply(status(nextProviders));
    if(url==='/api/media/generation-tasks/17') return reply({task_id:17,state:'ready',artifact:{id,bytes:8,width:512,height:512},enhance_available:true});
    if(url==='/api/media/generated/'+id) return new Response(png,{status:200,headers:{'Content-Type':'image/png'}});
    if(url==='/api/media/generation-tasks/18') return reply({task_id:18,state:'uncertain',artifact:null,resume_available:true});
    if(url==='/api/media/generation-tasks/19') return reply({task_id:19,state:'awaiting_approval',artifact:null});
    if(url==='/api/media/generate'&&options?.method==='POST') {
      const body=JSON.parse(options.body as string);
      return reply({reason:'approval_required',task_id:body.enhance_task_id ? 18 : 19},202);
    }
    throw new Error('unexpected request');
  });
  render(<ImagesPanel/>);
  fireEvent.click(await screen.findByRole('button',{name:'Propose Enhance 2×'}));
  fireEvent.click(await screen.findByRole('button',{name:'Resume saved job'}));
  await screen.findByText('Task 19');
  expect(posts().map(([,options])=>JSON.parse(options!.body as string))).toEqual([
    {kind:'image',cloud:true,backend:'krea',prompt:'',enhance_task_id:17},
    {kind:'image',cloud:true,backend:'krea',prompt:'',resume_task_id:18},
  ]);
  expect(screen.getByRole('img',{name:'Original image'}).getAttribute('src')).toBe('blob:resume-source');
  expect(URL.revokeObjectURL).not.toHaveBeenCalledWith('blob:resume-source');
});

it('offers DeepInfra catalog refresh without an image model and never watches the refresh task as an image',async()=>{
  transport({...nextProviders, deepinfra:{enabled:true,configured:false,reachable:null,models:[],default_model:'',
    reason:'catalog_unavailable',catalog_refresh_available:true,model_capabilities:{}}});
  await selectCloud('deepinfra');
  expect(screen.queryByLabelText('Cloud image model')).toBeNull();
  expect((screen.getByRole('button',{name:'Propose image'}) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button',{name:'Refresh DeepInfra catalog for approval'}));
  await screen.findByText(/Catalog refresh task 17/);
  expect(posts()).toHaveLength(1);
  expect(JSON.parse(posts()[0][1].body as string)).toEqual({kind:'image',cloud:true,backend:'deepinfra',prompt:'',refresh_catalog:true});
  expect(screen.queryByRole('button',{name:'Watch existing task'})).toBeTruthy();
  expect(screen.queryByText('Task 17')).toBeNull();
  expect((screen.getByRole('button',{name:'Refresh DeepInfra catalog for approval'}) as HTMLButtonElement).disabled).toBe(true);
});

it('queues one Krea saved-job continuation only when the task advertises it',async()=>{
  history.replaceState(null,'','/?image_task=17');
  vi.mocked(fetch).mockImplementation(async (url,options)=>{
    if(url==='/api/media') return reply(status(nextProviders));
    if(url==='/api/media/generation-tasks/17') return reply({task_id:17,state:'uncertain',artifact:null,resume_available:true});
    if(url==='/api/media/generation-tasks/18') return reply({task_id:18,state:'awaiting_approval',artifact:null});
    if(url==='/api/media/generate'&&options?.method==='POST') return reply({reason:'approval_required',task_id:18},202);
    throw new Error('unexpected request');
  });
  render(<ImagesPanel/>);
  await screen.findByRole('button',{name:'Resume saved job'});
  fireEvent.click(screen.getByRole('button',{name:'Resume saved job'}));
  await screen.findByText('Task 18');
  expect(posts()).toHaveLength(1);
  expect(JSON.parse(posts()[0][1].body as string)).toEqual({kind:'image',cloud:true,backend:'krea',prompt:'',resume_task_id:17});
  expect(screen.queryByRole('button',{name:'Resume saved job'})).toBeNull();
});

it('uses the selected OpenRouter chat model and artifact edit references without a quality fallback', async () => {
  transport(extendedProviders);
  await selectCloud('openrouter');
  expect(screen.queryByLabelText('Cloud image quality')).toBeNull();
  fireEvent.click(screen.getByLabelText('Edit an image'));
  fireEvent.change(screen.getByLabelText('Cloud reference artifact IDs'), { target: { value: id } });
  fireEvent.click(screen.getByRole('button', { name: 'Propose edit' }));
  await waitFor(() => expect(posts()).toHaveLength(1));
  expect(JSON.parse(posts()[0][1].body as string)).toEqual({
    kind: 'image', prompt: ' exact image prompt ', cloud: true,
    backend: 'openrouter', model: 'openai/gpt-5.4-image-2', size: '1024x1024', references: [id],
  });
});

it('proposes Krea style-guided generation with explicit URLs and creativity, never generic editing', async () => {
  transport(extendedProviders);
  await selectCloud('krea');
  expect(screen.queryByLabelText('Edit an image')).toBeNull();
  fireEvent.change(screen.getByLabelText('Krea creativity'), { target: { value: 'high' } });
  fireEvent.click(screen.getByLabelText('Use style references'));
  fireEvent.change(screen.getByLabelText('Krea style reference URLs'), {
    target: { value: 'https://images.example.com/one.png\nhttps://images.example.com/two.png' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'Propose style-guided image' }));
  await waitFor(() => expect(posts()).toHaveLength(1));
  expect(JSON.parse(posts()[0][1].body as string)).toEqual({
    kind: 'image', prompt: ' exact image prompt ', cloud: true,
    backend: 'krea', model: 'krea-2-medium', size: '1024x1024', creativity: 'high',
    image_style_references: ['https://images.example.com/one.png', 'https://images.example.com/two.png'],
  });
});

it('does not carry Krea style references into an OpenRouter proposal after provider switch', async () => {
  transport(extendedProviders);
  await selectCloud('krea');
  fireEvent.click(screen.getByLabelText('Use style references'));
  fireEvent.change(screen.getByLabelText('Krea style reference URLs'), {
    target: { value: 'https://images.example.com/one.png' },
  });
  fireEvent.change(screen.getByLabelText('Cloud image provider'), { target: { value: 'openrouter' } });
  expect(screen.queryByLabelText('Krea style reference URLs')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Propose image' }));
  await waitFor(() => expect(posts()).toHaveLength(1));
  expect(JSON.parse(posts()[0][1].body as string)).not.toHaveProperty('image_style_references');
});

it('rejects unsupported OpenRouter knobs and invalid Krea style URLs before POST', async () => {
  const valid = { size: '1024x1024', backend: 'openrouter', model: 'openai/gpt-image-2' };
  await expect(proposeCloudImage('prompt', { ...valid, quality: 'high', aspect_ratio_exact: '16:9', n: 1 } as any))
    .resolves.toBe(17);
  vi.mocked(fetch).mockClear();
  for (const options of [
    { ...valid, quality: 'ultra' },
    { ...valid, aspect_ratio_exact: '5:1' },
    { ...valid, references: ['https://example.com/ref.png'] },
    { ...valid, n: 2 },
    { size: '1024x1024', backend: 'openrouter', model: 'google/gemini-3.1-flash-image', resolution: '4K' },
    { size: '1024x1024', backend: 'krea', model: 'krea-2-medium', references: [id] },
    { size: '1024x1024', backend: 'krea', model: 'krea-2-medium', image_style_references: ['http://example.com/ref.png'] },
    { size: '1024x1024', backend: 'krea', model: 'krea-2-medium', image_style_references: ['https://127.0.0.1/ref.png'] },
    Object.create({ size: '1024x1024', quality: 'low' }),
  ]) {
    await expect(proposeCloudImage('prompt', options as any)).rejects.toMatchObject({ code: 'refused' });
  }
  expect(fetch).not.toHaveBeenCalled();
});

it.each(['fal', 'openai-codex'])('submits selected %s provider and default model through the actual API adapter', async backend => {
  localStorage.setItem('hud.admin_token', 'synthetic-owner');
  await selectCloud(backend);
  expect(screen.queryByLabelText('Cloud image quality')).toBeNull();
  expect(screen.queryByLabelText('2× bicubic upscale')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Propose image' }));
  await screen.findByText(/Awaiting approval/);
  expect(posts()).toHaveLength(1);
  expect(JSON.parse(posts()[0][1].body as string)).toEqual({
    kind: 'image', prompt: ' exact image prompt ', cloud: true, backend,
    model: providers[backend].default_model, size: '1024x1024',
  });
  expect(posts()[0][1].headers).toMatchObject({ 'X-Admin-Token': 'synthetic-owner' });
  expect(screen.queryByRole('button', { name: /approve/i })).toBeNull();
});

it('selects an OpenAI Image2 tier and derives quality from the model instead of posting a conflicting control', async () => {
  await selectCloud('openai');
  expect(screen.getByLabelText('Cloud image quality')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Cloud image model'), { target: { value: 'gpt-image-2-high' } });
  expect(screen.queryByLabelText('Cloud image quality')).toBeNull();
  fireEvent.change(screen.getByLabelText('Cloud image size'), { target: { value: '1536x1024' } });
  fireEvent.click(screen.getByRole('button', { name: 'Propose image' }));
  await waitFor(() => expect(posts()).toHaveLength(1));
  expect(JSON.parse(posts()[0][1].body as string)).toMatchObject({
    backend: 'openai', model: 'gpt-image-2-high', size: '1536x1024',
  });
  expect(JSON.parse(posts()[0][1].body as string)).not.toHaveProperty('quality');
});

it('edits a Codex image using opaque saved artifact IDs and no local strength', async () => {
  await selectCloud('openai-codex');
  fireEvent.click(screen.getByLabelText('Edit an image'));
  fireEvent.change(screen.getByLabelText('Cloud reference artifact IDs'), { target: { value: `${id}\n${'b'.repeat(32)}` } });
  expect(screen.queryByLabelText('Change strength')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Propose edit' }));
  await waitFor(() => expect(posts()).toHaveLength(1));
  const body = JSON.parse(posts()[0][1].body as string);
  expect(body).toMatchObject({ backend: 'openai-codex', references: [id, 'b'.repeat(32)] });
  expect(body).not.toHaveProperty('strength');
  expect(body).not.toHaveProperty('quality');
});

it('edits FAL with catalog-limited media URLs and clears references when switching to a generate-only model', async () => {
  await selectCloud('fal');
  fireEvent.click(screen.getByLabelText('Edit an image'));
  const input = screen.getByLabelText('Cloud reference image URLs');
  fireEvent.change(input, { target: { value: 'https://fal.media/files/first.png\nhttps://v3.fal.media/files/second.png' } });
  expect((screen.getByRole('button', { name: 'Propose edit' }) as HTMLButtonElement).disabled).toBe(false);
  fireEvent.change(screen.getByLabelText('Cloud image model'), { target: { value: 'fal-ai/z-image/turbo' } });
  expect(screen.queryByLabelText('Edit an image')).toBeNull();
  expect(screen.queryByLabelText('Cloud reference image URLs')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Propose image' }));
  await waitFor(() => expect(posts()).toHaveLength(1));
  expect(JSON.parse(posts()[0][1].body as string)).toMatchObject({ model: 'fal-ai/z-image/turbo' });
  expect(JSON.parse(posts()[0][1].body as string)).not.toHaveProperty('references');
});

it('sends the selected FAL edit references to the approval API', async () => {
  await selectCloud('fal');
  fireEvent.click(screen.getByLabelText('Edit an image'));
  fireEvent.change(screen.getByLabelText('Cloud reference image URLs'), { target: { value: 'https://fal.media/files/input.png' } });
  fireEvent.click(screen.getByRole('button', { name: 'Propose edit' }));
  await waitFor(() => expect(posts()).toHaveLength(1));
  expect(JSON.parse(posts()[0][1].body as string)).toMatchObject({ references: ['https://fal.media/files/input.png'] });
});

it('blocks a FAL edit above the advertised model capacity', async () => {
  await selectCloud('fal');
  fireEvent.click(screen.getByLabelText('Edit an image'));
  fireEvent.change(screen.getByLabelText('Cloud reference image URLs'), {
    target: { value: Array.from({ length: 10 }, (_, i) => `https://fal.media/files/${i}.png`).join('\n') },
  });
  expect((screen.getByRole('button', { name: 'Propose edit' }) as HTMLButtonElement).disabled).toBe(true);
  expect(posts()).toHaveLength(0);
});

it('keeps disabled Codex visible and cannot activate or submit it from the image panel', async () => {
  transport({ ...providers, 'openai-codex': provider('gpt-image-2-medium', { enabled: false, configured: false, reason: 'oauth_disabled' }) });
  await selectCloud('openai-codex');
  expect((screen.getByRole('button', { name: 'Propose image' }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/Cloud image generation is disabled/)).toBeTruthy();
  expect(posts()).toHaveLength(0);
});

it('does not infer edit support from a model name when status metadata is missing', async () => {
  transport({ ...providers, 'openai-codex': provider('gpt-image-2-medium', { model_capabilities: {} }) });
  await selectCloud('openai-codex');
  expect(screen.queryByLabelText('Edit an image')).toBeNull();
});

it('holds a lost cloud response without automatically resubmitting', async () => {
  const original = vi.mocked(fetch).getMockImplementation()!;
  vi.mocked(fetch).mockImplementation((url, opts) => opts?.method === 'POST'
    ? Promise.reject(new TypeError('lost response')) : original(url, opts));
  await selectCloud('openai-codex');
  fireEvent.click(screen.getByRole('button', { name: 'Propose image' }));
  await screen.findByText(/Proposal response lost or unclear/);
  expect(posts()).toHaveLength(1);
  expect(screen.queryByRole('button', { name: 'Propose image' })).toBeNull();
});

it.each([false, true])('never falls back to OpenAI if refreshed metadata loses the selected Codex provider (whole catalog lost: %s)', async lostCatalog => {
  await selectCloud('openai-codex');
  const raw = {
    local_image: { configured: false, local: true, approval_required: true },
    cloud_image: { configured: true, provider: 'openai', model: 'gpt-image-1.5', local: false,
      approval_required: true, reachable: null, sizes: ['1024x1024','1536x1024','1024x1536'],
      qualities: ['low','medium','high'],
      ...(lostCatalog ? {} : {providers: {openai: providers.openai, fal: providers.fal}}),
    },
  };
  vi.mocked(fetch).mockResolvedValue(reply(raw));
  fireEvent.click(screen.getByRole('button', {name: 'Check configuration'}));
  await screen.findByText(/Cloud image generation is disabled/);
  expect((screen.getByRole('button', {name: 'Propose image'}) as HTMLButtonElement).disabled).toBe(true);
  expect(posts()).toHaveLength(0);
  if (!lostCatalog) {
    fireEvent.change(screen.getByLabelText('Cloud image provider'), {target:{value:'fal'}});
    expect((screen.getByRole('button', {name: 'Propose image'}) as HTMLButtonElement).disabled).toBe(false);
  }
});

it.each([
  { backend: 'openai-codex', model: 'gpt-image-2-high', quality: 'low' },
  { backend: 'openai-codex', model: 'gpt-image-2-medium', references: ['https://fal.media/input.png'] },
  { backend: 'fal', model: 'fal-ai/flux-2/klein/9b', references: ['https://fal.media.evil.invalid/input.png'] },
  { backend: 'fal', model: 'fal-ai/flux-2/klein/9b', references: ['https://u:pw@fal.media/input.png'] },
  { backend: 'fal', model: 'fal-ai/flux-2/klein/9b', references: ['https://fal.media:8443/input.png'] },
  { backend: 'other', model: 'gpt-image-2-medium' },
])('rejects contradictory or invalid provider controls before POST: %j', async options => {
  await expect(proposeCloudImage('prompt', { size: '1024x1024', ...options } as any))
    .rejects.toMatchObject({ code: 'refused' });
  expect(fetch).not.toHaveBeenCalled();
});
