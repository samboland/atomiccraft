"""Validate expanded-atlas images and generate contact sheets for inspection."""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw
from explore import build


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    args=parser.parse_args(); root=args.output
    report=build(root); problems=[]; checked=0; samples=[]
    for entry in report['entries']:
        path=root/entry['path']
        try:
            if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:
                raise ValueError('PNG hash mismatch')
            with Image.open(path) as image:
                image.load()
                if list(image.size)!=entry['size']: raise ValueError('PNG dimension mismatch')
                if image.width<10 or image.height<10: raise ValueError('Trivial image dimensions')
            checked+=1
        except Exception as error: problems.append({'path':str(path),'error':str(error)})
        if not entry['run'].startswith('properties') or entry['title'].endswith(' initial'):
            samples.append(entry)
    review=root/'review'; review.mkdir(exist_ok=True)
    for offset in range(0,len(samples),20):
        sheet=Image.new('RGB',(1600,1500),'#202226'); draw=ImageDraw.Draw(sheet)
        for i,entry in enumerate(samples[offset:offset+20]):
            x=(i%4)*400; y=(i//4)*300
            with Image.open(root/entry['path']) as image:
                image=image.convert('RGB'); image.thumbnail((392,270)); sheet.paste(image,(x+(392-image.width)//2,y+24))
            draw.text((x+5,y+4),entry['title'][:62],fill='white')
        sheet.save(review/('sheet-'+str(offset//20).zfill(3)+'.jpg'),quality=88)
    (root/'validation.json').write_text(json.dumps({'checked':checked,'problems':problems,
        'contact_sheet_samples':len(samples),'visual_review':'Contact sheets require human or model inspection; generation is not visual verification.'},indent=2))
    print(json.dumps({'checked':checked,'problems':len(problems),'contact_sheet_samples':len(samples)}))


if __name__=='__main__': main()
