from pathlib import Path
from datetime import datetime, UTC
import json, os, hashlib, subprocess, xml.etree.ElementTree as E
OUT=Path('/tmp/nerva-kanban-resume-full-backend-20261005')
ROOT=Path('/Users/andrei649/Projects/nerva-pr-worktrees/consent')
freeze=json.loads((OUT/'frozen.json').read_text())
cmd=['/tmp/nerva-pr-python-20261001/bin/python','-m','pytest','tests','-n','3','--dist','loadfile','--timeout=90','-q','--tb=short','--junitxml='+str(OUT/'result.xml')]
state={'state':'running','pid':os.getpid(),'head':freeze['head'],'started_at':datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),'command':cmd,'expected_cases':freeze['backend_cases'],'frozen_paths':len(freeze['paths']),'freeze':str(OUT/'frozen.json'),'xml':str(OUT/'result.xml'),'log':str(OUT/'run.log'),'next_action':'Observe this exact process, never restart solely on an observation timeout. Inspect terminal JUnit and all frozen hashes before claiming full results. No push/merge/deploy.'}
(OUT/'handle.json').write_text(json.dumps(state,indent=2)+'\n')
env=dict(os.environ,JARVIS_TESTING='1',JARVIS_HOME=str(OUT/'scratch-home'),PYTHONDONTWRITEBYTECODE='1')
with (OUT/'run.log').open('w') as log: result=subprocess.run(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
state.update(state='terminal_review_required',exit_code=result.returncode,completed_at=datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ'))
state['drift']=[n for n,h in freeze['paths'].items() if not (ROOT/n).is_file() or hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h]
try:
 r=E.parse(OUT/'result.xml').getroot();state['results']={k:sum(int(s.get(k,0)) for s in r.iter('testsuite')) for k in ['tests','failures','errors','skipped']}
except Exception as exc: state['result_error']=type(exc).__name__
(OUT/'handle.json').write_text(json.dumps(state,indent=2)+'\n')
print(json.dumps({k:v for k,v in state.items() if k not in ['command','drift']}),flush=True)
print('frozen_drift_count='+str(len(state['drift'])),flush=True)
raise SystemExit(result.returncode)
