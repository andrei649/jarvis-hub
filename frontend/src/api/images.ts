import { apiFetchOnce } from './client';

export type ImageArtifact = { id: string; bytes: number; width: number; height: number };
export type ImageState = 'awaiting_approval' | 'queued' | 'generating' | 'ready' | 'rejected' | 'deferred' | 'refused' | 'uncertain';
export type ImageTask = { task_id: number; state: ImageState; artifact: ImageArtifact | null };
export class ImageRequestError extends Error {
  constructor(public code: 'auth' | 'refused' | 'uncertain' | 'unavailable') { super(code); }
}
const fail = (code: ImageRequestError['code'] = 'unavailable'): never => { throw new ImageRequestError(code); };
const positiveInt = (value: unknown, limit = Number.MAX_SAFE_INTEGER): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value > 0 && value <= limit;
const artifactValid = (value: any): value is ImageArtifact => value && typeof value.id === 'string'
  && /^[a-f0-9]{32}$/.test(value.id) && positiveInt(value.bytes, 16 * 1024 * 1024)
  && positiveInt(value.width, 1024) && positiveInt(value.height, 1024);
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
async function json(response: Response, signal: AbortSignal): Promise<any> {
  if (response.headers.get('content-type')?.split(';')[0].trim() !== 'application/json') fail();
  try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(await boundedBody(response, 64 * 1024, signal))); }
  catch (error) { if (signal.aborted) signal.throwIfAborted(); fail(); }
}
function readStatus(response: Response) {
  if (response.status === 401 || response.status === 403) fail('auth');
  if (!response.ok) fail();
}
export async function imageStatus(signal?: AbortSignal): Promise<{ configured: boolean }> {
  return timed(signal, async signal => {
    const response = await apiFetchOnce('/api/media', { admin: true, signal }); readStatus(response);
    const status = (await json(response, signal))?.local_image;
    if (!status || typeof status.configured !== 'boolean' || status.local !== true || status.approval_required !== true) fail();
    return { configured: status.configured };
  });
}
export async function proposeImage(prompt: string, signal?: AbortSignal): Promise<number> {
  if (!prompt.trim() || prompt.length > 4000) fail('refused');
  try {
    return await timed(signal, async signal => {
      const response = await apiFetchOnce('/api/media/generate', { method: 'POST', admin: true, signal,
        body: { kind: 'image', prompt, cloud: false } });
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
      return { task_id: taskId, state: 'ready', artifact: { id, bytes, width, height } };
    }
    if (value.artifact !== null) fail();
    return { task_id: taskId, state: value.state, artifact: null };
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
