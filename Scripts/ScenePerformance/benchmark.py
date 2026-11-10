"""Controlled original-map A/B/A/B editor rendering benchmark, not flight FPS."""
import json,sys,time
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'RouteCaptureDemo'))
from editor_command import editor,ROOT
output=ROOT/'Saved/ScenePerformance'/('tick_benchmark_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
output.mkdir(parents=True,exist_ok=False)
editor((ROOT/'Scripts/ScenePerformance/prepare_benchmark.py').read_text())
for label,profile in [('baseline_1','baseline'),('balanced_1','balanced'),('baseline_2','baseline'),('balanced_2','balanced')]:
    print(json.dumps(editor(f"result=scene_apply({profile!r})")),flush=True)
    time.sleep(5)
    editor(f'''
scene_bench_label={label!r}
scene_bench_output=Path({str(output)!r})
scene_bench_times=[]
scene_bench_started=time.perf_counter()
scene_bench_last=scene_bench_started

def scene_bench_tick(delta):
    global scene_bench_last
    now=time.perf_counter()
    scene_bench_times.append(now-scene_bench_last)
    scene_bench_last=now
    if now-scene_bench_started<15:return
    unreal.unregister_slate_post_tick_callback(scene_bench_callback)
    ordered=sorted(scene_bench_times)
    report={{'label':scene_bench_label,'measurement':'editor Slate tick wall intervals with one continuous 960x540 RGB SceneCapture; not packaged-game or sensor-flight FPS','seconds':now-scene_bench_started,'ticks':len(ordered),'tick_hz':len(ordered)/(now-scene_bench_started),'median_ms':ordered[len(ordered)//2]*1000,'p95_ms':ordered[min(len(ordered)-1,int(len(ordered)*.95))]*1000,'frame_intervals_s':scene_bench_times}}
    (scene_bench_output/(scene_bench_label+'.json')).write_text(json.dumps(report,indent=2))
scene_bench_callback=unreal.register_slate_post_tick_callback(scene_bench_tick)
result=True
''')
    deadline=time.monotonic()+90
    path=output/(label+'.json')
    while not path.exists():
        if time.monotonic()>deadline:raise TimeoutError(label)
        time.sleep(.5)
    print(json.dumps({k:v for k,v in json.loads(path.read_text()).items() if k!='frame_intervals_s'}),flush=True)
    editor(f"scene_probe_component.capture_scene();unreal.RenderingLibrary.export_render_target(scene_world(),scene_probe_target,{str(output)!r},{label+'.png'!r});result=True")
print(json.dumps(editor("result={'baseline':scene_apply('baseline'),'inventory':scene_audit()}")),flush=True)
editor("unreal.get_editor_subsystem(unreal.EditorActorSubsystem).destroy_actor(scene_probe_actor);result=True")
print('Evidence: '+str(output),flush=True)
