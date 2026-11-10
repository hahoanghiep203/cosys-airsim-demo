"""Run one real mission through the same native Start action used by the panel."""
import argparse
import json
from pathlib import Path
import time

from editor_command import editor, ROOT

def run(mode, tag='', control_probe=False, record_drone=False):
    mission=ROOT/'Config/RouteCapture'/(mode+'.json')
    name=mode+('_'+tag if tag else '')
    frames=ROOT/'Saved/RouteCaptureReview/Observer'/name
    drone_frames=ROOT/'Saved/RouteCaptureReview/DroneView'/name
    if frames.exists() and any(frames.iterdir()):
        raise RuntimeError('Choose a fresh recording folder; prior evidence is preserved')
    if record_drone and drone_frames.exists() and any(drone_frames.iterdir()):
        raise RuntimeError('Choose a fresh drone recording folder')
    # Import into the saved example level before Play, so the actual editor data
    # and runtime mission are the same configuration.
    info=editor(f'''
desired_map=json.loads(Path({str(mission)!r}).read_text(encoding='utf-8'))['map_asset']
world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
if world.get_path_name().split('.')[0]!=desired_map:
 if not unreal.EditorLevelLibrary.load_level(desired_map): raise RuntimeError('Cannot load mission map: '+desired_map)
 world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
cls=unreal.load_class(None,'/Script/AirSimRouteCapture.DroneCaptureRoute')
mission_route=next(a for a in unreal.GameplayStatics.get_all_actors_of_class(world,cls) if a.get_actor_label()=='RouteDemo_Route')
mission_route.set_editor_property('json_file',{str(mission)!r})
if not mission_route.import_mission(): raise RuntimeError(str(mission_route.get_editor_property('status')))
for p in mission_route.get_editor_property('ordered_points'):
 p.set_editor_property('demo_visible_in_game',True)
 p.get_editor_property('direction').set_hidden_in_game(False)
 p.get_editor_property('number').set_hidden_in_game(False)
mission_route.refresh_preview()
if mission_route.validate_route()!='Valid': raise RuntimeError(mission_route.validate_route())
unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).editor_request_begin_play()
result=True
''')
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        game=editor("world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world(); result=world.get_path_name() if world else None")
        if game: break
        time.sleep(.5)
    else: raise RuntimeError('Play did not start')
    time.sleep(3)
    print(json.dumps({'play_world':game}),flush=True)
    print(json.dumps(editor((ROOT/'Scripts/RouteCaptureDemo/observer.py').read_text(encoding='utf-8'))),flush=True)
    if record_drone:
        print(json.dumps(editor((ROOT/'Scripts/RouteCaptureDemo/drone_view.py').read_text(encoding='utf-8'))),flush=True)
    drone_start=f'drone_view_start({str(drone_frames)!r})' if record_drone else ''
    start=editor(f'''
cls=unreal.load_class(None,'/Script/AirSimRouteCapture.DroneCaptureRoute')
mission_route=next(a for a in unreal.GameplayStatics.get_all_actors_of_class(world,cls) if a.get_actor_label()=='RouteDemo_Route')
observer_start({str(frames)!r})
{drone_start}
started=mission_route.start()
result={{'started':started,'status':mission_route.get_editor_property('status'),'run_dir':mission_route.get_editor_property('run_directory')}}
''')
    print(json.dumps(start),flush=True)
    if not start['started']:
        editor('result=observer_finish()')
        if record_drone:
            editor('result=drone_view_finish()')
        raise RuntimeError('Mission Start failed: '+start['status'])
    run_dir=Path(start['run_dir'])
    if not run_dir.is_absolute(): run_dir=ROOT/run_dir
    deadline=time.monotonic()+1300
    previous=None
    probe={'enabled':control_probe, 'stage':'waiting_for_travel'}
    while time.monotonic()<deadline:
        if (run_dir/'status.json').exists():
            try: status=json.loads((run_dir/'status.json').read_text())
            except (OSError,json.JSONDecodeError): status={}
            compact={key:status.get(key) for key in ['state','message','pairs','pairs_saved','node_id','segment_id','reason'] if status.get(key) is not None}
            if compact!=previous:
                print(json.dumps(compact),flush=True)
                previous=compact
            if control_probe and probe['stage']=='waiting_for_travel' and status.get('segment_id') and status.get('state')=='running':
                editor('mission_route.pause();result=True')
                probe['stage']='pause_requested'
            elif control_probe and probe['stage']=='pause_requested' and status.get('state')=='paused':
                probe['paused_status']=status
                probe['paused_wall']=time.monotonic()
                probe['stage']='paused'
            elif control_probe and probe['stage']=='paused' and time.monotonic()-probe['paused_wall']>=2:
                probe['end_paused_status']=status
                if status.get('state')!='paused' or status.get('pairs')!=probe['paused_status'].get('pairs'):
                    raise RuntimeError('Pause did not retain paused state and capture count')
                probe['active_time_during_pause_s']=status['active_elapsed_s']-probe['paused_status']['active_elapsed_s']
                probe['world_time_during_pause_s']=status['simulation_elapsed_s']-probe['paused_status']['simulation_elapsed_s']
                if abs(probe['active_time_during_pause_s'])>.1 or probe['world_time_during_pause_s']<=0:
                    raise RuntimeError('Pause active-clock behavior is incorrect')
                if status.get('actual_speed_mps',float('inf'))>.3:
                    raise RuntimeError('Pause did not settle to hover')
                editor('mission_route.resume();result=True')
                probe['stage']='resume_requested'
            elif control_probe and probe['stage']=='resume_requested' and status.get('state')=='running':
                probe['resumed_status']=status
                editor('mission_route.stop_hover();result=True')
                probe['stage']='stop_requested'
        if (run_dir/'summary.json').exists(): break
        time.sleep(1)
    else:
        editor('mission_route.stop_hover(); result=True')
        raise TimeoutError('Mission did not finish before demonstration deadline')
    time.sleep(1)
    if record_drone:
        ended=editor("result={'observer':observer_finish(),'drone':drone_view_finish()}")
        recording,drone_recording=ended['observer'],ended['drone']
    else:
        recording,drone_recording=editor('result=observer_finish()'),None
    summary=json.loads((run_dir/'summary.json').read_text())
    output={'mode':mode,'run_dir':str(run_dir),'observer':recording,'drone_view':drone_recording,'summary':summary,'control_probe':probe}
    (ROOT/'Saved/RouteCaptureReview'/(name+'_result.json')).write_text(json.dumps(output,indent=2),encoding='utf-8')
    print(json.dumps({'mode':mode,'run_dir':str(run_dir),'recording':recording,'summary':summary}),flush=True)
    if control_probe:
        if probe['stage']!='stop_requested' or summary.get('state')!='stopped' or not summary.get('recovery',{}).get('hover'):
            raise RuntimeError('Control probe failed: '+str(summary.get('reason')))
    elif summary.get('state')!='completed' or not summary.get('route_complete'):
        raise RuntimeError('Demonstration mission failed: '+str(summary.get('reason')))
    return output

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['at_nodes','during_travel','during_distance','combined','mixed_showcase'])
    parser.add_argument('--tag',default='')
    parser.add_argument('--control-probe',action='store_true')
    parser.add_argument('--record-drone',action='store_true')
    args=parser.parse_args()
    run(args.mode,args.tag,args.control_probe,args.record_drone)
