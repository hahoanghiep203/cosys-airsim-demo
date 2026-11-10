"""Review captured pairs and run cached ThermalGen; never overwrite source data."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image, ImageDraw


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def review(source, output):
    rows = list(csv.DictReader((source / 'pairs.csv').open(newline='', encoding='utf-8-sig')))
    records = []
    seen = {'rgb': set(), 'ir': set()}
    for row in rows:
        item = dict(row, flags=[], errors=[], hashes={})
        for kind in ('rgb', 'ir'):
            path = source / row[kind]
            with Image.open(path) as image:
                image.load()
                if image.size != (1280, 720):
                    item['errors'].append(kind + '_unexpected_dimensions')
                values = np.asarray(image.convert('L'), dtype=np.float32)
            sha = digest(path)
            if sha in seen[kind]:
                item['errors'].append(kind + '_duplicate')
            seen[kind].add(sha)
            item['hashes'][kind] = sha
            item[kind + '_stats'] = dict(mean=float(values.mean()), std=float(values.std()),
                p01=float(np.percentile(values, 1)), p99=float(np.percentile(values, 99)),
                fraction_at_or_below_8=float((values <= 8).mean()),
                fraction_at_or_above_250=float((values >= 250).mean()))
            if values.max() == values.min():
                item['errors'].append(kind + '_constant')
        if item['rgb_stats']['fraction_at_or_below_8'] > .70:
            item['flags'].append('severe_low_light_rgb')
        if item['ir_stats']['std'] < 5:
            item['flags'].append('low_global_ir_contrast')
        if item['rgb_stats']['fraction_at_or_above_250'] > .01:
            item['flags'].append('rgb_highlight_clipping')
        item['eligible_for_exploratory_inference'] = not item['errors']
        item['realism_status'] = 'UNVALIDATED_SYNTHETIC_NOT_TRAINING_APPROVED'
        records.append(item)
    report = dict(source=str(source), count=len(records), records=records,
        capture_audit=json.loads((source / 'audit.json').read_text()),
        review_scope='All 50 pairs inspected on contact sheet; image statistics are screening flags, not physical validity tests.',
        decision='Exploratory appearance inference only; no physically calibrated or real-world training approval.',
        global_limitations=['No measured real-camera reference or radiometric calibration.',
            'Uniform component temperatures and effective mixed-material emissivity approximate reality.',
            'Warm preset tank does not heat its surroundings; no people; stylized imported props.',
            'Strong low-light RGB loss, flat IR backgrounds and localized hot patches create a domain gap.',
            'Operating vehicle preset is static, not actual motion; PNG intensities are not temperatures.'],
        thresholds={'severe_low_light_rgb': '>70% luminance <=8/255',
            'low_global_ir_contrast': 'global luminance standard deviation <5/255',
            'rgb_highlight_clipping': '>1% luminance >=250/255'})
    output.mkdir(parents=True, exist_ok=False)
    (output / 'review.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(pairs=len(records), eligible=sum(r['eligible_for_exploratory_inference'] for r in records),
        flagged=sum(bool(r['flags']) for r in records), errors=sum(bool(r['errors']) for r in records))), flush=True)


def infer(source, output, model_root, limit, style=0, height=144, control=False):
    # Offline cached inference only; no downloads, no paid service, no Unreal process.
    os.environ.update(HF_HOME=str(model_root / '.hf-cache'), HF_HUB_OFFLINE='1',
                      TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_SYMLINKS_WARNING='1')
    sys.path.insert(0, str(model_root))
    import torch
    from thermalgen_demo import ThermalGenSIT
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA required; refuse an accidental CPU inference batch')
    torch.set_num_threads(6)
    torch.set_float32_matmul_precision('high')
    checkpoint = next((model_root / '.hf-cache/hub/models--xjh19972--ThermalGen-XL-2/snapshots').glob('*/model.safetensors'))
    started = time.time()
    model = ThermalGenSIT.from_pretrained(str(checkpoint.parent)).to('cuda').eval()
    report = json.loads((output / 'review.json').read_text())
    rows = [r for r in report['records'] if r['eligible_for_exploratory_inference']]
    if limit:
        rows = rows[:limit]
    result = dict(model='ThermalGen-XL-2', snapshot=checkpoint.parent.name, checkpoint_sha256=digest(checkpoint),
        torch=torch.__version__, gpu=torch.cuda.get_device_name(), style_label=style, style={0:'Boson night aerial',5:'LLVIP night',7:'M3FD'}.get(style,str(style)),
        cfg_scale=1.0, precision='float32; matmul precision high', seed_rule='20261023 + input index',
        sampler='upstream adaptive dopri5, 50 output time points (not 50 model evaluations)',
        input_transform=f'Raw RGB bilinear resize to 256x{height}, normalize [-1,1]; no exposure adjustment/padding/crop. Square resize distorts 16:9 aspect, matching original demo.',
        output_dimensions=[256,height], calibrated_temperature=False, records=[])
    if control:
        with Image.open(model_root / 'test_color.png') as im:
            control_rgb=im.convert('RGB').resize((256,height),Image.Resampling.BILINEAR)
        control_tensor=torch.from_numpy(np.array(control_rgb).copy()).permute(2,0,1).float().div(127.5).sub(1).unsqueeze(0).to('cuda')
        torch.manual_seed(20261023)
        with torch.inference_mode():
            p=model(control_tensor,torch.tensor([style],device='cuda',dtype=torch.long))
            a=p[0,0].mul(.5).add(.5).clamp(0,1).mul(255).round().byte().cpu().numpy()
        Image.fromarray(a).save(output/'upstream_control_generated.png')
        control_rgb.save(output/'upstream_control_rgb.png')
        result['control']={'input':str(model_root/'test_color.png'),'sha256':digest(model_root/'test_color.png'),'output':'upstream_control_generated.png'}
    for directory in ('generated', 'comparisons'):
        (output / directory).mkdir(exist_ok=True)
    for i, row in enumerate(rows):
        path = source / row['rgb']
        if digest(path) != row['hashes']['rgb']:
            raise RuntimeError('Input modified since review: ' + str(path))
        seed = 20261023 + report['records'].index(row)
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        with Image.open(path) as im:
            rgb = im.convert('RGB').resize((256,height), Image.Resampling.BILINEAR)
        tensor = torch.from_numpy(np.array(rgb).copy()).permute(2,0,1).float().div(127.5).sub(1).unsqueeze(0).to('cuda')
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        with torch.inference_mode():
            prediction = model(tensor, torch.tensor([style], device='cuda', dtype=torch.long))
            if not torch.isfinite(prediction).all():
                raise RuntimeError('Non-finite prediction: ' + row['id'])
            array = (prediction[0,0].mul(.5).add(.5).clamp(0,1).mul(255).round().byte().cpu().numpy())
        torch.cuda.synchronize()
        seconds = time.perf_counter() - t0
        generated = Image.fromarray(array)
        name = row['id'] + '.png'
        generated.save(output / 'generated' / name)
        # Display comparison only: no pixel metric is a temperature-accuracy score.
        reference = Image.open(source / row['ir']).convert('L').resize((256,height), Image.Resampling.BILINEAR)
        panel = Image.new('RGB', (768,height+36), '#202124')
        draw = ImageDraw.Draw(panel)
        for j, (label, image) in enumerate((('Original RGB',rgb),('Simulated IR',reference),('ThermalGen (not temperature)',generated))):
            draw.text((j*256+4,4),label,fill='white')
            panel.paste(image.convert('RGB'), (j*256,30))
        panel.save(output / 'comparisons' / name)
        result['records'].append(dict(id=row['id'], seed=seed, seconds=seconds, sha256=digest(output/'generated'/name),
            minimum=int(array.min()), maximum=int(array.max()), std=float(array.std()),
            inference_flags=row['flags'], output='generated/'+name))
        result['peak_cuda_allocated_gib'] = torch.cuda.max_memory_allocated()/1024**3
        result['total_wall_seconds'] = time.time()-started
        (output/'inference.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(f"{i+1}/{len(rows)} {row['id']} {seconds:.2f}s range {array.min()}-{array.max()}",flush=True)
    result['status'] = 'completed'
    (output/'inference.json').write_text(json.dumps(result,indent=2),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['review','infer'])
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model-root',type=Path)
    parser.add_argument('--limit',type=int)
    parser.add_argument('--style',type=int,default=0)
    parser.add_argument('--height',type=int,choices=[144,256],default=144)
    parser.add_argument('--control',action='store_true')
    args=parser.parse_args()
    if args.stage=='review':
        review(args.source,args.output)
    else:
        infer(args.source,args.output,args.model_root,args.limit,args.style,args.height,args.control)


if __name__=='__main__':
    main()
