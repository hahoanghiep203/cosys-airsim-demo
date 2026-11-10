"""Export an audited still collection with matching RGB/IR filenames and gallery."""
import argparse
import csv
import hashlib
import html
import json
from pathlib import Path
import shutil


def export(run, destination, docs):
    run=Path(run).resolve();destination=Path(destination).resolve();docs=Path(docs).resolve()
    audit=json.loads((run/'audit.json').read_text())
    assert audit['status']=='passed','Audit the complete capture first'
    manifest=json.loads((run/'manifest.json').read_text())
    assert not destination.exists(),'Refuse to overwrite an exported dataset'
    for name in ('rgb','ir','metadata'):
        (destination/name).mkdir(parents=True)
    docs.mkdir(parents=True,exist_ok=True)
    rows=[];tiles=[]
    from PIL import Image
    (docs/'thumbnails').mkdir(exist_ok=True)
    for pair in manifest['pairs']:
        stem=f"{pair['index']:03d}_{pair['view_id']}"
        for channel in ('rgb','ir'):
            source=run/pair['images'][channel]['file'];target=destination/channel/(stem+'.png')
            shutil.copy2(source,target)
            assert hashlib.sha256(target.read_bytes()).hexdigest()==pair['images'][channel]['sha256']
            with Image.open(target) as image:
                image.thumbnail((480,270));image.convert('RGB').save(docs/'thumbnails'/(stem+'_'+channel+'.jpg'),quality=88)
        (destination/'metadata'/(stem+'.json')).write_text(json.dumps(pair,indent=2))
        rows.append({'id':stem,'zone':pair['zone'],'rgb':'rgb/'+stem+'.png','ir':'ir/'+stem+'.png','metadata':'metadata/'+stem+'.json'})
        tiles.append('<article><h3>'+html.escape(pair['view_id'])+'</h3><div>'+''.join(
            '<a href="'+(destination/channel/(stem+'.png')).as_uri()+'"><img alt="'+channel+'" src="thumbnails/'+stem+'_'+channel+'.jpg"></a>'
            for channel in ('rgb','ir'))+'</div></article>')
    with (destination/'pairs.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=['id','zone','rgb','ir','metadata']);writer.writeheader();writer.writerows(rows)
    shutil.copy2(run/'audit.json',destination/'audit.json')
    shutil.copy2(run/'contact_sheet.jpg',docs/'contact_sheet.jpg')
    (destination/'README.txt').write_text('50 independent viewpoints in one environment. Matching filenames in rgb/ir; metadata per pair. '+
        'No continuous video or route recording. Sources and vehicle poses held fixed across the collection; each pair captured at a paused simulation frame. '+
        'Native thermal fields may settle between viewpoints. Display-mapped 8-bit thermal PNGs, not calibrated radiometric ground truth. '+
        'No provided train/test split: avoid random angle splits of the same objects/background.\n')
    (docs/'INDEX.html').write_text('<!doctype html><meta charset="utf-8"><title>Combined environment: independent viewpoints</title>'+
        '<style>body{font:16px system-ui;background:#15191f;color:#eef;margin:24px}article{margin:20px 0;padding:12px;background:#222a34}'+
        'article div{display:flex;gap:8px}img{width:48%;max-width:480px;height:auto}h3{font-size:15px}</style>'+
        '<h1>One environment · 50 independent viewpoints</h1><p>Café, service, market and parking under one blue-hour sky. RGB left; IR right. Click for full 1280×720 PNG.</p>'+''.join(tiles))
    return {'pairs':len(rows),'dataset':str(destination),'gallery':str(docs/'INDEX.html'),'export_hashes_verified':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path);parser.add_argument('destination',type=Path);parser.add_argument('docs',type=Path)
    args=parser.parse_args();print(json.dumps(export(args.run,args.destination,args.docs),indent=2))
