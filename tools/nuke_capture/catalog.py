"""Run resumable node captures and build an evidence-linked gallery."""
import argparse
import csv
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid


def record_path(root,name):
    slug=re.sub(r'[^a-zA-Z0-9_-]+','-',name).strip('-') or 'unnamed'
    return root/'nodes'/(slug+'-'+hashlib.sha256(name.encode()).hexdigest()[:8]+'.json')


def build(root):
    inventory=json.loads((root/'inventory.json').read_text(encoding='utf-8'))
    records=[]
    for item in inventory['candidates']:
        path=record_path(root,item['type'])
        row=json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(item,status='pending')
        row['record']='nodes/'+path.name
        records.append(row)
    counts=dict(Counter(row['status'] for row in records))
    summary={'version':inventory['version'],'scope':inventory['scope'],'counts':counts,
             'candidates':len(records),'captured_classes':len({r['class'] for r in records if r['status']=='captured'}),
             'nodes':[{k:v for k,v in r.items() if k in ('type','class','status','reason','record','images','sources')} for r in records]}
    (root/'coverage.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    with (root/'nodes.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(['type','class','status','metadata','properties','graph'])
        for row in records:
            writer.writerow([row['type'],row.get('class',''),row['status'],row['record'],
                             *['nodes/'+row['images'][role]['file'] if role in row.get('images',{}) else ''
                               for role in ('properties','graph')]])
    cards=[]
    for row in records:
        body='<h2>'+html.escape(row['type'])+'</h2><p>'+html.escape(row['status'])+'</p>'
        if row.get('class') and row['class']!=row['type']: body+='<p>Class: '+html.escape(row['class'])+'</p>'
        for role,im in row.get('images',{}).items():
            body+='<a href="nodes/'+im['file']+'"><img loading="lazy" alt="'+role+'" src="nodes/'+im['file']+'"></a>'
        if row.get('reason'): body+='<pre>'+html.escape(row['reason'])+'</pre>'
        body+='<p><a href="'+row['record']+'">Node metadata</a></p>'
        cards.append('<article>'+body+'</article>')
    page='''<!doctype html><html><meta charset="utf-8"><title>NukeX node catalog</title>
<style>body{background:#191b1f;color:#ddd;font:15px system-ui;margin:24px}a{color:#a8ceff}input{padding:12px;width:70%}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:20px}article{padding:16px;background:#262a30}img{max-width:100%;max-height:600px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>
<h1>NukeX node catalog</h1><p>Initial properties and graph appearance. Nodes are unconnected; no rendering, tracking, or training is run.</p>
<p>Enumeration includes library candidates that are not creatable nodes. Unavailable candidates and failed captures remain listed.</p>
<p><a href="nodes.csv">Node list (CSV)</a> · <a href="coverage.json">Coverage</a> · <a href="inventory.json">Enumeration sources</a></p><p>'''+html.escape(str(counts))+'''</p>
<input placeholder="Filter type, class, status" oninput="document.querySelectorAll('article').forEach(x=>x.hidden=!x.textContent.toLowerCase().includes(this.value.toLowerCase()))"><main>'''+''.join(cards)+'</main></html>'
    (root/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='nodes'}),flush=True)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--exe',default=r'C:\Program Files\Nuke17.1v2\Nuke17.1.exe')
    p.add_argument('--build-only',action='store_true')
    p.add_argument('--batch-size',type=int,default=60)
    p.add_argument('--timeout',type=int,default=180)
    args=p.parse_args()
    root=args.output.resolve()
    root.mkdir(parents=True,exist_ok=True)
    if not args.build_only:
        while True:
            before=len(list((root/'nodes').glob('*.json')))
            run=root/'runs'/uuid.uuid4().hex[:10]
            run.parent.mkdir(exist_ok=True)
            command=[sys.executable,str(Path(__file__).with_name('capture.py')),'--exe',args.exe,
                     '--catalog',str(root),'--node-limit',str(args.batch_size),'--timeout',str(args.timeout),'--output',str(run)]
            with (run.parent/(run.name+'.log')).open('w',encoding='utf-8') as log:
                code=subprocess.call(command,stdout=log,stderr=subprocess.STDOUT)
            if not (root/'inventory.json').exists(): raise RuntimeError('Enumeration failed; inspect '+str(run))
            if code:
                current=json.loads((root/'current.json').read_text(encoding='utf-8')) if (root/'current.json').exists() else {}
                if current.get('state')=='creating':
                    path=record_path(root,current['type'])
                    if not path.exists():
                        path.write_text(json.dumps({'type':current['type'],'status':'interrupted',
                            'reason':'Worker timed out or exited; see runs/'+run.name+'.log'},indent=2),encoding='utf-8')
            report=build(root)
            if not report['counts'].get('pending'): break
            after=len(list((root/'nodes').glob('*.json')))
            if after<=before: raise RuntimeError('No progress; inspect '+str(run))
    else: build(root)


if __name__=='__main__': main()
