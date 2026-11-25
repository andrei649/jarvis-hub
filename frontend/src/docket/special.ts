/* The special kinds (PHASE_B_PLAN.md §5.4): requests the docket does not sign inline but opens in
   Decisions (/v2/console/decision-inbox?card=<id>), where their whole card is drawn — so every
   verdict the inbox can give stays reachable from the docket:

     image       an image proposal (a cloud image body, a catalog refresh, a Krea resume or
                 Enhance, a local image_generate tool call): its prompt and provider are shown
                 there and it cannot be edited
     consent     a reusable terminal consent offer (session / always / deny matching requests)
     retention   a data-retention change (panels/retention.tsx RETENTION_KIND)
     voice       a resident voice command (panels/voice-commands.tsx VOICE_COMMAND_KIND)
     guardian    a guardian's terminal verdict (judge.advisory === false): approved only through
                 the owner-once path the inbox draws

   The image predicates were the Decision Inbox's own closures (gap.tsx DecisionInboxPanel); they
   moved here unchanged and the inbox imports them, so the two surfaces cannot disagree about
   what an image proposal is. The two kind names mirror the panels' constants (model.test.ts,
   "mirror the panels' kind names", pins them equal) so the docket does not pull those panels
   into the main bundle. */
import type { DocketTask } from './types';

/** panels/retention.tsx RETENTION_KIND, mirrored. */
export const RETENTION_KIND = 'settings.retention';
/** panels/voice-commands.tsx VOICE_COMMAND_KIND, mirrored. */
export const VOICE_COMMAND_KIND = 'settings.voice_command';

export type SpecialKind = 'image' | 'consent' | 'retention' | 'voice' | 'guardian';

// ---- image proposals (moved verbatim from gap.tsx DecisionInboxPanel) ----------------------------

export const isCatalogRefreshProposal = (task: any): boolean => task.kind === 'plugin.egress'
  && task.payload?.plugin === 'cloud-image-deepinfra' && task.payload?.method === 'GET'
  && task.payload?.url === 'https://api.deepinfra.com/v1/openai/models?filter=true&sort_by=hermes'
  && task.payload?.image?.body?.operation === 'catalog_refresh'
  && task.payload?.image?.body?.prompt === '';

export const kreaEnhanceDetails = (task: any): { body: any; enhance: any } | null => {
  if (task.kind !== 'plugin.egress' || task.payload?.plugin !== 'cloud-image-krea'
    || !task.payload?.image?.body || !task.payload?.image?.enhance) return null;
  const { body, enhance } = task.payload.image;
  if (Object.keys(body).sort().join(',') !== 'image_scaling_factor,image_url,model,operation,prompt,size'
    || Object.keys(enhance).sort().join(',') !== 'artifact_id,binding,nonce,sha256,task_id'
    || body.operation !== 'enhance' || body.image_scaling_factor !== 2
    || !['krea-2-medium', 'krea-2-large', 'krea-2-medium-turbo'].includes(body.model)
    || typeof body.prompt !== 'string' || !body.prompt.trim() || body.prompt.length > 4000
    || !['1024x1024', '1536x1024', '1024x1536'].includes(body.size)
    || typeof body.image_url !== 'string' || body.image_url.length > 1024
    || !Number.isSafeInteger(enhance.task_id) || enhance.task_id < 1
    || typeof enhance.nonce !== 'string' || !/^[a-f0-9]{16,128}$/i.test(enhance.nonce)
    || typeof enhance.binding !== 'string' || !enhance.binding || enhance.binding.length > 256
    || typeof enhance.artifact_id !== 'string' || !/^[a-f0-9]{32}$/.test(enhance.artifact_id)
    || typeof enhance.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(enhance.sha256)) return null;
  try {
    const url = new URL(body.image_url);
    if (url.protocol !== 'https:' || !url.hostname || url.username || url.password || url.hash) return null;
  } catch { return null; }
  return { body, enhance };
};

export const isKreaEnhanceProposal = (task: any): boolean => task.payload?.method === 'POST'
  && task.payload?.url === 'https://api.krea.ai/generate/enhance/krea/enhance'
  && kreaEnhanceDetails(task) !== null;

