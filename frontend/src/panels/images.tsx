import React, { useEffect, useRef, useState } from 'react';
import { Card, asLive, taS } from '../panel-kit';
import { imageStatus, proposeImage, imageTask, imageBlob, editValid, type ImageCapability, type ImageTask } from '../api/images';

const stateText: Record<ImageTask['state'], string> = {
  awaiting_approval: 'Awaiting approval in the Decision Inbox.', queued: 'Approved and queued.',
  generating: 'Generating on the local service.', ready: 'Generation completed; loading the saved image.',
  rejected: 'Proposal rejected.', deferred: 'Proposal deferred.', refused: 'Execution refused.',
  uncertain: 'Result uncertain. Check the task before making another proposal; generation may have started.',
};
const errorText = (error: any) => error?.code === 'auth'
  ? 'Owner authentication required. Set the current owner credentials, then check again.'
  : 'Image status or saved bytes unavailable. Check again when the connection is restored.';

export function ImagesPanel() {
  const [configuration, setConfiguration] = useState<ImageCapability | null>(null);
  const [configError, setConfigError] = useState('');
  const [configVersion, setConfigVersion] = useState(0);
  const [prompt, setPrompt] = useState('');
  const [mode, setMode] = useState<'create' | 'edit'>('create');
  const [reference, setReference] = useState('');
  const [strength, setStrength] = useState(60);
  const [existingId, setExistingId] = useState('');
  const [submitted, setSubmitted] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<number | null>(null);
  const [task, setTask] = useState<ImageTask | null>(null);
  const [watching, setWatching] = useState(false);
  const [readVersion, setReadVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const epoch = useRef(0);
  const submitting = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setConfiguration(null); setConfigError('');
    imageStatus(controller.signal).then(value => {
      if (!controller.signal.aborted) setConfiguration(value);
    }).catch(error => { if (!controller.signal.aborted) setConfigError(errorText(error)); });
    return () => controller.abort();
  }, [configVersion]);
  useEffect(() => () => { epoch.current++; submitting.current?.abort(); }, []);

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
    return () => { controller.abort(); clearTimeout(timer); if (ownedUrl) URL.revokeObjectURL(ownedUrl); };
  }, [taskId, watching, readVersion]);

  const edit = mode === 'edit' ? { reference: reference.trim(), strength } : null;
  const submittable = !!configuration?.configured && !!prompt.trim() && (edit === null || editValid(edit));

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (submitting.current || submitted !== null || !submittable) return;
    const controller = new AbortController(); submitting.current = controller;
    const current = epoch.current;
    setSubmitted(prompt); setBusy(true); setMessage('Submitting one proposal…');
    try {
      const id = await proposeImage(prompt, edit, controller.signal);
      if (epoch.current !== current) return;
      setTaskId(id); setWatching(true);
      window.dispatchEvent(new Event('nerva:image-proposed'));
    } catch (error) {
      if (epoch.current !== current) return;
      setMessage(error?.code === 'auth' ? errorText(error)
        : error?.code === 'refused' ? 'Proposal refused. Review the local generation setup before making a new proposal.'
          : 'Proposal response lost or unclear. Check the Decision Inbox before making another proposal; it may already exist.');
    } finally { if (epoch.current === current) { submitting.current = null; setBusy(false); } }
  };
  const reset = () => {
    epoch.current++; submitting.current?.abort(); submitting.current = null;
    setSubmitted(null); setBusy(false); setTaskId(null); setTask(null);
    setWatching(false); setImageUrl(null); setMessage('');
  };
  const check = () => { setWatching(true); setReadVersion(value => value + 1); };
  return <Card title="IMAGES" sub="Local generation · owner instance" live={asLive(configuration)}>
    <p style={{ fontSize: 12 }}>Propose an image, approve its exact prompt in the Decision Inbox, then view the saved PNG here.</p>
    <div role="status" style={{ fontSize: 12 }}>
      {configError || (configuration ? configuration.configured ? 'Configured · connection untested.'
        : 'Local image generation is disabled or incomplete.' : 'Checking configuration…')}
    </div>
    <button className="tool-btn" onClick={() => setConfigVersion(value => value + 1)}>Check configuration</button>
    {submitted === null ? <><form onSubmit={submit}>
      {configuration?.edit && <div role="radiogroup" aria-label="Generation mode" style={{ marginTop: 10, fontSize: 12 }}>
        <label style={{ marginRight: 12 }}>
          <input type="radio" name="image-mode" checked={mode === 'create'} onChange={() => setMode('create')} /> New image
        </label>
        <label>
          <input type="radio" name="image-mode" checked={mode === 'edit'} onChange={() => setMode('edit')} /> Edit an image
        </label>
      </div>}
      <label style={{ display: 'block', marginTop: 10 }}>Image prompt
        <textarea aria-label="Image prompt" value={prompt} maxLength={4000} required style={{ ...taS, minHeight: 100 }}
          onChange={event => setPrompt(event.target.value)} />
      </label>
      {mode === 'edit' ? <>
        <label style={{ display: 'block', fontSize: 12 }}>Reference artifact ID
          <input aria-label="Reference artifact ID" value={reference} required pattern="[a-f0-9]{32}"
            onChange={event => setReference(event.target.value.trim())} style={{ width: '100%' }} />
        </label>
        <label style={{ display: 'block', fontSize: 12 }}>Change strength · {strength}%
          <input aria-label="Change strength" type="range" min={1} max={100} value={strength}
            onChange={event => setStrength(Number(event.target.value))} style={{ width: '100%' }} />
        </label>
        <div style={{ fontSize: 11, margin: '5px 0' }}>Keeps the reference's own size · 20 steps · random seed · local service only</div>
      </> : <div style={{ fontSize: 11, margin: '5px 0' }}>512 × 512 · 20 steps · random seed · local service only</div>}
      <button className="tool-btn" type="submit" disabled={!submittable}>{mode === 'edit' ? 'Propose edit' : 'Propose image'}</button>
    </form>
      <form style={{ marginTop: 12 }} onSubmit={event => {
        event.preventDefault();
        const id = Number(existingId);
        if (!/^\d+$/.test(existingId) || !Number.isSafeInteger(id) || id < 1) return;
        setSubmitted(''); setTaskId(id); setWatching(true);
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
      <a href="#decision-inbox" style={{ color: 'var(--accent-light)' }}>Open Decision Inbox</a>
      {taskId && <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
        <button className="tool-btn" onClick={check}>Check status</button>
        {watching && !imageUrl && <button className="tool-btn" onClick={() => {
          setWatching(false); setMessage('Watching stopped; the server task may continue.');
        }}>Stop watching</button>}
      </div>}
      {imageUrl && task?.artifact && <figure style={{ margin: '12px 0' }}>
        <img src={imageUrl} alt="Generated image" width={task.artifact.width} height={task.artifact.height}
          style={{ width: '100%', height: 'auto', display: 'block' }} />
        <figcaption style={{ fontSize: 11 }}>
          <a href={imageUrl} download={'nerva-image-' + task.artifact.id + '.png'} style={{ color: 'var(--accent-light)' }}>Download PNG</a>
          <span style={{ overflowWrap: 'anywhere' }}> · {task.artifact.id}</span>
        </figcaption>
        {configuration?.edit && <button className="tool-btn" onClick={() => {
          const id = task.artifact!.id;
          reset(); setMode('edit'); setReference(id);
        }}>Edit this image</button>}
      </figure>}
      <p style={{ fontSize: 11 }}>A new proposal is a separate request. It does not cancel an earlier task.</p>
      <button className="tool-btn" disabled={busy} onClick={reset}>New proposal</button>
    </>}
  </Card>;
}
