import { apiFetchOnce } from './client';

export type ImageArtifact = { id: string; bytes: number; width: number; height: number };
export type ImageState = 'awaiting_approval' | 'queued' | 'generating' | 'ready' | 'rejected' | 'deferred' | 'refused' | 'uncertain';
export type ImageTask = { task_id: number; state: ImageState; artifact: ImageArtifact | null; resume_available?: boolean; enhance_available?: boolean };
export type CloudImageSize = '1024x1024' | '1536x1024' | '1024x1536';
export type CloudImageQuality = 'low' | 'medium' | 'high';
export type CloudImageProviderId = 'openai' | 'openai-codex' | 'fal' | 'openrouter' | 'krea' | 'xai' | 'deepinfra';
export type KreaStyleReference = string | {url: string; strength: number};
export type CloudImageOptions = {size: CloudImageSize; quality: CloudImageQuality; backend?: never; model?: never; references?: never}
  | {size: CloudImageSize; backend: CloudImageProviderId; model: string; quality?: CloudImageQuality | 'auto'; references?: string[];
    aspect_ratio_exact?: string; resolution?: string; background?: string; output_compression?: number; seed?: number; n?: number;
    creativity?: 'raw' | 'low' | 'medium' | 'high'; image_style_references?: KreaStyleReference[]};
export type CloudImageCapability = {configured:boolean; provider:'openai'; model:'gpt-image-1.5'};
export type CloudImageModelCapability = {edit: boolean; max_reference_images: number;
  reference_kind: 'artifact_id' | 'fal_media_url' | 'style_url'; style_guided?: boolean; max_style_references?: number};
export type CloudImageProvider = {id: CloudImageProviderId; enabled: boolean; configured: boolean; default_model: string;
  models: string[]; model_capabilities: Record<string, CloudImageModelCapability>; catalog_refresh_available?: boolean};
export type ImageBackend = { id: string; models: string[]; protocol?: 'comfyui' | 'openai_images'; edit?: boolean; max_references?: number; upscale?: number[] };
export type ImageCapability = { cloud?: CloudImageCapability; cloudProviders?: CloudImageProvider[]; configured: boolean; backend?: string; edit: boolean; backends?: ImageBackend[]; max_references?: number; upscale?: number[] };
/** An edit of an artifact this hub already produced: its opaque id, plus how much of
 *  it to keep. There is deliberately no field here for a path, a URL or a filename. */
export type ImageEdit = { reference?: string; references?: string[]; strength?: number; backend?: string; model?: string; upscale?: number };
const modelValid = (value: unknown): value is string => typeof value === 'string'
  && /^[A-Za-z0-9][A-Za-z0-9_./:-]{0,172}$/.test(value) && value.trim() === value;
const deepInfraModelValid = (value: unknown): value is string => typeof value === 'string' && value.length >= 3
  && value.length <= 256 && value.split('/').length >= 2 && value.split('/').length <= 4
  && value.split('/').every(part => /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(part) && !part.includes('..'));
