import os,subprocess,json,time,hashlib,xml.etree.ElementTree as E
from pathlib import Path
OUT=Path('/tmp/nerva-h277-prepared49-resume-current-20261005');ROOT=Path('/Users/andrei649/Projects/nerva-pr-worktrees/consent');plan=json.loads((OUT/'execution-plan.json').read_text());manifest=json.loads((OUT/'input-manifest.json').read_text())['paths'];env=dict(os.environ,**plan['environment']);handle=OUT/'handle.json'
state={'state':'running','pid':os.getpid(),'started_at':time.time(),'source_head':plan['head'],'original_cases':49,'input_count':len(manifest),'source_changes':False};handle.write_text(json.dumps(state,indent=2)+'\n')
def verify_current():return [k for k,v in manifest.items() if hashlib.sha256((ROOT/k).read_bytes()).hexdigest()!=v]
assert not verify_current(),'source inputs changed before campaign'
for key,label in [('baseline_py_command','baseline-python'),('baseline_js_command','baseline-hud')]:
 with (OUT/(label+'.log')).open('w') as f:p=subprocess.run(plan[key],cwd=plan['cwd'],env=env,stdout=f,stderr=subprocess.STDOUT,timeout=180)
 print(label+' exit='+str(p.returncode),flush=True)
 if p.returncode:state.update(state='baseline_failed',label=label,exit_code=p.returncode);handle.write_text(json.dumps(state,indent=2)+'\n');raise SystemExit(p.returncode)
py=E.parse(OUT/'baseline.xml').getroot();s=list(py.iter('testsuite'));state['baseline_python']={k:sum(int(x.get(k,0)) for x in s) for k in ['tests','failures','errors','skipped']};js=json.loads((OUT/'baseline-hud.json').read_text());state['baseline_hud']={k:js.get(k) for k in ['numTotalTests','numPassedTests','numFailedTests','numPendingTests','success']};handle.write_text(json.dumps(state,indent=2)+'\n');print(json.dumps({'baseline_python':state['baseline_python'],'baseline_hud':state['baseline_hud']}),flush=True)
p=subprocess.run(plan['run_command'],cwd=plan['cwd'],env=env)
rows=json.loads((OUT/'results.json').read_text())['results'];counts={}
for row in rows:counts[row['classification']]=counts.get(row['classification'],0)+1
snapshot_drift=[k for k,v in manifest.items() if hashlib.sha256((OUT/'snapshot'/k).read_bytes()).hexdigest()!=v];source_drift=verify_current()
state.update(state='terminal',exit_code=p.returncode,completed_at=time.time(),outcomes=counts,restored=all(row.get('restoration_ok') for row in rows),source_drift=source_drift,snapshot_drift=snapshot_drift);handle.write_text(json.dumps(state,indent=2)+'\n');print(json.dumps(state),flush=True)
assert len(rows)==49 and p.returncode==0 and not source_drift and not snapshot_drift and state['restored']
assert all(row['classification'] in ['killed_assertion','killed_behavioral_exception','killed_mixed'] for row in rows)
