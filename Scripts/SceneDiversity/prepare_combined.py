"""Author one environment containing the four former layouts, without cloning worlds."""
import copy
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def prepare():
    path = ROOT / 'Config/SceneDiversity/scenes.json'
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    originals = config['scenes'][:4]
    scene = copy.deepcopy(originals[1])
    scene.update(id='05_combined_environment', map='/Game/CityPark/Maps/ThermalDiversity_05_CombinedEnvironment',
                 captures=50, vehicles=[], props=[], zones=[], ground_trace=True,
                 camera_route_cm=[], warmup_seconds=25,capture_mode='independent_viewpoints')
    # Following the surveyed road corridor; one sky and ambient across all zones.
    offsets = [(0,0),(6500,3500),(15000,0),(23000,0)]
    names = ['cafe','service','market','parking']
    for index, (source, (dx,dy), name) in enumerate(zip(originals, offsets, names)):
        zone = {'id':name,'offset_cm':[dx,dy,0],'center_cm':[-30000+dx,11300+dy,200],
                'lamp_kelvin':source['lamp_kelvin'],'lamp_cd':source['lamp_cd'],
                'lamp_heat_k':source['lamp_heat_k'],'counter_k':source['counter_k']}
        scene['zones'].append(zone)
        for v in source['vehicles']:
            v = copy.deepcopy(v)
            v['label'] = 'Combined_' + name + '_' + v['model'] + '_' + v['state']
            v['zone'] = name
            v['motion_enabled'] = False  # Warm operating states; deliberate static sample composition.
            for key in ('start_cm','end_cm'):
                v[key][0] += dx; v[key][1] += dy
            v['tire_initial_k'] = 308.15 if v['state']=='driving' else 300.15
            scene['vehicles'].append(v)
        for mesh,x,y,yaw in source['props']:
            scene['props'].append([mesh,x+dx,y+dy,yaw])
    scene['preview_position_cm'] = [-32300,13200,1300]
    scene['preview_target_cm'] = [-30000,11300,200]
    scene['counter_k']=363.15
    scene['lamp_heat_k']=328.15
    scene['lamp_kelvin']=3000
    scene['fixtures']=[]
    for zone in scene['zones'][1:]:
        cx,cy,_=zone['center_cm']
        for side in (-1,1):
            scene['fixtures'].append({'label':'Combined_'+zone['id']+'_WarmLamp_'+str(side),
                'zone':zone['id'],'xy_cm':[cx+side*950,cy-650],
                'blueprint':'/Game/Thermal/EveningSample/Blueprints/BP_SampleWarmLamp'})
    scene['fixtures'].append({'label':'Combined_market_HotCounter','zone':'market',
        'xy_cm':[-14500,10300],'yaw':180,
        'blueprint':'/Game/Thermal/EveningSample/Blueprints/BP_SampleHotCounter'})
    # This point intersects an existing low building in the source environment.
    cafe_cooling=scene['vehicles'][2]
    cafe_cooling['start_cm']=[-29600,11300,110]
    cafe_cooling['end_cm']=list(cafe_cooling['start_cm'])
    scene['props'][29][1:3]=[-7000,11400]  # Keep the parking barrier inside the lot, clear of the existing fence.
    config['scenes'] = originals + [scene]
    path.write_text(json.dumps(config,indent=2)+'\n')
    return scene


if __name__ == '__main__':
    print(json.dumps({'id':prepare()['id']}))