const cloudSizes = ['1024x1024', '1536x1024', '1024x1536'];
const cloudQualities = ['low', 'medium', 'high'];
const cloudProviderIds: CloudImageProviderId[] = ['openai', 'openai-codex', 'fal', 'openrouter', 'krea', 'xai', 'deepinfra'];
const xaiModels: Record<string,number> = {'grok-imagine-image':3,'grok-imagine-image-2.0':5,'grok-imagine-image-quality':3};
const image2Models = ['gpt-image-2-low', 'gpt-image-2-medium', 'gpt-image-2-high'];
const openRouterChat = ['openai/gpt-5.4-image-2', 'google/gemini-3-pro-image'];
const geminiRatios = ['1:1','1:4','1:8','2:3','3:2','3:4','4:1','4:3','4:5','5:4','8:1','9:16','16:9','21:9'];
const maiRatios = ['1:1','4:3','3:4','16:9','9:16','3:2','2:3','auto'];
const kreaRatios = ['1:1','4:3','3:2','16:9','4:5','2:3','9:16'];
const openRouterCatalog: Record<string, {ratios:string[]; resolutions:string[]; quality:string[];
  background:string[]; compression:boolean; seed:boolean; maxRefs:number}> = {
  'google/gemini-3.1-flash-lite-image': {ratios:geminiRatios,resolutions:['1K'],quality:[],background:[],compression:false,seed:false,maxRefs:14},
  'google/gemini-3.1-flash-image': {ratios:geminiRatios,resolutions:['512','1K','2K','4K'],quality:[],background:[],compression:false,seed:false,maxRefs:14},
  'openai/gpt-image-2': {ratios:['1:1','3:2','2:3','4:3','3:4','16:9','9:16','21:9','auto'],resolutions:[],quality:['auto','low','medium','high'],background:['auto','opaque'],compression:true,seed:false,maxRefs:16},
  'openai/gpt-image-1-mini': {ratios:['1:1','3:2','2:3','auto'],resolutions:[],quality:['auto','low','medium','high'],background:['auto','transparent','opaque'],compression:true,seed:false,maxRefs:16},
  'microsoft/mai-image-2.5': {ratios:maiRatios,resolutions:[],quality:[],background:[],compression:false,seed:false,maxRefs:1},
  'microsoft/mai-image-2.5-pro': {ratios:maiRatios,resolutions:[],quality:[],background:[],compression:false,seed:false,maxRefs:1},
  'x-ai/grok-imagine-image-quality': {ratios:['1:1','3:4','4:3','9:16','16:9','2:3','3:2','9:19.5','19.5:9','9:20','20:9','1:2','2:1','auto'],resolutions:['1K','2K'],quality:[],background:[],compression:false,seed:false,maxRefs:3},
  'krea/krea-2-medium': {ratios:kreaRatios,resolutions:['1K'],quality:[],background:[],compression:false,seed:true,maxRefs:1},
  'krea/krea-2-medium-turbo': {ratios:kreaRatios,resolutions:['1K'],quality:[],background:[],compression:false,seed:true,maxRefs:1},
  'qwen/qwen-image-3-pro': {ratios:['1:1','1:2','1:4','2:1','2:3','3:2','3:4','4:1','4:3','4:5','5:4','9:16','16:9'],resolutions:['1K','2K'],quality:[],background:[],compression:false,seed:true,maxRefs:4},
};
const kreaModels = ['krea-2-medium','krea-2-large','krea-2-medium-turbo'];
const artifactId = (value: unknown): value is string => typeof value === 'string' && /^[a-f0-9]{32}$/.test(value);
const safeSeed = (value: unknown): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
function referenceList(value: unknown, max: number, valid: (value: unknown) => boolean): value is string[] {
  return Array.isArray(value) && value.length > 0 && value.length <= max
    && new Set(value).size === value.length && value.every(valid);
}
function httpsImageUrl(value: unknown): value is string {
  if (typeof value !== 'string' || value.length > 2048 || !value.startsWith('https://')
    || /[\s\\\u0000-\u001f\u007f]/.test(value)) return false;
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase().replace(/\.$/, '');
    return host.includes('.') && !/^\d+(\.\d+){3}$/.test(host) && !host.includes(':')
      && !host.endsWith('.local') && !host.endsWith('.internal') && !host.endsWith('.localhost')
      && !url.username && !url.password && !url.hash && !url.port && url.pathname !== '/';
  } catch { return false; }
}
function styleReferencesValid(value: unknown): value is KreaStyleReference[] {
  if (!Array.isArray(value) || value.length < 1 || value.length > 10) return false;
  const urls: string[] = [];
  for (const ref of value) {
    let url: unknown = ref;
    if (ref && typeof ref === 'object' && !Array.isArray(ref)) {
      if (Object.keys(ref).sort().join(',') !== 'strength,url') return false;
      url = ref.url;
      if (typeof ref.strength !== 'number' || !Number.isFinite(ref.strength)
        || ref.strength < -2 || ref.strength > 2) return false;
    }
    if (!httpsImageUrl(url)) return false;
    urls.push(url);
  }
  return new Set(urls).size === urls.length;
}
function falMediaUrl(value: unknown): value is string {
  if (typeof value !== 'string' || value.length > 2048 || /[\s\\\u0000-\u001f\u007f]/.test(value)) return false;
  try {
    const url = new URL(value);
    const host = url.hostname.toLowerCase().replace(/\.$/, '');
    return value.startsWith('https://') && (host === 'fal.media' || host.endsWith('.fal.media'))
      && !url.port && !url.username && !url.password && !url.hash && url.pathname !== '/';
  } catch { return false; }
}
export function cloudOptionsValid(value: any): value is CloudImageOptions {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || !Object.prototype.hasOwnProperty.call(value, 'size') || !cloudSizes.includes(value.size)) return false;
  if (value.backend === undefined) return Object.keys(value).every(key => ['size', 'quality'].includes(key))
    && Object.prototype.hasOwnProperty.call(value, 'quality') && cloudQualities.includes(value.quality);
  if (!cloudProviderIds.includes(value.backend) || !(value.backend === 'deepinfra' ? deepInfraModelValid(value.model) : modelValid(value.model))
    || !Object.prototype.hasOwnProperty.call(value, 'backend')
    || !Object.prototype.hasOwnProperty.call(value, 'model')) return false;
  if (value.backend === 'krea') {
    if (!kreaModels.includes(value.model) || Object.keys(value).some(key => ![
      'size','backend','model','creativity','seed','image_style_references'].includes(key))) return false;
    return (value.creativity === undefined || ['raw','low','medium','high'].includes(value.creativity))
      && (value.seed === undefined || safeSeed(value.seed))
      && (value.image_style_references === undefined || styleReferencesValid(value.image_style_references));
  }
  if (value.backend === 'deepinfra') return Object.keys(value).every(key => ['size','backend','model'].includes(key));
  if (value.backend === 'xai') {
    const maxRefs = xaiModels[value.model];
    if (!maxRefs || Object.keys(value).some(key => !['size','backend','model','references','quality','resolution'].includes(key))) return false;
    const editing = value.references !== undefined;
    return (!editing || referenceList(value.references,maxRefs,artifactId))
      && (value.quality === undefined || (value.model === 'grok-imagine-image-2.0' && ['low','medium','auto'].includes(value.quality)))
      && (value.resolution === undefined || (!editing && ['1k','2k'].includes(value.resolution)));
  }
  if (value.backend === 'openrouter') {
    const chat = openRouterChat.includes(value.model);
    const cap = openRouterCatalog[value.model];
    if (!chat && !cap) return false;
    const allowed = chat ? ['size','backend','model','references'] : [
      'size','backend','model','references','aspect_ratio_exact','resolution','quality','background',
      'output_compression','seed','n'];
    if (Object.keys(value).some(key => !allowed.includes(key))) return false;
    if (value.references !== undefined && !referenceList(value.references, chat ? 3 : cap.maxRefs, artifactId)) return false;
    if (chat) return true;
    return (value.aspect_ratio_exact === undefined || cap.ratios.includes(value.aspect_ratio_exact))
      && (value.resolution === undefined || (value.resolution !== '4K' && cap.resolutions.includes(value.resolution)))
      && (value.quality === undefined || cap.quality.includes(value.quality))
      && (value.background === undefined || cap.background.includes(value.background))
      && (value.output_compression === undefined || (cap.compression && Number.isInteger(value.output_compression)
        && value.output_compression >= 0 && value.output_compression <= 100))
      && (value.seed === undefined || (cap.seed && safeSeed(value.seed)))
      && (value.n === undefined || value.n === 1);
  }
  if (Object.keys(value).some(key => !['size', 'quality', 'backend', 'model', 'references'].includes(key))) return false;
  if (value.backend !== 'fal') {
    if (value.backend === 'openai' && value.model === 'gpt-image-1.5') {
      return Object.prototype.hasOwnProperty.call(value, 'quality')
        && cloudQualities.includes(value.quality) && value.references === undefined;
    }
    if (!image2Models.includes(value.model)) return false;
  } else if (!value.model.startsWith('fal-ai/')) return false;
  if (value.quality !== undefined) return false;
  if (value.references === undefined) return true;
  return referenceList(value.references, 16, value.backend === 'fal' ? falMediaUrl : artifactId);
}
function readCloudProviders(raw: any): CloudImageProvider[] | undefined {
  if (raw?.local !== false || raw.approval_required !== true || !raw.providers
    || typeof raw.providers !== 'object' || Array.isArray(raw.providers)) return undefined;
  const result: CloudImageProvider[] = [];
  for (const id of cloudProviderIds) {
    const row = raw.providers[id];
    if (!row || typeof row.enabled !== 'boolean' || typeof row.configured !== 'boolean'
      || (row.configured && !row.enabled) || row.reachable !== null || !Array.isArray(row.models)
      || row.models.length > (id === 'deepinfra' ? 512 : 64) || new Set(row.models).size !== row.models.length
      || !row.models.every(id === 'deepinfra' ? deepInfraModelValid : modelValid)
      || (id === 'deepinfra' ? (typeof row.catalog_refresh_available !== 'boolean'
        || (row.models.length === 0 ? row.default_model !== '' || row.configured !== false || row.reason !== 'catalog_unavailable'
          : !row.models.includes(row.default_model)))
        : row.models.length < 1 || !row.models.includes(row.default_model))
      || (id === 'xai' && !row.models.every((model:string)=>Object.prototype.hasOwnProperty.call(xaiModels,model)))) continue;
    const kind = id === 'fal' ? 'fal_media_url' : id === 'krea' ? 'style_url' : 'artifact_id';
    const caps: Record<string, CloudImageModelCapability> = {};
    for (const model of row.models) {
      const cap = row.model_capabilities?.[model];
      const valid = cap?.reference_kind === kind && typeof cap.edit === 'boolean'
        && Number.isInteger(cap.max_reference_images) && cap.max_reference_images >= 0
        && cap.max_reference_images <= 16 && (cap.edit ? cap.max_reference_images > 0 : cap.max_reference_images === 0)
        && (id !== 'deepinfra' || (cap.edit === false && cap.max_reference_images === 0))
        && (id !== 'xai' || (cap.edit === true && cap.max_reference_images === xaiModels[model]))
        && (id !== 'krea' || (cap.edit === false && cap.style_guided === true
          && Number.isInteger(cap.max_style_references) && cap.max_style_references > 0 && cap.max_style_references <= 10));
      caps[model] = valid ? {edit: cap.edit, max_reference_images: cap.max_reference_images, reference_kind: kind,
        ...(id === 'krea' ? {style_guided: true, max_style_references: cap.max_style_references} : {})}
        : {edit: false, max_reference_images: 0, reference_kind: kind};
    }
    result.push({id, enabled: row.enabled, configured: row.configured, default_model: row.default_model,
      models: row.models, model_capabilities: caps,
      ...(id === 'deepinfra' ? {catalog_refresh_available:row.catalog_refresh_available} : {})});
  }
  return result.length ? result : undefined;
}
export class ImageRequestError extends Error {
  constructor(public code: 'auth' | 'refused' | 'uncertain' | 'unavailable') { super(code); }
}
const fail = (code: ImageRequestError['code'] = 'unavailable'): never => { throw new ImageRequestError(code); };
const positiveInt = (value: unknown, limit = Number.MAX_SAFE_INTEGER): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value > 0 && value <= limit;
const artifactValid = (value: any): value is ImageArtifact => value && typeof value.id === 'string'
  && /^[a-f0-9]{32}$/.test(value.id) && positiveInt(value.bytes, 16 * 1024 * 1024)
  && positiveInt(value.width, 4096) && positiveInt(value.height, 4096);
