import React, { useEffect, useRef, useState } from 'react';
import { Card, asLive, taS } from '../panel-kit';
import { appUrl } from '../base-path';
import { imageStatus, proposeCloudImage, proposeKreaResume, proposeKreaEnhance, proposeDeepInfraRefresh, cloudOptionsValid, type CloudImageOptions, type CloudImageProviderId, type CloudImageQuality, proposeImage, imageTask, imageBlob, editValid, type ImageCapability, type ImageTask } from '../api/images';

const cloudLabels: Record<CloudImageProviderId, string> = {
  openai: 'OpenAI', 'openai-codex': 'Codex OAuth', fal: 'FAL', openrouter: 'OpenRouter', krea: 'Krea', xai:'xAI', deepinfra:'DeepInfra',
};

const stateText: Record<ImageTask['state'], string> = {
  awaiting_approval: 'Awaiting approval in the Decision Inbox.', queued: 'Approved and queued.',
  generating: 'Generating the approved image.', ready: 'Generation completed; loading the saved image.',
  rejected: 'Proposal rejected.', deferred: 'Proposal deferred.', refused: 'Execution refused.',
  uncertain: 'Result uncertain. Check the task before making another proposal; generation may have started.',
};
const errorText = (error: any) => error?.code === 'auth'
  ? 'Owner authentication required. Set the current owner credentials, then check again.'
  : 'Image status or saved bytes unavailable. Check again when the connection is restored.';

