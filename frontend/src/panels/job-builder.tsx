import React, { useState } from 'react';
import { inpS } from '../panel-kit';

export type JobOptions = { repeat?: number | null; deliver?: string[] };

export function ScheduleBuilder({ onChange }: { onChange: (value: string) => void }) {
  const [mode, setMode] = useState('daily');
  const [time, setTime] = useState('09:00');
  const [day, setDay] = useState('1');
  const [interval, setInterval] = useState('30');
  function update(m: string, t: string, d: string, i: string) {
    const [h, minute] = t.split(':').map(Number);
    if (m === 'interval') onChange(`*/${i} * * * *`);
    else if (Number.isFinite(h) && Number.isFinite(minute)) onChange(`${minute} ${h} * * ${m === 'weekdays' ? '1-5' : m === 'weekly' ? d : '*'}`);
  }
  return <fieldset style={{ border: '1px solid var(--panel-line)', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
    <legend>Visual schedule (hub timezone)</legend>
    <select aria-label="schedule mode" style={inpS} value={mode} onChange={e => { setMode(e.target.value); update(e.target.value,time,day,interval); }}>
      <option value="daily">Daily</option><option value="weekdays">Weekdays</option><option value="weekly">Weekly</option><option value="interval">Every few minutes</option>
    </select>
    {mode !== 'interval' && <input aria-label="schedule time" type="time" style={inpS} value={time} onChange={e => { setTime(e.target.value); update(mode,e.target.value,day,interval); }} />}
    {mode === 'weekly' && <select aria-label="schedule day" style={inpS} value={day} onChange={e => { setDay(e.target.value); update(mode,time,e.target.value,interval); }}>
      {['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'].map((name,i) => <option key={i} value={i}>{name}</option>)}
    </select>}
    {mode === 'interval' && <select aria-label="schedule interval" style={inpS} value={interval} onChange={e => { setInterval(e.target.value); update(mode,time,day,e.target.value); }}>
      {[5,10,15,20,30].map(n=><option key={n} value={n}>{n} minutes</option>)}
    </select>}
    <button className="tool-btn" type="button" onClick={()=>update(mode,time,day,interval)}>use schedule</button>
  </fieldset>;
}

export function OptionsEditor({value,onChange}: {value:JobOptions;onChange:(v:JobOptions)=>void}) {
  const mode = value.deliver === undefined ? 'default' : value.deliver.length === 0 ? 'history' : 'channels';
  return <fieldset style={{border:'1px solid var(--panel-line)',display:'grid',gap:6}}>
    <legend>Advanced</legend>
    <label>Maximum attempts (blank = unlimited)<input aria-label="maximum attempts" type="number" min="1" max="10000" style={inpS} value={value.repeat ?? ''} onChange={e=>onChange({...value,repeat:e.target.value ? Number(e.target.value):null})}/></label>
    <label>Delivery <select aria-label="delivery mode" style={inpS} value={mode} onChange={e=>{
      const next={...value}; if(e.target.value==='default') delete next.deliver; else next.deliver=e.target.value==='history'?[]:['telegram']; onChange(next);
    }}><option value="default">Default owner channel</option><option value="history">Run history only</option><option value="channels">Configured owner channels</option></select></label>
    {mode==='channels' && <label>Channel names, separated by commas<input aria-label="delivery channels" style={inpS} value={value.deliver?.join(', ') ?? ''} onChange={e=>onChange({...value,deliver:e.target.value.split(',').map(x=>x.trim())})}/></label>}
    <small>Attempts include failures. Delivery keeps quiet hours and interrupt limits. Channels must already be configured for the owner.</small>
  </fieldset>;
}

export function JobBuilder({onSave}: {onSave:(body:Record<string,unknown>)=>void}) {
  const [name,setName]=useState(''); const [when,setWhen]=useState('0 9 * * *');
  const [kind,setKind]=useState('remind'); const [text,setText]=useState('');
  const [agent,setAgent]=useState('jarvis'); const [brief,setBrief]=useState('morning');
  const [taskKind,setTaskKind]=useState(''); const [payload,setPayload]=useState('{}');
  const [tier,setTier]=useState(3); const [options,setOptions]=useState<JobOptions>({});
  const [error,setError]=useState('');
  const save=()=>{try {
    const action=kind==='remind'?{type:kind,message:text}:kind==='ask'?{type:kind,prompt:text,agent,deliver:true}:kind==='brief'?{type:kind,kind:brief}:{type:kind,kind:taskKind,title:text,payload:JSON.parse(payload),risk_tier:tier};
    if(!name.trim()) throw new Error('A job needs a name');
    setError(''); onSave({name:name.trim(),schedule_text:when,action,options});
  } catch(e) {setError(String(e));}};
  return <div style={{display:'grid',gap:8,marginTop:8}}>
    <label>Name<input aria-label="job name" style={inpS} value={name} onChange={e=>setName(e.target.value)}/></label>
    <ScheduleBuilder onChange={setWhen}/>
    <label>Schedule<input aria-label="job schedule" style={inpS} value={when} onChange={e=>setWhen(e.target.value)}/></label>
    <label>Action<select aria-label="job action" style={inpS} value={kind} onChange={e=>setKind(e.target.value)}>{['remind','ask','brief','task'].map(k=><option key={k}>{k}</option>)}</select></label>
    {kind!=='brief' && <label>{kind==='ask'?'Prompt':kind==='task'?'Task title':'Message'}<textarea aria-label="job message" style={{...inpS,width:'100%'}} value={text} onChange={e=>setText(e.target.value)}/></label>}
    {kind==='ask' && <label>Agent<input aria-label="job agent" style={inpS} value={agent} onChange={e=>setAgent(e.target.value)}/></label>}
    {kind==='brief' && <select aria-label="brief kind" style={inpS} value={brief} onChange={e=>setBrief(e.target.value)}><option>morning</option><option>evening</option></select>}
    {kind==='task' && <><label>Registered task kind<input aria-label="task kind" style={inpS} value={taskKind} onChange={e=>setTaskKind(e.target.value)}/></label><label>Payload JSON<textarea aria-label="task payload" style={inpS} value={payload} onChange={e=>setPayload(e.target.value)}/></label><label>Requested risk tier<select aria-label="task tier" style={inpS} value={tier} onChange={e=>setTier(Number(e.target.value))}>{[0,1,2,3].map(n=><option key={n}>{n}</option>)}</select></label><small>Enqueued for the autonomy policy; a requested tier grants no authority.</small></>}
    <OptionsEditor value={options} onChange={setOptions}/>
    {error && <div role="alert">{error}</div>}
    <button className="tool-btn" onClick={save}>create job</button>
  </div>;
}
