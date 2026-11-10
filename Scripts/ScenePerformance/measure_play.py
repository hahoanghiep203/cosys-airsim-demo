"""Owned-editor PIE sweep: actual GPU dispatch cadence plus wall/world frame intervals.
No sensor API reads or pause/freeze pairing during timing. Not a packaged flight test.
"""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'RouteCaptureDemo'))
from editor_command import editor, ROOT
parser=argparse.ArgumentParser()
parser.add_argument('label')
parser.add_argument('--seconds',type=int,default=60)
parser.add_argument('--profile',choices=['baseline','balanced'],default='balanced')
parser.add_argument('--pool',type=int,default=6144)
parser.add_argument('--motion',action='store_true')
parser.add_argument('--diversity-scene',help='Measure the configured diversity preview while its vehicles keep moving')
parser.add_argument('--sample-view',action='store_true',help='Use the installed EveningSample preview pose instead of the external camera')
args=parser.parse_args()
output=ROOT/'Saved/ProjectMaintenance'/(args.label+'.json')
assert not output.exists(), 'Use a fresh label'
print(editor(f'''
import math,time
world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()
assert world,'PIE must be active'
hud=unreal.GameplayStatics.get_all_actors_of_class(world,unreal.load_class(None,'/Script/AirSim.SimHUD'))[0]
cameras=unreal.GameplayStatics.get_all_actors_of_class(world,unreal.load_class(None,'/Script/AirSim.PIPCamera'))
assert cameras,'No sensor camera'
profile_result=scene_apply({args.profile!r},True)
unreal.SystemLibrary.execute_console_command(world,'r.Streaming.PoolSize {args.pool}')
unreal.SystemLibrary.execute_console_command(world,'airsim.Thermal.LiveHz 30')
unreal.SystemLibrary.execute_console_command(world,'airsim.Thermal.GpuPreview 1')
assert hud.set_thermal_review_viewport_size(1280,720)
sweep_reference_origin=globals().get('sweep_reference_origin',cameras[0].get_actor_location())
sweep_reference_rotation=globals().get('sweep_reference_rotation',cameras[0].get_actor_rotation())
sweep_origin=sweep_reference_origin
sweep_rotation=sweep_reference_rotation
if {args.sample_view!r}:
 config=json.loads((ROOT/'Config/EveningSample/scene.json').read_text())
 sweep_origin=unreal.Vector(*config['preview_position_cm'])
 sweep_rotation=unreal.MathLibrary.find_look_at_rotation(sweep_origin,unreal.Vector(*config['preview_target_cm']))
if {args.diversity_scene is not None!r}:
 config=json.loads((ROOT/'Config/SceneDiversity/scenes.json').read_text())
 selected=next(s for s in config['scenes'] if s['id']=={args.diversity_scene!r})
 sweep_origin=unreal.Vector(*selected['preview_position_cm'])
 sweep_rotation=unreal.MathLibrary.find_look_at_rotation(sweep_origin,unreal.Vector(*selected['preview_target_cm']))
 diversity_set_view(selected['preview_position_cm'],selected['preview_target_cm'],False)
for camera in cameras:camera.set_actor_location_and_rotation(sweep_origin,sweep_rotation,False,True)
sweep_motion={args.motion!r}
sweep_label={args.label!r};sweep_duration={args.seconds}
sweep_started=time.perf_counter();sweep_last=sweep_started;sweep_samples=[];sweep_deltas=[]
sweep_before=json.loads(hud.get_thermal_gpu_stats())
unreal.SystemLibrary.execute_console_command(world,'csvprofile start')
def scene_play_measure(delta):
 global sweep_last
 now=time.perf_counter();elapsed=now-sweep_started
 sweep_samples.append(now-sweep_last);sweep_last=now
 sweep_deltas.append(unreal.GameplayStatics.get_world_delta_seconds(world))
 if sweep_motion:
  position=sweep_origin+unreal.Vector(600*math.sin(elapsed*.15),600*(math.cos(elapsed*.15)-1),100*math.sin(elapsed*.1))
  rotation=unreal.Rotator(sweep_rotation.pitch,sweep_rotation.yaw+elapsed*2,sweep_rotation.roll)
  for camera in cameras:camera.set_actor_location_and_rotation(position,rotation,False,True)
 if elapsed<sweep_duration:return
 unreal.unregister_slate_post_tick_callback(sweep_callback)
 unreal.SystemLibrary.execute_console_command(world,'csvprofile stop')
 after=json.loads(hud.get_thermal_gpu_stats());ordered=sorted(sweep_samples)
 report={{'label':sweep_label,'measurement':'UE editor PIE wall tick intervals; CSV profiler records engine frames separately; not packaged-flight FPS','motion':sweep_motion,'seconds':elapsed,'ticks':len(ordered),'wall_tick_hz':len(ordered)/elapsed,
 'median_ms':ordered[len(ordered)//2]*1000,'p95_ms':ordered[min(len(ordered)-1,int(len(ordered)*.95))]*1000,'p99_ms':ordered[min(len(ordered)-1,int(len(ordered)*.99))]*1000,'max_ms':max(ordered)*1000,'over_100ms':sum(t>.1 for t in ordered),'over_500ms':sum(t>.5 for t in ordered),
 'ir_dispatch_hz':(after.get('dispatched',0)-sweep_before.get('dispatched',0))/elapsed,'gpu_before':sweep_before,'gpu_after':after,'profile':profile_result,'texture_pool_mb':unreal.SystemLibrary.get_console_variable_int_value('r.Streaming.PoolSize'),'world_deltas':sweep_deltas,'wall_intervals':sweep_samples}}
 (ROOT/'Saved/ProjectMaintenance'/({args.label!r}+'.json')).write_text(json.dumps(report,indent=2))
 for camera in cameras:camera.set_actor_location_and_rotation(sweep_origin,sweep_rotation,False,True)
sweep_callback=unreal.register_slate_post_tick_callback(scene_play_measure)
result={{'started':sweep_label,'camera_origin':str(sweep_origin)}}
'''),flush=True)
deadline=time.monotonic()+args.seconds+180
while not output.exists():
    if time.monotonic()>deadline:raise TimeoutError(str(output))
    time.sleep(.5)
report=json.loads(output.read_text())
print(json.dumps({k:v for k,v in report.items() if k not in ('world_deltas','wall_intervals','gpu_before','gpu_after')},indent=2),flush=True)