function rememberTask(id:number|null) {
  const url = new URL(window.location.href);
  if (id === null) url.searchParams.delete('image_task');
  else url.searchParams.set('image_task',String(id));
  window.history.replaceState(window.history.state,'',url.pathname+url.search+url.hash);
}
function requestedTask() {
  const raw = new URLSearchParams(window.location.search).get('image_task') || '';
  const id = Number(raw);
  return /^[1-9][0-9]*$/.test(raw) && Number.isSafeInteger(id) ? id : null;
}
export function ImagesPanel() {
  const [configuration, setConfiguration] = useState<ImageCapability | null>(null);
  const [configError, setConfigError] = useState('');
  const [configVersion, setConfigVersion] = useState(0);
  const [prompt, setPrompt] = useState('');
  const [provider,setProvider] = useState<'local'|'cloud'>('local');
  const [size,setSize] = useState<CloudImageOptions['size']>('1024x1024');
  const [quality,setQuality] = useState<CloudImageQuality>('low');
  const [cloudBackend,setCloudBackend] = useState<CloudImageProviderId | ''>('');
  const [cloudCatalogSeen,setCloudCatalogSeen] = useState(false);
  const [cloudModel,setCloudModel] = useState('');
  const [cloudMode,setCloudMode] = useState<'create'|'edit'>('create');
  const [cloudReferences,setCloudReferences] = useState('');
  const [kreaCreativity,setKreaCreativity] = useState<'raw'|'low'|'medium'|'high'>('medium');
  const [kreaUseStyle,setKreaUseStyle] = useState(false);
  const [kreaStyleUrls,setKreaStyleUrls] = useState('');
  const [xaiQuality,setXaiQuality] = useState<'auto'|'low'|'medium'>('auto');
  const [xaiResolution,setXaiResolution] = useState<'1k'|'2k'>('1k');
  const [catalogRefreshTaskId,setCatalogRefreshTaskId] = useState<number|null>(null);
  const [catalogRefreshAttempted,setCatalogRefreshAttempted] = useState(false);
  const [mode, setMode] = useState<'create' | 'edit'>('create');
  const [reference, setReference] = useState('');
  const [strength, setStrength] = useState(60);
  const [additionalReferences, setAdditionalReferences] = useState('');
  const [backend, setBackend] = useState('');
  const [model, setModel] = useState('');
  const [upscale, setUpscale] = useState(false);
  const [existingId, setExistingId] = useState('');
  const [submitted, setSubmitted] = useState<string | null>(()=>requestedTask() ? "" : null);
  const [taskId, setTaskId] = useState<number | null>(requestedTask);
  const [task, setTask] = useState<ImageTask | null>(null);
  const [watching, setWatching] = useState(()=>requestedTask() !== null);
  const [readVersion, setReadVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [enhanceSource,setEnhanceSource] = useState<{taskId:number; artifact:NonNullable<ImageTask['artifact']>; url:string}|null>(null);
  const [enhanceAttempted,setEnhanceAttempted] = useState(false);
  const epoch = useRef(0);
  const submitting = useRef<AbortController | null>(null);
  const continuationSource = useRef<number|null>(null);
  const enhanceSourceRef = useRef<{taskId:number; artifact:NonNullable<ImageTask['artifact']>; url:string}|null>(null);
  const revokedUrls = useRef(new Set<string>());
  const releaseUrl = (url:string) => { if (!revokedUrls.current.has(url)) { revokedUrls.current.add(url); URL.revokeObjectURL(url); } };

  useEffect(() => {
    const controller = new AbortController();
    setConfiguration(null); setConfigError('');
    imageStatus(controller.signal).then(value => {
      if (!controller.signal.aborted) {
        if (value.cloudProviders?.length) {
          setCloudCatalogSeen(true);
          setCloudBackend(current => current || value.cloudProviders!.find(p=>p.id === 'openai')?.id || value.cloudProviders![0].id);
        }
        setConfiguration(value);
      }
    }).catch(error => { if (!controller.signal.aborted) setConfigError(errorText(error)); });
    return () => controller.abort();
  }, [configVersion]);
  useEffect(() => () => { epoch.current++; submitting.current?.abort(); if (enhanceSourceRef.current) releaseUrl(enhanceSourceRef.current.url); }, []);

  useEffect(() => {
    if (!taskId || !watching) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let ownedUrl: string | null = null;
    let reads = 0;
    setImageUrl(null); setMessage('Checking the saved task…');
    const poll = async () => {
      try {
        const next = await imageTask(taskId, controller.signal);
        if (controller.signal.aborted) return;
        setTask(next); setMessage(stateText[next.state]);
        if (next.state === 'ready') {
          const blob = await imageBlob(next.artifact!, controller.signal);
          if (controller.signal.aborted) return;
          ownedUrl = URL.createObjectURL(blob);
          setImageUrl(ownedUrl); setMessage('Saved image ready.');
        } else if (['awaiting_approval', 'queued', 'generating'].includes(next.state)) {
          if (++reads < 120) timer = setTimeout(poll, 1500);
          else setMessage('Automatic watching paused. Check status to continue; the server task may continue.');
        }
      } catch (error) { if (!controller.signal.aborted) setMessage(errorText(error)); }
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); if (ownedUrl && ownedUrl !== enhanceSourceRef.current?.url) releaseUrl(ownedUrl); };
  }, [taskId, watching, readVersion]);

  const extras = additionalReferences.split(/[\s,]+/).filter(Boolean);
  const selectedBackend = configuration?.backends?.find(b => b.id === (backend || configuration.backend || 'comfyui'));
  const canEdit = selectedBackend?.edit ?? configuration?.edit ?? false;
  const canUpscale = (selectedBackend?.upscale ?? configuration?.upscale)?.includes(2) ?? false;
  const editing = mode === 'edit' && canEdit;
  const selection = { ...(backend ? {backend} : {}), ...(model ? {model} : {}), ...(upscale && canUpscale ? {upscale:2} : {}) };
  const edit = editing ? { ...(extras.length ? {references:[reference.trim(), ...extras]} : {reference:reference.trim()}), strength, ...selection }
    : Object.keys(selection).length ? selection : null;
  const cloudProvider = configuration?.cloudProviders?.find(p => p.id === cloudBackend);
  const selectedCloudModel = cloudModel
    ? cloudProvider?.models.includes(cloudModel) ? cloudModel : undefined
    : cloudProvider?.default_model;
  const cloudCapability = selectedCloudModel ? cloudProvider?.model_capabilities[selectedCloudModel] : undefined;
  const cloudCanEdit = cloudCapability?.edit === true;
  const cloudEditing = cloudMode === 'edit' && cloudCanEdit;
  const cloudRefs = cloudReferences.split(/\r?\n/).map(ref => ref.trim()).filter(Boolean);
  const kreaStyleGuided = cloudProvider?.id === 'krea' && cloudCapability?.style_guided === true;
  const kreaRefs = kreaStyleUrls.split(/\r?\n/).map(ref => ref.trim()).filter(Boolean);
  const cloudQuality = !cloudCatalogSeen || (cloudProvider?.id === 'openai' && selectedCloudModel === 'gpt-image-1.5');
  const cloudOptions: CloudImageOptions | null = cloudProvider && selectedCloudModel
    ? cloudProvider.id === 'krea'
      ? {size, backend:'krea', model:selectedCloudModel, creativity:kreaCreativity,
        ...(kreaUseStyle ? {image_style_references:kreaRefs} : {})}
      : cloudProvider.id === 'xai'
        ? {size,backend:'xai',model:selectedCloudModel,
          ...(selectedCloudModel === 'grok-imagine-image-2.0' ? {quality:xaiQuality} : {}),
          ...(cloudEditing ? {references:cloudRefs} : {resolution:xaiResolution})}
      : {size, backend:cloudProvider.id, model:selectedCloudModel, ...(cloudQuality ? {quality} : {}),
        ...(cloudEditing ? {references:cloudRefs} : {})} : cloudCatalogSeen ? null : {size, quality};
  const configured = provider === 'cloud' ? cloudCatalogSeen ? cloudProvider?.enabled && cloudProvider.configured
    : configuration?.cloud?.configured : configuration?.configured;
  const submittable = !!configured && !!prompt.trim() && (provider === 'cloud'
    ? cloudOptionsValid(cloudOptions) && (cloudMode !== 'edit' || cloudCanEdit)
      && (!cloudEditing || cloudRefs.length <= (cloudCapability?.max_reference_images ?? 0))
      && (!kreaUseStyle || (kreaStyleGuided && kreaRefs.length <= (cloudCapability?.max_style_references ?? 0)))
    : edit === null || editValid(edit));

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (submitting.current || submitted !== null || !submittable) return;
    const controller = new AbortController(); submitting.current = controller;
    const current = epoch.current;
    setSubmitted(prompt); setBusy(true); setMessage('Submitting one proposal…');
    try {
      const id = provider === 'cloud' ? await proposeCloudImage(prompt, cloudOptions!, controller.signal) : await proposeImage(prompt, edit, controller.signal);
      if (epoch.current !== current) return;
      rememberTask(id); setTaskId(id); setWatching(true);
      window.dispatchEvent(new Event('nerva:image-proposed'));
    } catch (error) {
      if (epoch.current !== current) return;
      setMessage(error?.code === 'auth' ? errorText(error)
        : error?.code === 'refused' ? 'Proposal refused. Review the selected generation setup before making a new proposal.'
          : 'Proposal response lost or unclear. Check the Decision Inbox before making another proposal; it may already exist.');
    } finally { if (epoch.current === current) { submitting.current = null; setBusy(false); } }
  };
  const reset = () => {
    epoch.current++; submitting.current?.abort(); submitting.current = null;
    continuationSource.current = null;
    if (enhanceSourceRef.current) releaseUrl(enhanceSourceRef.current.url);
    enhanceSourceRef.current = null; setEnhanceSource(null); setEnhanceAttempted(false);
    rememberTask(null); setSubmitted(null); setBusy(false); setTaskId(null); setTask(null);
    setWatching(false); setImageUrl(null); setMessage('');
  };
  const check = () => { setWatching(true); setReadVersion(value => value + 1); };
  const resumeSavedJob = async () => {
    if (!taskId || task?.resume_available !== true || !['uncertain','generating'].includes(task.state)
      || continuationSource.current === taskId || submitting.current) return;
    continuationSource.current = taskId;
    const controller = new AbortController(); submitting.current = controller;
    const current = epoch.current;
    setBusy(true); setMessage('Submitting one continuation proposal…');
    try {
      const id = await proposeKreaResume(taskId,controller.signal);
      if (epoch.current !== current) return;
      rememberTask(id); setTaskId(id); setTask(null); setWatching(true);
      window.dispatchEvent(new Event('nerva:image-proposed'));
    } catch (error) {
      if (epoch.current !== current) return;
      setMessage(error?.code === 'auth' ? errorText(error) : error?.code === 'refused'
        ? 'Continuation refused. Check the saved job and configuration.'
        : 'Continuation response lost or unclear. Check the Decision Inbox; do not queue it again.');
    } finally { if (epoch.current === current) { submitting.current = null; setBusy(false); } }
  };
  const enhanceSavedImage = async () => {
    if (!taskId || task?.state !== 'ready' || task.enhance_available !== true || !task.artifact
      || !imageUrl || enhanceAttempted || submitting.current) return;
    setEnhanceAttempted(true);
    const source = {taskId,artifact:task.artifact,url:imageUrl};
    const controller = new AbortController(); submitting.current = controller;
    const current = epoch.current;
    setBusy(true); setMessage('Submitting one Krea Enhance proposal…');
    try {
      const id = await proposeKreaEnhance(taskId,controller.signal);
      if (epoch.current !== current) return;
      enhanceSourceRef.current = source; setEnhanceSource(source);
      rememberTask(id); setTaskId(id); setTask(null); setWatching(true);
      window.dispatchEvent(new Event('nerva:image-proposed'));
    } catch (error) {
      if (epoch.current !== current) return;
      setMessage(error?.code === 'auth' ? errorText(error) : error?.code === 'refused'
        ? 'Enhance proposal refused. Check the source image and configuration.'
        : 'Enhance response lost or unclear. Check the Decision Inbox; do not queue it again.');
    } finally { if (epoch.current === current) { submitting.current = null; setBusy(false); } }
  };
  const refreshDeepInfra = async () => {
    if (catalogRefreshAttempted || submitting.current || cloudProvider?.id !== 'deepinfra'
      || cloudProvider.catalog_refresh_available !== true) return;
    setCatalogRefreshAttempted(true);
    const controller = new AbortController(); submitting.current = controller;
    const current = epoch.current;
    setBusy(true); setMessage('Submitting one catalog refresh proposal…');
    try {
      const id = await proposeDeepInfraRefresh(controller.signal);
      if (epoch.current !== current) return;
      setCatalogRefreshTaskId(id); setMessage('Catalog refresh awaits approval. After approval, check configuration.');
      window.dispatchEvent(new Event('nerva:image-proposed'));
    } catch (error) {
      if (epoch.current !== current) return;
      setMessage(error?.code === 'auth' ? errorText(error) : error?.code === 'refused'
        ? 'Catalog refresh refused.' : 'Catalog refresh response lost or unclear. Check the Decision Inbox; do not queue it again.');
    } finally { if (epoch.current === current) { submitting.current = null; setBusy(false); } }
  };
  return <Card title="IMAGES" sub="Image generation · owner instance" live={asLive(configuration)}>
    <p style={{ fontSize: 12 }}>Propose an image, approve its exact prompt in the Decision Inbox, then view the saved PNG here.</p>
    <div role="status" style={{ fontSize: 12 }}>
      {configError || (configuration ? configured ? 'Configured · connection untested.'
        : provider === 'cloud' ? 'Cloud image generation is disabled or incomplete.' : 'Local image generation is disabled or incomplete.' : 'Checking configuration…')}
    </div>
    <button className="tool-btn" onClick={() => setConfigVersion(value => value + 1)}>Check configuration</button>
    {submitted === null && message && <div role="status" style={{fontSize:12}}>{message}</div>}
    {catalogRefreshTaskId && <p>Catalog refresh task {catalogRefreshTaskId} · review it in the <a href={appUrl('/v2/console/decision-inbox')}>Decision Inbox</a>, then check configuration.</p>}
    {submitted === null ? <><form onSubmit={submit}>
      <label>Image provider <select aria-label="Image provider" value={provider} onChange={e=>{setProvider(e.target.value as 'local'|'cloud'); setCloudMode('create'); setCloudReferences(''); setKreaUseStyle(false); setKreaStyleUrls('');}}>
        <option value="local">Local image service</option>{(configuration?.cloud || cloudCatalogSeen) && <option value="cloud">{cloudCatalogSeen ? 'Cloud image providers' : 'OpenAI cloud'}</option>}
      </select></label>
      {provider === 'cloud' && <div>
        {cloudCatalogSeen && <>
          <label>Cloud image provider <select aria-label="Cloud image provider" value={cloudBackend} onChange={e=>{
            setCloudBackend(e.target.value as CloudImageProviderId); setCloudModel(''); setCloudMode('create'); setCloudReferences('');
            setKreaUseStyle(false); setKreaStyleUrls(''); setKreaCreativity('medium');
          }}>{!cloudProvider && <option value={cloudBackend}>{cloudBackend ? cloudLabels[cloudBackend] : 'Provider'} · unavailable</option>}
            {configuration?.cloudProviders?.map(p=><option key={p.id} value={p.id}>{cloudLabels[p.id]}{p.configured && p.enabled ? '' : ' · setup required'}</option>)}</select></label>
          {cloudProvider && cloudProvider.models.length > 0 && <label>Cloud image model <select aria-label="Cloud image model" value={selectedCloudModel} onChange={e=>{
            setCloudModel(e.target.value); setCloudMode('create'); setCloudReferences(''); setKreaUseStyle(false); setKreaStyleUrls('');
          }}>{cloudProvider.models.map(m=><option key={m} value={m}>{m}</option>)}</select></label>}
        </>}
        <p>{cloudBackend ? cloudLabels[cloudBackend] : 'OpenAI'} · {selectedCloudModel || (cloudCatalogSeen ? 'model unavailable' : 'gpt-image-1.5')} · {cloudBackend === 'openai-codex' ? 'uses the configured Codex account after approval.' : 'potentially paid after approval.'}</p>
        {!configured && <p>Configure this provider on the hub, then check configuration.</p>}
        {cloudProvider?.id === 'deepinfra' && cloudProvider.catalog_refresh_available && <button className="tool-btn" type="button"
          disabled={catalogRefreshAttempted || busy} onClick={refreshDeepInfra}>Refresh DeepInfra catalog for approval</button>}
        <label>Cloud image size <select aria-label="Cloud image size" value={size} onChange={e=>setSize(e.target.value as CloudImageOptions['size'])}>{['1024x1024','1536x1024','1024x1536'].map(v=><option key={v}>{v}</option>)}</select></label>
        {cloudQuality && <label>Cloud image quality <select aria-label="Cloud image quality" value={quality} onChange={e=>setQuality(e.target.value as CloudImageQuality)}>{['low','medium','high'].map(v=><option key={v}>{v}</option>)}</select></label>}
        {cloudProvider?.id === 'xai' && selectedCloudModel === 'grok-imagine-image-2.0' && <label>xAI quality <select aria-label="xAI quality" value={xaiQuality} onChange={e=>setXaiQuality(e.target.value as typeof xaiQuality)}>{['auto','low','medium'].map(v=><option key={v}>{v}</option>)}</select></label>}
        {cloudProvider?.id === 'xai' && !cloudEditing && <label>xAI resolution <select aria-label="xAI resolution" value={xaiResolution} onChange={e=>setXaiResolution(e.target.value as typeof xaiResolution)}>{['1k','2k'].map(v=><option key={v}>{v}</option>)}</select></label>}
        {cloudProvider?.id === 'krea' && <label>Krea creativity <select aria-label="Krea creativity" value={kreaCreativity}
          onChange={e=>setKreaCreativity(e.target.value as typeof kreaCreativity)}>
          {['raw','low','medium','high'].map(v=><option key={v}>{v}</option>)}
        </select></label>}
        {kreaStyleGuided && <label><input aria-label="Use style references" type="checkbox" checked={kreaUseStyle}
          onChange={e=>{setKreaUseStyle(e.target.checked); if (!e.target.checked) setKreaStyleUrls('');}} />Use style references for generation</label>}
      </div>}
      {(provider === 'local' ? canEdit : cloudCanEdit) && <div role="radiogroup" aria-label="Generation mode" style={{ marginTop: 10, fontSize: 12 }}>
        <label style={{ marginRight: 12 }}>
          <input type="radio" name="image-mode" checked={(provider === 'local' ? mode : cloudMode) === 'create'} onChange={() => provider === 'local' ? setMode('create') : setCloudMode('create')} /> New image
        </label>
        <label>
          <input type="radio" name="image-mode" checked={(provider === 'local' ? mode : cloudMode) === 'edit'} onChange={() => provider === 'local' ? setMode('edit') : setCloudMode('edit')} /> Edit an image
        </label>
      </div>}
      {provider === "local" && !!configuration?.backends?.length && <div>
        <label>Image backend <select aria-label="Image backend" value={backend} onChange={e => {setBackend(e.target.value); setModel(''); setMode('create'); setUpscale(false); setReference(''); setAdditionalReferences('');}}>
          <option value="">Hub default</option>{configuration.backends.map(b => <option key={b.id} value={b.id}>{b.id} · {b.protocol === 'openai_images' ? 'local images API' : 'local ComfyUI'}</option>)}
        </select></label>
        <label>Image model <select aria-label="Image model" value={model} onChange={e => setModel(e.target.value)}>
          <option value="">Backend default</option>{selectedBackend?.models.map(m => <option key={m} value={m}>{m}</option>)}
        </select></label>
      </div>}
      {provider === "local" && canUpscale && <label><input aria-label="2× bicubic upscale" type="checkbox" checked={upscale} onChange={e => setUpscale(e.target.checked)} />2× bicubic upscale</label>}
      <label style={{ display: 'block', marginTop: 10 }}>Image prompt
        <textarea aria-label="Image prompt" value={prompt} maxLength={4000} required style={{ ...taS, minHeight: 100 }}
          onChange={event => setPrompt(event.target.value)} />
      </label>
      {provider === 'cloud' && cloudEditing && <label style={{display:'block',fontSize:12}}>
        {cloudCapability?.reference_kind === 'fal_media_url' ? 'Cloud reference image URLs' : 'Cloud reference artifact IDs'}
        <textarea aria-label={cloudCapability?.reference_kind === 'fal_media_url' ? 'Cloud reference image URLs' : 'Cloud reference artifact IDs'}
          value={cloudReferences} required maxLength={16 * 2049} style={taS} onChange={e=>setCloudReferences(e.target.value)} />
        <small>One {cloudCapability?.reference_kind === 'fal_media_url' ? 'HTTPS fal.media URL' : 'saved artifact ID'} per line · maximum {cloudCapability?.max_reference_images}.</small>
      </label>}
      {provider === 'cloud' && kreaStyleGuided && kreaUseStyle && <label style={{display:'block',fontSize:12}}>
        Krea style reference URLs
        <textarea aria-label="Krea style reference URLs" value={kreaStyleUrls} required maxLength={10 * 2049}
          style={taS} onChange={e=>setKreaStyleUrls(e.target.value)} />
        <small>One explicit HTTPS style URL per line · maximum {cloudCapability?.max_style_references}. Style-guided generation does not edit a source image.</small>
      </label>}
      {provider === 'local' && editing ? <>
        <label style={{ display: 'block', fontSize: 12 }}>Reference artifact ID
          <input aria-label="Reference artifact ID" value={reference} required pattern="[a-f0-9]{32}"
            onChange={event => setReference(event.target.value.trim())} style={{ width: '100%' }} />
        </label>
        {(selectedBackend?.max_references ?? configuration?.max_references ?? 1) > 1 && <label>Additional reference IDs (up to three, comma separated)
          <input aria-label="Additional reference IDs" value={additionalReferences} maxLength={100} onChange={e => setAdditionalReferences(e.target.value)} />
          <small>References are resized to the first image and blended equally before editing.</small>
        </label>}
        <label style={{ display: 'block', fontSize: 12 }}>Change strength · {strength}%
          <input aria-label="Change strength" type="range" min={1} max={100} value={strength}
            onChange={event => setStrength(Number(event.target.value))} style={{ width: '100%' }} />
        </label>
        <div style={{ fontSize: 11, margin: '5px 0' }}>Keeps the reference's own size · 20 steps · random seed · local service only</div>
      </> : provider === 'local' ? <div style={{ fontSize: 11, margin: '5px 0' }}>{selectedBackend?.protocol === 'openai_images' ? '512 × 512 · local service only' : '512 × 512 · 20 steps · random seed · local service only'}</div> : null}
      <button className="tool-btn" type="submit" disabled={!submittable}>{(provider === 'local' ? editing : cloudEditing)
        ? 'Propose edit' : provider === 'cloud' && cloudProvider?.id === 'krea' && kreaUseStyle
          ? 'Propose style-guided image' : 'Propose image'}</button>
    </form>
      <form style={{ marginTop: 12 }} onSubmit={event => {
        event.preventDefault();
        const id = Number(existingId);
        if (!/^\d+$/.test(existingId) || !Number.isSafeInteger(id) || id < 1) return;
        rememberTask(id); setSubmitted(''); setTaskId(id); setWatching(true);
      }}>
        <label style={{ fontSize: 12 }}>Existing image task ID
          <input aria-label="Existing image task ID" value={existingId} inputMode="numeric" pattern="[0-9]+" required
            onChange={event => setExistingId(event.target.value)} style={{ width: '100%' }} />
        </label>
        <button className="tool-btn" type="submit">Watch existing task</button>
      </form></> : <>
      {submitted && <p style={{ fontSize: 12, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{submitted}</p>}
      {taskId && <p style={{ fontSize: 12 }}>Task {taskId}</p>}
      <div role="status" aria-live="polite" style={{ fontSize: 12, margin: '8px 0' }}>{message}</div>
      <a href={appUrl("/v2/console/decision-inbox")} style={{ color: 'var(--accent-light)' }}>Open Decision Inbox</a>
      {taskId && <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
        <button className="tool-btn" onClick={check}>Check status</button>
        {task?.resume_available === true && ['uncertain','generating'].includes(task.state) && <button className="tool-btn"
          disabled={busy || continuationSource.current === taskId} onClick={resumeSavedJob}>Resume saved job</button>}
        {task?.state === 'ready' && task.enhance_available === true && imageUrl && !enhanceAttempted && <button className="tool-btn"
          disabled={busy} onClick={enhanceSavedImage}>Propose Enhance 2×</button>}
        {watching && !imageUrl && <button className="tool-btn" onClick={() => {
          setWatching(false); setMessage('Watching stopped; the server task may continue.');
        }}>Stop watching</button>}
      </div>}
      {enhanceSource && <figure style={{margin:'12px 0'}}>
        <p>Original image · task {enhanceSource.taskId}</p>
        <img src={enhanceSource.url} alt="Original image" width={enhanceSource.artifact.width} height={enhanceSource.artifact.height}
          style={{width:'100%',height:'auto',display:'block'}} />
        <figcaption style={{fontSize:11}}><a href={enhanceSource.url} download={'nerva-image-'+enhanceSource.artifact.id+'.png'}>Download original PNG</a>
          <span style={{overflowWrap:'anywhere'}}> · {enhanceSource.artifact.id}</span></figcaption>
      </figure>}
      {imageUrl && task?.artifact && <figure style={{ margin: '12px 0' }}>
        <img src={imageUrl} alt="Generated image" width={task.artifact.width} height={task.artifact.height}
          style={{ width: '100%', height: 'auto', display: 'block' }} />
        <figcaption style={{ fontSize: 11 }}>
          <a href={imageUrl} download={'nerva-image-' + task.artifact.id + '.png'} style={{ color: 'var(--accent-light)' }}>Download PNG</a>
          <span style={{ overflowWrap: 'anywhere' }}> · {task.artifact.id}</span>
        </figcaption>
        {(provider === 'local' ? canEdit : cloudCanEdit && cloudCapability?.reference_kind === 'artifact_id') && <button className="tool-btn" onClick={() => {
          const id = task.artifact!.id;
          reset();
          if (provider === 'cloud') {setCloudMode('edit'); setCloudReferences(id);}
          else {setMode('edit'); setReference(id);}
        }}>Edit this image</button>}
      </figure>}
      <p><a href={appUrl("/v2/console/media-gallery")}>Open Media Gallery</a> · Catalog recording must be enabled for generated images to appear there.</p>
      <p style={{ fontSize: 11 }}>A new proposal is a separate request. It does not cancel an earlier task.</p>
      <button className="tool-btn" disabled={busy} onClick={reset}>New proposal</button>
    </>}
  </Card>;
}
