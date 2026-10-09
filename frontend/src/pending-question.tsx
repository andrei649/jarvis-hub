import React, { useRef, useState } from 'react';
import './pending-question.css';

export type Question = {id:string; question:string; choices:string[]; multi_select:boolean};
export type QuestionAnswer = {answer?:string|string[]; other?:boolean; cancel?:boolean};

export function pendingQuestion(event:any): Question|null {
  if(!event || !/^[0-9a-f]{32}$/.test(event.id) || typeof event.question!=='string'
    || !event.question.trim() || event.question.length>4096 || !Array.isArray(event.choices)
    || event.choices.length>4 || event.choices.some((c:any)=>typeof c!=='string'||!c.trim()||c.length>16384)
    || typeof event.multi_select!=='boolean')return null;
  return {id:event.id,question:event.question,choices:event.choices,multi_select:event.multi_select};
}

export function PendingQuestion({question,onAnswer,lang='en'}:{question:Question;
  onAnswer:(answer:QuestionAnswer)=>Promise<void>;lang?:string}) {
  const [selected,setSelected]=useState<number[]>([]), [other,setOther]=useState(false);
  const [text,setText]=useState(''), [busy,setBusy]=useState(false), [error,setError]=useState('');
  const sending=useRef(false), ro=lang==='ro';
  async function answer(payload:QuestionAnswer){
    if(sending.current)return;
    sending.current=true;setBusy(true);setError('');
    try{await onAnswer(payload);}catch{setError(ro?'Răspunsul nu a fost acceptat. Poți reîncerca.':'Answer was not accepted. You can retry.');}
    finally{sending.current=false;setBusy(false);}
  }
  const typing=other || question.choices.length===0;
  return <section className="pending-question" role="dialog" aria-labelledby="pending-question-title">
    <h3 id="pending-question-title">{question.question}</h3>
    <div className="pending-question-options">{question.choices.map((label,index)=><button
      key={index} className="tool-btn" disabled={busy}
      aria-pressed={question.multi_select?selected.includes(index):undefined}
      onClick={()=>{if(question.multi_select){setOther(false);setSelected(current=>current.includes(index)
        ?current.filter(i=>i!==index):[...current,index]);}else void answer({answer:String(index+1)});}}>{label}</button>)}</div>
    {question.choices.length>0 && <button className="tool-btn" disabled={busy} aria-pressed={other}
      onClick={()=>{setOther(true);setSelected([]);}}>{ro?'Alt răspuns':'Other'}</button>}
    <form onSubmit={event=>{event.preventDefault();if(typing && text.trim())void answer({answer:text,...(other?{other:true}:{})});
      else if(selected.length)void answer({answer:selected.map(i=>String(i+1))});}}>
      {typing && <textarea autoFocus aria-label={ro?'Răspunsul tău':'Your answer'} maxLength={16384}
        value={text} disabled={busy} onChange={event=>setText(event.target.value)}/>}
      {(typing || question.multi_select) && <button className="tool-btn" type="submit"
        disabled={busy || (typing?!text.trim():selected.length===0)}>{ro?'Trimite răspunsul':'Send answer'}</button>}
      <button className="tool-btn" type="button" disabled={busy} onClick={()=>void answer({cancel:true})}>
        {ro?'Anulează întrebarea':'Cancel question'}</button>
    </form>
    {error && <p role="alert">{error}</p>}
  </section>;
}
