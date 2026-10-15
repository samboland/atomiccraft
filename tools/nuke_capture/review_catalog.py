"""Validate saved node evidence and make contact sheets. Requires Pillow."""
import hashlib
import json
from pathlib import Path
import sys
from PIL import Image,ImageDraw

root=Path(sys.argv[1])
records=[json.loads(p.read_text(encoding='utf-8')) for p in sorted((root/'nodes').glob('*.json'))]
captured=[r for r in records if r['status']=='captured']
problems=[]
for row in captured:
    for role in row['images']:
        data=row['images'][role]
        path=root/'nodes'/data['file']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=data['sha256']:
            problems.append({'type':row['type'],'error':'Hash mismatch: '+role})
        with Image.open(path) as image:
            if list(image.size)!=data['size']: problems.append({'type':row['type'],'error':'Dimensions mismatch: '+role})
            image.verify()
    if not row.get('knobs'): problems.append({'type':row['type'],'error':'No exported knobs'})
out=root/'review'
out.mkdir(exist_ok=True)
for start in range(0,len(captured),24):
    page=Image.new('RGB',(1800,1800),'#191b1f')
    draw=ImageDraw.Draw(page)
    for i,row in enumerate(captured[start:start+24]):
        x,y=(i%6)*300,(i//6)*450
        draw.text((x+5,y+5),row['type'][:40],fill='white')
        with Image.open(root/'nodes'/row['images']['properties']['file']) as im:
            im.thumbnail((290,415))
            page.paste(im,(x+5,y+30))
    page.save(out/f'properties-{start//24+1:02d}.jpg',quality=88)
report={'captured':len(captured),'images_checked':sum(len(r['images']) for r in captured),'problems':problems}
(root/'validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
if problems: raise SystemExit(1)