export const isKreaResumeProposal = (task: any): boolean => {
  if (task.kind !== 'plugin.egress' || task.payload?.plugin !== 'cloud-image-krea'
    || task.payload?.method !== 'GET' || !task.payload?.image?.body) return false;
  const resume = task.payload.image.resume;
  return Number.isSafeInteger(resume?.task_id) && resume.task_id > 0
    && typeof resume.nonce === 'string' && typeof resume.binding === 'string'
    && typeof resume.job_id === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(resume.job_id)
    && (task.payload.image.body.operation !== 'enhance' || kreaEnhanceDetails(task) !== null)
    && task.payload.url === 'https://api.krea.ai/jobs/' + resume.job_id;
};

export const isCloudImageProposal = (task: any): boolean => {
  if (isCatalogRefreshProposal(task) || isKreaResumeProposal(task) || isKreaEnhanceProposal(task)) return true;
  if (task.kind !== 'plugin.egress' || task.payload?.method !== 'POST' || !task.payload?.image?.body) return false;
  const { plugin, url, image } = task.payload;
  if (plugin === 'cloud-image') return ['https://api.openai.com/v1/images/generations', 'https://api.openai.com/v1/images/edits'].includes(url);
  if (plugin === 'cloud-image-codex') return ['https://chatgpt.com/backend-api/codex/images/generations', 'https://chatgpt.com/backend-api/codex/images/edits'].includes(url);
  if (plugin === 'cloud-image-openrouter') return ['https://openrouter.ai/api/v1/images',
    'https://openrouter.ai/api/v1/chat/completions'].includes(url);
  if (plugin === 'cloud-image-xai') return ['https://api.x.ai/v1/images/generations', 'https://api.x.ai/v1/images/edits'].includes(url);
  if (plugin === 'cloud-image-deepinfra') return url === 'https://api.deepinfra.com/v1/openai/images/generations';
  if (plugin === 'cloud-image-krea') return ({
    'krea-2-medium': 'https://api.krea.ai/generate/image/krea/krea-2/medium',
    'krea-2-large': 'https://api.krea.ai/generate/image/krea/krea-2/large',
    'krea-2-medium-turbo': 'https://api.krea.ai/generate/image/krea/krea-2/medium-turbo',
  } as Record<string, string>)[image.body.model] === url;
  return plugin === 'cloud-image-fal' && typeof image.body.endpoint === 'string'
    && /^fal-ai\/[A-Za-z0-9_./-]{1,160}$/.test(image.body.endpoint) && url === 'https://fal.run/' + image.body.endpoint;
};

export const isImageProposal = (task: any): boolean => isCloudImageProposal(task) || (task.payload?.tool === 'image_generate'
  && (task.kind === 'toolrpc.image_generate'
    || (task.kind === 'tool.rpc' && task.payload?.target === 'image_generate')));

// ---- the docket's routing ------------------------------------------------------------------------

/** A request with an image body the inbox may draw specially. The docket is deliberately broader
 *  than isImageProposal: any plugin egress carrying an image body, or any image_generate tool call,
 *  opens in Decisions — sending a request there is always safe, signing one here unseen is not. */
export function looksLikeImage(task: DocketTask): boolean {
  const payload = (task.payload ?? null) as any;
  if (isImageProposal(task)) return true;
  if (!payload || typeof payload !== 'object') return false;
  if (task.kind === 'plugin.egress' && payload.image && typeof payload.image === 'object') return true;
  return payload.tool === 'image_generate' || task.kind === 'toolrpc.image_generate';
}

/** Which special kind a request is, or null. `consentOffered` is whether the feed sent a
 *  well-formed consent offer for it (docket/model.ts normaliseConsentOffer). */
export function specialKindOf(task: DocketTask, consentOffered: boolean): SpecialKind | null {
  if (consentOffered) return 'consent';
  const judge = task.judge as { advisory?: unknown } | null | undefined;
  if (judge && typeof judge === 'object' && judge.advisory === false) return 'guardian';
  if (task.kind === RETENTION_KIND) return 'retention';
  if (task.kind === VOICE_COMMAND_KIND) return 'voice';
  if (looksLikeImage(task)) return 'image';
  return null;
}
