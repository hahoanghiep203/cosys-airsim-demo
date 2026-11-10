"""Validate separate generated outputs, preserve capture hashes, and build a review gallery."""
import argparse
from collections import Counter
import csv
import hashlib
import html
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def edge_cosine(a,b):
    ga=np.concatenate([v.ravel() for v in np.gradient(a.astype(float))])
    gb=np.concatenate([v.ravel() for v in np.gradient(b.astype(float))])
    return float(np.dot(ga,gb)/(np.linalg.norm(ga)*np.linalg.norm(gb)+1e-12))


def finalize(source,root,docs):
    review=json.loads((root/'review.json').read_text())
    rows=review['records']
    flags=Counter(flag for row in rows for flag in row['flags'])
    errors=[]
    metrics=[]
    for row in rows:
        for kind in ('rgb','ir'):
            if sha(source/row[kind])!=row['hashes'][kind]:
                errors.append('Changed raw input '+row['id']+' '+kind)
    summaries={}
    for variant,folder in [('BosonNight_aspect',root),('M3FD_original_demo',root/'M3FD_demo')]:
        manifest=json.loads((folder/'inference.json').read_text())
        width,height=manifest['output_dimensions']
        if manifest.get('status')!='completed' or len(manifest['records'])!=len(rows):
            errors.append(variant+' incomplete')
        seen=set()
        sheet=Image.new('RGB',(1280,10*150),'#202124')
        draw=ImageDraw.Draw(sheet)
        for i,(row,prediction) in enumerate(zip(rows,manifest['records'])):
            if prediction['id']!=row['id']:
                errors.append('Ordering mismatch '+variant)
            path=folder/prediction['output']
            image=Image.open(path)
            image.load()
            if image.size!=(width,height) or image.mode!='L':
                errors.append('Invalid output format '+str(path))
            a=np.asarray(image,dtype=float)
            checksum=sha(path)
            if checksum!=prediction['sha256'] or checksum in seen or a.std()==0:
                errors.append('Hash/duplicate/constant failure '+str(path))
            seen.add(checksum)
            ref=np.asarray(Image.open(source/row['ir']).convert('L').resize((width,height),Image.Resampling.BOX),dtype=float)
            rgb=np.asarray(Image.open(source/row['rgb']).convert('L').resize((width,height),Image.Resampling.BOX),dtype=float)
            # Bright-reference proxy, NOT a semantic component mask or calibrated temperature.
            mask=ref>max(float(np.percentile(ref,99)),float(np.median(ref))+12)
            background=~mask
            delta=float(a[mask].mean()-a[background].mean()) if mask.any() and background.any() else None
            metrics.append(dict(variant=variant,id=row['id'],generated_std=float(a.std()),
                ir_std=float(ref.std()),edge_cosine_vs_simulated_ir=edge_cosine(a,ref),
                edge_cosine_vs_rgb=edge_cosine(a,rgb),bright_ir_proxy_pixel_count=int(mask.sum()),
                generated_bright_proxy_delta=delta,flags=';'.join(row['flags'])))
            panel=Image.open(folder/'comparisons'/path.name).convert('RGB')
            # Contact-sheet thumbnails are display-only; full panels retain each run's dimensions.
            thumb=Image.new('RGB',(256,150),'#202124')
            thumb.paste(panel.resize((256,100)),(0,25))
            ImageDraw.Draw(thumb).text((3,3),row['id'][:36],fill='white')
            sheet.paste(thumb,((i%5)*256,(i//5)*150))
        sheet.save(folder/'all50_comparisons.jpg',quality=92)
        times=[r['seconds'] for r in manifest['records']]
        summaries[variant]=dict(count=len(manifest['records']),dimensions=[width,height],
            total_wall_seconds=manifest['total_wall_seconds'],median_inference_seconds=float(np.median(times)),
            peak_cuda_allocated_gib=manifest['peak_cuda_allocated_gib'],unique_outputs=len(seen),
            mean_edge_cosine_vs_ir=float(np.mean([r['edge_cosine_vs_simulated_ir'] for r in metrics if r['variant']==variant])))
    result=dict(file_integrity='PASS' if not errors else 'FAIL',raw_pairs_unchanged=not any('Changed raw' in e for e in errors),
        capture_pairs=len(rows),generated_images=sum(x['count'] for x in summaries.values()),
        flag_counts=dict(flags),flagged_pairs=sum(bool(r['flags']) for r in rows),variants=summaries,errors=errors,
        realism_decision='NOT SUITABLE as physically faithful thermal ground truth; exploratory outputs only.',
        visual_observations=['All source pairs inspected in contact sheet; all generated variants inspected in final comparison sheets.',
            'Boson aerial style invents blurred texture and loses vehicle structure in representative street views.',
            'Original-demo M3FD style retains more recognizable paving/buildings, but does not retain simulated hot hood/tire states.',
            'Official sample control yields recognizable road, buildings and vehicles; model execution works.',
            'No measured real LWIR validation exists; successful inference and recognizable objects do not prove thermal realism.'],
        metric_limitations='Edge cosines and bright-IR proxy deltas are image diagnostics only. The bright mask is not a hood/tire annotation; no temperature accuracy, semantic recall, FID or calibration claim.',
        next_capture_changes=['Raise indirect evening illumination/exposure enough to retain object details while keeping night lighting; recapture rather than invent shadow detail by postprocessing.',
            'Use closer/ground and moderate oblique views so tires and hood remain resolved after model preprocessing.',
            'Retain physically modeled source-state metadata separately; RGB-only ThermalGen cannot reliably infer hidden engine load/cooling state.',
            'Validate temperatures/emissivity/sensor response against measured matched-condition real LWIR before claiming physical realism.'])
    (root/'validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    with (root/'image_diagnostics.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(metrics[0]))
        writer.writeheader();writer.writerows(metrics)
    docs.mkdir(parents=True,exist_ok=True)
    def rel(path):
        return html.escape(os.path.relpath(path,docs).replace('\\','/'),quote=True)
    cards=[]
    for row in rows:
        name=row['id']+'.png'
        cards.append(f'<article><h3>{html.escape(row["id"])}</h3><p>{html.escape(", ".join(row["flags"]) or "No screening flag; realism unvalidated")}</p>'
            f'<a href="{rel(root/"M3FD_demo/comparisons"/name)}"><img loading="lazy" src="{rel(root/"M3FD_demo/comparisons"/name)}" alt="RGB, simulated IR, M3FD generated"></a>'
            f'<details><summary>Boson night comparison</summary><img loading="lazy" src="{rel(root/"comparisons"/name)}" alt="Boson comparison"></details></article>')
    document='''<!doctype html><html><head><meta charset="utf-8"><title>ThermalGen realism review</title><style>
body{background:#17191d;color:#e5e7eb;font:16px system-ui;max-width:1250px;margin:32px auto;padding:0 20px}a{color:#8fcaff} .warning{background:#482d20;padding:20px;border-left:5px solid #ffb86c}article{background:#22252c;margin:20px 0;padding:14px}img{display:block;max-width:100%;height:auto}h3{font-size:16px}p{line-height:1.5}</style></head><body>
<h1>ThermalGen: capture and realism review</h1><div class="warning"><strong>Inference completed; physical realism not validated.</strong>
<p>50 source pairs preserved. Both 50-image runs completed. Generated outputs miss source-dependent heat and can invent structure. Keep these as experiments, not temperature ground truth.</p></div>'''
    document+=f'<p>Screening: {dict(flags)}. These flags describe image quality, not measured temperature error. Original RGB/IR captures remain 1280×720; generated images are 256×144 (Boson) and 256×256 (original M3FD demo). The square demo stretches geometry; previews show that honestly.</p>'
    document+=f'<p><a href="{rel(root/"validation.json")}">Validation JSON</a> · <a href="{rel(root/"image_diagnostics.csv")}">Image diagnostics</a> · <a href="../THERMALGEN_REVIEW.md">Report and limitations</a></p>'
    document+='<h2>Original sample control</h2><p>RGB and M3FD output, confirming execution on the original demo input.</p>'
    document+=f'<img src="{rel(root/"M3FD_demo/upstream_control_rgb.png")}" alt="Original demo RGB"><img src="{rel(root/"M3FD_demo/upstream_control_generated.png")}" alt="Original demo generated IR">'
    document+='<h2>Captured views</h2><p>Each panel: original RGB | simulated IR | generated thermal appearance. No pixel value here is a measured temperature.</p>'+''.join(cards)+'</body></html>'
    (docs/'INDEX.html').write_text(document,encoding='utf-8')
    print(json.dumps(result,indent=2))
    if errors:raise SystemExit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--docs',type=Path,required=True)
    args=parser.parse_args()
    finalize(args.source,args.root,args.docs)
