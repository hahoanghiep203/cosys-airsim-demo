"""Create schema-valid small demonstration missions; no simulator side effects."""
import copy
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
example = json.loads((ROOT / 'Docs/RouteCapture/mission.example.json').read_text())
example['$schema']='../../Plugins/AirSimRouteCapture/Scripts/mission.schema.json'
example.update(map_asset='/Game/RouteCapture/Maps/RouteCaptureDemo')
example['connection'].update(port=41469, vehicle_name='RouteDrone', rpc_timeout_s=30)
example['camera'].update(width_px=640, height_px=480, horizontal_fov_deg=65)
example['thermal'].update(warmup_ms=10000)
example['flight']['takeoff'].update(height_above_takeoff_m=2.5, timeout_s=60)
example['flight']['entry_leg'].update(speed_mps=1, timeout_s=90)
example['defaults']['segment'].update(speed_mps=2, acceleration_mps2=1, deceleration_mps2=1, timeout_s=120)
example['defaults']['node'].update(settle_time_ms=500, aim_tolerance_deg=3, max_settled_speed_mps=.3)
example['acquisition'].update(capture_timeout_ms=15000, max_pair_position_delta_m=.02, max_pair_angle_delta_deg=.25, abort_after_consecutive_missed_triggers=30)
example['limits'].update(max_duration_wall_s=1200, max_pairs=1000, obstacle_clearance_m=.3, max_cross_track_error_m=2, cross_track_grace_ms=2000)
example['output']['root']='Saved/RouteCaptureReview/Runs'
example['nodes']=[]
positions=[(-600,-600,250),(600,-600,250),(600,600,250),(-600,600,250)]
for index,(x,y,z) in enumerate(positions):
    dx,dy,dz=-x,-y,80-z
    rotation={'pitch':math.degrees(math.atan2(dz, math.hypot(dx,dy))), 'yaw':math.degrees(math.atan2(dy,dx)), 'roll':0}
    example['nodes'].append({'id':chr(65+index),'label':'Node '+str(index+1),'position_cm':{'x':x,'y':y,'z':z},'camera_rotation_deg':rotation})
example['segments']=[{'id':f'{a}_to_{b}','from':a,'to':b} for a,b in zip('ABC','BCD')]

output=ROOT/'Config/RouteCapture'
output.mkdir(parents=True,exist_ok=True)
for mode in ['at_nodes','during_travel','during_distance','combined']:
    value=copy.deepcopy(example)
    value.update(mission_id='demo_'+mode,name='Route demonstration — '+mode)
    value['metadata']={'demo_mode':mode,'observer_camera':'fixed world transform throughout recording','thermal_subject':'BP_ThermalHatchback','note':'Actual saved images use the drone camera; visible markers belong to the observer demonstration.'}
    if mode=='at_nodes':
        value['defaults']['segment']['capture']={'mode':'off'}
    else:
        for index,segment in enumerate(value['segments']):
            segment['settings']={'speed_mps':2,'capture':{'mode':'time_interval','interval_ms':100 if index==2 else 1000}}
            if mode=='during_distance':
                segment['settings']['capture']={'mode':'distance_interval','interval_m':1}
        if mode in ('during_travel','during_distance'):
            value['defaults']['node']['capture']={'mode':'off'}
            for node in value['nodes'][1:-1]:
                node['settings']={'behavior':'fly_through','settle_time_ms':0,'extra_hold_ms':0,'capture':{'mode':'off'}}
    target=output/(mode+'.json')
    target.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    print(target)