export const editValid = (value: any): value is ImageEdit => {
  if (!value || typeof value !== 'object') return false;
  if (value.reference !== undefined && value.references !== undefined) return false;
  const refs = value.references ?? (value.reference ? [value.reference] : []);
  if (!Array.isArray(refs) || refs.length > 4 || new Set(refs).size !== refs.length || refs.some(r => typeof r !== 'string' || !/^[a-f0-9]{32}$/.test(r))) return false;
  if (value.references !== undefined && refs.length === 0) return false;
  if (value.reference !== undefined && refs.length !== 1) return false;
  if (refs.length ? !positiveInt(value.strength, 100) : value.strength !== undefined) return false;
  if (value.backend !== undefined && !/^[a-z][a-z0-9_-]{0,31}$/.test(value.backend)) return false;
  if (value.model !== undefined && !modelValid(value.model)) return false;
  return value.upscale === undefined || value.upscale === 2;
};
const states: ImageState[] = ['awaiting_approval', 'queued', 'generating', 'ready', 'rejected', 'deferred', 'refused', 'uncertain'];

async function boundedBody(response: Response, limit: number, signal: AbortSignal): Promise<Uint8Array> {
  signal.throwIfAborted();
  const length = response.headers.get('content-length');
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > limit)) {
    await response.body?.cancel();
    fail();
  }
  if (!response.body) fail();
  const reader = response.body.getReader();
  const abort = () => { void reader.cancel().catch(() => {}); };
  signal.addEventListener('abort', abort, { once: true });
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    for (;;) {
      signal.throwIfAborted();
      const { value, done } = await reader.read();
      signal.throwIfAborted();
      if (done) break;
      if (value.byteLength > limit - size) fail();
      chunks.push(value); size += value.byteLength;
    }
  } catch (error) { await reader.cancel().catch(() => {}); throw error; }
  finally { signal.removeEventListener('abort', abort); reader.releaseLock(); }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return bytes;
}

