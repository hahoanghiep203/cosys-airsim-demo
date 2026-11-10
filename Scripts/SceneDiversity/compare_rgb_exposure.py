"""Audit the paired recapture and compare matched-seed ThermalGen before/after."""
from collections import Counter
import csv
import hashlib
import html
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[2]
OLD=ROOT/'Saved/SceneDiversity/thermalgen_audited50'
NEW=ROOT/'Saved/SceneDiversity/thermalgen_iso25600_20261023'
OLD_RUN=ROOT/'Saved/SceneDiversity/ThermalGenReview_20261023'
RUN=ROOT/'Saved/SceneDiversity/ThermalGenISO_20261023'
DOCS=ROOT/'Docs/SceneDiversity/CameraExposure'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def source_states(metadata):
    return {(v['label'],s['name']):(s['temperature_k'],s['enabled']) for v in metadata['snapshot']['vehicles'] for s in v['sources']}


def main():
    original=json.loads((OLD_RUN/'review.json').read_text())
    fresh=json.loads((RUN/'review.json').read_text())
    old_model=json.loads((OLD_RUN/'M3FD_demo/inference.json').read_text())
    model=json.loads((RUN/'inference.json').read_text())
    assert model['status']=='completed' and len(model['records'])==50
    for key in ['checkpoint_sha256','style_label','cfg_scale','precision','seed_rule','output_dimensions','sampler']:
        assert model[key]==old_model[key],key
    DOCS.mkdir(parents=True,exist_ok=True)
    (RUN/'before_after').mkdir(exist_ok=True)
    records=[];seen=set();max_source_delta=0;enabled_diffs=0;camera_checks=0
    sheet=Image.new('RGB',(1600,10*180),'#202124')
    for index,(a,b,g0,g1) in enumerate(zip(original['records'],fresh['records'],old_model['records'],model['records'])):
        assert a['id']==b['id']==g0['id']==g1['id'] and g0['seed']==g1['seed']
        for base,row in [(OLD,a),(NEW,b)]:
            for kind in ['rgb','ir']:assert sha(base/row[kind])==row['hashes'][kind]
        m0=json.loads((OLD/a['metadata']).read_text());m1=json.loads((NEW/b['metadata']).read_text())
        s0,s1=source_states(m0),source_states(m1)
        assert s0.keys()==s1.keys()
        max_source_delta=max(max_source_delta,max(abs(s0[k][0]-s1[k][0]) for k in s0))
        enabled_diffs+=sum(s0[k][1]!=s1[k][1] for k in s0)
        assert m0['requested_camera_cm']==m1['requested_camera_cm']
        p=m1['snapshot']['rgb_camera_profile']
        assert p['applied'] and p['profile']['iso']==25600
        assert len(p['components'])==12
        for comp in p['components']:
            assert comp['iso']==25600 and comp['physical_exposure'] and abs(comp['f_stop']-1.4)<.001
            assert comp['shutter_denominator']==30
            camera_checks+=1
        path=RUN/g1['output'];assert sha(path)==g1['sha256']
        with Image.open(path) as im:
            im.load();assert im.size==(256,256) and im.mode=='L'
            assert np.asarray(im).std()>0
        assert g1['sha256'] not in seen;seen.add(g1['sha256'])
        record={'id':b['id'],'old_mean_rgb':a['rgb_stats']['mean'],'new_mean_rgb':b['rgb_stats']['mean'],
                'old_dark_fraction':a['rgb_stats']['fraction_at_or_below_8'],
                'new_dark_fraction':b['rgb_stats']['fraction_at_or_below_8'],
                'new_clipped_fraction':b['rgb_stats']['fraction_at_or_above_250'],
                'old_flags':';'.join(a['flags']),'new_flags':';'.join(b['flags'])}
        records.append(record)
        panel=Image.new('RGB',(1280,180),'#202124');d=ImageDraw.Draw(panel)
        entries=[('Previous RGB',OLD/a['rgb']),('New RGB: ISO 25600',NEW/b['rgb']),
            ('Previous ThermalGen',OLD_RUN/'M3FD_demo'/g0['output']),('New ThermalGen',path),('New simulated IR',NEW/b['ir'])]
        for col,(label,imgpath) in enumerate(entries):
            d.text((col*256+4,5),label,fill='white')
            with Image.open(imgpath) as im:panel.paste(im.convert('RGB').resize((256,144)),(col*256,30))
        panel.save(RUN/'before_after'/(b['id']+'.png'))
        thumb=panel.resize((320,45))
        x=(index%5)*320;y=(index//5)*180
        ImageDraw.Draw(sheet).text((x+3,y+4),b['id'][:40],fill='white')
        sheet.paste(thumb,(x,y+24))
        # Larger new RGB + generated thumbnails underneath improve screening.
        for col,imgpath in enumerate((NEW/b['rgb'],path)):
            with Image.open(imgpath) as im:sheet.paste(im.convert('RGB').resize((160,90)),(x+col*160,y+70))
    assert max_source_delta<1e-5 and enabled_diffs==0
    sheet.save(RUN/'before_after_contact_sheet.jpg',quality=94)
    report={'status':'PASS','pairs':50,'unique_generated_outputs':len(seen),'raw_capture_hashes':'unchanged',
        'matched_model_seed_and_style':True,'source_target_max_delta_K':max_source_delta,'source_enabled_differences':enabled_diffs,
        'camera_component_checks':camera_checks,'old_flag_counts':dict(Counter(f for r in original['records'] for f in r['flags'])),
        'new_flag_counts':dict(Counter(f for r in fresh['records'] for f in r['flags'])),
        'mean_rgb_luminance_before':float(np.mean([r['old_mean_rgb'] for r in records])),
        'mean_rgb_luminance_after':float(np.mean([r['new_mean_rgb'] for r in records])),
        'mean_dark_fraction_before':float(np.mean([r['old_dark_fraction'] for r in records])),
        'mean_dark_fraction_after':float(np.mean([r['new_dark_fraction'] for r in records])),
        'mean_clipped_fraction_after':float(np.mean([r['new_clipped_fraction'] for r in records])),
        'max_clipped_fraction_after':max(r['new_clipped_fraction'] for r in records),
        'inference_wall_seconds':model['total_wall_seconds'],'median_inference_seconds':float(np.median([r['seconds'] for r in model['records']])),
        'noise_model':'No added film grain; physical exposure gain only. Not a calibrated high-ISO sensor noise simulation.',
        'thermal_note':'Source target values/enabled states and camera positions match. Native thermal field can settle between views; no pixel-identical IR claim.',
        'physical_calibration':False}
    (RUN/'validation.json').write_text(json.dumps(report,indent=2))
    with (RUN/'before_after.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    def rel(path):return html.escape(os.path.relpath(path,DOCS).replace('\\','/'),quote=True)
    cards=[]
    for r in records:
        path=RUN/'before_after'/(r['id']+'.png')
        cards.append(f'<article><h3>{html.escape(r["id"])}</h3><p>Dark pixels: {r["old_dark_fraction"]:.1%} to {r["new_dark_fraction"]:.1%}. New flags: {html.escape(r["new_flags"] or "none")}.</p><a href="{rel(path)}"><img loading="lazy" src="{rel(path)}" alt="Previous RGB, new RGB, previous ThermalGen, new ThermalGen, simulated IR"></a></article>')
    doc='''<!doctype html><html><head><meta charset="utf-8"><title>Night RGB exposure and ThermalGen rerun</title><style>
body{font:16px system-ui;max-width:1450px;margin:32px auto;padding:0 20px;background:#17191d;color:#e5e7eb}a{color:#8fcaff}p{line-height:1.55}article{background:#242831;margin:20px 0;padding:14px}img{max-width:100%;height:auto}.note{padding:18px;background:#43301e;border-left:4px solid #ffb86c}h3{font-size:16px}</style></head><body><h1>Night RGB exposure and ThermalGen rerun</h1>
<p>Manual physical camera: ISO 25,600 / f/1.4 / 1/30 s / +1 EV. Scene lighting and source presets retained. No extra film grain or calibrated sensor-noise model.</p>'''
    doc+=f'<div class="note">50 fresh 720p paired views; 50 new M3FD ThermalGen outputs at 256x256. Low-light RGB flags: {report["old_flag_counts"].get("severe_low_light_rgb",0)} to {report["new_flag_counts"].get("severe_low_light_rgb",0)}. Better exposure is not proof of physical thermal accuracy.</div>'
    doc+=f'<p><a href="{rel(RUN/"validation.json")}">Validation</a> | <a href="{rel(RUN/"before_after.csv")}">Image statistics</a> | <a href="{rel(ROOT/"Config/SceneDiversity/rgb_camera.json")}">Camera profile</a> | <a href="Captures/INDEX.html">New RGB/IR captures</a> | <a href="../CAMERA_EXPOSURE_RERUN.md">Report</a></p>'
    doc+='<p>Each row: previous RGB | new RGB | previous ThermalGen | new ThermalGen | new simulated IR. Generated square images are reshaped to 16:9 here only for display; native outputs remain 256x256. Same M3FD style, model and per-view seeds before/after. ThermalGen consumes RGB, not source temperatures.</p>'+''.join(cards)+'</body></html>'
    (DOCS/'INDEX.html').write_text(doc,encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
