"""Audit committed demonstration outputs and assemble original-image previews."""
import argparse
import hashlib
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[2]

def write_json(path,value):
    candidate=path.with_suffix(path.suffix+'.tmp')
    with candidate.open('w',encoding='utf-8') as stream:
        json.dump(value,stream,indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(candidate,path)

def audit(result_file):
    result=json.loads(Path(result_file).read_text(encoding='utf-8'))
    run=Path(result['run_dir'])
    summary=json.loads((run/'summary.json').read_text(encoding='utf-8'))
    assert summary['state']=='completed' and summary['route_complete']
    assert summary['collisions']==0
    assert abs(summary['active_duration_sim_s']-summary['simulation_duration_s'])<1e-6
    pairs=[]
    for folder in sorted((run/'pairs').iterdir()):
        if not folder.is_dir() or not folder.name.isdecimal():
            continue
        record=json.loads((folder/'record.json').read_text(encoding='utf-8'))
        for kind in ['rgb','ir']:
            path=folder/(kind+'.png')
            assert hashlib.sha256(path.read_bytes()).hexdigest()==record['images'][kind]['sha256']
            with Image.open(path) as im:
                assert im.size==(640,480)
                im.verify()
        assert record['images']['rgb']['image_type']==0
        assert record['images']['ir']['image_type']==12
        assert record['quality']['position_delta_m']<=.02
        assert record['quality']['angle_delta_deg']<=.25
        pairs.append(record)
    assert len(pairs)==summary['pairs']
    expected_kind='node' if result['mode']=='at_nodes' else 'travel'
    assert pairs and all(p['trigger']['kind']==expected_kind for p in pairs)
    if expected_kind=='travel':
        expected_mode='distance_interval' if result['mode']=='during_distance' else 'time_interval'
        assert all(p['trigger']['mode']==expected_mode and p['trigger']['scheduled']>0 for p in pairs)
    if expected_kind=='node':
        assert [p['trigger']['node_id'] for p in pairs]==list('ABCD')
    return result,run,summary,pairs

def build(node_file,travel_file,distance_file=None,control_file=None):
    deliver=ROOT/'Saved/RouteCaptureReview/Deliverables'
    deliver.mkdir(parents=True,exist_ok=True)
    rows=[]
    report={'source':'Actual Unreal/AirSim mission outputs; original RGB and display-mapped ThermalIR PNGs',
            'thermal_note':'IR luminance is display-mapped signal, not calibrated Kelvin.',
            'runs':{}}
    for file in [node_file,travel_file]+([distance_file] if distance_file else []):
        result,run,summary,pairs=audit(file)
        mode=result['mode']
        camera=json.loads((deliver/(mode+'_fixed_observer.camera_check.json')).read_text())
        assert camera['camera_position_max_delta_cm']==0 and camera['camera_rotation_max_delta_deg']==0
        preflight=json.loads((run/'preflight.json').read_text())
        assert preflight['passed']
        report['runs'][mode]={'directory':str(run),'summary':summary,'observer':camera,
                            'hashes_dimensions_types_and_quality_verified':True,
                            'camera_mount_position_ned_m':preflight['camera_mount_position_ned_m'],
                            'coordinate_context':preflight['context']}
        last_segment=summary['segments'][-1]['id'] if summary['segments'] else None
        selected=[] if mode=='during_distance' else ([pairs[0],pairs[len(pairs)//2]] if mode=='at_nodes' else [pairs[0],next(p for p in pairs if p['trigger'].get('segment_id')==last_segment)])
        for pair in selected:
            label=f"{mode} | pair {pair['pair_id']} | {pair['trigger'].get('node_id',pair['trigger'].get('segment_id'))} | sim {pair['simulation_elapsed_s']:.2f}s"
            rows.append((run,pair,label))
    sheet=Image.new('RGB',(960,4*396),(24,28,34))
    draw=ImageDraw.Draw(sheet)
    for row,(run,pair,label) in enumerate(rows):
        top=row*396
        for col,kind in enumerate(['rgb','ir']):
            with Image.open(run/pair['images'][kind]['path']) as im:
                sheet.paste(im.convert('RGB').resize((480,360)),(col*480,top+36))
            draw.text((col*480+10,top+9),label+' | '+kind.upper(),fill=(235,240,245))
    candidate=deliver/'rgb_ir_examples.tmp.png'
    sheet.save(candidate)
    with candidate.open('r+b') as stream:
        os.fsync(stream.fileno())
    os.replace(candidate,deliver/'rgb_ir_examples.png')
    if control_file:
        control=json.loads(Path(control_file).read_text(encoding='utf-8'))
        assert control['summary']['state']=='stopped' and control['summary']['recovery']['hover']
        assert control['control_probe']['stage']=='stop_requested'
        assert abs(control['control_probe']['active_time_during_pause_s'])<.1
        report['controls']=control
    landing=json.loads((deliver/'landing_probe.json').read_text(encoding='utf-8'))
    assert landing['recovery']['landed'] and not landing['recovery']['errors']
    assert landing['landed_state']==0 and not landing['api_control_enabled']
    report['landing']=landing
    report['marker_visibility']=json.loads((ROOT/'Saved/RouteCaptureReview/marker_visibility.json').read_text(encoding='utf-8-sig'))
    write_json(deliver/'integration_report.json',report)
    print(json.dumps({'runs':{k:{'pairs':v['summary']['pairs'],'collisions':v['summary']['collisions']} for k,v in report['runs'].items()},'deliverables':str(deliver)},indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('node_result')
    parser.add_argument('travel_result')
    parser.add_argument('--distance-result')
    parser.add_argument('--control-result')
    args=parser.parse_args()
    build(args.node_result,args.travel_result,args.distance_result,args.control_result)