async function timed<T>(signal: AbortSignal | undefined, run: (signal: AbortSignal) => Promise<T>): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  if (signal?.aborted) controller.abort();
  const timer = setTimeout(abort, 20_000);
  try { controller.signal.throwIfAborted(); return await run(controller.signal); }
  finally { controller.abort(); clearTimeout(timer); signal?.removeEventListener('abort', abort); }
}
async function json(response: Response, signal: AbortSignal, limit = 64 * 1024): Promise<any> {
  if (response.headers.get('content-type')?.split(';')[0].trim() !== 'application/json') fail();
  try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(await boundedBody(response, limit, signal))); }
  catch (error) { if (signal.aborted) signal.throwIfAborted(); fail(); }
}
function readStatus(response: Response) {
  if (response.status === 401 || response.status === 403) fail('auth');
  if (!response.ok) fail();
}
export async function imageStatus(signal?: AbortSignal): Promise<ImageCapability> {
  return timed(signal, async signal => {
    const response = await apiFetchOnce('/api/media', { admin: true, signal }); readStatus(response);
    const value = await json(response, signal, 512 * 1024);
    const status = value?.local_image;
    const raw = value?.cloud_image;
    const cloudProviders = readCloudProviders(raw);
    const cloud: CloudImageCapability | undefined = raw && typeof raw.configured === 'boolean'
      && raw.provider === 'openai' && raw.model === 'gpt-image-1.5' && raw.local === false
      && raw.approval_required === true && raw.reachable === null
      && Array.isArray(raw.sizes) && raw.sizes.length === 3 && new Set(raw.sizes).size === 3
      && raw.sizes.every((v:unknown)=>['1024x1024','1536x1024','1024x1536'].includes(v as string))
      && Array.isArray(raw.qualities) && raw.qualities.length === 3 && new Set(raw.qualities).size === 3
      && raw.qualities.every((v:unknown)=>['low','medium','high'].includes(v as string))
      ? {configured:raw.configured,provider:'openai',model:'gpt-image-1.5'} : undefined;
    if (!status || typeof status.configured !== 'boolean' || status.local !== true || status.approval_required !== true) {
      if (cloud || cloudProviders) return {configured:false,edit:false,...(cloud ? {cloud} : {}), ...(cloudProviders ? {cloudProviders} : {})};
      fail();
    }
    // `edit` is read, never required: a hub that predates image editing still reports
    // a usable generator, and refusing the whole status over a missing capability flag
    // would break generation to advertise editing.
    const backends: ImageBackend[] | undefined = Array.isArray(status.backends) ? status.backends
      .filter((b: any) => typeof b?.id === 'string' && /^[a-z][a-z0-9_-]{0,31}$/.test(b.id)
        && b.id.trim() === b.id && [undefined, 'comfyui', 'openai_images'].includes(b.protocol)
        && Array.isArray(b.models) && b.models.length > 0 && b.models.length <= 32 && b.models.every(modelValid))
      .map((b: any) => ({id:b.id, models:b.models,
        ...(b.protocol ? {protocol:b.protocol, edit:b.edit === true,
          max_references:Number.isInteger(b.max_references) && b.max_references >= 0 && b.max_references <= 4 ? b.max_references : 0,
          upscale:Array.isArray(b.upscale) && b.upscale.includes(2) ? [2] : []} : {})})) : undefined;
    const backend = typeof status.backend === 'string' && backends?.some(b => b.id === status.backend) ? status.backend : undefined;
    return { ...(cloud ? {cloud} : {}), ...(cloudProviders ? {cloudProviders} : {}), configured: status.configured, edit: status.edit === true,
      ...(backend ? {backend} : {}), ...(backends ? {backends, max_references: status.max_references, upscale: status.upscale} : {}) };
  });
}
export async function proposeImage(prompt: string, edit?: ImageEdit | null, signal?: AbortSignal): Promise<number> {
  if (!prompt.trim() || prompt.length > 4000) fail('refused');
  if (edit && !editValid(edit)) fail('refused');
  return proposeBody({kind:'image', prompt, cloud:false, ...(edit ? Object.fromEntries(Object.entries(edit).filter(([key,value])=>['reference','references','strength','backend','model','upscale'].includes(key) && value !== undefined)) : {})}, signal);
}
export async function proposeCloudImage(prompt:string, options:CloudImageOptions, signal?:AbortSignal):Promise<number> {
  if (!prompt.trim() || prompt.length > 4000 || !cloudOptionsValid(options)) fail('refused');
  return proposeBody({kind:'image',prompt,cloud:true,...options},signal);
}
export async function proposeKreaResume(sourceTaskId:number, signal?:AbortSignal):Promise<number> {
  if (!positiveInt(sourceTaskId)) fail('refused');
  return proposeBody({kind:'image',cloud:true,backend:'krea',prompt:'',resume_task_id:sourceTaskId},signal);
}
export async function proposeKreaEnhance(sourceTaskId:number, signal?:AbortSignal):Promise<number> {
  if (!positiveInt(sourceTaskId)) fail('refused');
  return proposeBody({kind:'image',cloud:true,backend:'krea',prompt:'',enhance_task_id:sourceTaskId},signal);
}
export async function proposeDeepInfraRefresh(signal?:AbortSignal):Promise<number> {
  return proposeBody({kind:'image',cloud:true,backend:'deepinfra',prompt:'',refresh_catalog:true},signal);
}
async function proposeBody(body:Record<string,unknown>, signal?:AbortSignal):Promise<number> {
  try {
    return await timed(signal, async signal => {
      const response = await apiFetchOnce('/api/media/generate', { method: 'POST', admin: true, signal,
        body });
      if (response.status === 401 || response.status === 403) fail('auth');
      if ([400, 422].includes(response.status)) fail('refused');
      const value = await json(response, signal);
      if (response.status === 200 && value?.ok === false && value?.paused === true) fail('refused');
      if (response.status !== 202 || value?.reason !== 'approval_required' || !positiveInt(value.task_id)) fail('uncertain');
      return value.task_id;
    });
  } catch (error) {
    if (error instanceof ImageRequestError && ['auth', 'refused'].includes(error.code)) throw error;
    // Including cancellation: the server may already have durably queued it.
    fail('uncertain');
  }
}
export async function imageTask(taskId: number, signal?: AbortSignal): Promise<ImageTask> {
  if (!positiveInt(taskId)) fail();
  return timed(signal, async signal => {
    const response = await apiFetchOnce('/api/media/generation-tasks/' + taskId, { admin: true, signal }); readStatus(response);
    const value = await json(response, signal);
    if (value?.task_id !== taskId || !states.includes(value?.state)) fail();
    if (value.state === 'ready') {
      if (!artifactValid(value.artifact)) fail();
      const { id, bytes, width, height } = value.artifact;
      return { task_id: taskId, state: 'ready', artifact: { id, bytes, width, height }, enhance_available: value.enhance_available === true };
    }
    if (value.artifact !== null) fail();
    return { task_id: taskId, state: value.state, artifact: null,
      ...(value.resume_available === true ? {resume_available:true} : {}), enhance_available: false };
  });
}
export async function imageBlob(artifact: ImageArtifact, signal?: AbortSignal): Promise<Blob> {
  if (!artifactValid(artifact)) fail();
  return timed(signal, async signal => {
    const response = await apiFetchOnce('/api/media/generated/' + artifact.id, { admin: true, signal, accept: 'image/png' }); readStatus(response);
    if (response.headers.get('content-type')?.split(';')[0].trim() !== 'image/png') { await response.body?.cancel(); fail(); }
    const bytes = await boundedBody(response, artifact.bytes, signal);
    if (bytes.byteLength !== artifact.bytes || [137, 80, 78, 71, 13, 10, 26, 10].some((byte, index) => bytes[index] !== byte)) fail();
    return new Blob([bytes as BlobPart], { type: 'image/png' });
  });
}
