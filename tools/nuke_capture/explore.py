"""Run UI sections sequentially and build a linked coverage index."""
import argparse
import html
import json
from pathlib import Path
import subprocess
import sys


def build(root):
    entries=[]; failures=[]; runs=[]; requested_types=[]; captured_types=[]
    planned_types=[]
    for path in root.glob('properties-*-types.json'):
        planned_types.extend(json.loads(path.read_text(encoding='utf-8')))
    for directory in sorted(root.iterdir()):
        if not directory.is_dir(): continue
        manifest=directory/'atlas-manifest.json'
        result=directory/'result.json'
        if not manifest.exists():
            if (directory/'request.json').exists():
                failures.append({'run':directory.name,'case':'session','error':result.read_text() if result.exists() else 'No completed manifest'})
            continue
        data=json.loads(manifest.read_text(encoding='utf-8'))
        runs.append({'run':directory.name,'ended':result.exists(),
                     'ok':json.loads(result.read_text(encoding='utf-8')).get('ok',False) if result.exists() else False,
                     'captures':len(data['entries'])})
        if (directory/'requested-types.json').exists():
            requested_types.extend(json.loads((directory/'requested-types.json').read_text(encoding='utf-8')))
        failures.extend(dict(f,run=directory.name) for f in data['failures'])
        for e in data['entries']:
            evidence=json.loads((directory/'atlas'/e['evidence']).read_text(encoding='utf-8'))
            if evidence.get('widget_class')=='Foundry::UI::Chart' and not evidence.get('controls'): continue
            if directory.name.startswith('properties') and e['title'].endswith(' initial'):
                captured_types.append(e['title'][:-8])
            entries.append(dict(e,run=directory.name,path=directory.name+'/atlas/'+e['image']))
    unresolved=[]; recovered=[]
    for failure in failures:
        case=failure['case']
        if failure['run'].startswith('properties') and case.startswith('Properties '):
            case=case[len('Properties '):]+' initial'
        retries=[e for e in entries if e['run']>failure['run']
                 and e['run'].split('-')[0]==failure['run'].split('-')[0]
                 and (e['title']==case or e['title'].startswith(case+' '))]
        if retries: recovered.append(dict(failure,recovered_in=retries[0]['run']))
        else: unresolved.append(failure)
    report={'runs':runs,'captures':len(entries),'failures':failures,
            'unresolved_failures':unresolved,'recovered_failures':recovered,'entries':entries,
            'property_types_requested':sorted(set(requested_types)),
            'property_types_planned':sorted(set(planned_types)),
            'property_types_not_started':sorted(set(planned_types)-set(requested_types)),
            'property_types_captured':sorted(set(captured_types)),
            'property_types_missing':sorted(set(requested_types)-set(captured_types)),
            'limits':['Captured observations, not exhaustive combinations of every knob value.',
                      'External plugins, unavailable OFX, and crashing internal constructors remain outside this safe-mode session.',
                      'Window sizes are varied; OS display scaling is not changed.',
                      'No file dialog is accepted and no render or tracking job is submitted.']}
    (root/'coverage.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    latest={}
    for entry in entries: latest[(entry['run'].split('-')[0],entry['title'])]=entry
    cards=''.join('<article><h3>'+html.escape(e['title'])+'</h3><p>'+e['run']+'</p><a href="'+e['path']+'"><img loading="lazy" src="'+e['path']+'"></a></article>' for e in latest.values())
    page='''<!doctype html><meta charset="utf-8"><title>NukeX expanded UI references</title>
<style>body{font:16px system-ui;background:#191b1e;color:#ddd;margin:24px}input{padding:12px;width:60%}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(350px,1fr));gap:18px}article{background:#282b30;padding:16px}img{max-width:100%;max-height:440px}a{color:#a9ceff}</style>
<h1>NukeX expanded UI references</h1><p>Latest capture of each named state. <a href="coverage.json">All observations, failures and limits</a></p>
<input placeholder="Filter workspace, node or control" oninput="document.querySelectorAll('article').forEach(e=>e.hidden=!e.textContent.toLowerCase().includes(this.value.toLowerCase()))"><main>'''+cards+'</main>'
    (root/'index.html').write_text(page,encoding='utf-8')
    return report


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--catalog',type=Path)
    p.add_argument('--sections',nargs='+',default=['layouts','menus','graph','viewer','panels','dialogs','interactions','properties'])
    p.add_argument('--build-only',action='store_true')
    args=p.parse_args(); root=args.output.resolve(); root.mkdir(parents=True,exist_ok=True)
    if args.build_only: print(json.dumps({k:v for k,v in build(root).items() if k!='entries'})); return
    cases=[(section,None) for section in args.sections if section!='properties']
    if 'properties' in args.sections:
        if args.catalog:
            # Only types proven to instantiate in the earlier catalog, one per actual class.
            classes={}
            for path in sorted((args.catalog/'nodes').glob('*.json')):
                row=json.loads(path.read_text(encoding='utf-8'))
                if row.get('status')=='captured': classes.setdefault(row['class'],row['type'])
            types=sorted(classes.values())
            for i in range(0,len(types),40):
                name='properties-'+str(i//40).zfill(2)
                file=root/(name+'-types.json'); file.write_text(json.dumps(types[i:i+40]))
                cases.append((name,file))
        else: cases.append(('properties',None))
    for name,types in cases:
        output=root/name
        if output.exists():
            print('Retaining existing run '+name,flush=True); continue
        command=[sys.executable,str(Path(__file__).with_name('capture.py')),'--explore',name.split('-')[0],
                 '--output',str(output),'--timeout','1800']
        if types: command+=['--types',str(types)]
        print('Starting '+name,flush=True)
        with (root/(name+'.log')).open('w',encoding='utf-8') as log:
            code=subprocess.call(command,stdout=log,stderr=subprocess.STDOUT)
        report=build(root)
        print(json.dumps({'run':name,'exit':code,'captures':report['captures'],'failures':len(report['failures'])}),flush=True)
    build(root)


if __name__=='__main__': main()
